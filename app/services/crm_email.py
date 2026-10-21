"""E-mail from the lead page, and e-mail that comes in (Sales CRM 2.0, run 3a).

Out: a person writes an e-mail and presses Send; it goes from the CRM sender (mailer category 'crm': a
one-to-one message an agent wrote, so it is not a notification and no notification switch holds it back) and is
logged as a touchpoint. Nothing in this module ever sends anything by itself.
When the server cannot carry it (mailer.transport_for(False) is None: Gmail is kept for account mail) the
composer says so and offers the person's own mail app; they may still log "E-mail written in own mail app".

In: SendGrid Inbound Parse posts a message to /api/crm/email-inbound?token=...; the sender is matched to a
person and the message is logged as theirs, which puts them on "waiting on us" like a WhatsApp message.
"""
import hmac
import os
import re
from datetime import datetime
from email.utils import parseaddr

from sqlalchemy import func

from app import db
from app.models import ActivityEvent, CrmAnswer, CrmLead, CrmPerson, CrmTouchpoint
from app.services import crm, mailer, settings

SETTING_KEY = 'crm.email_from'
DEFAULT_NAME = 'NRI Parent Service'
BODY_CAP = 20000
SUBJECT_CAP = 200
OWN_APP_LINE = 'E-mail written in own mail app'

NO_ADDRESS = 'This person has no e-mail address yet. Add one under Edit details.'
NEED_WORDS = 'Write a subject and a message first.'
NOT_SENT = 'The e-mail could not be sent. Try again, or open it in your own mail app.'
CANNOT_SEND = ('This server is not set up to send e-mail to customers. Open it in your own mail app instead; '
               'you can still keep a note of it here.')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


# ------------------------------------------------------------------------------------------ out

def sender_for(user):
    """(name, reply_to): the setting `crm.email_from` {'name', 'reply_to'}; the reply goes to the agent's own
    e-mail unless an admin set one address for everybody."""
    cfg = settings.get_setting(SETTING_KEY) or {}
    name = (cfg.get('name') or '').strip() or DEFAULT_NAME
    reply_to = (cfg.get('reply_to') or '').strip() or getattr(user, 'email', None)
    return name, reply_to


def can_send():
    """Whether this server may carry a customer e-mail (Gmail is kept for account mail)."""
    return mailer.transport_for(False) is not None


def answers_for(person, lead, user, limit=60):
    """[(answer, filled-in text)] for the "Insert a ready answer" picker. With no lead (the contact page) the
    fill-ins come from the person and their newest lead, if any."""
    from types import SimpleNamespace
    rows = CrmAnswer.query.order_by(CrmAnswer.use_count.desc(), CrmAnswer.title).limit(limit).all()
    lead = lead or main_lead(person)
    if lead is None:
        lead = SimpleNamespace(person=person, owner=None, product='GEN', departure_date=None,
                               days_to_departure=None, ends_on=None)
    try:
        values = crm.fill_values(lead, user)
    except Exception:          # noqa: BLE001 -- the picker still opens, with the words as written
        values = {}
    return [(a, crm.fill_with(a.body, values)) for a in rows]


def composer(person, lead, user):
    """Everything the composer shows."""
    name, reply_to = sender_for(user)
    return {'to': person.email, 'can_send': can_send(), 'from_name': name, 'reply_to': reply_to,
            'answers': [{'id': a.id, 'title': a.title, 'text': text} for a, text in answers_for(person, lead, user)]}


def _log(person, lead, user, body):
    tp = CrmTouchpoint(lead=lead, person_id=person.id, channel='email', direction='out', body=body[:BODY_CAP],
                       agent_id=getattr(user, 'id', None), via='person', status='sent')
    db.session.add(tp)
    if lead is not None:
        lead.last_activity_at = datetime.utcnow()
    db.session.flush()
    return tp


def main_lead(person):
    """Their most recently active open lead, or None."""
    opens = [l for l in person.leads if l.status == 'open']
    return max(opens, key=lambda l: (l.last_activity_at or l.created_at or datetime.min, l.id), default=None)


def send(user, person, lead, subject, body, answer_id=None):
    """Send what the person wrote. (ok, message). The message is shown as it is. No commit on failure."""
    subject = (subject or '').strip()[:SUBJECT_CAP]
    body = (body or '').strip()[:BODY_CAP]
    if not person.email:
        return False, NO_ADDRESS
    if not subject or not body:
        return False, NEED_WORDS
    if not can_send():
        return False, CANNOT_SEND
    name, reply_to = sender_for(user)
    ok = mailer.send(subject, [person.email], body, reply_to=reply_to, category='crm', force=True, from_name=name)
    if not ok:
        return False, NOT_SENT
    _count_answer(answer_id)
    _log(person, lead or main_lead(person), user, 'Subject: %s\n\n%s' % (subject, body))
    ActivityEvent.log('crm_email_sent', actor=user, lead=getattr(lead, 'id', None))
    return True, 'E-mail sent.'


def log_own_app(user, person, lead, subject, answer_id=None):
    """They wrote it in their own mail app and ticked "Log it": a line on the timeline, nothing sent."""
    subject = (subject or '').strip()[:SUBJECT_CAP]
    _count_answer(answer_id)
    _log(person, lead or main_lead(person), user, OWN_APP_LINE + (': %s' % subject if subject else ''))
    ActivityEvent.log('crm_email_logged', actor=user, lead=getattr(lead, 'id', None))


