"""The "Get our apps" tab and box (services/store_apps.py, _get_app.html, static/js/get-app.js) and the QR codes'
/get-app/<key>, which sends a phone to its own store."""
import json
import re

import pytest

from app import create_app, db as _db
from conftest import make_user

PREFIX = '/travel-companions'
SITE = 'https://nriparentservice.com'
IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 Version/17.4 Mobile Safari/604.1'
ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/124.0 Mobile Safari/537.36'


@pytest.fixture()
def dapp(tmp_path):
    app = create_app({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        'UPLOAD_FOLDER': str(tmp_path / 'uploads'),
        'PRIVATE_UPLOAD_FOLDER': str(tmp_path / 'private'),
        'MAIL_PASSWORD': None,
        'APP_URL_PREFIX': PREFIX,
        'APP_PUBLIC_HOST': 'nriparentservice.com',
    })
    with app.app_context():
        _db.create_all()
        from app.services import settings as _settings
        _settings.clear_cache()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def dc(dapp):
    return dapp.test_client()


def box(html):
    """The box's data on a page, or None when the page has no box."""
    m = re.search(r'<script type="application/json" id="getAppData">(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


@pytest.mark.parametrize('path', ['/home', '/blog', '/travel-insurance', PREFIX + '/', PREFIX + '/help'])
def test_every_public_page_has_the_tab(dc, path):
    r = dc.get(path, base_url=SITE)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    data = box(html)
    assert data and [a['name'] for a in data['apps']] == ['Preventia', 'Preventia Provider']
    assert html.count('js/get-app.js') == 1


def test_the_box_carries_both_stores_and_a_qr_code(dc):
    data = box(dc.get('/home', base_url=SITE).get_data(as_text=True))
    user, provider = data['apps']
    assert user['play'] == 'https://play.google.com/store/apps/details?id=com.preventia.user'
    assert provider['play'] == 'https://play.google.com/store/apps/details?id=com.preventia.provider'
    # no country in the App Store address: Apple opens the visitor's own store, abroad too
    assert user['apple'] == 'https://apps.apple.com/app/id6781031704'
    assert provider['apple'] == 'https://apps.apple.com/app/id6781034381'
    assert user['qr'].startswith('<svg') and 'viewBox' in user['qr'] and user['qr'] != provider['qr']
    assert user['icon'].startswith(PREFIX + '/static/img/apps/preventia.png')
    assert data['group'] == 'https://preventia360.com/'


def test_staff_pages_have_no_tab(dc):
    make_user('ops@test.com', 'ops', role='admin')
    dc.post(PREFIX + '/auth/login', base_url=SITE, data={'email': 'ops@test.com', 'password': 'password123'})
    assert box(dc.get('/home', base_url=SITE).get_data(as_text=True)) is None


@pytest.mark.parametrize('ua, store', [
    (IPHONE, 'https://apps.apple.com/app/id6781031704'),
    (ANDROID, 'https://play.google.com/store/apps/details?id=com.preventia.user'),
    ('Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'https://play.google.com/store/apps/details?id=com.preventia.user'),
])
def test_the_qr_code_opens_the_phones_own_store(dc, ua, store):
    r = dc.get(PREFIX + '/get-app/user', base_url=SITE, headers={'User-Agent': ua})
    assert r.status_code == 302 and r.headers['Location'] == store


def test_the_provider_qr_code_and_an_unknown_app(dc):
    r = dc.get(PREFIX + '/get-app/provider', base_url=SITE, headers={'User-Agent': IPHONE})
    assert r.headers['Location'] == 'https://apps.apple.com/app/id6781034381'
    assert dc.get(PREFIX + '/get-app/nope', base_url=SITE).status_code == 404


def test_the_hero_links_the_group(dc):
    html = dc.get('/home', base_url=SITE).get_data(as_text=True)
    assert '"groupUrl": "https://preventia360.com/"' in html
