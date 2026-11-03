"""The picture a link to a public page shows when it is shared on WhatsApp, Facebook, X ... (base.html's og:image).

A page may pass its own `share_image` -- a blog post's picture, the travel-insurance page's crop. Every other public
page gets its section's picture from here, so no link previews as a bare logo: WhatsApp falls back to the site's
icon when a page names no picture, which is what the home page and most others did.

Each is a 1200x630 crop in static/img/share, well under the ~300 KB WhatsApp's fetcher will take (a bigger file is
skipped as if there were none):
    home       the home page, Contact us, the policies, Help and anything not listed (hero-parent-care)
    about      About us (a family with their Sahayak)
    sahayak    the Sahayak page (its hero)
    blog       the blog, its categories and tags, and a post whose own picture is gone or too big
    companion  the travel companion pages (the landing page names its own hero itself, landing.html)
"""
from flask import request, url_for

PICTURES = {'home': 'img/share/home.jpg', 'about': 'img/share/about.jpg', 'sahayak': 'img/share/sahayak.jpg',
            'blog': 'img/share/blog.jpg', 'companion': 'img/share/companion.jpg',
            'insurance': 'img/share/travel-insurance.jpg'}
# whole areas, by blueprint; then single pages that are the site's own rather than the companion app's
BLUEPRINTS = {'homepage_draft': 'home', 'sahayak': 'sahayak', 'blog': 'blog', 'insurance': 'insurance',
              'main': 'companion', 'trips': 'companion', 'chat': 'companion', 'auth': 'companion'}
PAGES = {'homepage_draft.about': 'about', 'main.contact_us': 'home', 'main.privacy_policy': 'home',
         'main.terms_conditions': 'home', 'main.help_page': 'home', 'main.help_category': 'home'}
TOO_BIG = 300 * 1024


def key_for(endpoint):
    """Which picture a page shows: its own line in PAGES, else its blueprint's, else the home page's."""
    endpoint = endpoint or ''
    if endpoint in PAGES:
        return PAGES[endpoint]
    return BLUEPRINTS.get(endpoint.split('.', 1)[0], 'home')


def url(key):
    return url_for('static', filename=PICTURES[key], _external=True)


def for_page():
    """This page's section picture, as the absolute address a link preview needs."""
    return url(key_for(request.endpoint))
