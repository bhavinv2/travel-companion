"""Admin translations editor: shipped catalog listing + DB overrides that win at render time."""
from conftest import login, logout


def test_requires_admin(client, cs_user):
    login(client, 'cs@test.com')
    assert client.get('/admin/options/translations?lang=hi').status_code in (302, 403)


def test_list_shipped_strings(client, admin_user):
    login(client, 'admin@test.com')
    d = client.get('/admin/options/translations?lang=hi').get_json()
    assert d['lang'] == 'hi' and len(d['items']) >= 25
    inbox = next(i for i in d['items'] if i['id'] == 'Inbox')
    assert inbox['shipped'] and inbox['override'] == ''
    assert {l['code'] for l in d['languages']} == {'hi', 'te'}


def test_google_only_language_rejected(client, admin_user):
    login(client, 'admin@test.com')
    r = client.get('/admin/options/translations?lang=ta')
    assert r.status_code == 400 and 'Google Translate only' in r.get_json()['error']


def test_save_override_and_reset(client, admin_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/options/translations/save',
                    json={'lang': 'hi', 'items': {'Inbox': 'TESTBOX'}}).get_json()
    assert r['success'] and r['overridden'] == 1
    d = client.get('/admin/options/translations?lang=hi').get_json()
    assert next(i for i in d['items'] if i['id'] == 'Inbox')['override'] == 'TESTBOX'
    r2 = client.post('/admin/options/translations/save',
                     json={'lang': 'hi', 'items': {'Inbox': ''}}).get_json()
    assert r2['success'] and r2['overridden'] == 0


def test_override_wins_on_rendered_pages(client, admin_user):
    login(client, 'admin@test.com')
    client.post('/admin/options/translations/save',
                json={'lang': 'hi', 'items': {'Privacy Policy': 'XXPRIVXX'}})
    logout(client)
    client.set_cookie('lang', 'hi')
    html = client.get('/').data.decode('utf-8')
    assert 'XXPRIVXX' in html                       # override beats the shipped catalog
    assert 'गोपनीयता नीति' not in html


def test_options_screen_has_translations_tab(client, admin_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/options').data.decode('utf-8')
    assert 'sec-translations' in html and 'trSave' in html      # lives inside the Languages tab


def test_new_curated_language_editable_immediately(client, admin_user):
    login(client, 'admin@test.com')
    client.post('/admin/options/site_languages',
                json={'items': [{'code': 'hi', 'label': 'हिंदी', 'mode': 'babel'},
                                {'code': 'ta', 'label': 'தமிழ்', 'mode': 'babel'}]})
    d = client.get('/admin/options/translations?lang=ta').get_json()
    assert d['lang'] == 'ta' and len(d['items']) >= 25          # full source list, no .po needed
    assert all(i['shipped'] == '' for i in d['items'])           # nothing shipped for Tamil yet
    assert 'ta' in {l['code'] for l in d['languages']}
    r = client.post('/admin/options/translations/save',
                    json={'lang': 'ta', 'items': {'Inbox': 'இன்பாக்ஸ்'}}).get_json()
    assert r['success'] and r['overridden'] == 1
