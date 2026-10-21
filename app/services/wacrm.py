"""The WhatsApp CRM (wacrm, served at studio.preventia360.com/crm) as seen from here.

Three things only, all through its public API (docs/public-api.md in that repo):

    find_or_create_contact() / update_contact()   the person's contact, its tags, name and e-mail
    send_text()       a message inside the 24-hour window Meta allows after the person last wrote
                      (outside it the WhatsApp CRM refuses with 422 window_closed)
    send_template()   an approved template, which is the only thing Meta lets you send first

and one thing back: verify_signature() for its outbound webhook, which tells us when somebody
replies (message.received) so their lead can move on its own.

Switched off until both WACRM_URL and WACRM_API_KEY are set. Until then the Sales CRM hands the
agent a wa.me link instead, so nothing waits on this being connected. The key never leaves the
server.
"""
import hashlib
import hmac
import logging
import os
import threading
import time
from contextlib import contextmanager

import requests
from urllib3.exceptions import ConnectTimeoutError

log = logging.getLogger(__name__)
TIMEOUT = (3.05, 10)
SYNC_TIMEOUT = (3, 6)          # the background sync: never hold a worker for long
_local = threading.local()


def timeout():
    """(connect, read) seconds for a call made from this thread."""
    return getattr(_local, 'timeout', None) or TIMEOUT


@contextmanager
def short_timeouts():
    before = getattr(_local, 'timeout', None)
    _local.timeout = SYNC_TIMEOUT
    try:
        yield
    finally:
        _local.timeout = before


class WacrmError(Exception):
    """`status`: the HTTP status, None when there was no answer at all; `code`: the CRM's error
    code ("window_closed", "meta_error"...); `reached`: False when no connection was ever made
    (refused, unknown host, connect timeout), so nothing it asked for can have happened."""
    def __init__(self, message='', status=None, code=None, reached=True):
        super().__init__(message)
        self.status, self.code, self.reached = status, code, reached


def base_url():
    """e.g. https://studio.preventia360.com/crm -- its base path is part of it."""
    return (os.environ.get('WACRM_URL') or '').strip().rstrip('/')


def api_key():
    return (os.environ.get('WACRM_API_KEY') or '').strip()


def webhook_secrets():
    """Every secret a reply may be signed with: the one the WhatsApp CRM gave when Set-up ->
    Connect registered our webhook (kept in the CRM's settings, never shown), then
    WACRM_WEBHOOK_SECRET -- so "Connect again" works whether or not that variable is set."""
    out = []
    try:
        from app.services import settings
        saved = ((settings.get_setting('crm') or {}).get('wacrm_webhook') or {}).get('secret') or ''
    except Exception:      # noqa: BLE001 -- no app context
        saved = ''
    for s in (saved.strip(), (os.environ.get('WACRM_WEBHOOK_SECRET') or '').strip()):
        if s and s not in out:
            out.append(s)
    return out


def webhook_secret():
    """The first of webhook_secrets(), or ''."""
    s = webhook_secrets()
    return s[0] if s else ''


def enabled():
    """The Sales CRM may use the WhatsApp CRM: its address and key are set, and the CRM being read or written just now
    is the workspace WhatsApp is linked to (a second workspace's leads have WhatsApp off -- services/crm_scope)."""
    if not (base_url() and api_key()):
        return False
    try:
        from app.services import crm_scope
        return crm_scope.wa_here()
    except RuntimeError:       # no app context
        return True


def _never_connected(exc):
    """Whether a failed request certainly never reached the WhatsApp CRM."""
    if isinstance(exc, requests.ConnectTimeout):
        return True
    reason = getattr(exc.args[0], 'reason', None) if exc.args else None
    return isinstance(reason, ConnectTimeoutError)     # NewConnectionError (refused, no such host) is one


def _call(method, path, payload=None, params=None):
    if not enabled():
        raise WacrmError('The WhatsApp CRM is not connected.', reached=False)
    try:
        r = requests.request(method, base_url() + path, json=payload, params=params, timeout=timeout(),
                             headers={'Authorization': 'Bearer ' + api_key(),
                                      'Accept': 'application/json'})
    except requests.RequestException as exc:
        raise WacrmError('The WhatsApp CRM could not be reached.', reached=not _never_connected(exc)) from exc
    try:
        body = r.json()
    except ValueError:
        # an HTML page: almost always a wrong address (the /crm part missing or doubled)
        raise WacrmError('The WhatsApp CRM answered with a web page, not data -- check WACRM_URL '
                         '(HTTP %s).' % r.status_code, status=r.status_code)
    if r.status_code >= 400:
        err = body.get('error') if isinstance(body, dict) else None
        code = err.get('code') if isinstance(err, dict) else (err if isinstance(err, str) else None)
        msg = (err.get('message') if isinstance(err, dict) else err) or ('HTTP %s' % r.status_code)
        raise WacrmError(str(msg)[:200], status=r.status_code, code=code)
    return (body or {}).get('data') if isinstance(body, dict) else None


def upsert_contact(phone, name=None, email=None, tags=None):
    """The contact's id in the CRM (found by number, created when new), with our tags added.

    Its API replaces a contact's whole tag list when tags are sent, and matches an existing
    contact without touching it, so tags are merged with what the contact already has and sent
    only when something is missing -- a tag somebody set by hand in the WhatsApp CRM survives.
    """
    body = {'phone': phone}
    if name:
        body['name'] = name
    if email:
        body['email'] = email
    data = _call('POST', '/api/v1/contacts', body) or {}
    cid = str(data.get('id') or '') or None
    have = {t.get('name') for t in data.get('tags') or [] if isinstance(t, dict)}
    want = {t for t in (tags or []) if t}
    if cid and want - have:
        _call('PATCH', '/api/v1/contacts/%s' % cid, {'tags': sorted(have | want)})
    return cid


