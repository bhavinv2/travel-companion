"""Contacts: everybody the Sales CRM can reach, one row each (Contacts, the contact page, Find a person),
and how people come in and go out: the one exporter, the CSV import, the one-off WhatsApp imports,
Erase this person and the do-not-contact list -- and the intake set-up behind them (Where leads come
from: who gets a source's leads, its tags, the inboxes to check, the marketing activities).

Nothing here sends a message, and nothing here writes to the WhatsApp CRM except a person's own
tag change and an erase, both only while writes are on (crm.wa_writes_on).

The do-not-contact list keeps only salted hashes (HMAC with the app's SECRET_KEY): the table alone gives
nobody their number. Changing SECRET_KEY orphans old entries.
"""
import csv
import hashlib
import hmac
import io
import re
import time
from collections import Counter
from datetime import datetime, timedelta

from flask import Response, current_app, stream_with_context
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

from app import db
from app.models import (ActivityEvent, CrmDoNotContact, CrmIdentity, CrmLead, CrmPerson, CrmSource, CrmTask,
                        CrmTouchpoint, Notification, User)
from app.services import crm, crm_products, wacrm_team
from app.services import phone as phone_svc

# ------------------------------------------------------------------------------ wording

CONTACTS_EMPTY = 'No contacts yet. Everyone who fills a form, writes on WhatsApp or is added by you appears here.'
CONTACTS_NO_MATCH = 'No contacts match these filters.'
FIND_NONE = 'No one found.'
PERM_OK = 'Agreed to WhatsApp messages on %s (%s)'
PERM_OK_PLAIN = 'Agreed to WhatsApp messages'
PERM_NONE = 'Not asked yet'
PERM_OUT = 'Opted out on %s: we only answer if they write'
TAGS_NOT_IN_WA = "Not in WhatsApp yet. Their tags go there once they are."
TAG_MANAGED = 'That tag is set by the Sales CRM. Change their stage or source instead.'
TAG_UNKNOWN = "That tag isn't in WhatsApp yet. Someone who can open Tags can add it."
TAG_NO_CONTACT = "This contact isn't in WhatsApp yet."
NEEDS_UPDATE = 'Needs the WhatsApp CRM update'
NO_ANSWER = 'WhatsApp did not answer. Try again in a minute.'
DUP_ASK = '%s (%s) is already a contact. Add this enquiry to them?'
DUP_ADD = 'Add to %s'
DUP_OTHER = "It's someone else"
DUP_SAME_PHONE = "%s already has that number. Give this person's own number, or add the enquiry to %s."
DUP_SAME_HANDLE = "%s already has that %s handle. Give this person's own, or add the enquiry to %s."
DNC_ASK = 'This person asked to be erased on %s. Add them only if they contacted us again.'
DNC_YES = 'They contacted us again'
DNC_RECORD = 'This person asked to be erased, so they were not added. Add them by hand only if they contact us again.'
ERASE_TYPE = 'Type their name exactly as shown to confirm.'
ERASE_DONE = 'Erased. Everything listed is gone, and they are on the do-not-contact list.'
ERASE_WA = {'off': 'The WhatsApp chat was not erased because WhatsApp is not connected for leads.',
            'shared': 'The WhatsApp chat was not erased because another contact here uses it.',
            'ambiguous': 'The WhatsApp chat was not erased: two WhatsApp contacts could be this number. '
                         'Delete the right one in WhatsApp.',
            'old': 'The WhatsApp chat was not erased: the WhatsApp CRM needs its update.'}
ERASE_NO_ANSWER = 'WhatsApp did not answer, so nothing was erased. Try again in a minute.'
LOGIN_STAYS = 'Their website login (%s) stays: remove it in Site settings → Users'
DNC_LINE = 'They go on the do-not-contact list: imports skip them. If they fill in a form again, they are added back.'
WA_FEED_OFF = 'WhatsApp is not connected yet. Connect it in Set-up → WhatsApp connection.'
IMPORT_NOTE = 'Brought in from the list “%s”'
NOTE_FROM = 'From WhatsApp: %s'
FREE_SECONDS = 60
WA_FEED_START = '1970-01-01T00:00:00Z'
WA_IMPORT_PAGE, WA_IMPORT_PAGES, WA_IMPORT_BUDGET = 200, 5, 20     # contacts a page, pages a press, seconds a press
CSV_MAX_ROWS, CSV_MAX_BYTES = 2000, 2 * 1024 * 1024
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _ist(dt):
    return dt + crm.IST if dt else None


def _day(dt):
    """'12 Oct' in India time, no leading zero."""
    d = _ist(dt)
    return '%d %s' % (d.day, d.strftime('%b')) if d else ''


def _crm_url(endpoint, **values):
    from app.routes.crm import crm_url
    return crm_url(endpoint, **values)


# ------------------------------------------------------------------------------ do-not-contact

def dnc_hash(value):
    """sha256 of an E.164 phone or a lower-case e-mail, keyed with the app's SECRET_KEY (HMAC): the same
    person gives the same hash here, and the table alone gives nobody their number."""
    key = (current_app.config.get('SECRET_KEY') or '').encode('utf-8')
    return hmac.new(key, (value or '').strip().lower().encode('utf-8'), hashlib.sha256).hexdigest()


def dnc_find(e164=None, email=None):
    """The do-not-contact rows for this phone or e-mail (one query; none for neither)."""
    conds = []
    if e164:
        conds.append(CrmDoNotContact.phone_hash == dnc_hash(e164))
    if email:
        conds.append(CrmDoNotContact.email_hash == dnc_hash(email))
    if not conds:
        return []
    return CrmDoNotContact.query.filter(or_(*conds)).order_by(CrmDoNotContact.at).all()


def dnc_add(phone, email, actor, reason='erased'):
    """Remember somebody erased at their request, by hash. Nothing when there is no phone or e-mail."""
    phone, email = (phone or '').strip(), (email or '').strip().lower()
    if not phone and not email:
        return None
    row = CrmDoNotContact(phone_hash=dnc_hash(phone) if phone else None,
                          email_hash=dnc_hash(email) if email else None, reason=reason,
                          at=datetime.utcnow(), by_id=getattr(actor, 'id', None))
    db.session.add(row)
    return row


def dnc_forget(rows, source=None):
    """They contacted us again themselves: take them off the list, and log that (no commit)."""
    n = 0
    for r in rows:
        db.session.delete(r)
        n += 1
    if n:
        ActivityEvent.log('crm_dnc_cleared', source=source, n=n)
    return n


def dnc_count():
    return db.session.query(func.count(CrmDoNotContact.id)).scalar() or 0


def dnc_since(rows):
    """'12 Oct': the earliest row's date, in India time."""
    return _day(min((r.at for r in rows), default=None))


# ------------------------------------------------------------------------------ the matcher

