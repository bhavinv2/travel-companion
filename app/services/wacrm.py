"""The WhatsApp CRM (wacrm, served at studio.preventia360.com/crm) as seen from here.

Three things only, all through its public API (docs/public-api.md in that repo):

    upsert_contact()  find-or-create the contact for a lead, with tags for product and source
    send_text()       a message inside the 24-hour window Meta allows after the person last wrote
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
import time

import requests

log = logging.getLogger(__name__)
TIMEOUT = (3.05, 10)


class WacrmError(Exception):
    pass


def base_url():
    """e.g. https://studio.preventia360.com/crm -- its base path is part of it."""
    return (os.environ.get('WACRM_URL') or '').strip().rstrip('/')


def api_key():
    return (os.environ.get('WACRM_API_KEY') or '').strip()


def webhook_secret():
    """The secret replies are signed with: the environment's, else the one the WhatsApp CRM gave
    when Set-up -> Connect registered our webhook (kept in the CRM's settings, never shown)."""
    env = (os.environ.get('WACRM_WEBHOOK_SECRET') or '').strip()
    if env:
        return env
    try:
        from app.services import settings
        return ((settings.get_setting('crm') or {}).get('wacrm_webhook') or {}).get('secret') or ''
    except Exception:      # noqa: BLE001 -- no app context
        return ''


def enabled():
    return bool(base_url() and api_key())


def _call(method, path, payload=None, params=None):
    if not enabled():
        raise WacrmError('The WhatsApp CRM is not connected.')
    try:
        r = requests.request(method, base_url() + path, json=payload, params=params, timeout=TIMEOUT,
                             headers={'Authorization': 'Bearer ' + api_key(),
                                      'Accept': 'application/json'})
    except requests.RequestException as exc:
        raise WacrmError('The WhatsApp CRM could not be reached.') from exc
    try:
        body = r.json()
    except ValueError:
        # an HTML page: almost always a wrong address (the /crm part missing or doubled)
        raise WacrmError('The WhatsApp CRM answered with a web page, not data -- check WACRM_URL '
                         '(HTTP %s).' % r.status_code)
    if r.status_code >= 400:
        err = body.get('error') if isinstance(body, dict) else None
        msg = (err.get('message') if isinstance(err, dict) else err) or ('HTTP %s' % r.status_code)
        raise WacrmError(str(msg)[:200])
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


def me():
    """Who the key belongs to: {'account': {'id', 'name'}, 'key': {'id', 'scopes'}}. No side
    effects -- this is the "Test the connection" button."""
    return _call('GET', '/api/v1/me') or {}


def register_webhook(url, events=('message.received', 'message.status_updated')):
    """Point the WhatsApp CRM's webhook at us. Returns {'id', 'secret', ...}; the secret is only
    ever shown this once. Needs a key with the webhooks:manage scope."""
    return _call('POST', '/api/v1/webhooks', {'url': url, 'events': list(events)}) or {}


def list_webhooks():
    return _call('GET', '/api/v1/webhooks') or []


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
    Five minutes either way, so a captured delivery cannot be replayed later."""
    secret = secret if secret is not None else webhook_secret()
    if not secret or not header:
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
    expected = hmac.new(secret.encode('utf-8'), str(t).encode('ascii') + b'.' + body,
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)
