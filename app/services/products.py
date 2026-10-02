"""The three things this app puts in front of the public, and which one you are looking at.

Travel Companion, Travel Insurance and Sahayak are separate products that happen to share a
codebase and a header. Until now the only way between them was a "Services" dropdown buried in
the main menu -- which on a phone is inside the drawer, behind the burger, so from the insurance
page there was no visible route back to the companion app at all.

The switcher under the logo replaces that. It reads as a label ("Travel Insurance") because that
is its first job: saying which product you are in. It happens to open.

This is the public twin of services/portals.py, which does the same for the two staff consoles.
They are deliberately not merged: those are consoles behind a login and these are products, the
lists have nothing in common, and one function pretending to answer both questions would have to
be read twice to be understood once.
"""
from flask import request, url_for

from app.services import urls

# key, label, the endpoint that serves it, and the icon for the menu.
#
# The icon is an inline SVG path rather than a Font Awesome class because the two headers that
# draw this menu do not load the same things: base.html has Font Awesome, the marketing landing
# page does not, and adding a render-blocking CDN stylesheet to the busiest page on the site for
# three glyphs is a poor trade. One path, drawn identically in both.
PRODUCTS = [
    {'key': 'companion', 'label': 'Travel Companion', 'endpoint': 'main.index',
     'blurb': 'Find a travel companion',
     'icon': 'M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L11 19v-5.5L21 16z'},
    {'key': 'insurance', 'label': 'Travel Insurance', 'endpoint': 'insurance.landing',
     'blurb': 'Quote and compare cover',
     'icon': 'M12 2 4 5.5v6c0 5 3.4 9.2 8 10.5 4.6-1.3 8-5.5 8-10.5v-6L12 2zm-1.2 13.3L7.5 12l1.4-1.4 1.9 1.9 4.3-4.3 1.4 1.4-5.7 5.7z'},
    {'key': 'sahayak', 'label': 'Sahayak', 'endpoint': 'sahayak.landing',
     'blurb': 'A nurse visit at home',
     'icon': 'M12 3 2 11h3v10h6v-6h2v6h6V11h3L12 3zm1 7h2v2h-2v2h-2v-2H9v-2h2V8h2v2z'},
]

# Drawn beside the product you are already on, and beside a link that leaves the site.
TICK = 'M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z'
EXTERNAL = 'M7 17 17 7M9 7h8v8'

# Which blueprint belongs to which product. Everything not named here is the companion app,
# which is what the rest of this codebase is.
BY_BLUEPRINT = {'insurance': 'insurance', 'sahayak': 'sahayak'}


def current_key():
    return BY_BLUEPRINT.get((request.blueprint or '').split('.')[0], 'companion')


def current_label():
    """The name of the product this page belongs to -- the text under the logo."""
    key = current_key()
    return next(p['label'] for p in PRODUCTS if p['key'] == key)


def menu():
    """Every product, with the current one marked.

    public_url, not url_for: insurance and Sahayak answer beside the app's prefix rather than
    inside it, and the menu should offer the address each product is actually known by.
    """
    here = current_key()
    out = []
    for p in PRODUCTS:
        out.append({'key': p['key'], 'label': p['label'], 'icon': p['icon'],
                    'blurb': p['blurb'], 'current': p['key'] == here,
                    'url': urls.public_url(p['endpoint'])})
    return out


def extras():
    """The group's other properties, minus anything this app already serves, so the menu does
    not offer two different links called the same thing."""
    from app.services import nri_services
    ours = {p['label'].lower() for p in PRODUCTS}
    return [(label, href) for label, href in nri_services.resolved()
            if href and label.lower() not in ours]
