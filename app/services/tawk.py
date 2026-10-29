"""tawk.to, the chat bubble on the websites: its webhooks bring each chat and offline ticket into the Sales CRM, so
nobody has to look in tawk on the half-hourly check (Set-up > Integrations > tawk.to, 2026-10-26).

In: tawk calls POST /api/crm/tawk-webhook (tawk: Administration > Settings > Webhooks) for chat:start,
chat:transcript_created and ticket:create, signed with that webhook's secret key: the header X-Tawk-Signature is the
hex HMAC-SHA1 of the raw body. parse() turns a delivery into one plain enquiry; record() files it.

A chat becomes a lead only when it leaves a way to reach the person: an e-mail or a phone number, from the visitor's
details or from what the visitor typed. A chat without either is answered and not stored (tawk keeps it). One chat is
filed once -- its id is the touchpoint's external id -- and its transcript, when it comes, replaces the first message.

Off (the address answers 404) until a secret is set: the server's TAWK_WEBHOOK_SECRET, or the key an admin pastes on
the integration's Settings tab (the setting `integrations.tawk`; never shown again, only replaced or removed).
"""
import hashlib
import hmac
import os
import re
from datetime import datetime

from app import db
from app.models import CrmTouchpoint
from app.services import settings

SOURCE_KEY = 'tawk'
SETTING = 'integrations.tawk'
ENV = 'TAWK_WEBHOOK_SECRET'
EVENTS = ('chat:start', 'chat:transcript_created', 'ticket:create')
ANON = re.compile(r'^V\d{6,}$')          # tawk's name for a visitor who gave none: V1784410364168612
BODY_MAX = 2000


def saved():
    """{'secret', 'at', 'by'} as an admin saved it, or {}."""
    v = settings.get_setting(SETTING) or {}
    return v if isinstance(v, dict) else {}


def secret():
    return (os.environ.get(ENV) or '').strip() or (saved().get('secret') or '').strip()


def enabled():
    return bool(secret())


def save_secret(value, actor):
    """Keep the key tawk showed (or forget it with an empty value). Commits."""
    value = (value or '').strip()
    settings.set_setting(SETTING, {'secret': value, 'at': datetime.utcnow().isoformat(),
                                   'by': getattr(actor, 'full_name', None) or getattr(actor, 'username', None)}
                         if value else {}, actor)


def verify_signature(header, raw_body, key=None):
    key = key if key is not None else secret()
    if not key or not header:
        return False
    body = raw_body if isinstance(raw_body, bytes) else (raw_body or '').encode('utf-8')
    expected = hmac.new(key.encode('utf-8'), body, hashlib.sha1).hexdigest()
    return hmac.compare_digest(expected, header.strip().lower())


def _name(v):
    v = ' '.join(str(v or '').split())[:120]
    return None if not v or ANON.match(v) else v


def _reach(texts):
    """(phone, email) the visitor typed, the first that look right."""
    from app.services import crm
    from app.services.crm_ai import EMAIL_RE, PHONE_RE
    phone = email = None
    for t in texts:
        if not email:
            m = EMAIL_RE.search(t or '')
            email = m.group(0).lower() if m else None
        if not phone:
            for raw in PHONE_RE.findall(t or ''):
                phone = crm.normalise_phone(re.sub(r'[\s().\-]', '', raw))
                if phone:
                    break
    return phone, email


def parse(payload):
    """One delivery as {'kind': 'chat'|'ticket', 'id', 'name', 'email', 'phone', 'text', 'whole'} -- `whole` when
    the text is the full transcript -- or None for an event this does not file."""
    p = payload if isinstance(payload, dict) else {}
    event = p.get('event')
    if event not in EVENTS:
        return None
    if event == 'ticket:create':
        who, t = p.get('requester') or {}, p.get('ticket') or {}
        text = '\n'.join(x for x in (t.get('subject'), t.get('message')) if x)
        tid = str(t.get('humanId') or t.get('id') or '')
        phone, typed = _reach([text])
        return {'kind': 'ticket', 'id': tid, 'name': _name(who.get('name')),
                'email': (who.get('email') or typed or '').strip().lower() or None, 'phone': phone,
                'text': ('tawk ticket #%s\n%s' % (tid, text)).strip(), 'whole': True} if tid else None
    if event == 'chat:start':
        visitor, msg = p.get('visitor') or {}, p.get('message') or {}
        said = msg.get('text') or ''
        cid = str(p.get('chatId') or '')
        lines = [said]
        whole = False
    else:
        chat = p.get('chat') or {}
        visitor, cid = chat.get('visitor') or {}, str(chat.get('id') or p.get('chatId') or '')
        lines, said = [], []
        for m in chat.get('messages') or []:
            if not isinstance(m, dict) or m.get('type') not in (None, 'msg'):
                continue
            sender = m.get('sender') or {}
            who = sender.get('t')
            text = (m.get('msg') or '').strip()
            if not text:
                continue
            if who == 'v':
                lines.append(text)
            said.append('%s: %s' % ('Visitor' if who == 'v' else (sender.get('n') or 'Us'), text))
        said = '\n'.join(said)
        whole = True
    if not cid:
        return None
    phone, typed = _reach(lines)
    return {'kind': 'chat', 'id': cid, 'name': _name(visitor.get('name')),
            'email': (visitor.get('email') or typed or '').strip().lower() or None,
            'phone': phone, 'text': said.strip(), 'whole': whole}


