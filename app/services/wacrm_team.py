"""Keeping the WhatsApp CRM's team in step with a portal workspace, and signing people into it.

The WhatsApp CRM (a separate Next.js app at WACRM_URL, studio.preventia360.com/crm) has its own
users and roles. The portal is where the team is managed, so this tells the CRM who belongs
(docs/portal-integration.md in the wacrm repo is the contract):

    a member whose pages include WhatsApp screens   -> a CRM member: 'admin' when they may manage
                                                       templates, tags, AI replies or the number,
                                                       otherwise 'agent'
    anybody else, or somebody removed               -> taken out of the CRM

It is also told which of its screens each person may open (contract 14: `pages`, on the member and
in every sign-in), so a link inside it cannot open a screen the person's roles leave out.

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
from app.services import wacrm

log = logging.getLogger(__name__)

# The WhatsApp pages that make somebody a CRM admin rather than an agent.
ADMIN_PAGES = {'wa_templates', 'wa_ai', 'wa_settings', 'wa_tags'}

# contract 14: the page keys the WhatsApp CRM knows; it drops any other
PORTAL_PAGE_KEYS = ('wa_inbox', 'wa_broadcasts', 'wa_automations', 'wa_flows', 'wa_ai', 'wa_templates',
                    'wa_tags', 'wa_quick', 'wa_settings')


class TeamError(Exception):
    """`status`: the HTTP status (None when there was no answer at all); `code`: the CRM's error
    code, e.g. "ambiguous_contact"."""
    def __init__(self, message='', status=None, code=None):
        super().__init__(message)
        self.status, self.code = status, code


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


def sso_url(user, role, next_path='/inbox', pages=None):
    """The address that signs `user` into the CRM as `role` and lands them on `next_path`. `pages`:
    the screens their roles give them (contract 14; default: worked out from their pages here). An
    old WhatsApp CRM ignores the claim."""
    from urllib.parse import quote
    name = user.full_name or user.username or user.email
    pages = wa_pages(user_pages(user)) if pages is None else list(pages)
    token = make_token('sso', email=user.email.lower(), name=name, role=role, next=next_path or '/inbox',
                       pages=pages)
    return '%s/api/portal/sso?t=%s' % (browser_base(), quote(token, safe=''))


def wa_pages(pages):
    """The page grants the WhatsApp CRM is told (contract 14): the person's wa_* pages, plus
    wa_quick when they have the portal's Quick replies. Sorted, so a token reads the same each time."""
    keys = {p for p in pages if p in PORTAL_PAGE_KEYS}
    if 'crm_quick' in pages:
        keys.add('wa_quick')
    return sorted(keys)


def member_pages(member):
    """A member's portal pages; a site owner has every page."""
    from app.services import access
    return access.ALL_PAGES if member.user.is_admin else access._member_pages(member)


def user_pages(user):
    """The portal pages behind this person's WhatsApp access: their pages in the linked workspace
    (the current one when none is linked yet)."""
    from app.models import WorkspaceMember
    from app.services import access
    if user.is_admin:
        return access.ALL_PAGES
    ws = linked_workspace() or access.current_workspace(user)
    m = WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=user.id).first() if ws else None
    return access._member_pages(m) if m else frozenset()


# ----------------------------------------------------------------------------- the API

def _api(method, path, payload=None, params=None):
    if not enabled():
        raise TeamError('The WhatsApp CRM is not connected (WACRM_URL / WACRM_PORTAL_SECRET).')
    try:
        r = requests.request(method, '%s/api/portal/%s' % (base_url(), path.lstrip('/')), json=payload,
                             params=params, timeout=wacrm.timeout(),
                             headers={'Authorization': 'Portal ' + make_token('api', ttl=60),
                                      'Accept': 'application/json'})
    except requests.RequestException as exc:
        raise TeamError('The WhatsApp CRM could not be reached.') from exc
    try:
        body = r.json()
    except ValueError:
        raise TeamError('The WhatsApp CRM answered with a web page, not data (HTTP %s) -- check WACRM_URL.'
                        % r.status_code, status=r.status_code)
    if r.status_code >= 400:
        err = body.get('error') if isinstance(body, dict) else None
        code = err.get('code') if isinstance(err, dict) else (err if isinstance(err, str) else None)
        msg = (err.get('message') if isinstance(err, dict) else err) or ('HTTP %s' % r.status_code)
        raise TeamError(str(msg)[:250], status=r.status_code, code=code)
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
    if member.user is None or not member.user.is_active:
        return None
    pages = member_pages(member)
    wa = set(wa_pages(pages))
    # Contacts is the portal's own page: only WhatsApp screens make somebody a CRM member
    if not wa:
        return None
    return 'admin' if (wa & ADMIN_PAGES or member.is_owner) else 'agent'


