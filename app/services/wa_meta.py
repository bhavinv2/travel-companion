"""WhatsApp through Meta's Cloud API directly: the numbers the portal talks to itself (Set-up › Channels, 2026-10-29),
beside the WhatsApp CRM, which keeps its own. One number = one CrmChannelLine (services/channels.py).

Out, with the number's own token:
    phone_info(line)                     what Meta says about the number (its name, quality, state)
    subscribe(line, url) / unsubscribe   our Meta app hears this number's account at OUR address (Meta's per-account
                                         callback override), so the WhatsApp CRM's address stays as it is
    send_text / send_template            a message; Meta's message id (wamid) back
    fetch_templates / submit_template    the account's templates, and a new one for Meta to approve

In: verify_signature() for X-Hub-Signature-256 (HMAC-SHA256 of the raw body with the Meta app's secret), and parse(),
which turns a delivery into plain events: {'kind': 'message' | 'echo' | 'status', ...}.

Errors are wacrm.WacrmError's kind (LineError), with the same meaning, so crm._wa_send treats a send through Meta and
one through the WhatsApp CRM alike: no answer at all = may have gone; 4xx = refused (131047, the 24 hours, is
code 'window_closed'); never connected = nothing went. No token or secret ever leaves the server or reaches a page.
"""
import hashlib
import hmac
import logging
import re
from datetime import datetime

import requests

from app.services import wacrm
from app.services.wacrm import WacrmError

log = logging.getLogger(__name__)
GRAPH = 'https://graph.facebook.com/v21.0'
PAGES_MAX = 5                       # template list pages read at most (100 a page)
WINDOW_CLOSED = 131047              # Meta: more than 24 hours since they last wrote


class LineError(WacrmError):
    """`meta_code`: Meta's own error number (131047, 132001 ...), when it gave one."""
    def __init__(self, message='', status=None, code=None, reached=True, meta_code=None):
        super().__init__(message, status=status, code=code, reached=reached)
        self.meta_code = meta_code


def _token(line, token=None):
    if token:
        return token
    from app.services import channels
    return (channels.secrets_of(line) or {}).get('token') or ''


def _call(line, method, path, payload=None, params=None, token=None, url=None):
    tok = _token(line, token)
    if not tok:
        raise LineError('No Meta access token is saved for this number (Set-up › Channels).', code='no_token',
                        reached=False)
    try:
        r = requests.request(method, url or (GRAPH + path), json=payload, params=params, timeout=wacrm.timeout(),
                             headers={'Authorization': 'Bearer ' + tok, 'Accept': 'application/json'})
    except requests.RequestException as exc:
        raise LineError('Meta could not be reached.', reached=not wacrm._never_connected(exc)) from exc
    try:
        body = r.json()
    except ValueError:
        body = {}
    err = body.get('error') if isinstance(body, dict) else None
    if r.status_code >= 400 or err:
        err = err if isinstance(err, dict) else {}
        code = err.get('code')
        details = (err.get('error_data') or {}).get('details') if isinstance(err.get('error_data'), dict) else None
        msg = details or err.get('error_user_msg') or err.get('message') or ('HTTP %s' % r.status_code)
        mapped = 'window_closed' if code == WINDOW_CLOSED else ('meta_error' if r.status_code < 500 else None)
        raise LineError(str(msg)[:200], status=r.status_code, code=mapped, meta_code=code)
    return body if isinstance(body, dict) else {}


def digits(phone):
    return ''.join(ch for ch in str(phone or '') if ch.isdigit())


# ============================================================================================== the number

def phone_info(line, token=None):
    """{'display_phone_number', 'verified_name', 'quality_rating', 'code_verification_status', 'platform_type',
    'status', 'throughput', 'messaging_limit_tier'} as Meta has them."""
    return _call(line, 'GET', '/%s' % line.phone_number_id, token=token,
                 params={'fields': 'display_phone_number,verified_name,quality_rating,code_verification_status,'
                                   'platform_type,status,throughput,messaging_limit_tier'})


