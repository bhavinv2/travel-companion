"""Flask-Babel i18n: curated Hindi/Telugu catalogs, /api/language, admin site-language config."""
from app import db
from app.models import User

HI_CONSENT_Q = 'मिलान हुआ साथी आपसे कैसे संपर्क कर सकता है?'
HI_PRIVACY = 'गोपनीयता नीति'
TE_CONSENT_Q = 'మ్యాచ్ అయిన సహచరుడు మిమ్మల్ని ఎలా సంప్రదించగలరు?'


def login(client, email, password='password123'):
    return client.post('/auth/login', data={'email': email, 'password': password})


def test_default_is_english(client):
    html = client.get('/').data.decode('utf-8')
    assert 'How can a matched companion reach you?' in html
    assert HI_CONSENT_Q not in html


def test_lang_cookie_renders_hindi(client):
    client.set_cookie('lang', 'hi')
    html = client.get('/').data.decode('utf-8')
    assert HI_CONSENT_Q in html
    assert HI_PRIVACY in html                       # footer link + consent link
    assert '<html lang="hi">' in html


def test_language_api_saves_preference_and_cookie(client, user):
    login(client, 'bob@test.com')
    r = client.post('/api/language', json={'lang': 'te'})
    assert r.status_code == 200 and r.get_json()['success']
    assert db.session.get(User, user.id).language_preference == 'te'
    html = client.get('/').data.decode('utf-8')     # the cookie set by the response sticks
    assert TE_CONSENT_Q in html


def test_saved_preference_wins_without_cookie(client, user):
    user.language_preference = 'hi'
    db.session.commit()
    login(client, 'bob@test.com')
    html = client.get('/').data.decode('utf-8')
    assert HI_CONSENT_Q in html


def test_language_api_works_for_anonymous(client):
    r = client.post('/api/language', json={'lang': 'hi'})
    assert r.get_json()['success']
    assert HI_CONSENT_Q in client.get('/').data.decode('utf-8')


def test_unknown_language_falls_back_to_english(client):
    client.set_cookie('lang', 'zz')                 # no catalog for zz
    html = client.get('/').data.decode('utf-8')
    assert 'How can a matched companion reach you?' in html


def test_admin_site_languages_config(client, admin_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/options/site_languages',
                    json={'items': [{'code': 'hi', 'label': 'हिंदी', 'mode': 'babel'},
                                    {'code': 'fr', 'label': 'Français', 'mode': 'google'}]})
    d = r.get_json()
    assert not d.get('error')
    codes = [row['code'] for row in d['rows']]
    assert 'en' in codes and 'hi' in codes and 'fr' in codes    # English is auto-protected
    en = next(row for row in d['rows'] if row['code'] == 'en')
    assert en['builtin'] and en['mode'] == 'babel'

    bad = client.post('/admin/options/site_languages',
                      json={'items': [{'code': 'not a code!', 'label': 'X', 'mode': 'babel'}]})
    assert bad.get_json().get('error')

    bad2 = client.post('/admin/options/site_languages',
                       json={'items': [{'code': 'hi', 'label': 'X', 'mode': 'nope'}]})
    assert bad2.get_json().get('error')


def test_header_selector_uses_configured_languages(client, admin_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/options/site_languages',
                    json={'items': [{'code': 'hi', 'label': 'हिंदी', 'mode': 'babel'}]})
    assert not r.get_json().get('error')
    client.get('/auth/logout')                      # the selector is on traveller pages
    html = client.get('/').data.decode('utf-8')
    assert 'value="hi"' in html and 'data-mode="babel"' in html
    assert 'value="ta"' not in html                 # removed from the configured list
