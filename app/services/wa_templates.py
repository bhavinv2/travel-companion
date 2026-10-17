"""WhatsApp templates for the Sales CRM's messages.

WhatsApp lets a business write first, or write after 24 hours of silence, only with a template
Meta has approved. Most follow-ups (TI #2 on day 3, the festival greeting, the policy-ending
reminder) are exactly that, so each WhatsApp step and each ready message gets a template made
from its own wording:

    "Hi {name}, {agent} here from NRI Parent Service ... {insurance_link}"
 -> "Hi {{1}}, {{2}} here from NRI Parent Service ... https://nriparentservice.com/travel-insurance"

Only what differs per person becomes a numbered blank ({name}, {agent}, {product}, {departure},
{days}, {ends}); links and the helpline numbers are written in, because a template with fewer
blanks is approved faster and a link Meta has reviewed is one it will not query.

The same function turns a step into its template and, when sending, a lead into the values for
the blanks -- so what is submitted to Meta and what is sent with it cannot drift apart.
"""
import csv
import io
import logging
import re
import threading
import time
from contextlib import contextmanager

from app import db

log = logging.getLogger(__name__)

# per-person tokens -> template blanks; everything else is written into the template text
VARIABLE_TOKENS = ('name', 'agent', 'product', 'departure', 'days', 'ends')
SAMPLES = {'name': 'Priya', 'agent': 'Harsha', 'product': 'travel insurance', 'departure': '12 Nov',
           'days': '10', 'ends': '20 Dec'}
LANGUAGE = 'en'
# every value a lead can fill into a message or a template blank (crm.fill_values), as the follow-up editor names them
FILL_LABELS = {'name': 'Name', 'agent': 'Your name', 'product': 'Product', 'departure': 'Travel date',
               'days': 'Days to travel', 'ends': 'Cover ends', 'helplines': 'Helplines',
               'insurance_link': 'Insurance page link', 'companion_link': 'Travel Companion page link',
               'sahayak_link': 'Sahayak page link', 'site_link': 'Website link'}
STATUS_WORDS = {'APPROVED': 'Approved', 'PENDING': 'Waiting for WhatsApp', 'IN_APPEAL': 'Waiting for WhatsApp',
                'DRAFT': 'Not sent for approval yet', 'REJECTED': 'Turned down', 'PAUSED': 'Paused by WhatsApp',
                'DISABLED': 'Turned off by WhatsApp'}
NO_TEMPLATE = 'No template yet'
TOKEN = re.compile(r'\{([a-z_]+)\}')
NAME_OK = re.compile(r'^[a-z0-9_]{1,512}$')


def _static_values():
    """The written-in values: the public links and the helplines, as the site publishes them."""
    from flask import current_app
    from app.services import offices, urls
    site = (current_app.config.get('SITE_URL') or '').rstrip('/')
    out = {'helplines': ', '.join('%s (%s)' % (n['display'], n['label']) for n in offices.numbers()[:3])
           or 'our helpline'}
    for var, endpoint in (('insurance_link', 'insurance.landing'), ('companion_link', 'main.all_trips'),
                          ('sahayak_link', 'sahayak.landing'), ('site_link', 'main.index')):
        try:
            out[var] = urls.site_link(endpoint)
        except Exception:      # noqa: BLE001 -- outside a request
            out[var] = site
    return out


def parts(body, static=None):
    """(template body, the tokens behind {{1}}, {{2}} ... in order) for a message text."""
    static = static if static is not None else _static_values()
    tokens = []

    def sub(m):
        t = m.group(1)
        if t in VARIABLE_TOKENS:
            if t not in tokens:
                tokens.append(t)
            return '{{%d}}' % (tokens.index(t) + 1)
        return str(static.get(t, m.group(0)))
    return TOKEN.sub(sub, body or ''), tokens


def params(body, values):
    """The values for a template's blanks, in its order, for one lead (values: crm.fill_values)."""
    _, tokens = parts(body, static={})
    return [str(values.get(t) or '').strip() or SAMPLES.get(t, '') for t in tokens]


def step_param_keys(step):
    """The fill-in map of a follow-up (wa_params: which lead value goes into blank 1, 2 ...), or None when it
    has none and the blanks follow the order of the {tokens} in its words."""
    keys = getattr(step, 'wa_params', None)
    if isinstance(keys, list) and keys and all(isinstance(k, str) and k in FILL_LABELS for k in keys):
        return list(keys)
    return None


