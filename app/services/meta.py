"""Instagram and Facebook Messenger, through Meta's Graph API -- the "Instagram Messenger", "FB
Messenger", "FB Comments" and "Insta Comments" inboxes of the sales sheet's Checker.

In: Meta calls /api/crm/meta-webhook for every message and comment on the Page and the Instagram
account linked to it. parse_events() turns a delivery into plain events the CRM files as replies
(or as new leads under the "instagram" / "facebook" sources).

Out: send_text() answers a message through the Page. Meta allows that within 24 hours of the
person's last message, which is how these chats work anyway.

Switched off until the Page token and the app secret are set (META_PAGE_TOKEN, META_APP_SECRET,
META_VERIFY_TOKEN). The Meta app needs Messenger and Instagram messaging (pages_messaging,
instagram_manage_messages; for comments pages_read_engagement and instagram_manage_comments).
Nothing here ever leaves the server.
"""
import hashlib
import hmac
import logging
import os

import requests

log = logging.getLogger(__name__)
TIMEOUT = (3.05, 10)


class MetaError(Exception):
    pass


def _env(name):
    return (os.environ.get(name) or '').strip()


def page_token():
    return _env('META_PAGE_TOKEN')


def app_secret():
    return _env('META_APP_SECRET')


def verify_token():
    return _env('META_VERIFY_TOKEN')


def graph_url(path):
    return 'https://graph.facebook.com/%s/%s' % (_env('META_GRAPH_VERSION') or 'v21.0', path.lstrip('/'))


def enabled():
    """Receiving needs the app secret (to check deliveries); answering needs the Page token too."""
    return bool(app_secret() and page_token())


def verify_signature(header, raw_body, secret=None):
    """Meta signs each delivery: X-Hub-Signature-256: sha256=<HMAC-SHA256 of the raw body>."""
    secret = secret if secret is not None else app_secret()
    if not secret or not header or not header.startswith('sha256='):
        return False
    body = raw_body if isinstance(raw_body, bytes) else (raw_body or '').encode('utf-8')
    expected = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split('=', 1)[1].strip().lower())


def parse_events(payload):
    """A webhook delivery as a list of {'channel', 'kind', 'sender_id', 'name', 'username',
    'text', 'external_id'} -- kind is 'message' or 'comment'. Echoes of our own messages and
    anything without text are dropped."""
    out = []
    obj = (payload or {}).get('object')
    channel = 'instagram' if obj == 'instagram' else 'facebook'
    for entry in (payload or {}).get('entry') or []:
        own_id = str(entry.get('id') or '')
        for m in entry.get('messaging') or []:
            msg = m.get('message') or {}
            sender = str((m.get('sender') or {}).get('id') or '')
            if not msg or msg.get('is_echo') or not sender or sender == own_id:
                continue
            text = msg.get('text') or ('[%s]' % ', '.join(a.get('type', 'attachment')
                                                          for a in msg.get('attachments') or []) if
                                       msg.get('attachments') else '')
            if not text:
                continue
            out.append({'channel': channel, 'kind': 'message', 'sender_id': sender, 'name': None,
                        'username': None, 'text': text[:4000], 'external_id': msg.get('mid')})
        for ch in entry.get('changes') or []:
            v = ch.get('value') or {}
            field = ch.get('field')
            if field == 'comments':                              # Instagram comment
                frm = v.get('from') or {}
                if not v.get('text') or str(frm.get('id') or '') == own_id:
                    continue
                out.append({'channel': 'instagram', 'kind': 'comment', 'sender_id': str(frm.get('id') or ''),
                            'name': None, 'username': frm.get('username'),
                            'text': v['text'][:4000], 'external_id': v.get('id')})
            elif field == 'feed' and v.get('item') == 'comment' and v.get('verb') == 'add':
                frm = v.get('from') or {}
                if not v.get('message') or str(frm.get('id') or '') == own_id:
                    continue
                out.append({'channel': 'facebook', 'kind': 'comment', 'sender_id': str(frm.get('id') or ''),
                            'name': frm.get('name'), 'username': None,
                            'text': v['message'][:4000], 'external_id': v.get('comment_id')})
    return out


def _call(method, path, params=None, payload=None):
    if not page_token():
        raise MetaError('Instagram / Facebook is not connected.')
    try:
        r = requests.request(method, graph_url(path), params={**(params or {}), 'access_token': page_token()},
                             json=payload, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise MetaError('Meta could not be reached.') from exc
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400 or (isinstance(body, dict) and body.get('error')):
        err = (body or {}).get('error') or {}
        raise MetaError(str(err.get('message') or 'HTTP %s' % r.status_code)[:200])
    return body


def profile(sender_id, channel):
    """The person's name (and Instagram username), best effort -- {} when Meta will not say."""
    fields = 'name,username' if channel == 'instagram' else 'first_name,last_name'
    try:
        d = _call('GET', sender_id, params={'fields': fields})
    except MetaError:
        return {}
    name = d.get('name') or ' '.join(x for x in (d.get('first_name'), d.get('last_name')) if x)
    return {'name': name or None, 'username': d.get('username')}


LEAD_FIELDS = 'created_time,field_data,ad_id,ad_name,campaign_id,campaign_name,form_id'


def fetch_lead(leadgen_id):
    """A lead-ad answer (Page token): {'field_data': [{'name', 'values'}], 'ad_id', 'form_id', 'campaign_name', ...}.
    The webhook only carries the ids. Needs the app permission leads_retrieval. Raises MetaError."""
    return _call('GET', str(leadgen_id), params={'fields': LEAD_FIELDS})


def send_text(recipient_id, text):
    """Answer a message (Messenger or Instagram -- the Page sends both). Returns Meta's message id."""
    d = _call('POST', 'me/messages', payload={'recipient': {'id': recipient_id},
                                              'messaging_type': 'RESPONSE',
                                              'message': {'text': text[:1900]}})
    return d.get('message_id')