def person_match(q):
    """SQL condition on CrmPerson: `q` is part of their name (every word), their phone in any format
    (phone_svc.matches; and the last 9 digits of a longer number), their e-mail, or an Instagram /
    Facebook handle. None for an empty q. Display only: it never links people."""
    q = ' '.join((q or '').split())[:80]
    if not q:
        return None
    like = '%%%s%%' % q
    parts = [phone_svc.matches(CrmPerson.phone, q), CrmPerson.email.ilike(like), CrmPerson.name.ilike(like)]
    d = phone_svc.search_digits(q)
    if len(d) >= 9:
        parts.append(CrmPerson.phone.like('%' + d[-9:] + '%'))
    words = q.split()
    if len(words) > 1:
        parts.append(and_(*[CrmPerson.name.ilike('%%%s%%' % w) for w in words]))
    h = crm.clean_identity('instagram', q) or q.strip().lstrip('@').lower()
    if h:
        parts.append(CrmPerson.id.in_(select(CrmIdentity.person_id).where(
            CrmIdentity.kind.in_(('instagram', 'facebook')), CrmIdentity.value.ilike('%' + h + '%'))))
    return or_(*parts)


def _activity_order():
    last = select(func.max(CrmLead.last_activity_at)).where(CrmLead.person_id == CrmPerson.id).scalar_subquery()
    return (func.coalesce(last, CrmPerson.created_at).desc(), CrmPerson.id.desc())


def _by_importance(leads):
    """Open leads first, then the most recently active."""
    ls = sorted(leads, key=lambda l: (l.last_activity_at or l.created_at or datetime.min), reverse=True)
    return sorted(ls, key=lambda l: l.status != 'open')


def short_reach(person):
    """How to show somebody before they are named for sure: '+91 98…', 'ab…@domain' or '@handle'."""
    if person.phone:
        return phone_svc.pretty(person.phone)[:6] + '…'
    if person.email:
        user, _, domain = person.email.partition('@')
        return '%s…@%s' % (user[:2], domain)
    handle = next((i.value for i in person.identities if i.kind in ('instagram', 'facebook')), None)
    return '@' + handle if handle else '—'


def find(q, user, limit=8):
    """Find a person (E25): {'items', 'contacts_url', 'add_url'} -- up to `limit` people (newest activity
    first) with every lead, open or closed, as chips; then site records nobody made a lead of
    (crm.search_records), to fill up to `limit`. A fixed number of queries. Display only."""
    q = ' '.join((q or '').split())[:80]
    out = {'items': [], 'contacts_url': _crm_url('contacts', q=q), 'add_url': _crm_url('add', name=q)}
    cond = person_match(q)
    if cond is None or len(q) < 2:
        return out
    people = (CrmPerson.query.options(selectinload(CrmPerson.identities)).filter(cond)
              .order_by(*_activity_order()).limit(limit).all())
    leads = {}
    if people:
        for l in (CrmLead.query.options(joinedload(CrmLead.stage))
                  .filter(CrmLead.person_id.in_([p.id for p in people]))):
            leads.setdefault(l.person_id, []).append(l)
    for p in people:
        ls = _by_importance(leads.get(p.id, []))
        out['items'].append({
            'kind': 'person', 'name': p.display_name, 'phone': phone_svc.pretty(p.phone) if p.phone else '',
            'email': p.email or '', 'url': _crm_url('contact', person_id=p.id),
            'chips': [{'text': '%s %s' % (l.product, l.stage.name if l.stage else 'Not routed'), 'state': l.status,
                       'url': _crm_url('lead', lead_id=l.id)} for l in ls]})
    free = limit - len(out['items'])
    if free > 0:
        for r in crm.search_records(q, limit=min(free, 4)):
            if r['lead'] is None and len(out['items']) < limit:
                out['items'].append({'kind': 'record', 'name': r['title'], 'label': r['label'], 'what': r['what'],
                                     'url': _crm_url('add', q=q, **{'from': 'existing'})})
    return out


# ------------------------------------------------------------------------------ the Contacts list

WA_FILTERS = (('waiting', 'Waiting on us'), ('nochat', 'No chat'), ('optout', 'Opted out'))
ENQ_FILTERS = (('yes', 'Yes'), ('no', 'No'))


def tag_choices():
    """The Tag filter's choices, the tags the Sales CRM itself puts on contacts: [(value, label)] -- each
    product's tag ('ti', 'Travel insurance · ti'), each source tag ('diwali', 'diwali · Source: Diwali
    page'), and 'opted-out' ('Opted out'). Tags made in WhatsApp are on each contact's page."""
    out = [(p.code.lower(), '%s · %s' % (p.name, p.code.lower())) for p in crm_products.all()]
    seen = {v for v, _ in out}
    for s in CrmSource.query.order_by(CrmSource.name).all():
        for t in s.crm_tags or []:
            t = str(t).strip().lower()
            if t and t not in seen:
                seen.add(t)
                out.append((t, '%s · Source: %s' % (t, s.name)))
    out.append((crm.OPT_OUT_TAG, 'Opted out'))
    return out


def contacts_filter(f, user):
    """The people Contacts shows, as a query (none runs here). `f`: tag, wa, enq, owner ('' anyone,
    'mine', 'none', '<user id>' -- whoever looks after one of their OPEN leads), q."""
    from app.services import crm_metrics
    query = CrmPerson.query
    tag = (f.get('tag') or '').strip().lower()
    if tag == crm.OPT_OUT_TAG:
        query = query.filter(CrmPerson.wa_opt_out_at.isnot(None))
    elif tag:
        if tag.upper() in set(crm_products.codes()):
            query = query.filter(CrmPerson.id.in_(select(CrmLead.person_id).where(
                func.upper(CrmLead.product) == tag.upper())))
        else:
            ids = [s.id for s in CrmSource.query.all() if tag in {str(t).strip().lower() for t in s.crm_tags or []}]
            query = query.filter(CrmPerson.id.in_(select(CrmLead.person_id).where(
                CrmLead.source_id.in_(ids or [0]))))
    wa = f.get('wa')
    if wa == 'waiting':
        w = crm_metrics.waiting_rows(CrmTouchpoint.person_id.isnot(None)).subquery()
        query = query.filter(CrmPerson.id.in_(select(w.c.person_id)))
    elif wa == 'nochat':
        query = query.filter(CrmPerson.wacrm_conversation_id.is_(None))
    elif wa == 'optout':
        query = query.filter(CrmPerson.wa_opt_out_at.isnot(None))
    enq = f.get('enq')
    if enq == 'yes':
        query = query.filter(CrmPerson.id.in_(select(CrmLead.person_id)))
    elif enq == 'no':
        query = query.filter(~CrmPerson.id.in_(select(CrmLead.person_id)))
    owner = f.get('owner') or ''
    if owner:
        opened = select(CrmLead.person_id).where(CrmLead.status == 'open')
        if owner == 'none':
            opened = opened.where(CrmLead.owner_id.is_(None))
        else:
            uid = getattr(user, 'id', None) if owner == 'mine' else (int(owner) if owner.isdigit() else 0)
            opened = opened.where(CrmLead.owner_id == uid)
        query = query.filter(CrmPerson.id.in_(opened))
    cond = person_match(f.get('q'))
    if cond is not None:
        query = query.filter(cond)
    return query.order_by(*_activity_order())