def step_params(step, values):
    """The values for a follow-up's template blanks, in order: its fill-in map when it has one, else the
    order of the {tokens} in its words (params)."""
    keys = step_param_keys(step)
    if keys is None:
        return params(step.body or '', values)
    return [str(values.get(k) or '').strip() or SAMPLES.get(k, '') for k in keys]


def step_blanks(step):
    """How many blanks a follow-up fills: its map's length, else one per person token in its words."""
    keys = step_param_keys(step)
    return len(keys) if keys is not None else blanks(step.body)


def status_words(status, reason=None):
    """A template's status as a person reads it: 'Approved', 'Waiting for WhatsApp', 'Turned down: <why>'."""
    if not status:
        return NO_TEMPLATE
    status = str(status).upper()
    if status == 'REJECTED' and (reason or '').strip():
        return 'Turned down: ' + reason.strip()[:200]
    return STATUS_WORDS.get(status, status.replace('_', ' ').capitalize())


def status_css(status):
    status = str(status or '').upper()
    return 'tpl-' + ('approved' if status == 'APPROVED' else 'pending' if status in ('PENDING', 'IN_APPEAL')
                     else 'draft' if status == 'DRAFT' else 'rejected' if status in ('REJECTED', 'PAUSED', 'DISABLED')
                     else 'missing')


def slug_name(code):
    """'TI #2' -> 'nri_ti_2'; Meta wants lowercase letters, digits and underscores."""
    s = re.sub(r'[^a-z0-9]+', '_', (code or '').lower()).strip('_')
    return ('nri_' + s)[:512] if s else ''


def problems(name, body, tokens):
    """What Meta would refuse, in words somebody can act on."""
    out = []
    if not NAME_OK.match(name or ''):
        out.append('The name may use only lowercase letters, digits and _.')
    if len(body) > 1024:
        out.append('Too long for a template (%d characters, at most 1024).' % len(body))
    stripped = body.strip()
    if stripped.startswith('{{') or stripped.endswith('}}'):
        out.append('A template cannot start or end with a blank ({{n}}).')
    if re.search(r'\}\}\s*\{\{', body):
        out.append('Two blanks next to each other need words between them.')
    if not stripped:
        out.append('There is no text.')
    return out


def _category(step=None, answer=None):
    """Sales follow-ups and greetings are MARKETING; reminders about something they already have
    (the policy ending, the trip coming up) are UTILITY. Meta has the last word either way."""
    if step is not None and step.stage is not None and step.stage.kind == 'won':
        return 'UTILITY'
    text = ((step.title if step else answer.title) or '').lower()
    if any(w in text for w in ('ends', 'ending', 'expir', 'renew', 'payment link', 'policy')):
        return 'UTILITY'
    return 'MARKETING'


def candidates():
    """Every message that needs a template: WhatsApp steps and ready messages (the ones with a
    code). [{name, code, title, category, language, body, tokens, samples, problems, step, answer}]"""
    from app.models import CrmAnswer, CrmPlaybookStep
    static = _static_values()
    rows = []
    steps = (CrmPlaybookStep.query.filter(CrmPlaybookStep.channel == 'whatsapp', CrmPlaybookStep.body.isnot(None))
             .order_by(CrmPlaybookStep.stage_id, CrmPlaybookStep.position).all())
    for s in steps:
        body, tokens = parts(s.body, static)
        rows.append({'kind': 'step', 'step': s, 'answer': None, 'code': s.code, 'title': s.title,
                     'pipeline': s.stage.pipeline.name if s.stage and s.stage.pipeline else '',
                     'product': s.stage.pipeline.product if s.stage and s.stage.pipeline else '',
                     'category': _category(step=s), 'body': body, 'tokens': tokens, 'source': s.body})
    for a in CrmAnswer.query.filter(CrmAnswer.code.isnot(None)).order_by(CrmAnswer.code).all():
        body, tokens = parts(a.body, static)
        rows.append({'kind': 'ready', 'step': None, 'answer': a, 'code': a.code, 'title': a.title,
                     'pipeline': 'Ready message', 'product': a.product,
                     'category': _category(answer=a), 'body': body, 'tokens': tokens, 'source': a.body})
    # One template per distinct text. A code used in two pipelines with different words gets the
    # product added, so neither overwrites the other; the same words used twice are one template
    # serving both (Meta would refuse a second with the same name anyway).
    out, by_name = [], {}
    for r in rows:
        name = r['step'].wa_template if r['step'] is not None and r['step'].wa_template else slug_name(r['code'])
        if name in by_name and by_name[name]['body'] != r['body']:
            name = '%s_%s' % (name, (r['product'] or 'x').lower())
        used = '%s: %s' % (r['pipeline'], r['title'])
        if name in by_name:
            first = by_name[name]
            first['used_for'].append(used)
            if r['step'] is not None:
                first['steps'].append(r['step'])
            continue
        r['name'] = name
        r['language'] = LANGUAGE
        r['samples'] = [SAMPLES.get(t, 'example') for t in r['tokens']]
        r['problems'] = problems(name, r['body'], r['tokens'])
        r['used_for'] = [used]
        r['steps'] = [r['step']] if r['step'] is not None else []
        by_name[name] = r
        out.append(r)
    return out


