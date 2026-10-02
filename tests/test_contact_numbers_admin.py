"""Adding a country is a row, not a code change.

There used to be exactly two fields, whatsapp_in and whatsapp_us, so a Canadian number had no
slot to go in. This walks the admin screen that replaced them: adding, targeting a number at one
page, and what happens to a number nobody could ring.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login  # noqa: E402
from app.services import offices  # noqa: E402

SCREEN = '/admin/landing'


def post(client, rows, **extra):
    """Post the screen the way the browser does: parallel arrays, one checkbox per row+site."""
    data = {'contact_email': '', 'num_label': [], 'num_iso': [], 'num_number': []}
    data.update(extra)
    for i, r in enumerate(rows):
        data['num_label'].append(r.get('label', ''))
        data['num_iso'].append(r.get('iso', 'IN'))
        data['num_number'].append(r.get('number', ''))
        for site in r.get('sites', []):
            data['num_sites_%d_%s' % (i, site)] = site
        if r.get('whatsapp'):
            data.setdefault('num_whatsapp', []).append(str(i))
    return client.post(SCREEN, data=data, follow_redirects=True)


def test_the_screen_lists_what_is_published(client, db, admin_user):
    login(client, 'admin@test.com')
    html = client.get(SCREEN).data.decode()
    assert 'id="numRows"' in html and 'id="addNum"' in html
    assert 'name="num_number"' in html and 'name="num_iso"' in html


def test_a_third_country_can_be_added(client, db, admin_user):
    """The whole point. India and USA were the only two slots there were."""
    login(client, 'admin@test.com')
    post(client, [
        {'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': True},
        {'label': 'USA', 'iso': 'US', 'number': '+1 917 900 5094'},
        {'label': 'Canada', 'iso': 'CA', 'number': '416 555 0199'},
    ])
    assert [n['label'] for n in offices.numbers()] == ['India', 'USA', 'Canada']
    assert offices.numbers()[2]['e164'] == '+14165550199'


def test_a_number_can_be_aimed_at_one_page(client, db, admin_user):
    """The checkbox carries its row's index, which is the only way it says which row it is for.
    Numbering it by the site instead ticks the wrong row."""
    login(client, 'admin@test.com')
    post(client, [
        {'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': True},
        {'label': 'Canada', 'iso': 'CA', 'number': '416 555 0199', 'sites': ['contact']},
    ])
    assert [n['label'] for n in offices.numbers('contact')] == ['India', 'Canada']
    assert [n['label'] for n in offices.numbers('insurance')] == ['India']


def test_a_number_nobody_could_ring_is_dropped(client, db, admin_user):
    login(client, 'admin@test.com')
    post(client, [
        {'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360'},
        {'label': 'Typo', 'iso': 'US', 'number': '+1'},
    ])
    assert [n['label'] for n in offices.numbers()] == ['India']


def test_clearing_them_all_hides_every_button(client, db, admin_user):
    login(client, 'admin@test.com')
    post(client, [])
    assert offices.numbers() == []
    assert 'class="wa-btn' not in client.get('/').data.decode()


def test_the_added_country_reaches_the_chooser(client, db, admin_user):
    """Not just stored -- shown. The chooser used to name India and USA in the markup."""
    login(client, 'admin@test.com')
    post(client, [
        {'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': True},
        {'label': 'USA', 'iso': 'US', 'number': '+1 917 900 5094'},
        {'label': 'Canada', 'iso': 'CA', 'number': '416 555 0199'},
    ])
    client.post('/auth/logout')
    html = client.get('/help').data.decode()
    assert 'wa.me/14165550199' in html and 'Canada' in html


def test_an_install_that_never_opens_the_screen_keeps_its_numbers(app, db):
    """Rows saved under the old two-field shape are read through the same path, so nothing has
    to be migrated before somebody gets round to the new screen."""
    from app.services import settings
    settings.set_landing_settings({'whatsapp_in': '+91 98765 43210', 'whatsapp_us': ''})
    rows = offices.numbers()
    assert [n['e164'] for n in rows] == ['+919876543210']


# ---------------------------------------------------------------------------
# Support addresses, the same way
# ---------------------------------------------------------------------------

def post_mail(client, rows):
    data = {'contact_email': '', 'num_label': [], 'num_iso': [], 'num_number': [],
            'mail_label': [], 'mail_address': []}
    for i, r in enumerate(rows):
        data['mail_label'].append(r.get('label', ''))
        data['mail_address'].append(r.get('address', ''))
        for site in r.get('sites', []):
            data['mail_sites_%d_%s' % (i, site)] = site
    return client.post(SCREEN, data=data, follow_redirects=True)


def test_a_second_address_can_be_added(client, db, admin_user):
    login(client, 'admin@test.com')
    post_mail(client, [
        {'label': 'General', 'address': 'info@nriparentservice.com'},
        {'label': 'Insurance desk', 'address': 'cover@nriparentservice.com',
         'sites': ['insurance']},
    ])
    assert [e['address'] for e in offices.emails()] == ['info@nriparentservice.com',
                                                        'cover@nriparentservice.com']


def test_an_address_can_be_aimed_at_one_page(client, db, admin_user):
    login(client, 'admin@test.com')
    post_mail(client, [
        {'label': 'General', 'address': 'info@nriparentservice.com'},
        {'label': 'Insurance desk', 'address': 'cover@nriparentservice.com',
         'sites': ['insurance']},
    ])
    assert [e['address'] for e in offices.emails('insurance')] == [
        'info@nriparentservice.com', 'cover@nriparentservice.com']
    assert [e['address'] for e in offices.emails('sahayak')] == ['info@nriparentservice.com']


def test_something_that_is_not_an_address_is_dropped(client, db, admin_user):
    """A mailto: that bounces is worse than no link."""
    login(client, 'admin@test.com')
    post_mail(client, [
        {'label': 'General', 'address': 'info@nriparentservice.com'},
        {'label': 'Typo', 'address': 'not-an-address'},
    ])
    assert [e['address'] for e in offices.emails()] == ['info@nriparentservice.com']


# ---------------------------------------------------------------------------
# The number has to reach the pages, not just the store
# ---------------------------------------------------------------------------

CANADA = '+1 (647) 770-2288'


def test_canada_ships_with_the_defaults(app, db):
    """An install nobody has configured still offers the three lines that are answered."""
    rows = offices.numbers()
    assert [r['e164'] for r in rows] == ['+918019111360', '+19179005094', '+16477702288']


def test_the_insurance_page_publishes_every_country(client, db):
    """It used to read whatsapp_in / whatsapp_us directly, so a third country could be saved on
    the admin screen and still never appear on the page that sells the policy."""
    offices.save_numbers([
        {'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': True,
         'sites': []},
        {'label': 'Canada', 'iso': 'CA', 'number': CANADA, 'whatsapp': False, 'sites': []},
    ])
    html = client.get('/travel-insurance').data.decode()
    assert '16477702288' in html and 'Canada' in html


def test_a_line_aimed_elsewhere_stays_off_the_insurance_page(client, db):
    offices.save_numbers([
        {'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': True,
         'sites': []},
        {'label': 'Canada', 'iso': 'CA', 'number': CANADA, 'whatsapp': False,
         'sites': ['sahayak']},
    ])
    assert '16477702288' not in client.get('/travel-insurance').data.decode()


def test_the_schema_names_the_country_that_answers(app, db):
    """areaServed was 'IN' for India and 'US' for everything else, so a Canadian line was
    announced to search engines as an American one."""
    from app.services import org
    rows = offices.numbers()
    with app.test_request_context():
        points = org.organization(rows)['contactPoint']
    assert [p['areaServed'] for p in points] == ['IN', 'US', 'CA']


def test_canada_reaches_the_contact_page_and_the_chooser(client, db):
    for path in ('/contact-us', '/help'):
        html = client.get(path).data.decode()
        assert '16477702288' in html, path
