"""The group's two phone apps on Google Play and the App Store: Preventia (families) and Preventia Provider (doctors
and care partners). The "Get our apps" tab and popup on every public page show them (_get_app.html,
static/js/get-app.js); a QR code there opens /get-app/<key> (routes/main.py), which sends the phone that scanned it
to its own store.

The App Store addresses carry no country: Apple opens the visitor's own store (both apps are in India's, the USA's
and Canada's), where a link copied from the Indian store would show families abroad India's.
"""
import functools
import re

APPS = [
    {'key': 'user', 'name': 'Preventia', 'who': 'For families',
     'text': "Doctor video calls, lab tests at home, Sahayak visits and the whole family's health records, in one app.",
     'play': 'com.preventia.user', 'apple': '6781031704'},
    {'key': 'provider', 'name': 'Preventia Provider', 'who': 'For healthcare partners',
     'text': 'Doctors, nutritionists, Sahayaks, pharmacies and labs: bookings, video consultations and patients, '
             'on your phone.',
     'play': 'com.preventia.provider', 'apple': '6781034381'},
]
ICON = 'img/apps/preventia.png'          # both apps wear the same icon in the stores

BY_KEY = {a['key']: a for a in APPS}


def play_url(app):
    return 'https://play.google.com/store/apps/details?id=' + app['play']


def apple_url(app):
    return 'https://apps.apple.com/app/id' + app['apple']


def store_url(key, user_agent=''):
    """The store a phone with this User-Agent installs `key` from (None: no such app). A computer gets Google Play's
    page, which can send the app to the visitor's Android phone."""
    app = BY_KEY.get(key)
    if not app:
        return None
    if re.search(r'iPhone|iPad|iPod', user_agent or ''):
        return apple_url(app)
    return play_url(app)


@functools.lru_cache(maxsize=16)
def qr_svg(url):
    """`url` as a QR code, an <svg> that takes the size its box gives it."""
    import segno
    return segno.make(url, error='m').svg_inline(dark='#0F1C55', light=None, border=0, omitsize=True)


def for_page():
    """What the tab and popup show: each app with its store links, icon and the QR code a computer's visitor scans,
    and the group's address for the box's "From Preventia360"."""
    from flask import url_for
    from app.services.nri_services import GROUP_URL
    out = []
    for a in APPS:
        go = url_for('main.get_app', key=a['key'], _external=True)
        out.append({'key': a['key'], 'name': a['name'], 'who': a['who'], 'text': a['text'],
                    'play': play_url(a), 'package': a['play'], 'apple': apple_url(a),
                    'icon': url_for('static', filename=ICON), 'qr': qr_svg(go)})
    return {'apps': out, 'group': GROUP_URL}