def _count_answer(answer_id):
    if str(answer_id or '').isdigit():
        a = db.session.get(CrmAnswer, int(answer_id))
        if a is not None:
            a.use_count = (a.use_count or 0) + 1


# ------------------------------------------------------------------------------------------ in

def inbound_token():
    return os.environ.get('CRM_INBOUND_EMAIL_TOKEN') or ''


def token_ok(given):
    want = inbound_token()
    return bool(want) and hmac.compare_digest(want.encode(), (given or '').encode())


_QUOTE_HEADS = (
    re.compile(r'^\s*On .{5,200}wrote:\s*$', re.I),                  # Gmail, Apple Mail
    re.compile(r'^\s*On .{5,120}$', re.I),                           # "On Tue, 3 Nov ..." wrapped onto a 2nd line
    re.compile(r'^\s*-{2,}\s*Original Message\s*-{2,}\s*$', re.I),   # Outlook
    re.compile(r'^\s*-{2,}\s*Forwarded message\s*-{2,}\s*$', re.I),
    re.compile(r'^\s*_{5,}\s*$'),
    re.compile(r'^\s*From:\s.+', re.I),                              # an Outlook header block
)


def strip_quoted(text):
    """What the person wrote, without the history under it: stops at "On ... wrote:", an Outlook header, a
    "-----Original Message-----" line, or the first line starting with ">". Keeps everything when that would
    leave nothing."""
    text = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')
    keep = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith('>'):
            break
        head = _QUOTE_HEADS[0].match(line) or _QUOTE_HEADS[2].match(line) or _QUOTE_HEADS[3].match(line) \
            or _QUOTE_HEADS[4].match(line)
        if head:
            break
        # "On Tue, 3 Nov 2026 at 10:15, Asha <a@x.com>" wrapped: the "wrote:" is on the next line
        if _QUOTE_HEADS[1].match(line) and i + 1 < len(lines) and lines[i + 1].strip().lower().endswith('wrote:'):
            break
        # "From: ..." only counts as a header block when "Sent:" or "Date:" follows
        if _QUOTE_HEADS[5].match(line) and any(re.match(r'^\s*(Sent|Date):', l, re.I) for l in lines[i + 1:i + 4]):
            break
        keep.append(line)
    out = '\n'.join(keep).strip()
    return out or text.strip()


def _html_to_text(html):
    html = re.sub(r'(?is)<(script|style).*?</\1>', '', html or '')
    html = re.sub(r'(?i)<br\s*/?>|</p>|</div>|</li>', '\n', html)
    text = re.sub(r'(?s)<[^>]+>', '', html)
    for a, b in (('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"'), ('&#39;', "'")):
        text = text.replace(a, b)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _message_id(headers):
    m = re.search(r'(?im)^Message-ID:\s*(<[^>\s]+>)', headers or '')
    return m.group(1)[:120] if m else None


def _find_person(address):
    people = CrmPerson.query.filter(func.lower(CrmPerson.email) == address).order_by(CrmPerson.id).all()
    if not people:
        return None
    best = None
    for p in people:
        lead = main_lead(p)
        score = (lead.last_activity_at or lead.created_at or datetime.min) if lead is not None else datetime.min
        if best is None or score > best[0]:
            best = (score, p)
    return best[1]


def receive(form):
    """One message from SendGrid Inbound Parse (`form`: its fields: from, subject, text, html, headers).
    Returns {'result': 'logged' | 'new_lead' | 'ignored' | 'duplicate', 'lead_id'?, 'person_id'?}. Commits."""
    name, address = parseaddr((form.get('from') or '').strip())
    address = (address or '').strip().lower()
    if not EMAIL_RE.match(address):
        return {'result': 'ignored'}
    text = form.get('text') or _html_to_text(form.get('html'))
    subject = (form.get('subject') or '').strip()[:SUBJECT_CAP]
    words = strip_quoted(text)[:BODY_CAP]
    body = (('Subject: %s\n\n%s' % (subject, words)) if subject else words)[:BODY_CAP]
    mid = _message_id(form.get('headers'))
    if mid and CrmTouchpoint.query.filter_by(external_id=mid, channel='email').first() is not None:
        return {'result': 'duplicate'}
    person = _find_person(address)
    if person is None:
        try:
            lead = crm.capture('email', name=(name or '').strip() or None, email=address, message=body[:4000],
                               channel='email', external_id=mid, refuse_dnc=True, sync=False)
        except crm.DoNotContact:
            return {'result': 'ignored'}
        if lead is None:
            return {'result': 'ignored'}
        return {'result': 'new_lead', 'lead_id': lead.id, 'person_id': lead.person_id}
    lead = main_lead(person)
    db.session.add(CrmTouchpoint(lead=lead, person_id=person.id, channel='email', direction='in', body=body,
                                 external_id=mid))
    if lead is not None:
        lead.last_activity_at = datetime.utcnow()
    db.session.commit()
    return {'result': 'logged', 'lead_id': lead.id if lead is not None else None, 'person_id': person.id}
