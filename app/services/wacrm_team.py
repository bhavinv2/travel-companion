"""Keeping the WhatsApp CRM's team in step with a portal workspace, and signing people into it.

The WhatsApp CRM (a separate Next.js app at WACRM_URL, studio.preventia360.com/crm) has its own
users and roles. The portal is where the team is managed, so this tells the CRM who belongs
(docs/portal-integration.md in the wacrm repo is the contract):

    a member whose pages include WhatsApp screens   -> a CRM member: 'admin' when they may manage
                                                       templates, the AI assistant or settings,
                                                       otherwise 'agent'
    anybody else, or somebody removed               -> taken out of the CRM

Everything goes through the CRM's /api/portal endpoints with a short-lived signed token (the
secret is WACRM_PORTAL_SECRET, shared with the CRM as PORTAL_SECRET). It is best effort: the CRM
being down must never stop somebody being added to a workspace here, so failures are written on
the member (wacrm_error) for the Members screen to show, and "Sync now" tries again.

Only one workspace can be linked: the CRM side is one WhatsApp number, one workspace.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime

import requests

from app import db

log = logging.getLogger(__name__)
TIMEOUT = (3.05, 10)

# The WhatsApp pages that make somebody a CRM admin rather than an agent.
ADMIN_PAGES = {'wa_templates', 'wa_ai', 'wa_settings'}


class TeamError(Exception):
    pass


# ------------------------------------------------------------------------------ settings

def base_url():
    """Where the CRM answers, e.g. https://studio.preventia360.com/crm -- its base path is part
    of it. WACRM_URL is the same address the public API uses."""
    return (os.environ.get('WACRM_URL') or '').strip().rstrip('/')


def secret():
    return (os.environ.get('WACRM_PORTAL_SECRET') or '').strip()


def enabled():
    return bool(base_url() and len(secret()) >= 32)


def browser_origin():
    """The CRM's origin as the browser sees it ('' when it is this site): the only sender the
    portal's WhatsApp pages accept "which page am I on" messages from."""
    from urllib.parse import urlparse
    base = browser_base()
    if base.startswith('/'):
        return ''
    p = urlparse(base)
    return '%s://%s' % (p.scheme, p.netloc)


def browser_base():
    """The CRM's address as the browser should load it inside the portal: the path alone when it
    is on this site (same origin, so it can be framed and its cookies are sent), the full URL
    otherwise (local development on another port)."""
    from urllib.parse import urlparse
    from flask import has_request_context, request
    url = os.environ.get('WACRM_BROWSER_URL') or base_url()
    parsed = urlparse(url)
    if has_request_context() and parsed.netloc and parsed.netloc == request.host:
        return parsed.path.rstrip('/')
    return url.rstrip('/')


# ------------------------------------------------------------------------------- tokens