# ------------------------------------------------------------------- what WhatsApp has

_cache = {'at': 0.0, 'rows': None, 'info': None, 'error': None}
CACHE_SECONDS = 60
_local = threading.local()


@contextmanager
def cache_only():
    """Inside: statuses() answers from what it last heard (maybe nothing) and never asks the
    WhatsApp CRM -- for drawing a page without a network call."""
    before = getattr(_local, 'cache_only', False)
    _local.cache_only = True
    try:
        yield
    finally:
        _local.cache_only = before


def statuses(force=False):
    """{template name: status} from the WhatsApp CRM (APPROVED, PENDING, DRAFT, REJECTED...).
    Asked at most once a minute; {} when it cannot be reached (and error() says why)."""
    from app.services import wacrm_team
    if getattr(_local, 'cache_only', False):
        return _cache['rows'] or {}
    now = time.monotonic()
    if not force and _cache['rows'] is not None and now - _cache['at'] < CACHE_SECONDS:
        return _cache['rows']
    rows, info, error = {}, {}, None
    if wacrm_team.enabled():
        try:
            for t in wacrm_team.templates(status='ALL'):
                if (t.get('language') or LANGUAGE).split('_')[0] == LANGUAGE or t.get('name') not in rows:
                    rows[t.get('name')] = (t.get('status') or '').upper()
                    v = t.get('variables')
                    info[t.get('name')] = {
                        'status': (t.get('status') or '').upper(),
                        'rejection_reason': t.get('rejection_reason') or None,
                        'category': (t.get('category') or '').strip().upper() or None,
                        'body': t.get('body') or '', 'language': t.get('language') or None,
                        'variables': v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None}
        except wacrm_team.TeamError as exc:
            error = str(exc)
    else:
        error = 'The WhatsApp CRM is not connected.'
    _cache.update(at=now, rows=rows, info=info, error=error)
    return rows


def infos():
    """Everything statuses() last heard about each template: {name: {status, category, body, variables...}}."""
    statuses()
    return dict(_cache.get('info') or {})


# the pipeline editor's list of templates: asked at most every ten minutes
LIBRARY_SECONDS = 600
_lib = {'at': 0.0, 'rows': None, 'error': None}


def library(force=False):
    """[{name, status, category, body, variables, language, rejection_reason}] -- every template the WhatsApp
    CRM has, for the pipeline editor's picker (cached ten minutes; [] and library_error() when it cannot be
    reached). Inside cache_only() it answers from what it last heard."""
    from app.services import wacrm_team
    if getattr(_local, 'cache_only', False):
        return list(_lib['rows'] or [])
    now = time.monotonic()
    if not force and _lib['rows'] is not None and now - _lib['at'] < LIBRARY_SECONDS:
        return list(_lib['rows'])
    rows, error = [], None
    if wacrm_team.enabled():
        try:
            for t in wacrm_team.templates(status='ALL'):
                v = t.get('variables')
                rows.append({'name': t.get('name'), 'status': (t.get('status') or '').upper(),
                             'category': (t.get('category') or '').strip().upper() or None,
                             'body': t.get('body') or '', 'language': t.get('language') or None,
                             'variables': v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None,
                             'rejection_reason': t.get('rejection_reason') or None})
        except wacrm_team.TeamError as exc:
            error = str(exc)
    else:
        error = 'The WhatsApp CRM is not connected.'
    _lib.update(at=now, rows=rows, error=error)
    return list(rows)


def library_error():
    return _lib['error']