def record(ev):
    """File one parsed event: the lead (new, or the person's open one), or None when nobody can be reached. A chat
    already filed only gets its transcript."""
    from app.services import crm
    ext = 'tawk-%s:%s' % (ev['kind'], ev['id'])
    seen = CrmTouchpoint.query.filter_by(external_id=ext).first()
    if seen is not None:
        if ev['whole'] and ev['text']:
            seen.body = ev['text'][:BODY_MAX * 4]
            db.session.commit()
        return seen.lead
    if not ev['phone'] and not ev['email']:
        return None
    return crm.capture_safely(SOURCE_KEY, name=ev['name'], phone=ev['phone'], email=ev['email'],
                              message=(ev['text'] or 'Started a chat on the website')[:BODY_MAX * (4 if ev['whole'] else 1)],
                              channel='chat', external_id=ext)


# ------------------------------------------------------------------------------------------- what tawk sent lately
# tawk documents its webhook for the website chat only, and names no channel field; with WhatsApp connected to tawk
# (2026-10-29: +1 917 900 5094) nobody knows yet what a WhatsApp chat's delivery carries. Each delivery is kept as
# the names of its fields and a few one-word labels (the event, a type, a channel) -- never a name, an e-mail, a
# number or what anybody wrote -- so one test message shows it on the card (Overview › What tawk sent lately).
SEEN = 'integrations.tawk_seen'
SEEN_MAX = 15
LABEL_KEYS = ('event', 'type', 't', 'channel', 'source', 'platform', 'medium', 'origin', 'kind', 'via', 'domain')
LABEL = re.compile(r'^[A-Za-z][\w.:-]{0,39}$')


def _fields(v, at='', depth=0, out=None, labels=None):
    out = set() if out is None else out
    labels = {} if labels is None else labels
    if depth > 5:
        return out, labels
    if isinstance(v, dict):
        for k, x in list(v.items())[:80]:
            k = re.sub(r'[^\w:-]', '', str(k))[:40] or '?'
            path = at + '.' + k if at else k
            out.add(path)
            if k.lower() in LABEL_KEYS and isinstance(x, str) and LABEL.match(x.strip()) and '@' not in x:
                labels.setdefault(path, x.strip())
            _fields(x, path, depth + 1, out, labels)
    elif isinstance(v, list):
        for x in v[:25]:
            _fields(x, at + '[]', depth + 1, out, labels)
    return out, labels


def note_delivery(payload, filed):
    """Keep this delivery's shape, newest first, the last SEEN_MAX. Never raises: the webhook's answer comes first."""
    try:
        fields, labels = _fields(payload if isinstance(payload, dict) else {})
        said = ' '.join(sorted(fields) + ['%s=%s' % kv for kv in labels.items()]).lower()
        row = {'at': datetime.utcnow().isoformat(timespec='seconds'),
               'event': labels.get('event') or '?', 'fields': sorted(fields)[:120], 'labels': labels,
               'filed': bool(filed), 'whatsapp': 'whatsapp' in said or 'wa_id' in said or 'wamid' in said}
        settings.set_setting(SEEN, ([row] + seen())[:SEEN_MAX])
    except Exception:          # noqa: BLE001 -- a diagnostic, never a reason to fail tawk's delivery
        db.session.rollback()


def seen():
    v = settings.get_setting(SEEN) or []
    return v if isinstance(v, list) else []


def last_seen():
    """When the newest tawk chat or ticket came in, or None."""
    row = (CrmTouchpoint.query.filter(CrmTouchpoint.external_id.like('tawk-%'))
           .order_by(CrmTouchpoint.created_at.desc()).first())
    return row.created_at if row is not None else None
