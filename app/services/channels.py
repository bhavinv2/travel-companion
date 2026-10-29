"""Set-up › Channels (2026-10-29): every WhatsApp number the portal works with, the system that answers each, and the
kinds of provider behind them -- the one place that says which system talks to which number.

Three kinds of provider today, each described by the same checklist (CHECKLIST), so the portal turns on only what a
provider can do and the next one is an adapter and a card:

    wacrm   our WhatsApp CRM: its own number (India), its inbox, broadcasts, reply rules, chatbot
    meta    Meta direct: a number the portal talks to itself through Meta's Cloud API (services/wa_meta.py), one
            CrmChannelLine each (+1 917 900 5094, connected 29 Oct 2026)
    tawk    tawk.to: the website chat; it only listens (it has no way for another system to answer)

A WhatsApp message keeps the number it went through (CrmTouchpoint.line_id; NULL = the WhatsApp CRM's), and a person
the number they last wrote to (CrmPerson.wa_line_id), so the 24 hours, the templates and the reply all go by number.

    lines(...)            the Meta-direct numbers
    line_for(person)      the number a message to them goes out on: the one they last wrote to; somebody who never
                          wrote, the first live number whose prefixes their number starts with; else None (the CRM's)
    sender(line) / templates(line)   what the send paths in crm.py call for that number
    numbers(ws)           the rows of "Numbers & who answers"
    record(events)        a delivery from Meta, filed (routes/channels.py's webhook)
"""
import re
import secrets as _secrets
from datetime import datetime

from app import db
from app.models import CrmChannelLine, CrmPerson, CrmTouchpoint

# what a provider can do, in the order the page lists it
CHECKLIST = (('hear', 'Hears each message as it arrives'), ('whole', 'Hears the whole chat'),
             ('phone', 'Knows their phone number'), ('reply', 'Replies from the portal'),
             ('templates', 'Sends approved templates'), ('auto', 'Sends follow-ups by itself'),
             ('status', 'Says delivered and read'), ('own', 'Has its own inbox screens'))
PROVIDERS = {
    'wacrm': {'label': 'Our WhatsApp CRM', 'icon': 'fa-brands fa-whatsapp', 'color': '#1f5fc0',
              'says': 'Its own inbox, templates, broadcasts, reply rules, chatbot and AI replies, framed in the '
                      'portal; every message also lands on the lead.',
              'can': {'hear': True, 'whole': True, 'phone': True, 'reply': True, 'templates': True, 'auto': True,
                      'status': True, 'own': True}},
    'meta': {'label': 'Meta direct', 'icon': 'fa-solid fa-plug-circle-bolt', 'color': '#0866ff',
             'says': "The portal talks to Meta's WhatsApp Cloud API itself: replies, templates and follow-ups from "
                     'the lead page and All conversations.',
             'can': {'hear': True, 'whole': True, 'phone': True, 'reply': True, 'templates': True, 'auto': True,
                     'status': True, 'own': 'The lead page and All conversations'}},
    'tawk': {'label': 'tawk.to', 'icon': 'fa-solid fa-comment-dots', 'color': '#03a84e',
             'says': 'The website chat bubble. On a WhatsApp number it shares it only listens: tawk.to has no way '
                     'for another system to answer.',
             'can': {'hear': 'First message only', 'whole': 'When the chat ends', 'phone': 'Not sent',
                     'reply': False, 'templates': False, 'auto': False, 'status': False, 'own': 'In tawk.to'}},
}
STATUS_WORDS = {'new': 'Not connected yet', 'live': 'Live', 'paused': 'Paused', 'error': 'Needs attention'}
KEY_RE = re.compile(r'[^a-z0-9]+')
PREFIX_RE = re.compile(r'^\+\d{1,4}$')
LANGUAGE = 'en'


# ================================================================================================= numbers

def lines(live_only=False):
    q = CrmChannelLine.query.order_by(CrmChannelLine.id)
    if live_only:
        q = q.filter(CrmChannelLine.status == 'live')
    return q.all()


def get(line_id):
    return db.session.get(CrmChannelLine, line_id) if line_id else None


def by_number_id(pnid):
    return CrmChannelLine.query.filter_by(phone_number_id=str(pnid or '')).first() if pnid else None


def line_workspace(line):
    from app.services import crm_scope
    return line.workspace_id if line.workspace_id is not None else crm_scope.default_id()


def secrets_of(line):
    """{'token', 'app_secret'} as saved; None when they cannot be read (the server's SECRET_KEY changed)."""
    from app.services import secretbox
    return secretbox.open(line.secrets) if line is not None else {}