def _push(member):
    """Tell the CRM where this member stands. Writes the outcome on the member; never raises."""
    want = role_for(member)
    try:
        if want:
            _api('POST', 'members', {'email': member.user.email.lower(), 'role': want,
                                     'name': member.user.full_name or member.user.username,
                                     'pages': wa_pages(member_pages(member))})
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


# ------------------------------------------------------------------- messages and conversations

def push_template_drafts(items):
    """New WhatsApp templates as DRAFTs (a person submits each to Meta on WhatsApp -> Templates).
    Existing names are left alone. {created, skipped: [{name, reason}]}."""
    out = {'created': 0, 'skipped': []}
    for i in range(0, len(items), 100):
        data = _api('POST', 'templates/drafts', {'items': items[i:i + 100]}) or {}
        out['created'] += int(data.get('created') or 0)
        out['skipped'] += list(data.get('skipped') or [])
    return out


def push_quick_replies(items, remove_titles=None):
    """The quick replies into the WhatsApp CRM, matched by title; remove_titles are taken out (ones the
    portal put there and no longer has). At most 200 of each per request, so long lists go in parts.
    {created, updated, removed, conflicts}: conflicts are titles a WhatsApp button reply already has,
    left out there (contract 21)."""
    out = {'created': 0, 'updated': 0, 'removed': 0, 'conflicts': []}
    remove = [t for t in (remove_titles or []) if t]
    for n in range(max((len(items) + 199) // 200, (len(remove) + 199) // 200)):
        body = {'items': items[n * 200:(n + 1) * 200]}
        if remove[n * 200:(n + 1) * 200]:
            body['remove_titles'] = remove[n * 200:(n + 1) * 200]
        data = _api('POST', 'quick-replies', body) or {}
        for k in ('created', 'updated', 'removed'):
            out[k] += int(data.get(k) or 0)
        out['conflicts'] += [str(t) for t in (data.get('conflicts') or []) if t and str(t) not in out['conflicts']]
    return out


def quick_replies_unmanaged():
    """Contract 21: the WhatsApp CRM's quick replies the portal does not keep -- [{title, type: 'text' |
    'interactive', body}], for the one-off import. TeamError 404 on an older WhatsApp CRM."""
    return list((_api('GET', 'quick-replies', params={'managed': 'none'}) or {}).get('items') or [])


def conversation_info(conversation_id):
    """{conversation_id, status, assignee_email, last_inbound_at, contact: {...}} or None."""
    try:
        return _api('GET', 'conversation/%s' % conversation_id)
    except TeamError:
        return None


def ensure_conversation(phone_digits, name=None, email=None, create=True, assign_email=None):
    """The person's contact and conversation in the WhatsApp CRM, made when missing (create=False:
    only looked up). The number must match exactly, or be the same number saved without its
    country code or trunk 0; name and e-mail are used only when the contact is made, never to
    rename. assign_email gives the chat to that member only when nobody has it. Never sends
    anything. {contact_id, conversation_id, contact_phone, contact_name, created_contact,
    created_conversation, assignee_email, assignment, last_inbound_at, status}.
    TeamError 409 (code ambiguous_contact) when two contacts could be the number."""
    return _api('POST', 'conversation/ensure', {
        'phone': ''.join(ch for ch in str(phone_digits or '') if ch.isdigit()),
        'name': name or None, 'email': email or None, 'create': bool(create),
        'assign_email': (assign_email or '').strip().lower() or None}) or {}


def activity(since, limit=100):
    """Conversations with a message after `since` (a naive UTC datetime, or an ISO string), oldest
    first: {items: [...], next_since} -- next_since is where to carry on, None when that was all."""
    if isinstance(since, datetime):
        since = since.replace(microsecond=0).isoformat() + 'Z'
    data = _api('GET', 'conversations/activity',
                params={'since': since, 'limit': max(1, min(int(limit), 200))}) or {}
    return {'items': list(data.get('items') or []), 'next_since': data.get('next_since')}


def automations_info():
    """GET /api/portal/automations in full: {'items': [...], 'flows_active': int | None, 'ai_auto_reply': bool | None}.
    The chatbot count and the AI switch are newer; an older WhatsApp CRM leaves them out, and None means it did
    not say."""
    data = _api('GET', 'automations') or {}
    if not isinstance(data, dict):
        data = {}
    flows, ai = data.get('flows_active'), data.get('ai_auto_reply')
    return {'items': list(data.get('items') or []),
            'flows_active': flows if isinstance(flows, int) and not isinstance(flows, bool) and flows >= 0 else None,
            'ai_auto_reply': ai if isinstance(ai, bool) else None}


def automations():
    """The WhatsApp CRM's automations: [{id, name, active, trigger_type, trigger_tags, sends}];
    `sends` when a step messages the customer -- checked before tags are switched on."""
    return automations_info()['items']


def assign_conversation(phone_digits, email, conversation_id=None, only_if_unassigned=False):
    """Give the person's WhatsApp conversation -- found by number, or by its id -- to `email`
    (None: nobody). only_if_unassigned leaves a chat somebody already has alone."""
    body = {'conversation_id': str(conversation_id)} if conversation_id else {'phone': phone_digits}
    body['email'] = email
    if only_if_unassigned:
        body['only_if_unassigned'] = True
    return _api('POST', 'conversation/assign', body)


def put_managed_tags(prefixes, names):
    """Contract 16: which tags are the Sales CRM's (stored by the WhatsApp CRM in its owner's
    app_metadata). {'ok': True}. 404 on an older WhatsApp CRM."""
    return _api('PUT', 'managed-tags', {'prefixes': prefixes, 'names': names}) or {}


def rename_tags(renames):
    """Contract 18: Sales tags renamed in place, ids kept, nothing fired. [{'from', 'to'}], 100 a call.
    {'renamed': [from], 'skipped': [{'from', 'reason': 'missing' | 'not_managed' | 'exists'}]}."""
    out = {'renamed': [], 'skipped': []}
    for i in range(0, len(renames), 100):
        data = _api('POST', 'tags/rename', {'renames': renames[i:i + 100]}) or {}
        out['renamed'] += list(data.get('renamed') or [])
        out['skipped'] += list(data.get('skipped') or [])
    return out


def list_tags():
    """Contract 17: [{id, name, color, managed, contacts}]."""
    return list((_api('GET', 'tags') or {}).get('items') or [])


TAGS_SECONDS = 60
_tags_cache = {'at': 0.0, 'items': None}


def tags(force=False):
    """Contract 17 for pickers: list_tags(), kept TAGS_SECONDS in this process. A check before a save
    (crm.wa_tag_clashes) asks list_tags itself."""
    now = time.monotonic()
    if not force and _tags_cache['items'] is not None and now - _tags_cache['at'] < TAGS_SECONDS:
        return _tags_cache['items']
    items = list_tags()
    _tags_cache.update(at=now, items=items)
    return items


def forget_tags():
    _tags_cache.update(at=0.0, items=None)


def contact_tags(contact_id, add=(), remove=(), create=False, quiet=False):
    """Contract 20: add or take off a contact's free tags. `create` makes a missing tag (only for people
    with Tags); `quiet` sends dispatch_tag_events false. [{name, managed}] afterwards. TeamError 422
    managed_tag / unknown_tag, 404 (an unknown contact, or an older WhatsApp CRM: code None)."""
    body = {'contact_id': str(contact_id)}
    if add:
        body['add'] = [str(t) for t in add][:50]
    if remove:
        body['remove'] = [str(t) for t in remove][:50]
    if create:
        body['create'] = True
    if quiet:
        body['dispatch_tag_events'] = False
    return list((_api('POST', 'contact/tags', body) or {}).get('tags') or [])


def contacts_export(since, limit=100):
    """Contract 27: the WhatsApp CRM's contacts made after `since` (a naive UTC datetime or ISO text with a
    time zone), oldest first, with tag names and notes: {items, next_since}."""
    if isinstance(since, datetime):
        since = since.replace(microsecond=0).isoformat() + 'Z'
    data = _api('GET', 'contacts', params={'since': since, 'limit': max(1, min(int(limit), 200))}) or {}
    return {'items': list(data.get('items') or []), 'next_since': data.get('next_since')}


def erase_contact(contact_id):
    """Contract 28: the contact, its chats, messages, notes and tags, gone. TeamError 404 code 'not_found'
    when it is not there (already erased); 404 without a code: an older WhatsApp CRM."""
    return _api('POST', 'contact/erase', {'contact_id': str(contact_id)}) or {}
