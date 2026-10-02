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
    client.post('/auth/logout')
    assert '--amber:#123456' in client.get('/').data.decode()


def test_admin_landing_rejects_bad_hex(client, db, admin_user):
    settings.set_landing_settings({'colors': {'amber': 'not-a-colour'}}, admin_user)
    assert settings.landing_settings()['colors']['amber'] == settings.LANDING_COLOR_DEFAULTS['amber']


def test_admin_landing_requires_admin(client, db, user):
    login(client, 'bob@test.com')
    assert client.get('/admin/landing').status_code in (302, 403)


def test_whatsapp_buttons_follow_the_configured_numbers(client, db, admin_user, user):
    """None -> no button anywhere. One -> direct wa.me links. Several -> one button and a team
    chooser listing every published number. Never a placeholder.

    The numbers used to be two fixed fields, India and USA, so a third country meant editing the
    markup. They are a list an admin adds to now, which is what this walks.
    """
    from app.services import offices

    offices.save_numbers([], admin_user)
    html = client.get('/').data.decode()
    assert 'id="suModal"' in html and 'id="suContactBtn"' in html and 'mailto:' in html
    assert 'class="wa-btn' not in html and 'wa.me/' not in html and 'id="waChooser"' not in html

    # one number: every placement is a plain link straight to it, no chooser
    offices.save_numbers([{'label': 'India', 'iso': 'IN', 'number': '+91 98765 43210',
                           'whatsapp': True, 'sites': []}], admin_user)
    html = client.get('/').data.decode()
    # the number, plus the opener every link now carries
    assert html.count('href="https://wa.me/919876543210?text=') == 4   # float, sign-up, contact modal, footer
    assert 'data-wa-open' not in html and 'id="waChooser"' not in html

    # two: the placements become chooser buttons and exactly one chooser is on the page
    offices.save_numbers([
        {'label': 'India', 'iso': 'IN', 'number': '+91 98765 43210', 'whatsapp': True, 'sites': []},
        {'label': 'USA', 'iso': 'US', 'number': '+1 917 555 0100', 'whatsapp': False, 'sites': []},
    ], admin_user)
    html = client.get('/').data.decode()
    assert html.count('data-wa-open') == 4
    assert html.count('id="waChooser"') == 1
    assert 'https://wa.me/919876543210' in html and 'https://wa.me/19175550100' in html
    assert 'India' in html and 'USA' in html

    # ...and a third country is a row, not a code change
    offices.save_numbers([
        {'label': 'India', 'iso': 'IN', 'number': '+91 98765 43210', 'whatsapp': True, 'sites': []},
        {'label': 'USA', 'iso': 'US', 'number': '+1 917 555 0100', 'whatsapp': False, 'sites': []},
        {'label': 'Canada', 'iso': 'CA', 'number': '+1 416 555 0199', 'whatsapp': False, 'sites': []},
    ], admin_user)
    html = client.get('/').data.decode()
    assert 'https://wa.me/14165550199' in html and 'Canada' in html

    # the footer is shared, so a signed-in traveller's home gets the same button and chooser
    login(client, 'bob@test.com')
    html = client.get('/').data.decode()
    assert 'data-wa-open' in html and html.count('id="waChooser"') == 1
    client.post('/auth/logout')

    # clearing the list hides every button again
    offices.save_numbers([], admin_user)
    assert 'class="wa-btn' not in client.get('/').data.decode()


def test_whatsapp_number_needs_enough_digits_to_count(client, db, admin_user):
    """A typo like '+91' alone must not put a broken button on the site."""
    settings.set_landing_settings({'whatsapp_in': '+91', 'whatsapp_us': ''}, admin_user)
    assert settings.whatsapp_numbers() == {'in': None, 'us': None}
    assert 'class="wa-btn' not in client.get('/').data.decode()
