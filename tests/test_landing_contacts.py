"""Admin -> Landing page: what is saved there is what every public page shows.

Changing a number or the support address on that screen used to leave most pages as they were.
The home page, the insurance page, help, privacy and terms printed the configured SUPPORT_EMAIL
instead of the published list; the Sahayak forms had two numbers typed into the bundle; and each
server process kept its own copy of the settings for a while after a save made in another."""
import json
import re

from conftest import login
from app.services import offices, settings


NEW_NUMBERS = {'num_label': ['India desk', 'Canada desk'], 'num_iso': ['IN', 'CA'],
               'num_number': ['98765 43210', '(416) 555-0188'], 'num_whatsapp': ['0']}
NEW_EMAIL = {'mail_label': ['Help'], 'mail_address': ['care@example.org']}


def save(client, **extra):
    data = {'contact_email': '', 'contact_email_enabled': ''}
    data.update(NEW_NUMBERS)
    data.update(NEW_EMAIL)
    data.update(extra)
    return client.post('/admin/landing', data=data)


def page_data(html, name):
    """The JSON a React page is handed (window.__INSURANCE__ / window.__SAHAYAK__)."""
    raw = re.search(r'window\.%s = (\{.*?\});\s*</script>' % name, html, re.S).group(1)
    return json.loads(raw)


def test_every_public_page_follows_the_admin_screen(client, db, admin_user):
    login(client, admin_user.email)
    assert save(client).status_code == 302
    client.post('/auth/logout')

    home = client.get('/').get_data(as_text=True)
    assert 'mailto:care@example.org' in home and 'support@connectingdesis.com' not in home
    assert 'wa.me/919876543210' in home and '4165550188' in home

    ins = page_data(client.get('/travel-insurance').get_data(as_text=True), '__INSURANCE__')
    assert ins['supportEmail'] == 'care@example.org'
    assert ins['whatsapp'] == '919876543210'
    assert [p['digits'] for p in ins['supportPhones']] == ['919876543210', '14165550188']

    sah = page_data(client.get('/sahayak').get_data(as_text=True), '__SAHAYAK__')
    assert sah['supportEmail'] == 'care@example.org'
    assert [p['digits'] for p in sah['phones']] == ['919876543210', '14165550188']

    for path in ('/contact-us', '/help', '/privacy', '/terms'):
        html = client.get(path).get_data(as_text=True)
        assert 'care@example.org' in html, path
        assert 'support@connectingdesis.com' not in html, path


def test_a_number_kept_to_one_page(client, db, admin_user):
    login(client, admin_user.email)
    save(client, num_sites_1_insurance='on')            # the Canada desk: insurance only
    client.post('/auth/logout')
    assert '4165550188' in client.get('/travel-insurance').get_data(as_text=True)
    assert '4165550188' not in client.get('/').get_data(as_text=True)


def test_the_insurance_page_override_is_shown_on_the_landing_screen(client, db, admin_user):
    from app.services import insurance_page
    insurance_page.save_page('', [], admin_user, support_email_text='insure@example.org')
    login(client, admin_user.email)
    save(client)
    page = client.get('/admin/landing').get_data(as_text=True)
    assert 'insure@example.org' in page and 'Empty that box' in page
    client.post('/auth/logout')
    ins = page_data(client.get('/travel-insurance').get_data(as_text=True), '__INSURANCE__')
    assert ins['supportEmail'] == 'insure@example.org'           # the more specific screen wins


def test_a_save_in_another_worker_is_seen_at_once(app, client, db, admin_user):
    """Two gunicorn workers each keep a copy. Saving in one used to leave the other showing the
    old address for up to CACHE_SECONDS; the next request now notices the change."""
    assert 'mailto:info@nriparentservice.com' in client.get('/').get_data(as_text=True)
    # this process's copy is warm; now another worker writes straight to the table
    from app.models import AppSetting
    from datetime import datetime, timedelta
    row = db.session.get(AppSetting, settings.LANDING_KEY) or AppSetting(key=settings.LANDING_KEY, value={})
    value = dict(row.value or {})
    value['contact_emails'] = [{'label': 'Help', 'address': 'other@example.org', 'sites': []}]
    row.value = value
    row.updated_at = datetime.utcnow() + timedelta(seconds=1)
    db.session.add(row)
    db.session.commit()
    assert settings._cache                                      # still holding the old copy
    assert 'mailto:other@example.org' in client.get('/').get_data(as_text=True)


def test_support_address_falls_back_to_the_configured_one(app, db, admin_user):
    offices.save_emails([], admin_user)
    with app.test_request_context('/'):
        assert offices.support_address() == app.config['SUPPORT_EMAIL']