def account_numbers(line, token=None):
    """The phone number ids listed under the line's WhatsApp Business Account, to check the two ids belong together."""
    if not line.waba_id:
        return []
    body = _call(line, 'GET', '/%s/phone_numbers' % line.waba_id, token=token,
                 params={'fields': 'id,display_phone_number,verified_name'})
    return [r for r in body.get('data') or [] if isinstance(r, dict)]


def subscribe(line, callback_url, token=None):
    """Our Meta app hears this account, its deliveries sent to `callback_url` (Meta checks it first with a GET that
    echoes the line's verify token). The app's own address -- the WhatsApp CRM's -- is untouched."""
    return _call(line, 'POST', '/%s/subscribed_apps' % line.waba_id, token=token,
                 payload={'override_callback_uri': callback_url, 'verify_token': line.verify_token})


def subscriptions(line, token=None):
    body = _call(line, 'GET', '/%s/subscribed_apps' % line.waba_id, token=token)
    return [r for r in body.get('data') or [] if isinstance(r, dict)]


def unsubscribe(line, token=None):
    """Our app stops hearing this account (tawk.to and any other app keep theirs)."""
    return _call(line, 'DELETE', '/%s/subscribed_apps' % line.waba_id, token=token)


# =============================================================================================== messages

def send_text(line, to, text):
    """Free text, inside the 24 hours after they last wrote; Meta's message id."""
    body = _call(line, 'POST', '/%s/messages' % line.phone_number_id,
                 payload={'messaging_product': 'whatsapp', 'recipient_type': 'individual', 'to': digits(to),
                          'type': 'text', 'text': {'preview_url': True, 'body': text}})
    return _wamid(body)


def send_template(line, to, name, language=None, params=None):
    """An approved template of the line's account, its {{1}}, {{2}} ... filled from `params`; Meta's message id."""
    tpl = {'name': name, 'language': {'code': language or 'en'}}
    if params:
        tpl['components'] = [{'type': 'body', 'parameters': [{'type': 'text', 'text': str(p)} for p in params]}]
    body = _call(line, 'POST', '/%s/messages' % line.phone_number_id,
                 payload={'messaging_product': 'whatsapp', 'recipient_type': 'individual', 'to': digits(to),
                          'type': 'template', 'template': tpl})
    return _wamid(body)


def _wamid(body):
    rows = body.get('messages') or []
    wamid = rows[0].get('id') if rows and isinstance(rows[0], dict) else None
    if not wamid:
        raise LineError('Meta took the message but gave no id back.', status=None, reached=True)
    return wamid


# ============================================================================================== templates

def _template_row(t):
    body = ''
    for c in t.get('components') or []:
        if isinstance(c, dict) and str(c.get('type') or '').upper() == 'BODY':
            body = c.get('text') or ''
    blanks = {int(n) for n in re.findall(r'\{\{(\d+)\}\}', body)}
    return {'name': t.get('name'), 'status': str(t.get('status') or '').upper(),
            'category': str(t.get('category') or '').upper() or None, 'language': t.get('language') or None,
            'body': body, 'variables': len(blanks), 'rejection_reason': t.get('rejected_reason') or None}


def fetch_templates(line):
    """Every template of the line's WhatsApp Business Account: [{name, status, category, language, body, variables,
    rejection_reason}]."""
    if not line.waba_id:
        raise LineError('Add the WhatsApp Business Account id first.', code='no_account', reached=False)
    rows, url = [], None
    params = {'fields': 'name,status,category,language,components,rejected_reason', 'limit': 100}
    for _ in range(PAGES_MAX):
        body = _call(line, 'GET', '/%s/message_templates' % line.waba_id, params=None if url else params, url=url)
        rows += [_template_row(t) for t in body.get('data') or [] if isinstance(t, dict) and t.get('name')]
        url = ((body.get('paging') or {}).get('next')) or None
        if not url:
            break
    return rows


def submit_template(line, name, category, language, body, samples=None):
    """A new template for Meta to approve (Meta answers {'id', 'status', 'category'})."""
    comp = {'type': 'BODY', 'text': body}
    if samples:
        comp['example'] = {'body_text': [[str(s) for s in samples]]}
    return _call(line, 'POST', '/%s/message_templates' % line.waba_id,
                 payload={'name': name, 'category': (category or 'UTILITY').upper(), 'language': language or 'en',
                          'components': [comp]})