def template_labels():
    """{template name: the follow-up's or ready message's title} for templates the portal made; other names
    read as their words with spaces."""
    from app.models import CrmAnswer, CrmPlaybookStep
    out = {}
    for s in CrmPlaybookStep.query.filter(CrmPlaybookStep.channel == 'whatsapp').all():
        name = s.wa_template or slug_name(s.code)
        if name and name not in out:
            out[name] = s.title
    for a in CrmAnswer.query.filter(CrmAnswer.code.isnot(None)).all():
        name = slug_name(a.code)
        if name and name not in out:
            out[name] = a.title
    return out


def template_info(name):
    """What the WhatsApp CRM says about one template -- {status, category ('MARKETING', 'UTILITY'...),
    variables (how many blanks it has)} -- from the same once-a-minute list as statuses(); {} when
    it is not known."""
    statuses()
    return dict((_cache.get('info') or {}).get(name) or {})


def heard():
    """Whether the WhatsApp CRM's template list has been heard at all yet."""
    return _cache['rows'] is not None


def approved_templates():
    """[{name, language, category, body, variables}] for the APPROVED templates, by name."""
    statuses()
    info = _cache.get('info') or {}
    return [{'name': n, 'language': i.get('language'), 'category': i.get('category'), 'body': i.get('body') or '',
             'variables': i.get('variables')}
            for n, i in sorted(info.items()) if i.get('status') == 'APPROVED' and n]


def template_text(name, params):
    """An approved template's words with {{1}}, {{2}} ... filled in; '' when its body is not known."""
    body = (template_info(name) or {}).get('body') or ''
    return re.sub(r'\{\{(\d+)\}\}', lambda m: str(params[int(m.group(1)) - 1])
                  if 0 < int(m.group(1)) <= len(params) else m.group(0), body)


def known_fills(values):
    """{template name: {'fill': [...], 'title'}} for templates the portal made from its own words:
    WhatsApp follow-ups (step.wa_template or slug_name(code)) and ready messages with a code
    (slug_name(code)); fill = params(body, values). Two queries."""
    from app.models import CrmAnswer, CrmPlaybookStep
    out = {}
    for s in CrmPlaybookStep.query.filter(CrmPlaybookStep.channel == 'whatsapp',
                                           CrmPlaybookStep.body.isnot(None)).all():
        name = s.wa_template or slug_name(s.code)
        if name and name not in out:
            out[name] = {'fill': step_params(s, values), 'title': s.title}
    for a in CrmAnswer.query.filter(CrmAnswer.code.isnot(None)).all():
        name = slug_name(a.code)
        if name and name not in out:
            out[name] = {'fill': params(a.body, values), 'title': a.title}
    return out


def blanks(body):
    """How many blanks ({{1}}, {{2}} ...) a step's words make: one per person token, counted once."""
    return len(parts(body or '', static={})[1])


def error():
    return _cache['error']


def approved(name):
    return bool(name) and statuses().get(name) == 'APPROVED'


def forget():
    _cache.update(at=0.0, rows=None, info=None, error=None)
    _lib.update(at=0.0, rows=None, error=None)


# ------------------------------------------------------------------- putting them in

def push_drafts(rows=None):
    """Every candidate the WhatsApp CRM does not have yet goes in as a DRAFT (nothing is sent to
    Meta: a person reviews and submits each one on WhatsApp -> Templates), and each step is
    linked to its template so one-click and automatic sends use it once it is approved.
    Returns {created, skipped: [{name, reason}]}."""
    from app.services import wacrm_team
    rows = rows if rows is not None else candidates()
    items = [{'name': r['name'], 'category': r['category'], 'language': r['language'], 'body': r['body'],
              'sample_values': r['samples']} for r in rows if not r['problems']]
    skipped = [{'name': r['name'], 'reason': '; '.join(r['problems'])} for r in rows if r['problems']]
    result = wacrm_team.push_template_drafts(items) if items else {'created': 0, 'skipped': []}
    for r in rows:
        for step in r['steps']:
            if not step.wa_template and not r['problems']:
                step.wa_template = r['name']
    db.session.commit()
    forget()
    return {'created': result.get('created', 0), 'skipped': skipped + list(result.get('skipped') or [])}