def set_secrets(line, token=None, app_secret=None, clear=False):
    """Keep a new token and/or app secret (a blank one keeps what was saved). No commit."""
    from app.services import secretbox
    have = {} if clear else (secrets_of(line) or {})
    if token:
        have['token'] = token.strip()
    if app_secret:
        have['app_secret'] = app_secret.strip()
    line.secrets = secretbox.seal(have) if have else None


def app_secrets():
    """Every Meta app secret a delivery may be signed with: each number's own, then the server's WA_META_APP_SECRET
    and META_APP_SECRET (comma-separated lists)."""
    import os
    out = []
    for line in lines():
        s = (secrets_of(line) or {}).get('app_secret')
        if s and s not in out:
            out.append(s)
    for name in ('WA_META_APP_SECRET', 'META_APP_SECRET'):
        for s in (os.environ.get(name) or '').split(','):
            if s.strip() and s.strip() not in out:
                out.append(s.strip())
    return out


def new_verify_token():
    return 'nps-' + _secrets.token_urlsafe(24)


def free_key(label):
    base = KEY_RE.sub('-', (label or 'number').lower()).strip('-')[:24] or 'number'
    key, n = base, 2
    while CrmChannelLine.query.filter_by(key=key).first() is not None:
        key, n = '%s-%d' % (base, n), n + 1
    return key


def clean_prefixes(text):
    """'+1, +44' -> ['+1', '+44']; anything that is not a + and 1-4 digits is dropped."""
    out = []
    for p in re.split(r'[\s,;]+', text or ''):
        p = p.strip()
        if p and not p.startswith('+'):
            p = '+' + p
        if PREFIX_RE.match(p) and p not in out:
            out.append(p)
    return out[:8]


def ensure_source(line):
    """The lead source the number's newcomers come in under ("WhatsApp USA · chat"), made once in its workspace."""
    from app.models import CrmSource
    from app.services import crm_scope
    key = line.source_key or ('wa-%s' % line.key)[:60]
    line.source_key = key
    with crm_scope.use(line_workspace(line)):
        src = CrmSource.query.filter_by(key=key).first()
        if src is None:
            db.session.add(CrmSource(key=key, name=('WhatsApp %s · chat' % line.label)[:100], kind='chat',
                                     product='GEN', status='live'))
            db.session.flush()
    return key


# ========================================================================================== which number

def _wrote_on_crm(person):
    return db.session.query(CrmTouchpoint.id).filter(
        CrmTouchpoint.person_id == person.id, CrmTouchpoint.channel == 'whatsapp', CrmTouchpoint.direction == 'in',
        CrmTouchpoint.line_id.is_(None)).first() is not None


def line_for(person):
    """The Meta-direct number a WhatsApp message to them goes out on, or None for the WhatsApp CRM's number."""
    if person is None:
        return None
    if person.wa_line_id:
        line = get(person.wa_line_id)
        if line is not None:
            return line
    phone = (person.phone or '').strip()
    if not phone or not CrmChannelLine.query.filter(CrmChannelLine.status == 'live').first():
        return None
    if person.wacrm_conversation_id or _wrote_on_crm(person):
        return None
    from app.services import crm_scope
    ws = crm_scope.of(person)
    for line in lines(live_only=True):
        if line_workspace(line) == ws and any(phone.startswith(p) for p in line.prefixes or ()):
            return line
    return None


def label_of(line):
    """'USA · +1 917 900 5094' -- how a page names a number."""
    if line is None:
        return 'WhatsApp CRM'
    from app.services import phone as phone_svc
    num = phone_svc.pretty(line.phone, line.phone) if line.phone else ''
    return '%s · %s' % (line.label, num) if num else line.label


# =========================================================================================== the send paths

class _CrmSender:
    """The WhatsApp CRM's number: the portal's switch ("Keep in step and send follow-ups") decides."""
    line = None

    def ready(self, by_hand=False):
        from app.services import crm
        return crm.wa_writes_on() if by_hand else crm.wa_can_send()

    def text(self, phone, text):
        from app.services import wacrm
        return wacrm.send_text(phone, text)

    def template(self, phone, name, language=None, params=None):
        from app.services import wacrm
        return wacrm.send_template(phone, name, language=language, params=params)


class _LineSender:
    """A Meta-direct number: it sends while it is live."""
    def __init__(self, line):
        self.line = line

    def ready(self, by_hand=False):
        return self.line.status == 'live'

    def text(self, phone, text):
        from app.services import wa_meta
        wamid = wa_meta.send_text(self.line, phone, text)
        self.line.last_out_at = datetime.utcnow()
        return wamid

    def template(self, phone, name, language=None, params=None):
        from app.services import wa_meta
        wamid = wa_meta.send_template(self.line, phone, name, language=language or LANGUAGE, params=params)
        self.line.last_out_at = datetime.utcnow()
        return wamid


