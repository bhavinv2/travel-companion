"""Addresses for the routes that answer beside the app's prefix, not inside it.

The app is mounted under a prefix in production (/travel-companions), so PrefixMiddleware sets
SCRIPT_NAME and url_for emits /travel-companions/... for everything. That is right for every
screen of the companion app.

It is wrong for the two standalone service pages. /travel-insurance and /sahayak are their own
front doors -- the addresses printed, shared and advertised -- and the Worker forwards them
unprefixed. url_for still returns /travel-companions/travel-insurance for them, because the
middleware put the prefix back so that links rendered ON those pages stay inside one canonical
prefix. Both addresses reach the same page, but only one of them is the one to show somebody.

So: url_for for links within the app, public_url for a link TO one of these pages.

With no prefix configured (local, tests) the two are identical, which is why this is easy to
forget about until it is live.
"""
from urllib.parse import urlparse, urlsplit, urlunsplit

from flask import current_app, has_request_context, request, url_for


def _prefix():
    p = (current_app.config.get('APP_URL_PREFIX') or '').strip('/')
    return '/' + p if p else ''


def on_site(path):
    """The address on the domain for a path inside the app (prefix removed), or None.

    Once the domain points at this app (PrefixMiddleware's "direct" requests), its own pages and
    sections live at the root: /home, /about-us ... (APP_SITE_PAGES) and everything under /blog
    (APP_SITE_SECTIONS) -- never /travel-companions/blog. Before that (through the Worker, on
    Railway's own address, locally) those root addresses are WordPress's or nobody's: None."""
    if not (has_request_context() and request.environ.get('app.direct')):
        return None
    for public, inside in (current_app.config.get('APP_SITE_PAGES') or {}).items():
        if path == inside:
            return public
    if any(path == s or path.startswith(s + '/') for s in (current_app.config.get('APP_SITE_SECTIONS') or ())):
        return path
    return None


def to_site(url):
    """An address the app built (url_for, absolute or not) with the prefix taken off when the domain
    serves that page at its root (on_site). The app's link builder runs every address through this,
    so templates keep writing url_for('blog.blog_post', ...) and get /blog/<slug>."""
    prefix = _prefix()
    if not prefix or not isinstance(url, str):
        return url
    parts = urlsplit(url)
    if not parts.path.startswith(prefix + '/'):
        return url
    public = on_site(parts.path[len(prefix):])
    if public is None:
        return url
    return urlunsplit((parts.scheme, parts.netloc, public, parts.query, parts.fragment))


def _aliases():
    return [('/' + a.strip('/')) for a in (current_app.config.get('APP_ALIAS_PATHS') or [])
            if a and a.strip('/')]


def public_url(endpoint, **values):
    """The address to show somebody for `endpoint`, prefix removed if it is an alias route."""
    url = url_for(endpoint, **values)
    prefix = ('/' + (current_app.config.get('APP_URL_PREFIX') or '').strip('/')).rstrip('/')
    if not prefix or prefix == '/' or not url.startswith(prefix + '/'):
        return url
    bare = url[len(prefix):]
    # Only strip for a path that really is served beside the prefix. Anything else keeps it, or
    # the link would 404.
    if any(bare == a or bare.startswith(a + '/') for a in _aliases()):
        return bare
    # (the domain's own pages and /blog come out of url_for at their root address already: to_site)
    return url


def site_link(endpoint, **values):
    """public_url as a full address on the public site, for a link that leaves in a message (a
    WhatsApp text or template). The host comes from SITE_URL -- its scheme and host only: SITE_URL
    already ends in the app's prefix, and the path public_url gives carries it too, so joining the
    two whole put /travel-companions in the link twice."""
    from urllib.parse import urlparse
    path = public_url(endpoint, **values)
    if path.startswith('http'):
        return path
    site = urlparse(current_app.config.get('SITE_URL') or '')
    return ('%s://%s' % (site.scheme, site.netloc) if site.netloc else '') + path


def site_page_seo(endpoint):
    """For one of the domain's own pages (APP_SITE_PAGES): reached at its own address on the domain it
    is the real page, {'live': True, 'canonical_url': ...}; at its route inside the app it is a copy of
    what WordPress still serves there, {'live': False}, and its template keeps it out of search results."""
    if request.environ.get('app.entry') == 'site-page':
        return {'live': True, 'canonical_url': public_absolute(endpoint)}
    return {'live': False}


def public_absolute(endpoint, **values):
    """public_url as a full https://host/path, for canonical tags and the sitemap."""
    path = public_url(endpoint, **values)
    if path.startswith('http'):
        return path
    return request.host_url.rstrip('/') + path

def app_url(path):
    """A root-relative path, moved inside the app's prefix.

    The Jinja twin of appUrl() in static/js/app-root.js, for the paths Python did not build with
    url_for: a `base` a route passed as a string, or a link stored in a Notification row years
    before anybody deployed under a prefix. Without it those come out as /cs/notifications, which
    under /travel-companions is the WordPress site, not us -- a 404 that only ever happens in
    production.

    Anything that is not a plain root-relative path (an absolute URL, a protocol-relative one, a
    fragment, something already prefixed) is handed back untouched.
    """
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//'):
        return path
    root = (request.script_root or '').rstrip('/')
    if not root or path == root or path.startswith(root + '/'):
        return to_site(path) if root else path
    if on_site(path.split('?', 1)[0].split('#', 1)[0]) is not None:
        return path                    # /blog/... once the domain is ours: the root address is the page's
    return root + path


def here(with_query=True):
    """This request's address, as a browser can use it.

    request.path and request.full_path both leave SCRIPT_NAME out, so a `next` built from either
    sends the visitor outside the app when it is mounted under a prefix. full_path also appends a
    bare '?' to every URL that has no query string, which then shows up in the address bar.
    """
    root = (request.script_root or '').rstrip('/')
    url = to_site(root + request.path)          # a /blog page is at /blog, not inside the prefix
    if with_query and request.query_string:
        url += '?' + request.query_string.decode('latin-1')
    return url


def safe_next(value):
    """A `next` that came from a form or a query string, if it is safe to follow.

    None when it is not, so callers read `safe_next(x) or url_for(...)`. Only a path inside this
    site: a full URL in a redirect is how a phishing page gets to claim it was reached from ours,
    and this value arrives somewhere anybody can write it.
    """
    if not isinstance(value, str) or not value:
        return None
    value = value.strip()
    if not value.startswith('/') or value.startswith('//'):
        return None
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return None
    # Somewhere to land, not something to call. An API path here means a background fetch got
    # itself recorded as the destination, which is how signing in ended up at a JSON endpoint.
    path = parsed.path
    root = (request.script_root or '').rstrip('/')
    if root and path.startswith(root):
        path = path[len(root):] or '/'
    if path.startswith('/api/') or path.startswith('/static/'):
        return None
    return value