def push_step_draft(step):
    """One follow-up's words as ONE WhatsApp template draft ("Make it a WhatsApp template"; nothing goes to
    Meta -- a person sends it for approval in WhatsApp). The follow-up is linked to it (wa_template, and its
    fill-in map from the order of the {tokens}). Words WhatsApp already has under a name are linked, not
    made again; changed words get 'name_2', 'name_3' ...; a name another follow-up uses is never taken.
    {'name', 'created', 'body', 'variables', 'params', 'category'} or {'error'}. No commit: the caller commits;
    the caller checks crm.wa_writes_on()."""
    from app.models import CrmPlaybookStep
    from app.services import wacrm_team
    if not (step.body or '').strip():
        return {'error': 'Write its words first.'}
    body, tokens = parts(step.body)
    statuses(force=True)
    if error():
        return {'error': 'WhatsApp could not be reached. Try again in a minute.'}
    have = infos()
    others = {n for (n,) in db.session.query(CrmPlaybookStep.wa_template)
              .filter(CrmPlaybookStep.id != step.id, CrmPlaybookStep.wa_template.isnot(None))}
    base = slug_name(step.code) or 'nri_follow_up'
    names = ([step.wa_template] if step.wa_template else []) + [base] + ['%s_%d' % (base, i) for i in range(2, 21)]
    chosen, created = None, 0
    for n in names:
        if n in have and (have[n].get('body') or '').strip() == body.strip() and n not in others:
            chosen = n
            break
        if n not in have and n not in others:
            chosen, created = n, 1
            break
    if chosen is None:
        return {'error': 'No free template name: change its code under More.'}
    category = _category(step=step)
    if created:
        probs = problems(chosen, body, tokens)
        if probs:
            return {'error': '; '.join(probs)}
        result = wacrm_team.push_template_drafts([{'name': chosen, 'category': category, 'language': LANGUAGE,
                                                   'body': body, 'sample_values': [SAMPLES.get(t, 'example') for t in tokens]}])
        created = int(result.get('created') or 0)
    else:
        category = have[chosen].get('category') or category
    step.wa_template = chosen
    step.wa_params = list(tokens) or None
    forget()
    return {'name': chosen, 'created': created, 'body': body, 'variables': len(tokens), 'params': list(tokens),
            'category': category}


def csv_text(rows=None):
    """The list as a spreadsheet: for review, or for submitting somewhere else."""
    rows = rows if rows is not None else candidates()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['Template name', 'Category', 'Language', 'Body', 'Sample values (in order)', 'Used for',
                'Code', 'Problems'])
    for r in rows:
        w.writerow([r['name'], r['category'], r['language'], r['body'], ' | '.join(r['samples']),
                    ' / '.join(r['used_for']), r['code'], '; '.join(r['problems'])])
    return out.getvalue()


# ------------------------------------------------------------------- ready answers -> quick replies

QUICK_TOKENS = {'name': '{{contact.first_name}}', 'agent': '{{agent.first_name}}'}


def quick_reply_text(body, static=None):
    """A ready answer in the WhatsApp CRM's quick-reply language: their first name and the
    agent's are filled in when it is picked in the inbox; links and helplines are written in.
    A lead-only value ({departure}, {days} ...) has no equivalent there and becomes "..."."""
    static = static if static is not None else _static_values()

    def sub(m):
        t = m.group(1)
        if t in QUICK_TOKENS:
            return QUICK_TOKENS[t]
        if t in static:
            return str(static[t])
        return '...'
    return TOKEN.sub(sub, body or '')


QUICK_KEY = 'crm_wa_quick'     # its own settings row, never "crm": a stale copy written back there could undo the switch
QUICK_TITLES_MAX = 500
QUICK_CONFLICT = '%d not copied: a WhatsApp button reply has the same title (%s). Rename one of them.'
# the fill-ins WhatsApp chats can fill (their name, the agent's, the written-in links) and the ones only a lead has
STATIC_TOKENS = ('helplines', 'insurance_link', 'companion_link', 'sahayak_link', 'site_link')
DATE_TOKENS = ('departure', 'days', 'ends')
WORKS_CHATS = 'Lead page & WhatsApp chats'
WORKS_LEAD_DATE = 'Lead page & chat panel (needs a date)'
WORKS_LEAD = 'Lead page & chat panel (needs the lead)'
WORKS_HELP = 'From the help page — edit there'
WORKS_BUTTONS = 'Made in WhatsApp (buttons) — stays there'
QR_SAVED_WA = "Saved. It's ready in WhatsApp chats too."
QR_SAVED_LEAD = 'Saved. Lead page and chat panel only, because it needs %s.'
QR_SAVED_OFF = 'Saved. It reaches WhatsApp chats once WhatsApp is connected.'
QR_REMOVED, QR_REMOVED_WA = 'Quick reply removed.', ' It goes from WhatsApp chats too.'
QR_BUTTON_CONFLICT = 'WhatsApp already has a button reply called “%s”. Rename one of them.'
QUICK_TOO_MANY = ('WhatsApp keeps about 150 quick replies from the Sales CRM, and these are more. '
                  'Remove some here, then press Push all to WhatsApp now.')
