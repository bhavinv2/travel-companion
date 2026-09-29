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
from urllib.parse import urlparse

from flask import current_app, request, url_for


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
    return url


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
        return path
    return root + path


def here(with_query=True):
    """This request's address, as a browser can use it.

    request.path and request.full_path both leave SCRIPT_NAME out, so a `next` built from either
    sends the visitor outside the app when it is mounted under a prefix. full_path also appends a
    bare '?' to every URL that has no query string, which then shows up in the address bar.
    """
    root = (request.script_root or '').rstrip('/')
    url = root + request.path
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
    return value