def sender(line):
    return _CrmSender() if line is None else _LineSender(line)


class _CrmTemplates:
    """The WhatsApp CRM's templates (services/wa_templates)."""
    line = None

    def approved(self, name):
        from app.services import wa_templates
        return wa_templates.approved(name)

    def info(self, name):
        from app.services import wa_templates
        return wa_templates.template_info(name)

    def text(self, name, params):
        from app.services import wa_templates
        return wa_templates.template_text(name, params)

    def statuses(self):
        from app.services import wa_templates
        return wa_templates.statuses()

    def approved_list(self):
        from app.services import wa_templates
        return wa_templates.approved_templates()

    def language(self, name):
        from app.services import wa_templates
        return wa_templates.LANGUAGE


class _LineTemplates:
    """A Meta-direct number's templates, as Meta last listed them (refresh_templates), English first."""
    def __init__(self, line):
        self.line = line
        rows = {}
        for t in line.templates or []:
            name = t.get('name')
            if name and (name not in rows or (t.get('language') or '').startswith(LANGUAGE)):
                rows[name] = t
        self.rows = rows

    def approved(self, name):
        return (self.rows.get(name) or {}).get('status') == 'APPROVED'

    def info(self, name):
        return dict(self.rows.get(name) or {})

    def text(self, name, params):
        body = (self.rows.get(name) or {}).get('body') or ''
        return re.sub(r'\{\{(\d+)\}\}', lambda m: str(params[int(m.group(1)) - 1])
                      if 0 < int(m.group(1)) <= len(params) else m.group(0), body)

    def statuses(self):
        return {n: t.get('status') for n, t in self.rows.items()}

    def approved_list(self):
        return [{'name': n, 'language': t.get('language'), 'category': t.get('category'), 'body': t.get('body') or '',
                 'variables': t.get('variables')} for n, t in sorted(self.rows.items()) if t.get('status') == 'APPROVED']

    def language(self, name):
        return (self.rows.get(name) or {}).get('language') or LANGUAGE


def templates(line):
    return _CrmTemplates() if line is None else _LineTemplates(line)


def refresh_templates(line):
    """Ask Meta for the number's templates and keep them. Raises wa_meta.LineError. No commit."""
    from app.services import wa_meta
    line.templates = wa_meta.fetch_templates(line)
    line.templates_at = datetime.utcnow()
    return line.templates


TEMPLATES_EVERY = 3600          # seconds between two asks for a live number's templates (the jobs runner)


def refresh_due(now=None):
    """The jobs runner: each live number's templates again once an hour, so one Meta approved shows up without
    anybody pressing a button. A failure is kept on the number (last_error), never stops the others. Commits."""
    from app.services import wa_meta
    now = now or datetime.utcnow()
    done = failed = 0
    for line in lines(live_only=True):
        if line.templates_at is not None and (now - line.templates_at).total_seconds() < TEMPLATES_EVERY:
            continue
        try:
            refresh_templates(line)
            line.last_error = None
            done += 1
        except wa_meta.LineError as exc:
            line.last_error = ('Templates: %s' % exc)[:300]
            failed += 1
        db.session.commit()
    return {'wa_lines_templates': done, 'wa_lines_failed': failed}


def copy_templates(line):
    """Our follow-ups' WhatsApp templates, sent to this number's account for Meta to approve -- the same names and
    words, so a follow-up runs on either number. Names the account already has are left alone.
    {'sent': [names], 'had': [names], 'failed': [(name, why)]}. No commit."""
    from app.models import CrmPlaybookStep
    from app.services import wa_meta, wa_templates
    have = {t.get('name') for t in (line.templates or [])}
    out = {'sent': [], 'had': [], 'failed': []}
    seen = set()
    steps = CrmPlaybookStep.query.filter(CrmPlaybookStep.channel == 'whatsapp').order_by(CrmPlaybookStep.id).all()
    for step in steps:
        if not (step.body or '').strip():
            continue
        name = step.wa_template or wa_templates.slug_name(step.code)
        if not name or name in seen:
            continue
        seen.add(name)
        if name in have:
            out['had'].append(name)
            continue
        body, tokens = wa_templates.parts(step.body)
        probs = wa_templates.problems(name, body, tokens)
        if probs:
            out['failed'].append((name, '; '.join(probs)))
            continue
        try:
            wa_meta.submit_template(line, name, wa_templates._category(step=step), LANGUAGE, body,
                                    [wa_templates.SAMPLES.get(t, 'example') for t in tokens])
            out['sent'].append(name)
        except wa_meta.LineError as exc:
            out['failed'].append((name, str(exc)))
    return out