QUICK_WAITING = 'WhatsApp has not taken the last change yet. It is tried again by itself.'
OLD_TITLE = '%s · %s'            # how release 1 titled a reply with a code in WhatsApp
HELP_PRODUCT = {'insurance': 'TI', 'sahayak': 'SH', 'companion': 'TC'}
HELP_PAGE = {'companion': ('help', None), 'insurance': ('help_insurance', 'insurance'),
             'sahayak': ('help_sahayak', 'sahayak')}         # (page key, ?site=) of the help editor
WA_VAR_BACK = re.compile(r'\{\{\s*(contact|agent)\.(first_name|name)\s*\}\}')


def lead_only(body):
    """The fill-ins of a reply that WhatsApp chats cannot fill (the trip date, the cover end, the product...):
    every {token} that is in neither QUICK_TOKENS nor STATIC_TOKENS, in order, each once. [] for a reply that
    works everywhere."""
    out = []
    for t in TOKEN.findall(body or ''):
        if t not in QUICK_TOKENS and t not in STATIC_TOKENS and t not in out:
            out.append(t)
    return out


def lead_only_reason(tokens):
    """Why a reply stays off WhatsApp chats, for the toast: 'a trip date', "the lead's product" ..."""
    if any(t in DATE_TOKENS for t in tokens):
        return 'a trip date'
    if 'product' in tokens:
        return "the lead's product"
    return 'details of the lead'


def works_in(body):
    """Where a reply can be used: WORKS_CHATS, or the lead page and chat panel only."""
    tokens = lead_only(body)
    if not tokens:
        return WORKS_CHATS
    return WORKS_LEAD_DATE if any(t in DATE_TOKENS for t in tokens) else WORKS_LEAD


def help_rows(own_titles=None):
    """The Help & FAQ questions as read-only quick replies: [{'title', 'body', 'product', 'site', 'page',
    'site_arg'}]. Each question appears once (the first site wins, in help_center.SITE_KEYS order), none that an
    own reply already asks (ignoring case), and none with a blank question or answer."""
    from app.models import CrmAnswer
    from app.services import crm_products, help_center
    if own_titles is None:
        own_titles = [t for (t,) in db.session.query(CrmAnswer.title).all()]
    seen = {(t or '').strip().lower() for t in own_titles}
    codes = set(crm_products.codes())
    out = []
    for site in help_center.SITE_KEYS:
        for f in help_center.faqs(site):
            title = str(f.get('question') or '').strip()[:160]
            body = str(f.get('answer') or '').strip()
            if not title or not body or title.lower() in seen:
                continue
            seen.add(title.lower())
            product = HELP_PRODUCT.get(site, 'GEN')
            page, arg = HELP_PAGE.get(site, ('help', None))
            out.append({'title': title, 'body': body, 'site': site, 'page': page, 'site_arg': arg,
                        'product': product if product in codes else crm_products.general_code()})
    return out


def _quick_items():
    """Every reply WhatsApp chats can use, as its quick replies take them: own replies first (title as written,
    never the code), then the Help & FAQ questions. A reply with a lead-only fill-in is left out. A title is sent
    once (ignoring case, cut to 120 characters). Built inside a request, so the links are the site's."""
    from app.models import CrmAnswer
    static = _static_values()
    rows = [(a.title, a.body) for a in CrmAnswer.query.order_by(CrmAnswer.title).all()]
    rows += [(h['title'], h['body']) for h in help_rows([t for t, _ in rows])]
    items, seen = [], set()
    for title, body in rows:
        title = (title or '').strip()[:120]
        if not title or title.lower() in seen or lead_only(body):
            continue
        seen.add(title.lower())
        items.append({'title': title, 'text': quick_reply_text(body, static)})
    return items


def _quick_raw():
    from app.models import AppSetting
    row = db.session.get(AppSetting, QUICK_KEY, populate_existing=True)
    return row.value if row is not None and isinstance(row.value, dict) else {}


