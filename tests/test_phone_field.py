"""Phone numbers: one list of dialling codes, one rule, every form.

Every form here used a bare <input type="tel"> with a hint in the placeholder, so people typed
nine digits with no country, a trunk-prefixed 0, or 0091 -- and nothing noticed until somebody
tried to ring it. The number is stored dialable now, whatever was typed.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import phone  # noqa: E402

# Every server-rendered form that asks for a number. A new one must use the shared field too,
# which is what the last test in this file is for.
FORMS = ['/contact-us', '/auth/register']


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw,iso,expected', [
    ('9848000000', 'IN', '+919848000000'),          # bare national number
    ('098480 00000', 'IN', '+919848000000'),        # trunk prefix, dropped not dialled
    ('0091 98480 00000', 'IN', '+919848000000'),    # 00 is how much of the world writes +
    ('+91 98480 00000', 'IN', '+919848000000'),     # already international
    ('91 98480 00000', 'IN', '+919848000000'),      # code typed without the plus
    ('917 900 5094', 'US', '+19179005094'),
    ('416 555 0199', 'CA', '+14165550199'),         # a country the site did not used to know
])
def test_whatever_was_typed_is_stored_dialable(app, raw, iso, expected):
    assert phone.normalise(raw, iso)[0] == expected


@pytest.mark.parametrize('raw,why', [
    ('123', 'too short'),
    ('1' * 20, 'too long'),
    ('+999 12345678', 'no such dialling code'),
])
def test_a_number_nobody_could_ring_is_refused(app, raw, why):
    value, error = phone.normalise(raw, 'IN')
    assert value == '' and error, why


def test_an_empty_number_is_not_an_error(app):
    """Most of these fields are optional; whether a missing one matters is the caller's call."""
    assert phone.normalise('', 'IN') == ('', None)


def test_the_country_is_chosen_not_guessed(app):
    """The same digits mean different numbers in different countries, which is exactly why the
    picker exists rather than a parser."""
    assert phone.normalise('9848000000', 'IN')[0] == '+919848000000'
    assert phone.normalise('9848000000', 'US')[0] == '+19848000000'


def test_the_picker_offers_the_common_ones_first(app):
    """US at the top, and selected before anybody chooses: the parents are in India, the person
    filling the form in usually is not."""
    popular, rest = phone.choices()
    assert [c['iso'] for c in popular][:3] == ['US', 'IN', 'CA']
    assert phone.DEFAULT_ISO == 'US'
    assert len(popular) + len(rest) == len(phone.BY_ISO)
    assert all(c['dial'].isdigit() for c in rest)


def test_the_field_opens_on_that_country(client, db):
    """The default is what the markup actually marks selected, not just a constant."""
    import re
    html = client.get('/contact-us').data.decode()
    block = html.split('name="phone_cc"', 1)[1].split('</select>', 1)[0]
    chosen = re.findall(r'value="([A-Z]{2})"[^>]*selected', block)
    assert chosen == [phone.DEFAULT_ISO]


# ---------------------------------------------------------------------------
# The field
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('path', FORMS)
def test_every_form_uses_the_shared_field(client, db, path):
    html = client.get(path).data.decode()
    assert 'data-phone-field' in html, path
    assert 'name="phone_cc"' in html, path
    assert 'phone-field.js' in html, path


@pytest.mark.parametrize('path', FORMS)
def test_the_picker_carries_the_dialling_code(client, db, path):
    """The browser check reads it off the chosen option, so there is no second copy of the
    country table in JavaScript."""
    html = client.get(path).data.decode()
    field = html.split('data-phone-field', 1)[1]
    assert 'data-dial="91"' in field and 'data-dial="1"' in field


def test_no_form_is_left_with_a_bare_phone_box(client, db):
    """A new form that asks for a number has to use the field, or it is back to nine digits and
    no country."""
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'app', 'templates')
    offenders = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith('.html'):
                continue
            path = os.path.join(folder, name)
            body = open(path, encoding='utf-8').read()
            for m in re.finditer(r'<input[^>]*name="phone"[^>]*>', body):
                offenders.append(os.path.relpath(path, root) + ': ' + m.group(0)[:70])
    assert not offenders, 'bare phone inputs left: %s' % offenders


def test_what_the_contact_form_stores_is_dialable(app, db, client):
    from app.models import ContactMessage
    client.post('/contact-us', data={
        'name': 'Asha', 'email': 'a@example.com', 'message': 'Please ring me back.',
        'phone': '09848000000', 'phone_cc': 'IN'})
    assert ContactMessage.query.one().phone == '+919848000000'


def test_a_number_from_another_country_survives_the_form(app, db, client):
    from app.models import ContactMessage
    client.post('/contact-us', data={
        'name': 'Ravi', 'email': 'r@example.com', 'message': 'Please ring me back.',
        'phone': '416 555 0199', 'phone_cc': 'CA'})
    assert ContactMessage.query.one().phone == '+14165550199'


# ---------------------------------------------------------------------------
# How a stored number is written down
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('e164,shown', [
    ('+19179005094', '+1 (917) 900-5094'),
    ('+16477702288', '+1 (647) 770-2288'),      # the same shape, so the same spelling
    ('+918019111360', '+91 80191 11360'),
    ('+971501234567', '+971 50 123 4567'),
])
def test_a_number_is_written_the_way_its_country_writes_it(e164, shown):
    assert phone.pretty(e164) == shown


