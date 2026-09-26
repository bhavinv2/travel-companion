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
