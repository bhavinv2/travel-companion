"""Lead-ad connectors (Sales CRM 2.0, run 4b): Facebook/Instagram lead forms and Google Ads lead forms.

Both turn an ad form's answers into an ordinary CRM lead through crm.capture(), under a source of their own that
stays UNROUTED until an admin chooses its pipeline on Lead sources (so nothing is messaged and nobody is assigned
before then):

* Meta: the Page's `leadgen` webhook event carries only ids; the lead itself is fetched from the Graph API with the
  Page token meta.py already uses (meta.fetch_lead -- tests replace it, nothing calls out in tests). Source key
  `meta-form-<form id>`, named "Facebook/Instagram form <id>".
* Google: `POST /api/crm/google-leads` with Google's webhook JSON; the `google_key` must equal CRM_GOOGLE_LEADS_KEY
  (404 while that is unset). Source key `google-form-<form id>`. Test leads (`is_test`) are answered and not stored.

Both are idempotent: the lead id of the ad platform is kept as the external id of the lead's first line, and a lead
already seen is not stored again.
"""
import hmac
import os
import re

from app import db
from app.models import CrmSource, CrmTouchpoint
from app.services import crm, crm_products, crm_scope

META_PREFIX = 'meta-form-'
GOOGLE_PREFIX = 'google-form-'
KEY_CLEAN = re.compile(r'[^a-z0-9-]+')


def google_key():
    return (os.environ.get('CRM_GOOGLE_LEADS_KEY') or '').strip()


def key_ok(sent):
    """The `google_key` of the request equals ours (constant-time)."""
    mine = google_key()
    return bool(mine and sent) and hmac.compare_digest(str(sent).encode('utf-8'), mine.encode('utf-8'))


def _seen(external_id):
    return CrmTouchpoint.query.filter_by(external_id=external_id).first() is not None


def _source(key, name):
    """The source for this form, made unrouted the first time (an admin routes it on Lead sources)."""
    src = crm.source(key)
    if src is None:
        src = CrmSource(key=key, name=name, kind='form', product=crm_products.general_code(), status='unrouted')
        db.session.add(src)
        db.session.flush()
    return src


def _form_key(prefix, form_id):
    form = KEY_CLEAN.sub('-', str(form_id or 'unknown').lower()).strip('-')[:40] or 'unknown'
    return prefix + form, form


# ================================================================================================ Meta

def meta_leads(payload):
    """The `leadgen` events of a Meta webhook delivery: [{'leadgen_id', 'form_id', 'ad_id', 'page_id'}]."""
    out = []
    for entry in (payload or {}).get('entry') or []:
        for ch in entry.get('changes') or []:
            if ch.get('field') != 'leadgen':
                continue
            v = ch.get('value') or {}
            lid = str(v.get('leadgen_id') or '').strip()
            if lid:
                out.append({'leadgen_id': lid, 'form_id': str(v.get('form_id') or ''), 'ad_id': str(v.get('ad_id') or ''),
                            'page_id': str(v.get('page_id') or entry.get('id') or '')})
    return out


def _answers(field_data):
    """{lowercase field name: first value} from Graph's field_data [{name, values: [...]}]."""
    out = {}
    for item in field_data or []:
        vals = item.get('values') if isinstance(item, dict) else None
        name = str((item or {}).get('name') or '').strip().lower() if isinstance(item, dict) else ''
        if name and vals:
            out[name] = str(vals[0]).strip()
    return out


def _split(answers, full_keys, first_keys, last_keys, email_keys, phone_keys):
    def first(keys):
        return next((answers[k] for k in keys if answers.get(k)), '')
    name = first(full_keys) or ' '.join(x for x in (first(first_keys), first(last_keys)) if x)
    used = set(full_keys) | set(first_keys) | set(last_keys) | set(email_keys) | set(phone_keys)
    details = {k.replace('_', ' '): v[:300] for k, v in answers.items() if k not in used and v}
    return name.strip() or None, first(email_keys) or None, first(phone_keys) or None, details