def contact_rows(people, now=None):
    """What each row (and each exported contact) shows, for many people in a fixed number of queries:
    {person id: {'leads': [lead...], 'chips': [(cls, text, url)], 'more': n, 'owner': name or None,
                 'last_contact': dt, 'wa': (cls, text), 'touch': last_touches entry}}."""
    from app.services import crm_metrics
    now = now or datetime.utcnow()
    ids = [p.id for p in people]
    if not ids:
        return {}
    leads = {}
    for l in (CrmLead.query.options(joinedload(CrmLead.stage), joinedload(CrmLead.owner))
              .filter(CrmLead.person_id.in_(ids)).order_by(CrmLead.created_at.desc())):
        leads.setdefault(l.person_id, []).append(l)
    touches = crm_metrics.last_touches(ids)
    last = dict(db.session.query(CrmTouchpoint.person_id, func.max(CrmTouchpoint.created_at))
                .filter(CrmTouchpoint.person_id.in_(ids), CrmTouchpoint.direction.in_(('in', 'out')),
                        CrmTouchpoint.channel != 'form').group_by(CrmTouchpoint.person_id).all())
    mode = crm.wa_mode()
    out = {}
    for p in people:
        ls = _by_importance(leads.get(p.id, []))
        entry = touches.get(p.id) or {}
        left = crm_metrics.window_left_hours(entry.get('wa_last_in'), now) if entry.get('wa_last_in') else None
        if p.wa_opt_out_at is not None:
            wa = ('optout', 'opted out')
        elif crm_metrics.waiting_on_us(entry):
            wa = ('wait', 'waiting on us')
        elif left:
            wa = ('open', 'open %dh' % left if left >= 1 else 'open under 1h')
        elif p.wacrm_conversation_id:
            wa = ('', 'chat')
        elif p.phone and mode != 'off':
            wa = ('nochat', 'no chat')
        else:
            wa = ('', '—')
        opened = [l for l in ls if l.status == 'open']
        out[p.id] = {'leads': ls, 'touch': entry, 'wa': wa, 'last_contact': last.get(p.id),
                     'chips': [('r-%s' % crm.stage_role(l.stage) if l.stage else 'r-none',
                                '%s %s' % (l.product, l.stage.name if l.stage else 'Not routed'),
                                _crm_url('lead', lead_id=l.id)) for l in ls[:4]],
                     'more': max(len(ls) - 4, 0),
                     'owner': (opened[0].owner.full_name if opened and opened[0].owner else None)}
    return out


# ------------------------------------------------------------------------------ the contact page

def permission(person):
    """The Permission card's line (E7): PERM_OUT with the IST date when they opted out; else PERM_OK with
    the date and form of the newest note starting 'Agreed to WhatsApp messages (' (PERM_OK_PLAIN when the
    flag is set without one); else PERM_NONE."""
    if person.wa_opt_out_at is not None:
        return PERM_OUT % _day(person.wa_opt_out_at)
    if person.consent_whatsapp:
        tp = (CrmTouchpoint.query.filter(CrmTouchpoint.person_id == person.id, CrmTouchpoint.channel == 'note',
                                         CrmTouchpoint.body.like('Agreed to WhatsApp messages (%'))
              .order_by(CrmTouchpoint.created_at.desc(), CrmTouchpoint.id.desc()).first())
        if tp is not None:
            m = re.search(r'\((.*)\)\s*$', tp.body or '')
            return PERM_OK % (_day(tp.created_at), m.group(1) if m else 'form')
        return PERM_OK_PLAIN
    return PERM_NONE


def sales_tags(person):
    """The tags the Sales CRM computes for them (shown locked, "automatic")."""
    return sorted(crm._wa_wanted_tags(person))


def is_sales_tag(name):
    n = (name or '').strip().lower()
    return n == crm.OPT_OUT_TAG or crm._wa_is_portal_tag(n, crm._wa_source_tags())


_free = {}          # contact key -> (monotonic time, [names])


def forget(contact_id=None):
    """Tests and every successful tag write."""
    if contact_id is None:
        _free.clear()
    else:
        _free.pop(str(contact_id), None)


def free_tags(person, force=False):
    """Their WhatsApp tags that are not Sales tags, sorted, or None when it cannot be asked (not connected,
    not in WhatsApp yet, no answer). From their chat (GET /api/portal/conversation/<id>) or, without one,
    their contact (v1), with short timeouts; kept FREE_SECONDS per contact in this process."""
    from app.services import wacrm, wacrm_team
    cid, conv = person.wacrm_contact_id, person.wacrm_conversation_id
    key = str(cid or conv or '')
    if not key or not (wacrm_team.enabled() or wacrm.enabled()):
        return None
    hit = _free.get(key)
    if hit and not force and time.monotonic() - hit[0] < FREE_SECONDS:
        return hit[1]
    tags = None
    try:
        with wacrm.short_timeouts():
            if conv and wacrm_team.enabled():
                info = wacrm_team.conversation_info(conv)
                if info is not None:
                    tags = (info.get('contact') or {}).get('tags')
            if tags is None and cid and wacrm.enabled():
                tags = (wacrm.get_contact(cid) or {}).get('tags')
    except (wacrm.WacrmError, wacrm_team.TeamError):
        tags = None
    if tags is None:
        return None
    names = sorted({(t.get('name') if isinstance(t, dict) else str(t)).strip() for t in tags
                    if (t.get('name') if isinstance(t, dict) else t)}, key=str.lower)
    names = [n for n in names if not is_sales_tag(n)]
    _free[key] = (time.monotonic(), names)
    return names


def remember_free(contact_id, names):
    _free[str(contact_id)] = (time.monotonic(), list(names))


def recent(person, limit=3):
    """The last `limit` messages either way across their leads (crm_timeline.BUBBLE_CHANNELS, in/out),
    newest first: [{'lead', 'side', 'icon', 'who', 'text', 'at'}]. One query."""
    from app.routes.crm import _said
    from app.services import crm_timeline
    rows = (CrmTouchpoint.query.options(joinedload(CrmTouchpoint.agent), joinedload(CrmTouchpoint.lead))
            .filter(CrmTouchpoint.person_id == person.id, CrmTouchpoint.channel.in_(crm_timeline.BUBBLE_CHANNELS),
                    CrmTouchpoint.direction.in_(('in', 'out')))
            .order_by(CrmTouchpoint.created_at.desc(), CrmTouchpoint.id.desc()).limit(limit).all())
    out = []
    for t in rows:
        out.append({'lead': t.lead, 'side': t.direction, 'icon': crm_timeline.ICONS.get(t.channel, 'fa-regular fa-comment'),
                    'who': 'They wrote' if t.direction == 'in' else (t.agent.full_name if t.agent else 'Us'),
                    'text': _said(t.body), 'at': t.created_at})
    return out