def quick_state():
    """What the portal last put in the WhatsApp CRM's quick replies, and the one-off steps:
    {titles, conflicts, due, error, at, coded_cleaned, import_missing, imported_at, imported, buttons}.
    Read past the settings cache: both workers and a background thread write it. Every save merges into this,
    so a push never drops the import keys and the reverse."""
    v = _quick_raw()
    return {'titles': [t for t in v.get('titles') or [] if isinstance(t, str) and t.strip()],
            'conflicts': [t for t in v.get('conflicts') or [] if isinstance(t, str)],
            'due': bool(v.get('due')), 'error': v.get('error'), 'at': v.get('at'),
            'coded_cleaned': bool(v.get('coded_cleaned')), 'import_missing': bool(v.get('import_missing')),
            'imported_at': v.get('imported_at'), 'imported': int(v.get('imported') or 0),
            'buttons': [b for b in v.get('buttons') or [] if isinstance(b, dict) and b.get('title')][:50]}


def _save_quick_state(state):
    from app.services import settings
    settings.set_setting(QUICK_KEY, state)        # commits


def conflict_words(titles):
    shown = ', '.join(titles[:5]) + (', …' if len(titles) > 5 else '')
    return QUICK_CONFLICT % (len(titles), shown)


def _old_coded_titles(state):
    """Release 1's WhatsApp titles of replies with a code (OLD_TITLE), for the one removal: the code and title
    of each reply that has a code, plus every stored title holding ' · '. Each once (ignoring case).
    [(title, text)]: the text is the matching reply's words, else the title (never empty: the WhatsApp CRM
    refuses an empty text)."""
    from app.models import CrmAnswer
    static = _static_values()
    out, seen = [], set()
    for a in CrmAnswer.query.filter(CrmAnswer.code.isnot(None)).all():
        t = (OLD_TITLE % (a.code, a.title)).strip()[:120]
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append((t, quick_reply_text(a.body, static) or t))
    for t in state['titles']:
        if ' · ' in t and t.strip().lower() not in seen:
            seen.add(t.strip().lower())
            out.append((t.strip(), t.strip()))
    return out


def push_quick_replies(items=None):
    """Every quick reply into the WhatsApp CRM's quick replies, matched by title. The ones this portal
    put there before and no longer has (renamed or removed here, or now needing a lead) go out with
    remove_titles, so nothing the portal made stays there, locked, for good (contract 21). Once, release 1's
    "CODE · title" rows are adopted and then removed. {created, updated, removed, conflicts}.
    Raises wacrm_team.TeamError, leaving the change marked for the jobs runner (unless only a person can fix
    it); the caller checks crm.wa_writes_on()."""
    from datetime import datetime
    from app.services import wacrm_team
    items = _quick_items() if items is None else items
    state = quick_state()
    have = {i['title'].strip().lower() for i in items}
    remove = [t for t in state['titles'] if t.strip().lower() not in have]
    try:
        if not state['coded_cleaned']:
            old = [(t, x) for t, x in _old_coded_titles(state) if t.lower() not in have]
            if old:
                # the WhatsApp CRM only takes out replies it knows are ours: push them once as items (adopted)
                wacrm_team.push_quick_replies([{'title': t, 'text': x} for t, x in old])
                known = {r.strip().lower() for r in remove}
                remove += [t for t, _ in old if t.lower() not in known]
        out = (wacrm_team.push_quick_replies(items, remove_titles=remove) if (items or remove)
               else {'created': 0, 'updated': 0, 'removed': 0, 'conflicts': []})
    except wacrm_team.TeamError as exc:
        if exc.status == 404:                    # a WhatsApp CRM without it: nothing to copy to, nothing waits
            _save_quick_state(dict(_quick_raw(), due=False, error=None))
        elif exc.code == 'rule_too_large':
            _save_quick_state(dict(_quick_raw(), due=False, error=QUICK_TOO_MANY))
        elif exc.status and 400 <= exc.status < 500 and exc.status not in (401, 403, 408, 429):
            _save_quick_state(dict(_quick_raw(), due=False, error=str(exc)[:250]))     # a person has to fix it
        else:
            _save_quick_state(dict(_quick_raw(), due=True, error=str(exc)[:250]))
        raise
    titles, seen = [], set()
    for i in items:
        k = i['title'].strip().lower()
        if k not in seen:
            seen.add(k)
            titles.append(i['title'].strip())
    _save_quick_state(dict(_quick_raw(), titles=titles[:QUICK_TITLES_MAX], conflicts=out['conflicts'], due=False,
                           error=None, at=datetime.utcnow().isoformat(timespec='seconds'), coded_cleaned=True))
    return out