def handle_meta(ev, fetch=None):
    """One `leadgen` event: fetch the lead from Meta and capture it. Returns the lead, or None (seen before, nothing
    to reach them by, or Meta could not be asked). `fetch(leadgen_id)` is meta.fetch_lead unless a test passes one."""
    from app.services import meta
    ext = 'meta-lead-%s' % ev['leadgen_id']
    if _seen(ext):
        return None
    got = (fetch or meta.fetch_lead)(ev['leadgen_id']) or {}
    answers = _answers(got.get('field_data'))
    form_id = ev.get('form_id') or str(got.get('form_id') or '')
    key, form = _form_key(META_PREFIX, form_id)
    name, email, phone, details = _split(answers, ('full_name', 'name'), ('first_name',), ('last_name',),
                                         ('email', 'work_email'), ('phone_number', 'phone', 'phone number'))
    if not (email or phone):
        return None
    utm = {k: v for k, v in {'ad_id': ev.get('ad_id') or str(got.get('ad_id') or ''), 'form_id': form_id,
                             'campaign': str(got.get('campaign_name') or got.get('campaign_id') or '')}.items() if v}
    with crm_scope.for_source(key):            # the workspace that has this form's source (else the default one)
        _source(key, 'Facebook/Instagram form %s' % form)
        return crm.capture(key, name=name, phone=phone, email=email, details=details, channel='form', utm=utm,
                           external_id=ext, message='Filled in a Facebook/Instagram lead form')


# ================================================================================================ Google

GOOGLE_NAME = ('full_name',)
GOOGLE_FIRST, GOOGLE_LAST = ('first_name',), ('last_name',)
GOOGLE_EMAIL, GOOGLE_PHONE = ('email', 'work_email'), ('phone_number', 'work_phone')


def handle_google(body):
    """A Google Ads lead form delivery (already past the key check). Returns {'result': 'test' | 'seen' | 'stored' |
    'ignored', 'lead_id'?}. Test leads and repeats are not stored."""
    if body.get('is_test') in (True, 'true', 'True', 1, '1'):
        return {'result': 'test'}
    lead_id = str(body.get('lead_id') or '').strip()
    if not lead_id:
        return {'result': 'ignored'}
    ext = 'google-lead-%s' % lead_id[:100]
    if _seen(ext):
        return {'result': 'seen'}
    answers, labels = {}, {}
    for col in body.get('user_column_data') or []:
        if not isinstance(col, dict):
            continue
        cid = str(col.get('column_id') or '').strip().lower()
        val = str(col.get('string_value') or '').strip()
        if cid and val:
            answers[cid] = val
            labels[cid] = str(col.get('column_name') or '').strip()
    name, email, phone, details = _split(answers, GOOGLE_NAME, GOOGLE_FIRST, GOOGLE_LAST, GOOGLE_EMAIL, GOOGLE_PHONE)
    details = {(labels.get(k) or k.replace('_', ' ')): v for k, v in
               {k: v for k, v in answers.items() if v and k not in GOOGLE_NAME + GOOGLE_FIRST + GOOGLE_LAST
                + GOOGLE_EMAIL + GOOGLE_PHONE}.items()}
    if not (email or phone):
        return {'result': 'ignored'}
    form_id = str(body.get('form_id') or '')
    key, form = _form_key(GOOGLE_PREFIX, form_id)
    utm = {k: v for k, v in {'form_id': form_id, 'campaign': str(body.get('campaign_id') or ''),
                             'gclid': str(body.get('gcl_id') or '')}.items() if v}
    with crm_scope.for_source(key):            # the workspace that has this form's source (else the default one)
        _source(key, 'Google Ads form %s' % form)
        lead = crm.capture(key, name=name, phone=phone, email=email, details=details, channel='form', utm=utm,
                           external_id=ext, message='Filled in a Google Ads lead form')
    return {'result': 'stored' if lead is not None else 'ignored', 'lead_id': lead.id if lead is not None else None}