# ------------------------------------------------------------------------------ the contact form

def save_details(person, form, actor):
    """The one contact form (Edit details): name, phone (+ phone_cc), e-mail, Instagram, Facebook. Returns
    {} when saved (no commit) or {field: message}. A new number goes through crm.change_phone (their old
    WhatsApp contact loses the portal's tags; the new number gets its own), and any change marks them for
    the WhatsApp CRM (crm.mark_wa_due)."""
    errors = {}
    name = (form.get('name') or '').strip()[:120] or None
    raw_phone = (form.get('phone') or '').strip()
    e164 = crm.normalise_phone(raw_phone, form.get('phone_cc'))
    email = (form.get('email') or '').strip().lower() or None
    handles = {}
    if raw_phone and not e164:
        errors['phone'] = 'That phone number does not look right for the country chosen.'
    elif e164:
        other = CrmPerson.query.filter(CrmPerson.phone == e164, CrmPerson.id != person.id).first()
        if other is not None:
            errors['phone'] = 'That number belongs to %s already.' % other.display_name
    elif person.phone:
        errors['phone'] = 'A contact keeps a phone number once it has one. Type their new number to change it.'
    if email and not EMAIL_RE.match(email):
        errors['email'] = 'That e-mail address does not look right.'
    for kind in ('instagram', 'facebook'):
        raw = (form.get(kind) or '').strip()
        if not raw:
            handles[kind] = None
            continue
        v = crm.clean_identity(kind, raw)
        if not v:
            errors[kind] = 'That %s handle does not look right.' % kind.capitalize()
            continue
        other = CrmIdentity.query.filter_by(kind=kind, value=v).first()
        if other is not None and other.person_id != person.id:
            errors[kind] = 'That %s handle belongs to %s already.' % (kind.capitalize(), other.person.display_name)
        handles[kind] = v
    if not errors and not (e164 or person.phone or email or any(handles.values())):
        errors['phone'] = ('Keep at least one way to reach them: a phone, an e-mail, or an Instagram or '
                           'Facebook handle.')
    if errors:
        return errors
    changed = (name != person.name) or (email != (person.email or None))
    person.name = name
    person.email = email
    for kind, v in handles.items():
        have = next((i for i in person.identities if i.kind == kind), None)
        if v and have is None:
            person.identities.append(CrmIdentity(kind=kind, value=v))
            changed = True
        elif v and have.value != v:
            have.value = v
            changed = True
        elif not v and have is not None:
            person.identities.remove(have)
            changed = True
    if e164 and e164 != person.phone:
        crm.change_phone(person, e164)       # marks them itself
    elif changed:
        crm.mark_wa_due(person)
    db.session.flush()
    return {}


# ------------------------------------------------------------------------------ erase

class EraseRefused(Exception):
    """The WhatsApp CRM did not answer: nothing was erased."""


def _plural(n, one, many=None):
    return one if n == 1 else (many or one + 's')


def erase_plan(person):
    """Exactly what Erase this person removes, for the dialog and for erase(): {'leads', 'touches', 'tasks',
    'chat': bool, 'records': [{'kind', 'id', 'label'}], 'kept': [label], 'login': e-mail or None, 'bells'}.
    A fixed number of queries."""
    from app.models import ContactMessage, InsuranceQuote, SahayakBooking
    leads = CrmLead.query.filter_by(person_id=person.id).all()
    lead_ids = [l.id for l in leads] or [0]
    touches = db.session.query(func.count(CrmTouchpoint.id)).filter(CrmTouchpoint.person_id == person.id).scalar() or 0
    tasks = db.session.query(func.count(CrmTask.id)).filter(CrmTask.lead_id.in_(lead_ids)).scalar() or 0
    refs = {(l.ref_type, l.ref_id) for l in leads if l.ref_type and l.ref_id}
    records, kept = [], []
    for ref_type, rid in sorted(refs, key=lambda r: (r[0], r[1])):
        if ref_type == 'insurance_quotes':
            r = db.session.get(InsuranceQuote, rid)
            if r is not None:
                records.append({'kind': 'insurance_quote', 'id': rid,
                                'label': 'Their insurance quote request of %s' % _day(r.created_at)})
        elif ref_type == 'contact_messages':
            r = db.session.get(ContactMessage, rid)
            if r is not None:
                records.append({'kind': 'contact_message', 'id': rid,
                                'label': 'Their contact message of %s' % _day(r.created_at)})
        elif ref_type == 'sahayak_bookings':
            r = db.session.get(SahayakBooking, rid)
            if r is not None:
                records.append({'kind': 'sahayak_booking', 'id': rid,
                                'label': 'Their Sahayak booking of %s (%s)' % (_day(r.created_at), r.service_name)})
        elif ref_type == 'companion_requests':
            kept.append('Their trip post #%d stays: remove it in All posts' % rid)
    user = db.session.get(User, person.user_id) if person.user_id else None
    if user is None and person.email:
        user = User.query.filter(func.lower(User.email) == person.email.lower()).first()
    bells = 0
    if leads:
        bells = (db.session.query(func.count(Notification.id))
                 .filter(or_(*[Notification.link.like('%%/crm/lead/%d' % i) for i in lead_ids])).scalar() or 0)
    return {'leads': len(leads), 'touches': touches, 'tasks': tasks,
            # only promise the chat goes when erase() will really reach WhatsApp
            'chat': bool((person.wacrm_contact_id or person.phone) and crm.wa_writes_on() and wacrm_team.enabled()),
            'records': records, 'kept': kept, 'login': user.email if user is not None else None, 'bells': bells}


