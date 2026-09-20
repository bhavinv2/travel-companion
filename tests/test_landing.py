"""New public landing page: routing (landing vs functional home), contact e-mail, admin colours."""
from conftest import login
from app.models import ContactMessage
from app.services import settings, mailer


def test_landing_for_logged_out_and_functional_home_for_logged_in(client, db, user):
    html = client.get('/').data.decode()
    assert 'id="heroPostForm"' in html and 'searchForm' not in html      # marketing landing
    login(client, 'bob@test.com')
    html = client.get('/').data.decode()
    assert 'searchForm' in html and 'id="heroPostForm"' not in html       # functional home


def test_landing_contact_saves_and_only_emails_when_enabled(client, db, admin_user):
    mailer.OUTBOX.clear()
    long_msg = 'Please help me with my parents flight, this is a long enough message.'
    # default: not enabled -> stored as a CS message, no landing e-mail
    r = client.post('/api/landing-contact', json={'name': 'Asha', 'email': 'asha@x.com', 'phone': '', 'message': long_msg})
    assert r.get_json()['success'] and ContactMessage.query.filter_by(email='asha@x.com').count() == 1
    assert not any('asha' in ' '.join(m['recipients']).lower() for m in mailer.OUTBOX)

    # enable + configure -> the configured address is e-mailed
    settings.set_landing_settings({'contact_email_enabled': True, 'contact_email': 'team@desis.com'}, admin_user)
    mailer.OUTBOX.clear()
    r = client.post('/api/landing-contact', json={'name': 'Bala', 'email': 'bala@x.com', 'phone': '', 'message': long_msg})
    assert r.get_json()['success']
    assert any('team@desis.com' in m['recipients'] for m in mailer.OUTBOX)


def test_landing_contact_validates(client, db):
    r = client.post('/api/landing-contact', json={'name': '', 'email': 'bad', 'phone': '', 'message': 'x'})
    assert r.status_code == 400


def test_admin_landing_settings_save_and_inject(client, db, admin_user):
    login(client, 'admin@test.com')
    assert client.get('/admin/landing').status_code == 200
    r = client.post('/admin/landing', data={'contact_email': 'x@y.com', 'contact_email_enabled': 'on', 'color_amber': '#123456'})
    assert r.status_code in (302, 200)
    ls = settings.landing_settings()
    assert ls['contact_email'] == 'x@y.com' and ls['contact_email_enabled'] is True
    assert ls['colors']['amber'] == '#123456'
    # the colour is injected into the logged-out landing
    client.get('/auth/logout')
    assert '--amber:#123456' in client.get('/').data.decode()


def test_admin_landing_rejects_bad_hex(client, db, admin_user):
    settings.set_landing_settings({'colors': {'amber': 'not-a-colour'}}, admin_user)
    assert settings.landing_settings()['colors']['amber'] == settings.LANDING_COLOR_DEFAULTS['amber']


def test_admin_landing_requires_admin(client, db, user):
    login(client, 'bob@test.com')
    assert client.get('/admin/landing').status_code in (302, 403)


def test_signup_prompt_contact_block_only_with_a_configured_number(client, db, admin_user):
    """The 'reach us directly' block must never show a placeholder number."""
    html = client.get('/').data.decode()
    assert 'id="suModal"' in html                       # the prompt itself is always there
    # contact form + support e-mail are always offered; WhatsApp only once a number exists
    assert 'id="suContactBtn"' in html and 'mailto:' in html
    assert 'wa.me/' not in html and 'Call or text' not in html

    settings.set_landing_settings({'contact_whatsapp': '+91 98765 43210'}, admin_user)
    html = client.get('/').data.decode()
    assert 'https://wa.me/919876543210' in html and 'tel:+919876543210' in html
    assert 'Call or text +91 98765 43210' in html

    # admins set it from the Landing page screen, and clearing it hides the block again
    login(client, 'admin@test.com')
    client.post('/admin/landing', data={'contact_email': '', 'contact_whatsapp': ''})
    assert settings.landing_settings()['contact_whatsapp'] == ''
    client.get('/auth/logout')
    assert 'wa.me/' not in client.get('/').data.decode()