def import_quick_replies():
    """One-off: the text quick replies somebody made by hand in WhatsApp become quick replies here -- no code,
    for any product -- so they are edited only here from now on; the next push makes them the portal's there
    (the WhatsApp CRM adopts a same-title text reply). Replies with buttons stay in WhatsApp and are only
    listed. {'added', 'already', 'buttons'}. Raises wacrm_team.TeamError (404: an older WhatsApp CRM --
    remembered, so the page says so). Commits."""
    from datetime import datetime
    from app.models import CrmAnswer
    from app.services import crm_products, wacrm, wacrm_team
    try:
        with wacrm.short_timeouts():
            rows = wacrm_team.quick_replies_unmanaged()
    except wacrm_team.TeamError as exc:
        if exc.status == 404:
            _save_quick_state(dict(_quick_raw(), import_missing=True))
        raise
    have = {(t or '').strip().lower() for (t,) in db.session.query(CrmAnswer.title).all()}
    added = already = 0
    buttons = []
    for r in rows:
        title = str(r.get('title') or '').strip()[:160]
        if not title:
            continue
        if r.get('type') == 'interactive':
            buttons.append({'title': title, 'body': str(r.get('body') or '')[:300]})
            continue
        body = WA_VAR_BACK.sub(lambda m: '{name}' if m.group(1) == 'contact' else '{agent}',
                               str(r.get('body') or '')).strip()[:4000]
        if not body:
            continue
        if title.lower() in have:
            already += 1
            continue
        have.add(title.lower())
        db.session.add(CrmAnswer(title=title, body=body, product=crm_products.general_code(), code=None))
        added += 1
    db.session.commit()
    _save_quick_state(dict(_quick_raw(), import_missing=False,
                           imported_at=datetime.utcnow().isoformat(timespec='seconds'),
                           imported=added, buttons=buttons[:50]))
    return {'added': added, 'already': already, 'buttons': len(buttons)}


def quick_replies_changed():
    """A quick reply was saved or removed here, so WhatsApp's quick replies follow straight away in a
    background thread (WA_SYNC_INLINE, in tests: here and now). Marked first, so the jobs runner tries
    again if that fails. Nothing while the portal may not write to WhatsApp, as for contacts."""
    from flask import current_app
    from app.services import crm, wacrm_team
    if not (crm.wa_writes_on() and wacrm_team.enabled()):
        return
    items = _quick_items()                       # here, in the request: the links are the site's
    _save_quick_state(dict(quick_state(), due=True))
    app = current_app._get_current_object()
    if app.config.get('WA_SYNC_INLINE'):
        _push_isolated(app, items)
        return
    try:
        threading.Thread(target=_push_isolated, args=(app, items), daemon=True, name='wacrm-quick').start()
    except Exception:      # noqa: BLE001 -- marked: the jobs runner copies them
        log.warning('Quick replies not copied after a save; the jobs runner copies them', exc_info=True)


def _push_isolated(app, items):
    from app.services import wacrm
    with app.app_context():                     # its own session: the save is already committed
        try:
            with wacrm.short_timeouts():
                push_quick_replies(items)
        except Exception:      # noqa: BLE001 -- still marked; the jobs runner tries again
            db.session.rollback()
            log.warning('Quick replies not copied to WhatsApp after a save', exc_info=True)
        finally:
            db.session.remove()


def run_quick_replies():
    """For the jobs runner: quick replies a save could not copy to WhatsApp, tried again while the
    portal may write to WhatsApp. Only inside a request (POST /internal/jobs/run): from the command line
    the links would come out as the bare site, so it waits for the next posted run.
    {'crm_wa_quick': 'copied' | 'failed'}, or {} when nothing waits."""
    from flask import has_request_context
    from app.services import crm, wacrm, wacrm_team
    if not (has_request_context() and crm.wa_writes_on() and wacrm_team.enabled()) or not quick_state()['due']:
        return {}
    try:
        with wacrm.short_timeouts():
            push_quick_replies()
    except wacrm_team.TeamError:
        return {'crm_wa_quick': 'failed'}
    return {'crm_wa_quick': 'copied'}