def erase(person, actor, now=None):
    """Erase this person (contract 28, H12): their chat in WhatsApp first (only while writes are on), then
    every portal row erase_plan lists and those website records -- never a User -- then a do-not-contact
    entry and one ActivityEvent without their name, number or e-mail. Commits. Returns the WhatsApp outcome:
    'erased' | 'gone' | 'none' | 'off' | 'shared' | 'ambiguous' | 'old'. Raises EraseRefused (nothing
    changed) when the WhatsApp CRM does not answer."""
    from app.models import ContactMessage, InsuranceQuote, SahayakBooking
    from app.services import admin_delete, wacrm, wacrm_team
    plan = erase_plan(person)
    cid, phone, email, pid = person.wacrm_contact_id, person.phone, person.email, person.id
    outcome = 'none'
    if crm.wa_writes_on() and wacrm_team.enabled():
        try:
            with wacrm.short_timeouts():
                if not cid and phone:
                    try:
                        r = wacrm_team.ensure_conversation(crm._digits(phone), create=False)
                        cid = r.get('contact_id')
                    except wacrm_team.TeamError as exc:
                        if exc.status == 409 or exc.code == 'ambiguous_contact':
                            outcome, cid = 'ambiguous', None
                        else:
                            raise EraseRefused(ERASE_NO_ANSWER) from exc
                if cid and outcome != 'ambiguous':
                    if CrmPerson.query.filter(CrmPerson.wacrm_contact_id == cid, CrmPerson.id != pid).first():
                        outcome = 'shared'
                    else:
                        try:
                            wacrm_team.erase_contact(cid)
                            outcome = 'erased'
                        except wacrm_team.TeamError as exc:
                            if exc.status == 404 and exc.code == 'not_found':
                                outcome = 'gone'
                            elif exc.status == 404:
                                outcome = 'old'
                            else:
                                raise EraseRefused(ERASE_NO_ANSWER) from exc
        except wacrm_team.TeamError as exc:        # noqa: BLE001 -- the first call failed
            raise EraseRefused(ERASE_NO_ANSWER) from exc
    elif cid or phone:
        outcome = 'off'
    # the portal rows
    for rec in plan['records']:
        model = {'insurance_quote': InsuranceQuote, 'contact_message': ContactMessage,
                 'sahayak_booking': SahayakBooking}[rec['kind']]
        row = db.session.get(model, rec['id'])
        if row is None:
            continue
        if rec['kind'] == 'contact_message':
            admin_delete._cascade_contact(row, actor, [])
        else:
            db.session.delete(row)
    leads = CrmLead.query.filter_by(person_id=pid).all()
    lead_ids = [l.id for l in leads]
    if lead_ids:
        Notification.query.filter(or_(*[Notification.link.like('%%/crm/lead/%d' % i) for i in lead_ids])) \
            .delete(synchronize_session=False)
    for l in leads:
        db.session.delete(l)
    db.session.flush()
    CrmTouchpoint.query.filter_by(person_id=pid).delete(synchronize_session=False)
    db.session.expire_all()
    person = db.session.get(CrmPerson, pid)
    db.session.delete(person)
    dnc_add(phone, email, actor)
    ActivityEvent.log('crm_person_erased', actor=actor, person_id=pid, leads=plan['leads'],
                      touches=plan['touches'], tasks=plan['tasks'],
                      records=[{'kind': r['kind'], 'id': r['id']} for r in plan['records']], whatsapp=outcome)
    db.session.commit()
    crm._wa_inbound.pop(crm._digits(phone), None)
    forget(cid)
    return outcome


# ------------------------------------------------------------------------------ the one exporter

LEAD_COLS = ['Name', 'Phone (with country code)', 'E-mail', 'Product', 'Pipeline', 'Stage', 'Open / Won / Lost',
             'Looked after by', 'Where they came from', 'Added on', 'Last contact', 'Next follow-up',
             'Travels on', 'Why it was lost']
CONTACT_COLS = ['Name', 'Phone (with country code)', 'E-mail', 'Instagram', 'Facebook', 'Enquiries',
                'Looked after by', 'Added on', 'Last contact']
WA_COLS = ['In WhatsApp', 'Opted out of WhatsApp', 'Last WhatsApp message', 'WhatsApp chat open']
EXPORT_BATCH = 500


def _cell(v):
    """A cell a spreadsheet will not run as a formula."""
    if v is None:
        return ''
    v = str(v)
    return "'" + v if v[:1] in ('=', '+', '-', '@', '\t', '\r') else v


def _stamp(dt):
    d = _ist(dt)
    return d.strftime('%Y-%m-%d %H:%M') if d else ''


def _plain_phone(e164):
    return phone_svc.pretty(e164).lstrip('+') if e164 else ''


def _wa_cells(person, entry, now):
    from app.services import crm_metrics
    wl = (entry or {}).get('wa_last')
    left = crm_metrics.window_left_hours((entry or {}).get('wa_last_in'), now) if (entry or {}).get('wa_last_in') else None
    return ['Yes' if person.wacrm_contact_id else 'No',
            _stamp(person.wa_opt_out_at),
            (_stamp(wl[1]) + (' (from them)' if wl[0] == 'in' else ' (from us)')) if wl else '',
            ('Yes (%dh left)' % left) if left and left >= 1 else ('Yes (under 1h left)' if left else 'No')]


def export(query, kind='leads', actor=None, filters=None):
    """The one "Download this list" (F3, H13): every row of `query` (CrmLead for 'leads', CrmPerson for
    'contacts') as a CSV that opens straight in Excel -- UTF-8 with a BOM -- 500 rows at a time, with the
    WhatsApp columns. The download is logged (ActivityEvent 'crm_export', committed first). A Response."""
    kind = 'contacts' if kind == 'contacts' else 'leads'
    model = CrmPerson if kind == 'contacts' else CrmLead
    ids = [i for (i,) in query.with_entities(model.id).all()]
    ActivityEvent.log('crm_export', actor=actor, kind=kind, rows=len(ids), filters=filters or {})
    db.session.commit()
    today = (datetime.utcnow() + crm.IST).strftime('%Y-%m-%d')

    def line(cells):
        buf = io.StringIO()
        csv.writer(buf).writerow(cells)
        return buf.getvalue()

    def rows():
        yield '﻿' + line((LEAD_COLS if kind == 'leads' else CONTACT_COLS) + WA_COLS)
        now = datetime.utcnow()
        for i in range(0, len(ids), EXPORT_BATCH):
            chunk = ids[i:i + EXPORT_BATCH]
            if kind == 'leads':
                found = {l.id: l for l in (CrmLead.query.options(*crm.lead_load(), joinedload(CrmLead.pipeline),
                                                                 joinedload(CrmLead.source))
                                           .filter(CrmLead.id.in_(chunk)))}
                batch = [found[x] for x in chunk if x in found]
                cards = crm.lead_cards(batch, now)
                for l in batch:
                    c, p = cards[l.id], l.person
                    task = c['task']
                    yield line([_cell(v) for v in [
                        p.display_name, _plain_phone(p.phone), p.email, l.product,
                        l.pipeline.name if l.pipeline else '', l.stage.name if l.stage else '', l.status,
                        l.owner.full_name if l.owner else '', l.source.name if l.source else '',
                        _stamp(l.created_at), _stamp(c['last_contact']), _stamp(task.due_at) if task else '',
                        l.departure_date.isoformat() if l.departure_date else '', l.fallout_reason or '']]
                        + _wa_cells(p, c['touch'], now))
            else:
                found = {p.id: p for p in CrmPerson.query.options(selectinload(CrmPerson.identities))
                         .filter(CrmPerson.id.in_(chunk))}
                batch = [found[x] for x in chunk if x in found]
                info = contact_rows(batch, now)
                for p in batch:
                    r = info[p.id]
                    yield line([_cell(v) for v in [
                        p.display_name, _plain_phone(p.phone), p.email,
                        p.identity('instagram'), p.identity('facebook'),
                        ', '.join('%s %s' % (l.product, l.stage.name if l.stage else 'Not routed') for l in r['leads']),
                        r['owner'] or '', _stamp(p.created_at), _stamp(r['last_contact'])]]
                        + _wa_cells(p, r['touch'], now))

    return Response(stream_with_context(rows()), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=%s-%s.csv' % (kind, today)})


# ------------------------------------------------------------------------------ CSV import

FIELDS = (('name', 'Name'), ('phone', 'Phone'), ('email', 'E-mail'), ('product', 'Product'),
          ('source', 'Where they came from'), ('owner', 'Looked after by'), ('stage', 'Stage'))
GUESS = {'name': ('name', 'full name', 'customer', 'lead', 'contact name'),
         'phone': ('phone', 'mobile', 'whatsapp', 'phone number', 'mobile number', 'contact number'),
         'email': ('email', 'e-mail', 'email address', 'email id'),
         'product': ('product', 'interested in', 'enquiry', 'service'),
         'source': ('source', 'lead source', 'came from', 'where'),
         'owner': ('owner', 'looked after by', 'assigned to', 'agent', 'sales person'),
         'stage': ('stage', 'status')}
WHAT = {'new': 'New lead', 'existing': 'New enquiry for an existing contact', 'already': 'Skipped: already here',
        'unreachable': 'Skipped: no phone or e-mail', 'dnc': 'Skipped: on the do-not-contact list'}


def read_csv(path):
    """(headers, rows): utf-8-sig, else cp1252; the delimiter sniffed among , ; and tab (',' when unsure);
    blank rows dropped. ValueError with a sentence for a file that is not a list we can read, or longer than
    CSV_MAX_ROWS."""
    with open(path, 'rb') as fh:
        raw = fh.read(CSV_MAX_BYTES + 1)
    if len(raw) > CSV_MAX_BYTES:
        raise ValueError('Choose a .csv file of at most 2 MB.')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp1252', errors='replace')
    head = text[:4096]
    delim = max((',', ';', '\t'), key=lambda d: head.count(d)) if any(d in head for d in (',', ';', '\t')) else ','
    try:
        table = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any((c or '').strip() for c in r)]
    except csv.Error as exc:
        raise ValueError('That file could not be read as a list.') from exc
    if len(table) < 2:
        raise ValueError('That file has no rows to import. The first row must be the column names.')
    if len(table) - 1 > CSV_MAX_ROWS:
        raise ValueError('This list has more than %d rows. Split it and import each part.' % CSV_MAX_ROWS)
    headers = [h.strip() for h in table[0]]
    return headers, table[1:]