def test_a_country_we_are_unsure_of_keeps_what_staff_typed():
    """A London landline groups 20 7946 0958 and a mobile 7700 900123; guessing one rule for
    both prints something no British reader recognises."""
    assert phone.pretty('+442079460958', '+44 20 7946 0958') == '+44 20 7946 0958'
    assert phone.pretty('+61412345678', '0412 345 678') == '0412 345 678'
    # with nothing to fall back on, the dialling code is still split off -- a reader has to be
    # able to see where +44 ends even when we cannot group the rest
    assert phone.pretty('+442079460958') == '+44 2079460958'


def test_nothing_in_nothing_out():
    assert phone.pretty('', 'as typed') == 'as typed'


def test_the_contact_page_lists_them_all_the_same_way(client, db, admin_user):
    """Two people entering the same shape of number differently is what made two US-format
    lines sit under each other looking like one of them was wrong."""
    from app.services import offices
    offices.save_numbers([
        {'label': 'USA', 'iso': 'US', 'number': '+1 917 900 5094', 'whatsapp': False, 'sites': []},
        {'label': 'Canada', 'iso': 'CA', 'number': '6477702288', 'whatsapp': False, 'sites': []},
    ], admin_user)
    shown = [n['display'] for n in offices.numbers()]
    assert shown == ['+1 (917) 900-5094', '+1 (647) 770-2288']
    html = client.get('/contact-us').data.decode()
    for line in shown:
        assert line in html, line


# The empty box
# ---------------------------------------------------------------------------

def test_the_empty_box_shows_that_country_s_shape():
    """A US visitor met "98480 00000" -- an Indian mobile -- as the hint for their own number,
    which is both wrong and the one place the field gets to teach the shape it wants."""
    assert phone.example('US') == '(555) 123-4567'
    assert phone.example('CA') == '(555) 123-4567'      # same dialling code, same shape
    assert phone.example('IN') == '98480 00000'
    assert phone.example() == phone.example(phone.DEFAULT_ISO)


def test_no_example_is_offered_for_a_country_we_cannot_spell():
    """Better an empty box than one suggesting a shape that country does not use."""
    assert phone.example('DE') == ''
    assert phone.example('ZZ') == ''


def test_every_form_hints_with_the_country_it_has_selected(client, db):
    """The placeholder is rendered server-side so the first paint is already right; the script
    only takes over when the country changes."""
    html = client.get('/auth/register').data.decode()
    field = html.split('class="pf-num"', 1)[1]
    assert 'placeholder="(555) 123-4567"' in field.split('/>', 1)[0]


def test_staff_lists_spell_stored_numbers_the_same_way(client, db, admin_user):
    """Numbers reach these tables as E.164 from the server, so without pretty() the console
    showed "+19179005094" while the contact page showed "+1 (917) 900-5094"."""
    from app.models import ContactMessage, db as _db
    _db.session.add(ContactMessage(name='Asha', email='asha@example.com',
                                   phone='+19179005094', message='Hello', topic='companion'))
    _db.session.commit()
    client.post('/auth/login', data={'email': admin_user.email, 'password': 'password123'},
                follow_redirects=True)
    html = client.get('/cs/voices').data.decode()
    assert '+1 (917) 900-5094' in html


# Finding the country code at a glance
# ---------------------------------------------------------------------------

def test_a_country_we_cannot_group_still_shows_where_its_code_ends():
    """"+46764498115" is a Swedish mobile, but nothing in it says where the 46 stops. A column
    of those cannot be scanned without counting digits against a table."""
    assert phone.pretty('+46764498115') == '+46 764498115'
    assert phone.pretty('+61412345678') == '+61 412345678'
    assert phone.pretty('+442079460958') == '+44 2079460958'


def test_the_countries_we_do_know_keep_their_own_spelling():
    """The split is a floor, not a replacement: where there is a real convention it wins."""
    assert phone.pretty('+19179005094') == '+1 (917) 900-5094'
    assert phone.pretty('+919848000000') == '+91 98480 00000'
    assert phone.pretty('+971501234567') == '+971 50 123 4567'


def test_a_number_a_human_has_already_spaced_is_left_alone():
    """Somebody who wrote it out knows their own country's grouping better than this does."""
    assert phone.pretty('+442079460958', '+44 20 7946 0958') == '+44 20 7946 0958'
    assert phone.pretty('+61412345678', '0412 345 678') == '0412 345 678'
    # but a run of digits as the fallback is no better than no fallback
    assert phone.pretty('+46764498115', '0764498115') == '+46 764498115'


def test_where_the_code_ends_is_the_longest_match():
    """Codes overlap -- 1 is the USA and Canada, 7 is Russia and Kazakhstan -- so this cannot
    say which country it is, only where the code stops."""
    assert phone.split_dial('+971501234567') == ('971', '501234567')   # not '97' or '9'
    assert phone.split_dial('+19179005094') == ('1', '9179005094')
    assert phone.split_dial('+999999') == ('', '999999')               # no such code


def test_a_sahayak_booking_is_stored_the_same_way_every_other_number_is(client, db):
    """The form sends the dialling code and the number joined by a space. Stored as typed, the
    bookings table would hold a shape no other table uses."""
    from app.models import SahayakBooking
    r = client.post('/api/sahayak-booking', json={
        'service': 'health_checkup', 'patient_name': 'Asha',
        'phone': '+46 764498115', 'address': '12 Rose Lane', 'when_type': 'asap',
    })
    assert r.status_code == 201, r.get_json()
    booking = SahayakBooking.query.get(r.get_json()['booking_id'])
    assert booking.phone == '+46764498115'
    assert phone.pretty(booking.phone) == '+46 764498115'