# ================================================================================================ webhook

def verify_signature(raw_body, header, secrets):
    """X-Hub-Signature-256 ('sha256=<hex>') made with any of `secrets` (each Meta app signs with its own)."""
    header = (header or '').strip()
    if not header.startswith('sha256='):
        return False
    got = header[7:].lower()
    body = raw_body if isinstance(raw_body, bytes) else (raw_body or '').encode('utf-8')
    for s in secrets or ():
        if s and hmac.compare_digest(hmac.new(s.encode('utf-8'), body, hashlib.sha256).hexdigest(), got):
            return True
    return False


def _when(ts):
    try:
        return datetime.utcfromtimestamp(int(ts))
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def message_words(m):
    """(text, content_type) of one Meta message, the way crm.wa_body keeps it; None for one that is not a message
    (a reaction)."""
    kind = str(m.get('type') or '')
    part = m.get(kind) if isinstance(m.get(kind), dict) else {}
    if kind == 'text':
        return (part.get('body') or ''), None
    if kind in ('image', 'video', 'document', 'audio', 'sticker'):
        return (part.get('caption') or part.get('filename') or ''), kind
    if kind == 'location':
        where = part.get('name') or part.get('address') or ''
        if not where and part.get('latitude') is not None:
            where = '%s, %s' % (part.get('latitude'), part.get('longitude'))
        return where, 'location'
    if kind == 'contacts':
        return '', 'contacts'
    if kind == 'button':
        return (part.get('text') or ''), 'button'
    if kind == 'interactive':
        reply = part.get('button_reply') or part.get('list_reply') or {}
        return (reply.get('title') or ''), 'interactive'
    if kind == 'reaction':
        return None
    return '', 'unsupported'


def parse(payload):
    """A delivery as plain events, each with the number it came to ('pnid'):
      {'kind': 'message', 'pnid', 'from', 'name', 'wamid', 'text', 'content_type', 'at'}   they wrote to us
      {'kind': 'echo', 'pnid', 'to', 'wamid', 'text', 'content_type', 'at'}               we wrote from the phone's
                                                                                          WhatsApp Business app
      {'kind': 'status', 'pnid', 'wamid', 'status', 'error_code', 'error_title', 'at'}   a message we sent moved on
    """
    out = []
    p = payload if isinstance(payload, dict) else {}
    for entry in p.get('entry') or []:
        for change in (entry or {}).get('changes') or []:
            if not isinstance(change, dict):
                continue
            v = change.get('value') if isinstance(change.get('value'), dict) else {}
            pnid = str((v.get('metadata') or {}).get('phone_number_id') or '')
            names = {str(c.get('wa_id') or ''): ((c.get('profile') or {}).get('name') or None)
                     for c in v.get('contacts') or [] if isinstance(c, dict)}
            for m in v.get('messages') or []:
                if not isinstance(m, dict) or not m.get('id'):
                    continue
                words = message_words(m)
                if words is None:
                    continue
                sender = str(m.get('from') or '')
                out.append({'kind': 'message', 'pnid': pnid, 'from': sender, 'name': names.get(sender),
                            'wamid': m['id'], 'text': words[0], 'content_type': words[1], 'at': _when(m.get('timestamp'))})
            for m in v.get('message_echoes') or []:
                if not isinstance(m, dict) or not m.get('id'):
                    continue
                words = message_words(m)
                if words is None:
                    continue
                out.append({'kind': 'echo', 'pnid': pnid, 'to': str(m.get('to') or ''), 'wamid': m['id'],
                            'text': words[0], 'content_type': words[1], 'at': _when(m.get('timestamp'))})
            for s in v.get('statuses') or []:
                if not isinstance(s, dict) or not s.get('id'):
                    continue
                errs = [e for e in s.get('errors') or [] if isinstance(e, dict)]
                out.append({'kind': 'status', 'pnid': pnid, 'wamid': s['id'], 'status': str(s.get('status') or ''),
                            'error_code': errs[0].get('code') if errs else None,
                            'error_title': ((errs[0].get('error_data') or {}).get('details') or errs[0].get('title')
                                            or errs[0].get('message')) if errs else None,
                            'at': _when(s.get('timestamp'))})
    return out