def guess_map(headers):
    """{field: column index or None}, from the column names."""
    low = [h.strip().lower() for h in headers]
    out = {}
    for field, names in GUESS.items():
        out[field] = next((low.index(n) for n in names if n in low), None)
    return out


def _cellv(row, idx):
    if idx is None or idx >= len(row):
        return ''
    return (row[idx] or '').strip()


def plan_csv(path, mapping, defaults, staff=()):
    """What importing would do, row by row, without storing anything: {'total', 'counts': Counter(new,
    existing, already, unreachable, dnc), 'preview': first 10 [{values..., 'what'}], 'rows': all resolved}.
    `mapping`: {field: column index or None}. `defaults`: product code, source key, owner id (None: whoever
    is least busy), phone_cc."""
    _, table = read_csv(path)
    crm.ensure_defaults()
    sources = {s.key.lower(): s for s in CrmSource.query.all()}
    by_name = {s.name.lower(): s for s in sources.values()}
    default_src = sources.get((defaults.get('source') or 'csv-import').lower()) or sources.get('csv-import')
    default_product = crm_products.by_code(defaults.get('product'))
    products = {p.name.lower(): p for p in crm_products.all()}
    owners = {}
    for u in staff:
        for k in (u.email, u.full_name, u.username):
            if k:
                owners[str(k).strip().lower()] = u
    default_owner = next((u for u in staff if u.id == defaults.get('owner')), None)
    counts, rows, seen = Counter(), [], set()
    for row in table:
        name = _cellv(row, mapping.get('name'))
        e164 = crm.normalise_phone(_cellv(row, mapping.get('phone')), defaults.get('phone_cc') or 'IN')
        email = _cellv(row, mapping.get('email')).lower() or None
        if email and not EMAIL_RE.match(email):
            email = None
        text = _cellv(row, mapping.get('product')).lower()
        product = (crm_products.by_code(text) or products.get(text) or default_product) if text else default_product
        stext = _cellv(row, mapping.get('source')).lower()
        src = (sources.get(stext) or by_name.get(stext)) if stext else None
        src = src or default_src
        pipe = crm.pipeline_for(src, product.code if product else src.product)[0] if src else None
        stage_text = _cellv(row, mapping.get('stage')).lower()
        stage = next((s for s in pipe.stages if s.name.lower() == stage_text), None) if pipe and stage_text else None
        owner = owners.get(_cellv(row, mapping.get('owner')).lower()) or default_owner
        key = e164 or email
        if not e164 and not email:
            what = 'unreachable'
        elif dnc_find(e164, email):
            what = 'dnc'
        elif key in seen:
            what = 'already'
        else:
            person = crm.find_person(e164, email, None)
            seen.add(key)
            if person is None:
                what = 'new'
            elif pipe is not None and CrmLead.query.filter_by(person_id=person.id, pipeline_id=pipe.id,
                                                              status='open').first():
                what = 'already'
            else:
                what = 'existing'
        counts[what] += 1
        rows.append({'name': name, 'phone': e164, 'email': email, 'product': product.code if product else None,
                     'source': src, 'stage': stage, 'owner': owner, 'what': what})
    preview = [{'name': r['name'] or '—', 'phone': phone_svc.pretty(r['phone']) if r['phone'] else '—',
                'email': r['email'] or '—', 'product': r['product'] or '—', 'stage': r['stage'].name if r['stage'] else '—',
                'owner': r['owner'].full_name if r['owner'] else 'Whoever is least busy', 'what': WHAT[r['what']]}
               for r in rows[:10]]
    return {'total': len(rows), 'counts': counts, 'preview': preview, 'rows': rows}


def import_csv(path, mapping, defaults, filename, staff=()):
    """Store what plan_csv shows, quietly (F7, contract 19): each new person through crm.capture with
    sync=False, plan=False, notify=False, imported=True and refuse_dnc=True, so nobody is messaged,
    tagged or given a follow-up until "Add existing leads and customers to WhatsApp". Returns the Counter."""
    plan = plan_csv(path, mapping, defaults, staff)
    counts = Counter()
    for r in plan['rows']:
        if r['what'] not in ('new', 'existing'):
            counts[r['what']] += 1
            continue
        stage = r['stage']
        try:
            lead = crm.capture(r['source'].key, name=r['name'] or None, phone=r['phone'], email=r['email'],
                               product=r['product'], start_stage=stage, utm={}, plan=False, notify=False,
                               sync=False, imported=True, refuse_dnc=True,
                               note=IMPORT_NOTE % (filename or 'list')[:120], created_by_id=None,
                               fallout_reason='From an imported list' if stage is not None and stage.kind == 'lost' else None)
        except crm.DoNotContact:
            counts['dnc'] += 1
            continue
        if lead is None:
            counts['unreachable'] += 1
            continue
        if r['owner'] is not None and lead.owner_id != r['owner'].id:
            lead.owner_id = r['owner'].id
            for t in lead.tasks:
                if t.status == 'open':
                    t.owner_id = r['owner'].id
            db.session.commit()
        counts[r['what']] += 1
    return counts