def find_or_create_contact(phone, name=None, email=None):
    """The contact with this number, made when there is none: {id, phone, name, email, tags: [{name}]...}.
    The name and e-mail are used only when it is made; an existing contact is not changed here."""
    body = {'phone': phone}
    if name:
        body['name'] = name
    if email:
        body['email'] = email
    return _call('POST', '/api/v1/contacts', body) or {}


def update_contact(contact_id, name=None, email=None, tags=None, quiet=False):
    """Change only what is given: the name, the e-mail, or the whole tag list (the API replaces it).
    `quiet`: a bulk change -- the tags go without starting the WhatsApp CRM's "tag added"
    automations (dispatch_tag_events false). An older WhatsApp CRM ignores it and starts them."""
    body = {k: v for k, v in (('name', name), ('email', email), ('tags', tags)) if v is not None}
    if not body:
        return None
    if quiet:
        body['dispatch_tag_events'] = False
    return _call('PATCH', '/api/v1/contacts/%s' % contact_id, body)


def find_contact(phone):
    """The id of the contact with this number, or None. It stores numbers as digits only and
    searches by part of the number, so the last ten digits are searched and compared in full."""
    digits = ''.join(ch for ch in (phone or '') if ch.isdigit())
    if len(digits) < 8:
        return None
    rows = _call('GET', '/api/v1/contacts', params={'search': digits[-10:], 'limit': 20}) or []
    for c in rows:
        theirs = ''.join(ch for ch in str(c.get('phone') or '') if ch.isdigit())
        if theirs and (theirs == digits or theirs[-10:] == digits[-10:]):
            return str(c.get('id'))
    return None


def conversation_for(contact_id):
    rows = _call('GET', '/api/v1/conversations', params={'contact_id': contact_id, 'limit': 1}) or []
    return str(rows[0].get('id')) if rows else None


def conversation_messages(conversation_id, limit=40):
    """Newest first: [{'direction': inbound/outbound, 'content_type', 'content_text', 'status',
    'created_at', 'sender_type'}]."""
    return _call('GET', '/api/v1/conversations/%s/messages' % conversation_id,
                 params={'limit': max(1, min(int(limit), 100))}) or []


def inbox_url(conversation_id):
    return '%s/inbox?c=%s' % (base_url(), conversation_id) if conversation_id else base_url() + '/inbox'


def me():
    """Who the key belongs to: {'account': {'id', 'name'}, 'key': {'id', 'scopes'}}. No side
    effects -- this is the "Test the connection" button."""
    return _call('GET', '/api/v1/me') or {}


def register_webhook(url, events=('message.received', 'message.status_updated', 'message.sent',
                                   'conversation.assigned')):
    """Point the WhatsApp CRM's webhook at us. Returns {'id', 'secret', ...}; the secret is only
    ever shown this once. Needs a key with the webhooks:manage scope."""
    return _call('POST', '/api/v1/webhooks', {'url': url, 'events': list(events)}) or {}


def list_webhooks():
    return _call('GET', '/api/v1/webhooks') or []


def switch_webhook_on(webhook_id):
    """Our webhook back on after the WhatsApp CRM switched it off (15 failed deliveries in a row);
    that also clears its failure count."""
    return _call('PATCH', '/api/v1/webhooks/%s' % webhook_id, {'is_active': True})


def delete_webhook(webhook_id):
    return _call('DELETE', '/api/v1/webhooks/%s' % webhook_id)


def get_contact(contact_id):
    return _call('GET', '/api/v1/contacts/%s' % contact_id)


def send_text(phone, text):
    data = _call('POST', '/api/v1/messages', {'to': phone, 'type': 'text', 'text': text})
    return (data or {}).get('whatsapp_message_id') or (data or {}).get('message_id')


def send_template(phone, name, language=None, params=None):
    """An approved template. Without a language the WhatsApp CRM picks the synced one (en_US,
    then en). Variables must be strings -- it silently drops anything else."""
    template = {'name': name, 'params': [str(p) for p in (params or [])]}
    if language:
        template['language'] = language
    data = _call('POST', '/api/v1/messages', {'to': phone, 'type': 'template', 'template': template})
    return (data or {}).get('whatsapp_message_id') or (data or {}).get('message_id')


def verify_signature(header, raw_body, secret=None, now=None, tolerance=300):
    """The CRM signs `"{t}.{raw body}"` with HMAC-SHA256 and sends `X-Wacrm-Signature: t=..,v1=..`.
    Five minutes either way, so a captured delivery cannot be replayed later. Either secret will
    do (webhook_secrets())."""
    secrets = [s for s in ([secret] if secret is not None else webhook_secrets()) if s]
    if not secrets or not header:
        return False
    parts = {}
    for kv in header.split(','):
        k, _, v = kv.partition('=')
        parts[k.strip()] = v.strip()
    try:
        t = int(parts.get('t', ''))
    except ValueError:
        return False
    v1 = parts.get('v1', '').lower()
    if not v1 or abs((now if now is not None else time.time()) - t) > tolerance:
        return False
    body = raw_body if isinstance(raw_body, bytes) else (raw_body or '').encode('utf-8')
    msg = str(t).encode('ascii') + b'.' + body
    return any(hmac.compare_digest(hmac.new(s.encode('utf-8'), msg, hashlib.sha256).hexdigest(), v1)
               for s in secrets)
