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

# key, label, the endpoint that serves it, and an icon for the menu.
PRODUCTS = [
    {'key': 'companion', 'label': 'Travel Companion', 'endpoint': 'main.index',
     'icon': 'fa-plane-departure', 'blurb': 'Find a travel companion'},
    {'key': 'insurance', 'label': 'Travel Insurance', 'endpoint': 'insurance.landing',
     'icon': 'fa-shield-heart', 'blurb': 'Quote and compare cover'},
    {'key': 'sahayak', 'label': 'Sahayak', 'endpoint': 'sahayak.landing',
     'icon': 'fa-house-medical', 'blurb': 'A nurse visit at home'},
]

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