# ========================================================================================= Meta's deliveries

def record(events):
    """File Meta's events (wa_meta.parse) for the numbers we have: a message from them on its lead (the same rules
    as the WhatsApp CRM's, crm.record_whatsapp_in), a message sent from the phone's WhatsApp Business app on the lead's
    history, and a delivery status on the message it is about. {'messages', 'echoes', 'statuses', 'unknown'}."""
    from app.services import crm, crm_scope
    done = {'messages': 0, 'echoes': 0, 'statuses': 0, 'unknown': 0}
    for ev in events:
        line = by_number_id(ev.get('pnid'))
        if line is None:
            done['unknown'] += 1
            continue
        with crm_scope.use(line_workspace(line)):
            if ev['kind'] == 'message':
                crm.record_whatsapp_in(phone=ev['from'], name=ev.get('name'), wamid=ev['wamid'], text=ev.get('text'),
                                       content_type=ev.get('content_type'), at=ev.get('at'), line=line)
                line.last_in_at = datetime.utcnow()
                db.session.commit()
                done['messages'] += 1
            elif ev['kind'] == 'echo':
                if _record_echo(line, ev):
                    done['echoes'] += 1
            elif ev['kind'] == 'status':
                crm.wa_status_update(ev['wamid'], ev.get('status'), ev.get('error_code'), ev.get('error_title'))
                done['statuses'] += 1
    return done


def _record_echo(line, ev):
    """We wrote from the phone's WhatsApp Business app (coexistence): on their lead's history, once."""
    from app.services import crm
    if not ev.get('wamid') or CrmTouchpoint.query.filter_by(external_id=ev['wamid']).first() is not None:
        return False
    person = crm.wa_person(None, ev.get('to'))
    lead = (crm.wa_lead_for(person) or (person.leads[0] if person.leads else None)) if person is not None else None
    if lead is None:
        return False
    body = crm.wa_body(ev.get('text'), ev.get('content_type'))
    crm.log_touch(lead, 'whatsapp', 'out', body=('%s (from the WhatsApp Business app)' % body).strip(),
                  status='sent', external_id=ev['wamid'], at=ev.get('at'), line_id=line.id)
    line.last_out_at = datetime.utcnow()
    db.session.commit()
    return True


# ================================================================================ "Numbers & who answers"

def numbers(ws=None):
    """[{'name', 'number', 'provider', 'answers', 'listens', 'state', 'state_words', 'line'}] -- the WhatsApp CRM's
    number, each Meta-direct number, and tawk.to's website chat."""
    from app.services import tawk, wacrm, wacrm_team
    rows = []
    wa = wacrm_team.number_of(ws) if ws is not None else {'phone': None, 'state': 'none'}
    rows.append({'name': 'WhatsApp CRM number', 'number': wa.get('phone'), 'provider': 'wacrm', 'answers': 'wacrm',
                 'listens': [], 'line': None,
                 'state': 'live' if wa.get('state') == 'live' else ('new' if wacrm.base_url() else 'off'),
                 'state_words': {'live': 'Live', 'planned': 'Set up, not linked yet'}.get(wa.get('state'),
                                                                                       'Not linked')})
    for line in lines():
        rows.append({'name': line.label, 'number': line.phone, 'provider': 'meta', 'answers': 'meta',
                     'listens': list(line.also_on or []), 'line': line, 'state': line.status,
                     'state_words': STATUS_WORDS.get(line.status, line.status)})
    rows.append({'name': 'Website chat bubble', 'number': None, 'provider': 'tawk', 'answers': 'tawk', 'listens': [],
                 'line': None, 'state': 'live' if tawk.enabled() else 'off',
                 'state_words': 'Live' if tawk.enabled() else 'Webhook not connected'})
    return rows


def counts(line):
    """Messages in and out through the number, and the people it reached."""
    from sqlalchemy import func
    q = db.session.query(CrmTouchpoint.direction, func.count(CrmTouchpoint.id)).filter(
        CrmTouchpoint.line_id == line.id).group_by(CrmTouchpoint.direction)
    got = dict(q.all())
    people = db.session.query(func.count(CrmPerson.id)).filter(CrmPerson.wa_line_id == line.id).scalar() or 0
    return {'in': got.get('in', 0), 'out': got.get('out', 0), 'people': people}
