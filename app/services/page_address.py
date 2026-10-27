"""Where a favourite or a saved view goes (2026-10-27): a staff screen and its filters, kept as words and turned back
into an address for whoever opens it.

An address comes in as the browser had it (path and query, with or without the app's prefix) and is kept as
(endpoint, args, params): the screen, the words of its path (a lead's id) and the query string -- never as a URL to
follow. Only a GET screen that a page of the staff menu claims (access.ENDPOINT_PAGES) is kept, and never a download:
not an action, not a file, not somewhere else. Opening it builds the address again with url_for, in the console of
whoever opens it (the Sales CRM is mounted twice: /cs/crm for agents, /admin/crm for site admins), so a view an admin
saved opens for an agent too.

Filters are plain words: at most MAX_KEYS, each key a short lowercase word, each value at most VALUE_MAX characters (a
list for a repeated key). Words about the visit rather than the filter (the page of results, a tour, a download's
reason) are dropped. The screen decides what its words mean, exactly as when somebody types them, so record
visibility, look-only roles and the rest apply to a favourite or a view as to any link.
"""
import hashlib
import json
import re
from urllib.parse import parse_qs, urlsplit

from flask import current_app, request, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.routing import BuildError, RequestRedirect

MAX_KEYS = 15
VALUE_MAX = 120
LIST_MAX = 10
KEY_RE = re.compile(r'^[a-z][a-z0-9_]{0,29}$')
# about this visit, not the filter: the page of results, a fragment, the tour, a download's format and reason
VISIT_WORDS = frozenset({'page', 'partial', 'tour', 'step', 'next', 'csrf_token', 'ts', 'format', 'reason',
                         'download', 'saved', 'added'})
# screens that hand over a file or data rather than show something
NOT_A_SCREEN = re.compile(r'(^|_)(export|download|csv|api|json|file|files|image|images|photo|manifest|preview|sso|'
                          r'go)(_|$)')


def clean_params(raw):
    """Plain filter words from a query string: a MultiDict (request.args), or a dict of strings or lists."""
    if hasattr(raw, 'lists'):
        items = raw.lists()
    else:
        items = ((k, v if isinstance(v, (list, tuple)) else [v]) for k, v in (raw or {}).items())
    out = {}
    for k, values in items:
        if len(out) >= MAX_KEYS:
            break
        if not isinstance(k, str) or not KEY_RE.match(k) or k in VISIT_WORDS:
            continue
        values = [' '.join(str(v).split())[:VALUE_MAX] for v in values if v is not None and str(v).strip()][:LIST_MAX]
        if values:
            out[k] = values[0] if len(values) == 1 else values
    return out


def is_screen(endpoint):
    """A GET screen of the staff menu's pages (not a download, a file or a JSON answer)."""
    from app.services import access
    return bool(endpoint) and endpoint in access.ENDPOINT_PAGES and not NOT_A_SCREEN.search(endpoint.split('.', 1)[-1])


def menu_endpoints():
    """The screens the menu's lines open, both consoles: the only ones a saved view may be of."""
    from app.services import access
    return frozenset(e for p in access.PAGES.values() for e in p['links'].values() if e) | frozenset(
        e for p in access.PAGES.values() for e in p['lit'])


def _match(path):
    adapter = current_app.url_map.bind_to_environ(request.environ)
    for p in (path, path.rstrip('/') or '/', path + '/'):
        try:
            return adapter.match(p, method='GET')
        except RequestRedirect:
            continue
        except HTTPException:
            return None
    return None


def parse(address):
    """(endpoint, args, params) for an address of this app, or None when it is not a staff screen."""
    if not isinstance(address, str) or not address.strip() or len(address) > 2000:
        return None
    parts = urlsplit(address.strip())
    if parts.scheme or parts.netloc:
        return None
    path = parts.path or ''
    root = (request.script_root or '').rstrip('/')
    if root and (path == root or path.startswith(root + '/')):
        path = path[len(root):] or '/'
    if not path.startswith('/') or path.startswith('//'):
        return None
    got = _match(path)
    if got is None or not is_screen(got[0]):
        return None
    endpoint, args = got
    return endpoint, {k: v for k, v in args.items() if isinstance(v, (int, str))}, \
        clean_params(parse_qs(parts.query, keep_blank_values=False))


def here():
    """(endpoint, args, params) of the screen being answered now, or None when it is not one."""
    if not is_screen(request.endpoint):
        return None
    return request.endpoint, dict(request.view_args or {}), clean_params(request.args)


def key(endpoint, args, params):
    """The same screen with the same filters, the same key (in either console): a page is starred once."""
    base = 'crm.' + endpoint[len('admin_crm.'):] if endpoint.startswith('admin_crm.') else endpoint
    blob = json.dumps([base, args or {}, params or {}], sort_keys=True, ensure_ascii=True)
    return hashlib.sha1(blob.encode()).hexdigest()


def console_of(user):
    """'admin' for a site admin working as such, else 'cs': which copy of the Sales CRM their links open."""
    from app.services import access
    act = access.acting_role(user)
    return 'admin' if user.is_admin and (act is None or act.system_key == 'admin') else 'cs'


def in_console(endpoint, console):
    if console == 'cs' and endpoint.startswith('admin_crm.'):
        return 'crm.' + endpoint[len('admin_crm.'):]
    if console == 'admin' and endpoint.startswith('crm.'):
        return 'admin_crm.' + endpoint[len('crm.'):]
    return endpoint


def url(endpoint, args, params, user):
    """The address of a kept screen for `user`, or None when it cannot be built any more (a screen switched off)."""
    values = dict(params or {})
    values.update(args or {})
    for ep in dict.fromkeys((in_console(endpoint, console_of(user)), endpoint)):
        try:
            return url_for(ep, **values)
        except (BuildError, ValueError, TypeError):
            continue
    return None


def page_of(endpoint):
    """The page an endpoint belongs to: the one whose menu line opens it, else the first that claims it."""
    from app.services import access
    owners = access.ENDPOINT_PAGES.get(endpoint or '') or set()
    for key_ in sorted(owners):
        p = access.PAGES[key_]
        if endpoint in (p['links']['admin'], p['links']['cs']) and p['nav']:
            return key_
    for key_ in sorted(owners):
        if access.PAGES[key_]['nav']:
            return key_
    return min(owners) if owners else None