def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def make_token(purpose, ttl=120, **claims):
    """b64url(payload) "." b64url(HMAC-SHA256(secret, b64url(payload))) -- the contract's format."""
    now = int(time.time())
    payload = dict(claims, v=1, purpose=purpose, iat=now, exp=now + min(int(ttl), 300))
    body = _b64(json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8'))
    sig = _b64(hmac.new(secret().encode('utf-8'), body.encode('ascii'), hashlib.sha256).digest())
    return body + '.' + sig


def sso_url(user, role, next_path='/inbox'):
    """The address that signs `user` into the CRM as `role` and lands them on `next_path`."""
    from urllib.parse import quote
    name = user.full_name or user.username or user.email
    token = make_token('sso', email=user.email.lower(), name=name, role=role, next=next_path or '/inbox')
    return '%s/api/portal/sso?t=%s' % (browser_base(), quote(token, safe=''))


# ----------------------------------------------------------------------------- the API

def _api(method, path, payload=None, params=None):
    if not enabled():
        raise TeamError('The WhatsApp CRM is not connected (WACRM_URL / WACRM_PORTAL_SECRET).')
    try:
        r = requests.request(method, '%s/api/portal/%s' % (base_url(), path.lstrip('/')), json=payload,
                             params=params, timeout=TIMEOUT,
                             headers={'Authorization': 'Portal ' + make_token('api', ttl=60),
                                      'Accept': 'application/json'})
    except requests.RequestException as exc:
        raise TeamError('The WhatsApp CRM could not be reached.') from exc
    try:
        body = r.json()
    except ValueError:
        raise TeamError('The WhatsApp CRM answered with a web page, not data (HTTP %s) -- check WACRM_URL.'
                        % r.status_code)
    if r.status_code >= 400:
        err = body.get('error') if isinstance(body, dict) else None
        msg = (err.get('message') if isinstance(err, dict) else err) or ('HTTP %s' % r.status_code)
        raise TeamError(str(msg)[:250])
    return (body or {}).get('data') if isinstance(body, dict) else None


def workspace_info():
    return _api('GET', 'workspace')


def list_members():
    return _api('GET', 'members') or []


def templates(status='APPROVED'):
    return _api('GET', 'templates', params={'status': status}) or []


def conversation(phone_digits):
    return _api('GET', 'conversation', params={'phone': phone_digits}) or {}


# ------------------------------------------------------------------------- the linking

def linked(ws):
    return bool(ws is not None and (ws.wacrm or {}).get('account_id'))


def linked_workspace():
    from app.models import Workspace
    for ws in Workspace.query.order_by(Workspace.id).all():
        if linked(ws):
            return ws
    return None


def link(ws):
    """Link `ws` to the CRM's workspace and bring its team in. Any other link is dropped: the CRM
    is one workspace."""
    from app.models import Workspace
    info = workspace_info()
    for other in Workspace.query.filter(Workspace.id != ws.id).all():
        if other.wacrm:
            other.wacrm = None
    ws.wacrm = {'account_id': info.get('account_id'), 'name': info.get('name'),
                'linked_at': datetime.utcnow().isoformat(timespec='seconds'), 'error': None}
    db.session.commit()
    if info.get('name') != ws.name:
        _rename(ws)
    return sync_all(ws)


def unlink(ws):
    ws.wacrm = None
    for m in ws.members:
        m.wacrm_role, m.wacrm_error = None, None
    db.session.commit()


def status(ws):
    """What the Workspace screen says about the WhatsApp CRM."""
    if not enabled():
        return {'configured': False}
    info = ws.wacrm or {}
    synced = [m for m in ws.members if m.wacrm_role]
    failed = [m for m in ws.members if m.wacrm_error]
    return {'configured': True, 'linked': linked(ws), 'name': info.get('name'), 'error': info.get('error'),
            'synced': len(synced), 'failed': len(failed), 'other': (None if linked(ws) else
                                                                     getattr(linked_workspace(), 'name', None))}


# --------------------------------------------------------------------------- the team

def role_for(member):
    """'admin' / 'agent' for somebody whose pages include WhatsApp screens, else None."""
    from app.services import access
    if member.user is None or not member.user.is_active:
        return None
    pages = access.ALL_PAGES if member.user.is_admin else access._member_pages(member)
    wa = {p for p in pages if p.startswith('wa_')}
    if not wa:
        return None
    return 'admin' if (wa & ADMIN_PAGES or member.is_owner) else 'agent'


def _push(member):
    """Tell the CRM where this member stands. Writes the outcome on the member; never raises."""
    want = role_for(member)
    try:
        if want:
            _api('POST', 'members', {'email': member.user.email.lower(), 'role': want,
                                     'name': member.user.full_name or member.user.username})
        elif member.wacrm_role:
            _api('POST', 'members/remove', {'email': member.user.email.lower()})
        member.wacrm_role, member.wacrm_error = want, None
        member.wacrm_synced_at = datetime.utcnow()
        return True
    except TeamError as exc:
        member.wacrm_error = str(exc)[:255]
        log.warning('WhatsApp CRM team sync failed for %s: %s', member.user.email, exc)
        return False


def member_changed(member):
    if not (enabled() and linked(member.workspace)):
        return
    _push(member)
    db.session.commit()


def member_removed(member):
    if not (enabled() and linked(member.workspace)) or not member.wacrm_role:
        return
    try:
        _api('POST', 'members/remove', {'email': member.user.email.lower()})
    except TeamError as exc:
        log.warning('WhatsApp CRM could not remove %s: %s', member.user.email, exc)


def _rename(ws):
    try:
        _api('PATCH', 'workspace', {'name': ws.name})
        info = dict(ws.wacrm or {})
        info['name'] = ws.name
        ws.wacrm = info
        db.session.commit()
    except TeamError as exc:
        log.warning('WhatsApp CRM rename failed: %s', exc)


def workspace_changed(ws):
    """Its name or modules changed: the CRM's name follows, and everybody's role is re-checked
    (switching the WhatsApp module off takes the whole team out of the CRM)."""
    if not (enabled() and linked(ws)):
        return
    if (ws.wacrm or {}).get('name') != ws.name:
        _rename(ws)
    sync_all(ws)


def sync_all(ws):
    """Every member's place in the CRM. People the CRM has that this workspace does not are
    listed, never removed: they may be the team that used the CRM before it was linked, and
    taking their access away is a decision for a person on the Workspace screen. Returns
    (ok, failed)."""
    ok = failed = 0
    for m in ws.members:
        if _push(m):
            ok += 1
        else:
            failed += 1
    known = {m.user.email.lower() for m in ws.members}
    info = dict(ws.wacrm or {})
    try:
        info['extra'] = [{'email': row.get('email'), 'name': row.get('name'), 'role': row.get('role')}
                         for row in list_members()
                         if (row.get('email') or '').lower() not in known and not row.get('banned')]
        info['error'] = None
    except TeamError as exc:
        info['error'] = str(exc)[:255]
    info['synced_at'] = datetime.utcnow().isoformat(timespec='seconds')
    ws.wacrm = info
    db.session.commit()
    return ok, failed


def remove_extra(ws, email):
    """Take somebody the workspace does not have out of the CRM (from the Workspace screen)."""
    _api('POST', 'members/remove', {'email': email.lower()})
    info = dict(ws.wacrm or {})
    info['extra'] = [x for x in info.get('extra') or [] if (x.get('email') or '').lower() != email.lower()]
    ws.wacrm = info
    db.session.commit()