# ------------------------------------------------------------------------------ From WhatsApp (one-off)

def strict_matches(digits):
    """People here whose number is this WhatsApp number by the strict rule (crm.same_whatsapp_number):
    the exact E.164 alone when there is one, else every near match (several = ambiguous)."""
    d = crm._digits(digits)
    if len(d) < 8:
        return []
    e164 = crm.wa_e164(d)
    exact = CrmPerson.query.filter_by(phone=e164).first() if e164 else None
    if exact is not None:
        return [exact]
    return [p for p in CrmPerson.query.filter(CrmPerson.phone.like('%' + d[-8:])).limit(20).all()
            if crm.same_whatsapp_number(p.phone, d)]


def _held(cid):
    return (CrmPerson.query.filter_by(wacrm_contact_id=cid).first() is not None
            or CrmIdentity.query.filter_by(kind='wacrm', value=cid).first() is not None)


def wa_import_contacts(since=None, budget=WA_IMPORT_BUDGET):
    """One press of "Bring in WhatsApp-only contacts" (H2): up to WA_IMPORT_PAGES pages of GET
    /api/portal/contacts from `since`. A WhatsApp contact nobody here has becomes a contact with no lead and
    its wacrm_contact_id -- not marked for sync, nothing written to WhatsApp. One matched by the strict
    phone rule is linked only when nobody here holds that contact id and they hold no other one. Commits
    a page at a time; safe to run again. {'done', 'since' (carry on from), 'looked', 'counts'}.
    TeamError as raised (404 without a code: an older WhatsApp CRM)."""
    from app.services import wacrm_team
    started = time.monotonic()
    since = since or WA_FEED_START
    counts, looked, done = Counter(), 0, False
    for _ in range(WA_IMPORT_PAGES):
        page = wacrm_team.contacts_export(since, WA_IMPORT_PAGE)
        for item in page['items']:
            looked += 1
            cid = str(item.get('contact_id') or '').strip()[:64]
            if not cid or _held(cid):
                counts['already'] += 1
                continue
            digits = crm._digits(item.get('phone'))
            e164 = crm.wa_e164(digits) if digits else None
            if not e164:
                counts['no_number'] += 1
                continue
            if dnc_find(e164, (item.get('email') or '').strip().lower() or None):
                counts['dnc'] += 1
                continue
            near = strict_matches(digits)
            if len(near) > 1:
                counts['ambiguous'] += 1
            elif near:
                if near[0].wacrm_contact_id:
                    counts['other_contact'] += 1
                else:
                    near[0].wacrm_contact_id = cid
                    counts['linked'] += 1
            else:
                email = (item.get('email') or '').strip().lower()
                db.session.add(CrmPerson(phone=e164, name=crm._wa_name(item.get('name')),
                                         email=email if EMAIL_RE.match(email) else None,
                                         country=(phone_svc.iso_for(e164) or '')[:2] or None,
                                         wacrm_contact_id=cid))
                counts['brought_in'] += 1
            db.session.flush()
        db.session.commit()
        nxt = page.get('next_since')
        if not nxt:
            done = True
            break
        since = nxt
        if time.monotonic() - started > budget:
            break
    return {'done': done, 'since': None if done else since, 'looked': looked, 'counts': dict(counts)}


def wa_import_notes(since=None, budget=WA_IMPORT_BUDGET):
    """One press of "Bring in WhatsApp notes" (F14): the feed's notes onto each linked person's newest lead
    as notes, at their real time, "From WhatsApp: <author>", each once (same body and time). People here
    with no lead yet are counted, not given one -- run it again after they have one."""
    from app.services import wacrm_team
    started = time.monotonic()
    since = since or WA_FEED_START
    counts, looked, done = Counter(), 0, False
    for _ in range(WA_IMPORT_PAGES):
        page = wacrm_team.contacts_export(since, WA_IMPORT_PAGE)
        items = [i for i in page['items'] if i.get('notes')]
        looked += len(page['items'])
        cids = [str(i.get('contact_id')) for i in items if i.get('contact_id')]
        people = {p.wacrm_contact_id: p for p in CrmPerson.query.filter(CrmPerson.wacrm_contact_id.in_(cids or ['-']))}
        emails = {(n.get('author_email') or '').lower() for i in items for n in i['notes'] if n.get('author_email')}
        staff = {u.email.lower(): u for u in User.query.filter(func.lower(User.email).in_(list(emails) or ['-']))}
        have = set()
        if people:
            for pid, at, body in (db.session.query(CrmTouchpoint.person_id, CrmTouchpoint.created_at, CrmTouchpoint.body)
                                  .filter(CrmTouchpoint.person_id.in_([p.id for p in people.values()]),
                                          CrmTouchpoint.channel == 'note',
                                          CrmTouchpoint.body.like(NOTE_FROM % '%'))):
                have.add((pid, at, body))
        newest = {}
        if people:
            for l in (CrmLead.query.filter(CrmLead.person_id.in_([p.id for p in people.values()]))
                      .order_by(CrmLead.created_at, CrmLead.id)):
                newest[l.person_id] = l
        for item in items:
            person = people.get(str(item.get('contact_id')))
            for n in item['notes']:
                if person is None:
                    counts['not_here'] += 1
                    continue
                lead = newest.get(person.id)
                if lead is None:
                    counts['no_lead'] += 1
                    continue
                at = crm._parse_utc(n.get('created_at')) or datetime.utcnow()
                email = (n.get('author_email') or '').lower()
                author = (staff[email].full_name if email in staff else None) or email or 'WhatsApp'
                body = (NOTE_FROM % author) + '\n' + (n.get('body') or '')[:3900]
                if (person.id, at, body) in have:
                    counts['already'] += 1
                    continue
                have.add((person.id, at, body))
                db.session.add(CrmTouchpoint(lead=lead, person_id=person.id, channel='note', direction='none',
                                             body=body, created_at=at))
                counts['copied'] += 1
        db.session.commit()
        nxt = page.get('next_since')
        if not nxt:
            done = True
            break
        since = nxt
        if time.monotonic() - started > budget:
            break
    return {'done': done, 'since': None if done else since, 'looked': looked, 'counts': dict(counts)}


# ------------------------------------------------------------------------------ Where leads come from

