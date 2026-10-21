"""Sales CRM 2.0, run 5b -- the staff app: installable from staff pages (5.7), and Find a person (5.8).

    manifest   /manifest.webmanifest: the CRM's name, My day as the start, standalone, the console's colour, the
               existing logo; linked only on staff pages; no service worker; under the /travel-companions prefix
               every address in it carries the prefix
    find       Find a person matches quote and payment references and family names, and its chips name the
               product (never its code)
"""
import json
import os
import re

import pytest

from conftest import login, make_user
from app import create_app, db as _db
from app.models import CrmHousehold, CrmPayment, CrmQuote
from app.services import crm

from test_crm_wa_sync_engine import ti_lead

PREFIX = '/travel-companions'


def test_the_manifest_says_what_the_app_is(app, client):
    r = client.get('/manifest.webmanifest')
    assert r.status_code == 200 and r.mimetype == 'application/manifest+json'
    m = json.loads(r.get_data(as_text=True))
    assert m['name'] == 'NRI Parent Service CRM' and m['short_name'] == 'CRM'
    assert m['start_url'] == '/cs/crm/today' and m['display'] == 'standalone' and m['scope'] == '/'
    assert m['theme_color'] == '#1f6fd6'
    css = open(os.path.join('app', 'static', 'css', 'ui.css'), encoding='utf-8').read()
    assert '--ui-primary: #1f6fd6' in css                               # the console's own blue
    # two square icons made from the logo (final review: a browser offers "Install" only with a square >= 192 px)
    assert [i['sizes'] for i in m['icons']] == ['192x192', '512x512']
    from PIL import Image
    for i in m['icons']:
        assert i['type'] == 'image/png' and i['src'].startswith('/static/img/app-icon-')
        n = int(i['sizes'].split('x')[0])
        with Image.open(os.path.join('app', 'static', 'img', 'app-icon-%d.png' % n)) as im:
            assert im.size == (n, n)


def test_only_staff_pages_link_it_and_nothing_registers_a_service_worker(app, client, admin_user):
    assert 'rel="manifest"' not in client.get('/').get_data(as_text=True)
    traveller = make_user('trav@test.com', 'trav')
    login(client, traveller.email)
    assert 'rel="manifest"' not in client.get('/dashboard').get_data(as_text=True)
    client.post('/auth/logout')
    from flask import g
    g.pop('_login_user', None)
    login(client, admin_user.email)
    page = client.get('/admin/crm/today').get_data(as_text=True)
    assert '<link rel="manifest" href="/manifest.webmanifest"/>' in page and 'name="theme-color"' in page
    for root, _, files in os.walk(os.path.join('app', 'static', 'js')):
        for f in files:
            if f.endswith('.js'):
                assert 'serviceWorker' not in open(os.path.join(root, f), encoding='utf-8', errors='ignore').read(), f
    assert 'serviceWorker' not in page


@pytest.fixture()
def papp(tmp_path):
    app = create_app({'TESTING': True, 'WTF_CSRF_ENABLED': False, 'SQLALCHEMY_DATABASE_URI': 'sqlite://',
                      'UPLOAD_FOLDER': str(tmp_path / 'u'), 'PRIVATE_UPLOAD_FOLDER': str(tmp_path / 'p'),
                      'SERVER_NAME': 'nriparentservice.com', 'MAIL_PASSWORD': None, 'APP_URL_PREFIX': PREFIX})
    with app.app_context():
        _db.create_all()
        from app.services import settings as _settings
        _settings.clear_cache()
        yield app
        _db.session.remove()
        _db.drop_all()


def test_under_the_prefix_every_address_carries_it(papp):
    c = papp.test_client()
    r = c.get(PREFIX + '/manifest.webmanifest', base_url='https://nriparentservice.com')
    m = json.loads(r.get_data(as_text=True))
    assert m['start_url'] == PREFIX + '/cs/crm/today' and m['scope'] == PREFIX + '/'
    assert all(i['src'].startswith(PREFIX + '/static/img/app-icon-') for i in m['icons'])
    u = make_user('cs@test.com', 'cs', role='cs')
    c.post(PREFIX + '/auth/login', data={'email': u.email, 'password': 'password123'},
           base_url='https://nriparentservice.com')
    page = c.get(PREFIX + '/cs/crm/today', base_url='https://nriparentservice.com').get_data(as_text=True)
    assert 'rel="manifest" href="%s/manifest.webmanifest"' % PREFIX in page


# ============================================================================================ Find a person

def test_find_matches_quotes_payments_and_families_and_names_the_product(app, client, admin_user):
    crm.ensure_defaults()
    a = ti_lead(phone='+919800004001', name='Quoted Qamar')
    b = ti_lead(phone='+919800004002', name='Paying Parvati')
    c = ti_lead(phone='+919800004003', name='Family Farah')
    q = CrmQuote(lead_id=a.id, title='Cover for Dallas', status='sent')
    _db.session.add(q)
    _db.session.add(CrmPayment(lead_id=b.id, reference='pay_ZX81Q', status='pending'))
    fam = CrmHousehold(name='Varadarajan family')
    _db.session.add(fam)
    _db.session.flush()
    c.person.household_id = fam.id
    _db.session.commit()
    login(client, admin_user.email)
    find = lambda text: client.get('/admin/crm/find?q=' + text).get_json()['items']
    assert [i['name'] for i in find('Q-%d' % q.id)] == ['Quoted Qamar']
    assert [i['name'] for i in find('pay_ZX81Q')] == ['Paying Parvati']
    assert [i['name'] for i in find('Varadarajan')] == ['Family Farah']
    chips = find('Quoted Qamar')[0]['chips']
    assert chips and chips[0]['text'].startswith('Travel Insurance · ') and not chips[0]['text'].startswith('TI ')