def goes_to(src, staff_by_id, teams_by_id):
    """The Sources table's "Goes to": 'Anyone in sales', 'Team: Sales India', 'Priya Sharma' or '3 people'."""
    team = src.team
    if isinstance(team, dict):
        t = teams_by_id.get(int(team.get('team_id') or 0))
        return 'Team: %s' % t.name if t is not None else 'Anyone in sales'
    ids = [int(i) for i in team or [] if str(i).isdigit()]
    names = [staff_by_id[i].full_name for i in ids if i in staff_by_id]
    if not names:
        return 'Anyone in sales'
    return names[0] if len(names) == 1 else '%d people' % len(names)


def really_goes(src):
    """(pipeline its leads really go to or None, the catch-all sentence or None), from crm.pipeline_for:
    "Leads from this source go to Travel insurance sales (General enquiry passes on leads with a known
    product)." -- or "<name> is not taking new leads, so its leads go to <other>."."""
    if src.pipeline is None or src.status == 'unrouted':
        return None, None
    chosen = src.pipeline
    pipe, _ = crm.pipeline_for(src, src.product)
    if pipe is None:
        return None, None
    if chosen.catch_all and pipe.id == chosen.id:
        return pipe, ("Leads from this source go to %s (%s passes on leads with a known product)."
                      % (pipe.name, chosen.name))
    if pipe.id != chosen.id:
        if not chosen.is_active:
            return pipe, '%s is not taking new leads, so its leads go to %s.' % (chosen.name, pipe.name)
        return pipe, ('Leads from this source go to %s (%s passes on leads with a known product).'
                      % (pipe.name, chosen.name))
    return pipe, None


def parse_routing(form, staff_ids, team_ids):
    """(team value, error): who='anyone' -> None; 'team' -> {'team_id': n} ('Choose a team.' when n is not
    one); 'people' -> the ticked ids ('team' checkboxes) or None; no 'who' (an older form) -> the ticked
    ids as before."""
    who = form.get('who')
    ticked = [int(x) for x in form.getlist('team') if str(x).isdigit() and int(x) in staff_ids] or None
    if who == 'anyone':
        return None, None
    if who == 'team':
        tid = form.get('team_id', type=int)
        return ({'team_id': tid}, None) if tid in team_ids else (None, 'Choose a team.')
    return ticked, None


def source_tag_problem(tag, take_over=()):
    """F56 for a tag a source would start adding: None, or {'error'} / {'error', 'clash', 'take_over'}."""
    from app.services import crm_editor
    t = (tag or '').strip().lower()
    if not re.match(r'^[a-z0-9][a-z0-9 _.&-]{0,29}$', t):
        return {'error': 'Use letters, digits, spaces and - only, at most 30.'}
    if t == crm.OPT_OUT_TAG:
        return {'error': crm_editor.L_RESERVED}
    if t.upper() in set(crm_products.codes()) or t in {c.lower() for c in crm_products.codes()}:
        return {'error': '“%s” is a product tag. Pick another tag.' % t}
    if any(t.startswith(x + ': ') for x in crm._wa_rule()[1]):
        return {'error': 'That looks like a stage tag. Pick another name.'}
    clash = crm_editor._first_clash(crm.wa_tag_clashes(names=[t]))
    if clash and t not in {str(x).strip().lower() for x in take_over}:
        return {'error': crm_editor._clash_said(clash), 'clash': clash, 'take_over': crm_editor.TAKE_OVER}
    return None


def parse_inboxes(form, source_keys):
    """Inboxes to check from the editor: rows in the order of form.getlist('row') (one key per row), each
    name_<k> (<=40, unique ignoring case, empty rows dropped), source_<k> (a known key or None), auto_<k>
    (kept only for the WhatsApp source). (rows <=30, errors)."""
    wa_key = current_app.config.get('WACRM_SOURCE_KEY', 'wa-india')
    rows, errors, seen = [], [], set()
    for k in form.getlist('row'):
        name = (form.get('name_%s' % k) or '').strip()[:40]
        if not name:
            continue
        if name.lower() in seen:
            errors.append('“%s” is in the list twice.' % name)
            continue
        seen.add(name.lower())
        src = (form.get('source_%s' % k) or '').strip()
        src = src if src in source_keys else None
        rows.append({'name': name, 'source_key': src, 'auto': bool(form.get('auto_%s' % k)) and src == wa_key})
    if len(rows) > 30:
        errors.append('At most 30 inboxes.')
    if not rows and not errors:
        errors.append('Keep at least one inbox to check.')
    return rows[:30], errors


def parse_activities(form):
    """Marketing activities from the table editor: aligned getlists platform / activity / who / status; a
    row needs a platform or an activity; at most 80. [[4 strings]]."""
    cols = [form.getlist(k) for k in ('platform', 'activity', 'who', 'status')]
    out = []
    for i in range(max(len(c) for c in cols)):
        row = [(c[i] if i < len(c) else '').strip()[:200] for c in cols]
        if row[0] or row[1]:
            out.append(row)
    return out[:80]


def check_auto(rows, now=None):
    """The inboxes that tick themselves right now (crm.check_ticks_itself): [{'row', 'waiting': [{'lead',
    'person', 'since'}], 'n'}] -- people waiting on us on WhatsApp longer than the waiting-bell minutes (the
    'crm' setting, 15), for at most crm.WAITING_ALERT_MAX, oldest first. Two queries."""
    from app.services import crm_metrics
    auto = [r for r in rows if crm.check_ticks_itself(r)]
    if not auto:
        return []
    now = now or datetime.utcnow()
    minutes = crm.crm_settings()['waiting_alert_minutes']
    w = crm_metrics.waiting_rows(CrmTouchpoint.person_id.in_(
        select(CrmTouchpoint.person_id).where(CrmTouchpoint.channel == 'whatsapp', CrmTouchpoint.direction == 'in',
                                              CrmTouchpoint.created_at > now - crm.WAITING_ALERT_MAX))).subquery()
    waiting = db.session.execute(
        select(w.c.person_id, w.c.lead_id, w.c.created_at)
        .where(w.c.channel == 'whatsapp', w.c.created_at <= now - timedelta(minutes=minutes))
        .order_by(w.c.created_at)).all()
    leads = {}
    if waiting:
        for l in (CrmLead.query.options(joinedload(CrmLead.person).selectinload(CrmPerson.identities))
                  .filter(CrmLead.id.in_([x.lead_id for x in waiting if x.lead_id] or [0]))):
            leads[l.id] = l
        missing = [x.person_id for x in waiting if x.lead_id not in leads]
        if missing:
            for l in (CrmLead.query.options(joinedload(CrmLead.person).selectinload(CrmPerson.identities))
                      .filter(CrmLead.person_id.in_(missing)).order_by(CrmLead.last_activity_at.desc())):
                leads.setdefault(('p', l.person_id), l)
    items = []
    for x in waiting:
        lead = leads.get(x.lead_id) or leads.get(('p', x.person_id))
        if lead is not None:
            items.append({'lead': lead, 'since': x.created_at})
    return [{'row': r, 'waiting': items, 'n': len(items)} for r in auto]
