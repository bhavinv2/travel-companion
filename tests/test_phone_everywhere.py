"""Every phone number on the site: picked with its country, stored dialable, shown with the code
separated, and findable however it is spaced.

These are the places a sweep of the whole codebase found falling short. Each test names the
promise it holds, because the ways this went wrong were quiet ones -- a number stored without
its country, a code eaten off the front of a mobile, a search that found nothing -- and nobody
saw them until somebody tried to ring a customer.
"""
from datetime import date, timedelta

import pytest

from conftest import login
from app import db as _db
from app.models import (CompanionRequest, ContactMessage, ContactPoint, InsuranceQuote,
                        SahayakBooking, ScrapeRecipe, ScrapeRow, ScrapeRun, User)
from app.services import contacts, phone


# ---------------------------------------------------------------------------
# Sign-up and staff accounts
# ---------------------------------------------------------------------------

SIGNUP = {'email': 'new@example.com', 'password': 'longenough1', 'first_name': 'Asha',
          'agree_terms': 'on'}


def test_a_mistyped_number_at_sign_up_is_an_error_not_a_crash(client, db):
    """The phone check ran before the error list existed, so this answered 500."""
    r = client.post('/auth/register', data={**SIGNUP, 'phone': '12', 'phone_cc': 'IN'})
    assert r.status_code == 200
    assert User.query.filter_by(email='new@example.com').count() == 0
    assert b'too short' in r.data


def test_a_redrawn_sign_up_keeps_the_country_that_was_picked(client, db):
    """Redrawn after any error, the picker used to guess from the digits: an Indian number
    typed with India chosen came back with Iran selected, and resubmitting stored a wrong one."""
    r = client.post('/auth/register', data={**SIGNUP, 'agree_terms': '', 'phone': '98480 00000',
                                            'phone_cc': 'IN'})
    html = r.data.decode()
    picker = html.split('name="phone_cc"', 1)[1].split('</select>', 1)[0]
    assert 'value="IN" data-dial="91" selected' in picker
    assert 'value="IR" data-dial="98" selected' not in picker


def test_sign_up_stores_the_number_with_its_country(client, db):
    client.post('/auth/register', data={**SIGNUP, 'phone': '098480 00000', 'phone_cc': 'IN'})
    assert User.query.filter_by(email='new@example.com').one().phone == '+919848000000'


def test_an_account_made_by_an_admin_stores_its_number_dialable(client, db, admin_user):
    """The form drew a country picker; the route ignored it and kept the box as typed."""
    login(client, 'admin@test.com')
    client.post('/admin/users/new', data={'email': 'agent2@example.com', 'username': 'agent2',
                                          'phone': '0764498115', 'phone_cc': 'SE', 'roles': 'cs'})
    u = User.query.filter_by(email='agent2@example.com').first()
    assert u is not None and u.phone == '+46764498115'


# ---------------------------------------------------------------------------
# The shared phone field
# ---------------------------------------------------------------------------

def test_the_field_does_not_guess_a_country_from_national_digits(app):
    """iso_for reads a STORED number; given "98480 00000" it answers Iran."""
    with app.test_request_context():
        from flask import render_template_string
        html = render_template_string(
            "{% from '_phone_field.html' import phone_field with context %}"
            "{{ phone_field(value='98480 00000') }}")
    picker = html.split('name="phone_cc"', 1)[1].split('</select>', 1)[0]
    assert 'value="%s" data-dial' % phone.DEFAULT_ISO in picker
    assert 'value="IR" data-dial="98" selected' not in picker


def test_the_field_still_reads_the_country_off_a_stored_number(app):
    with app.test_request_context():
        from flask import render_template_string
        html = render_template_string(
            "{% from '_phone_field.html' import phone_field with context %}"
            "{{ phone_field(value='+46764498115') }}")
    assert 'value="SE" data-dial="46" selected' in html


# ---------------------------------------------------------------------------
# Contact forms
# ---------------------------------------------------------------------------

def test_a_number_that_cannot_be_dialled_is_refused_not_stored(client, db):
    """contact_form.clean knew it was unusable and stored it as typed anyway."""
    r = client.post('/api/landing-contact', json={
        'name': 'Asha', 'email': 'a@example.com', 'phone': '+0 1234567', 'phone_cc': 'IN',
        'message': 'Please call me back about my mother.'})
    assert r.status_code == 400
    assert 'country dialling code' in r.get_json()['error']
    assert ContactMessage.query.count() == 0


def test_the_footer_newsletter_signs_people_up(client, db):
    """It borrowed the call-back endpoint, which requires a phone, so every sign-up failed."""
    r = client.post('/api/newsletter', json={'email': 'Reader@Example.com'})
    assert r.status_code == 201 and r.get_json()['success']
    m = ContactMessage.query.one()
    assert m.email == 'reader@example.com' and m.phone is None
    assert 'Newsletter' in m.message


def test_the_newsletter_still_wants_a_real_address(client, db):
    assert client.post('/api/newsletter', json={'email': 'nope'}).status_code == 400
    assert ContactMessage.query.count() == 0


def test_the_footer_posts_to_the_newsletter_endpoint(client, db):
    html = client.get('/about').data.decode()
    assert 'ftrNewsForm' in html, 'the footer sign-up should be on this page'
    assert '/api/newsletter' in html and 'api/landing-contact' not in html.split('ftrNewsForm', 1)[1]


# ---------------------------------------------------------------------------
# Insurance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('phone_in, cc, stored', [
    ('0764498115', 'SE', '+46764498115'),       # trunk 0 dropped -- sent apart, not "+46 0764..."
    ('91234 56789', 'IN', '+919123456789'),     # an Indian mobile that starts with 91
    ('+1 917 900 5094', 'IN', '+19179005094'),  # a + typed in the box wins over the picker
])
def test_an_insurance_enquiry_stores_the_number_dialable(client, db, phone_in, cc, stored):
    r = client.post('/api/insurance-enquiry', json={
        'name': 'Asha', 'email': 'a@example.com', 'phone': phone_in, 'phone_cc': cc,
        'destination': 'Canada'})
    assert r.status_code == 201, r.get_json()
    assert ContactMessage.query.one().phone == stored


def test_the_insurance_page_hint_shows_the_numbers_the_page_shows(client, db, admin_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/insurance-page').data.decode()
    hint = html.split('Phone numbers come from', 1)[1].split('</p>', 1)[0]
    from app.services import offices
    for p in offices.numbers('insurance'):
        assert p['display'] in hint


# ---------------------------------------------------------------------------
# Sahayak
# ---------------------------------------------------------------------------

BOOKING = {'service': 'phlebotomy', 'patient_name': 'Lakshmi Rao', 'email': 'c@example.com',
           'address': '12 Green Park, New Delhi', 'when_type': 'asap'}


@pytest.mark.parametrize('phone_in, cc, stored', [
    ('0764498115', 'SE', '+46764498115'),
    ('91234 56789', 'IN', '+919123456789'),
    ('+91 90000 00000', '', '+919000000000'),   # a bundle cached from before still works
])
def test_a_sahayak_booking_reads_the_country_beside_the_number(client, db, phone_in, cc, stored):
    from app.services import sahayak
    BOOKING['service'] = sahayak.services()[0]['key']
    r = client.post('/api/sahayak-booking', json={**BOOKING, 'phone': phone_in, 'phone_cc': cc})
    assert r.status_code == 201, r.get_json()
    assert SahayakBooking.query.one().phone == stored


def test_a_sahayak_application_reads_each_numbers_country(client, db):
    r = client.post('/api/sahayak-apply', json={
        'full_name': 'Asha Menon', 'mobile': '91234 56789', 'mobile_cc': 'IN',
        'whatsapp': '0764498115', 'whatsapp_cc': 'SE', 'email': 'asha@example.com',
        'qualification': 'GNM', 'registration_number': 'TNNMC 2231'})
    assert r.status_code == 201, r.get_json()
    m = ContactMessage.query.one()
    assert m.phone == '+919123456789'
    assert 'WhatsApp: +46 764498115' in m.message


# ---------------------------------------------------------------------------
# Contact rows -- the CS post form, the claim page, the public post form
# ---------------------------------------------------------------------------

def test_a_phone_row_is_stored_with_the_country_picked_beside_it():
    rows, errors = contacts.parse_contact_rows([
        {'type': 'auto', 'value': '0764498115', 'label': '', 'cc': 'SE'},
        {'type': 'mobile', 'value': '98480 00000', 'label': '', 'cc': 'IN'},
        {'type': 'auto', 'value': 'ravi@example.com', 'label': '', 'cc': 'IN'},
    ])
    assert errors == []
    assert [r['value'] for r in rows] == ['+46764498115', '+919848000000', 'ravi@example.com']


@pytest.mark.parametrize('value, cc, stored', [
    # a WhatsApp link already carries the full international number -- read as a national one
    # with the default country picked, it became +146764498115
    ('https://wa.me/46764498115', 'US', '+46764498115'),
    ('wa.me/+919848000000', 'US', '+919848000000'),
    ('https://api.whatsapp.com/send/?phone=19179005094', 'IN', '+19179005094'),
    # the picker is not shown beside this (it is not a bare number), so its hidden default must
    # not be applied: no country is known, and none is invented
    ('whatsapp: 0764498115', 'US', '0764498115'),
])
def test_a_country_is_only_applied_where_the_screen_showed_it(value, cc, stored):
    rows, errors = contacts.parse_contact_rows([{'type': 'auto', 'value': value, 'cc': cc}])
    assert errors == [] and rows[0]['value'] == stored


def test_a_row_with_no_country_chosen_is_left_alone():
    """"Country?" means nobody said. A legacy bare number must not quietly become Indian."""
    rows, _ = contacts.parse_contact_rows([{'type': 'mobile', 'value': '9175551234', 'cc': ''}])
    assert rows[0]['value'] == '9175551234'


def test_the_form_post_carries_each_rows_country(app):
    from werkzeug.datastructures import MultiDict
    form = MultiDict([('contact_type', 'auto'), ('contact_value', '0764498115'),
                      ('contact_label', ''), ('contact_cc', 'SE'),
                      ('contact_type', 'email'), ('contact_value', 'x@example.com'),
                      ('contact_label', ''), ('contact_cc', 'IN')])
    rows, errors = contacts.parse_contact_rows(form)
    assert errors == [] and [r['value'] for r in rows] == ['+46764498115', 'x@example.com']


def test_every_contact_row_draws_a_country_picker(client, db, cs_user):
    login(client, 'cs@test.com')
    html = client.get('/cs/posts/new').data.decode()
    assert 'name="contact_cc"' in html
    # in the template for an added row too, or the lists would fall out of step
    tpl = html.split('id="contactRowTpl"', 1)[1].split('</template>', 1)[0]
    assert 'name="contact_cc"' in tpl


# ---------------------------------------------------------------------------
# Shown with the code separated
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('ctype, value, shown', [
    ('mobile', '+46764498115', '+46 764498115'),
    ('whatsapp', '+919848000000', '+91 98480 00000'),
    ('mobile', '9175551234', '9175551234'),      # no + : no country known, none invented
    ('email', 'a@example.com', 'a@example.com'),
    ('facebook', 'https://facebook.com/x', 'https://facebook.com/x'),
])
def test_a_contact_value_reads_with_its_country_separated(ctype, value, shown):
    assert contacts.display(ctype, value) == shown


def test_the_post_detail_shows_the_spaced_number_and_copies_the_raw_one(client, db, cs_user):
    t = CompanionRequest(travel_type='air', trip_type='one_way', role='seeking_help',
                         flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                         from_date=date.today() + timedelta(days=30))
    t.set_status('open')
    _db.session.add(t)
    _db.session.flush()
    _db.session.add(ContactPoint(trip=t, type='mobile', value='+46764498115'))
    _db.session.commit()
    login(client, 'cs@test.com')
    html = client.get('/cs/posts/%d' % t.id).data.decode()
    assert '<code>+46 764498115</code>' in html
    assert 'data-copy="+46764498115"' in html


# ---------------------------------------------------------------------------
# Found however it is spaced
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('typed', ['+91 98765 43210', '098765 43210', '9876543210',
                                   '+919876543210', '0091 98765 43210'])
def test_a_number_copied_off_the_screen_finds_its_user(client, db, admin_user, typed):
    u = User(email='caller@example.com', username='caller', phone='+919876543210')
    u.set_password('x' * 10)
    _db.session.add(u)
    _db.session.commit()
    login(client, 'admin@test.com')
    html = client.get('/admin/users', query_string={'q': typed}).data.decode()
    assert 'caller@example.com' in html


def test_a_spaced_search_finds_an_insurance_lead(client, db, admin_user):
    _db.session.add(InsuranceQuote(email='lead@example.com', phone='+12145550101',
                                   insurance_type='visitors', citizenship='IND',
                                   start_date=date.today() + timedelta(days=5),
                                   end_date=date.today() + timedelta(days=30),
                                   status='quoted', travellers=[{'age': '62'}]))
    _db.session.commit()
    login(client, 'admin@test.com')
    html = client.get('/admin/insurance-quotes', query_string={'q': '(214) 555-0101'}).data.decode()
    assert 'lead@example.com' in html


def test_a_row_saved_before_numbers_were_normalised_is_found_too(client, db, admin_user):
    _db.session.add(ContactMessage(name='Old Row', email='old@example.com',
                                   phone='+91 98765 43210', message='hello there', topic='companion'))
    _db.session.commit()
    login(client, 'admin@test.com')
    html = client.get('/admin/voices', query_string={'tab': 'contact', 'q': '9876543210'}).data.decode()
    assert 'Old Row' in html


def test_a_word_is_not_treated_as_a_phone_search():
    assert phone.search_digits('Ravi') == ''
    assert phone.search_digits('ravi@example.com') == ''
    assert phone.search_digits('12345') == ''          # too short to be a number search
    assert phone.search_digits('+91 98765 43210') == '919876543210'


# ---------------------------------------------------------------------------
# The scraper's row editor
# ---------------------------------------------------------------------------

def _scraped(db, phone_value):
    rec = ScrapeRecipe(name='phone-test', start_url='http://example.test', mode='source',
                       field_mapping={'origin': 'origin', 'destination': 'destination',
                                      'phone': 'phone'}, default_source='website')
    db.session.add(rec)
    db.session.flush()
    run = ScrapeRun(recipe_id=rec.id, kind='run', status='done')
    db.session.add(run)
    db.session.flush()
    row = ScrapeRow(recipe_id=rec.id, run_id=run.id, row_index=0, key='k1', status='new',
                    data={'origin': 'Hyderabad (HYD)', 'destination': 'Dallas (DFW)',
                          'phone': phone_value, '_key': 'k1'})
    db.session.add(row)
    db.session.commit()
    return row


def test_a_scraped_number_saved_with_a_country_becomes_dialable(client, db, admin_user):
    row = _scraped(db, '0764498115')
    login(client, 'admin@test.com')
    # the digits were not retyped -- only the country picked -- and it must still be kept
    r = client.post('/cs/scraper/api/rows/%d/edit' % row.id,
                    json={'edits': {'phone': '0764498115', 'phone_cc': 'SE'}})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['edits']['phone'] == '+46764498115'
    assert 'phone_cc' not in r.get_json()['edits']


def test_a_scraped_number_that_cannot_be_dialled_is_refused(client, db, admin_user):
    row = _scraped(db, '0764498115')
    login(client, 'admin@test.com')
    r = client.post('/cs/scraper/api/rows/%d/edit' % row.id,
                    json={'edits': {'phone': '12', 'phone_cc': 'SE'}})
    assert r.status_code == 400 and 'too short' in r.get_json()['error']


def test_a_scraped_number_without_a_country_is_kept_as_it_was(client, db, admin_user):
    row = _scraped(db, '0764498115')
    login(client, 'admin@test.com')
    r = client.post('/cs/scraper/api/rows/%d/edit' % row.id,
                    json={'edits': {'phone': '076 449 8115'}})
    assert r.status_code == 200
    assert r.get_json()['edits']['phone'] == '076 449 8115'


@pytest.mark.parametrize('stored', ['9175551234', '0764498115'])
def test_an_existing_bare_number_is_not_given_a_guessed_country(client, db, cs_user, stored):
    """A legacy row saved before rows had a picker. Its picker must start on "Country?" -- a
    guessed India (or the default) would be applied the next time anybody re-saved the post."""
    t = CompanionRequest(travel_type='air', trip_type='one_way', role='seeking_help',
                         flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                         from_date=date.today() + timedelta(days=30))
    t.set_status('open')
    _db.session.add(t)
    _db.session.flush()
    _db.session.add(ContactPoint(trip=t, type='mobile', value=stored))
    _db.session.commit()
    login(client, 'cs@test.com')
    html = client.get('/cs/posts/%d/edit' % t.id).data.decode()
    row = html.split('id="contactRowsBody"', 1)[1].split('</tr>', 1)[0]
    picker = row.split('name="contact_cc"', 1)[1].split('</select>', 1)[0]
    assert '<option value="" selected>Country?</option>' in picker


# ---------------------------------------------------------------------------
# The same person, however their number was stored
# ---------------------------------------------------------------------------

def _trip_with_contact(value, days=30):
    t = CompanionRequest(travel_type='air', trip_type='one_way', role='seeking_help',
                         flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                         from_date=date.today() + timedelta(days=days))
    t.set_status('open')
    _db.session.add(t)
    _db.session.flush()
    _db.session.add(ContactPoint(trip=t, type='mobile', value=value))
    _db.session.commit()
    return t


@pytest.mark.parametrize('stored, typed', [
    ('9876543210', '+919876543210'),      # imported as bare digits, typed through a form
    ('+919876543210', '9876543210'),      # the other way round
    ('09876543210', '+919876543210'),     # with a trunk 0
])
def test_a_shared_contact_is_found_however_it_was_stored(db, stored, typed):
    """Form numbers are E.164 now; imported ones keep their digits. An exact comparison stopped
    seeing that they are the same person."""
    from app.services import duplicates
    other = _trip_with_contact(stored)
    candidate = CompanionRequest(travel_type='air', trip_type='one_way', role='seeking_help',
                                 flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                                 from_date=date.today() + timedelta(days=30))
    found = duplicates.find(candidate, contact_values=[typed])
    assert [d['id'] for d in found] == [other.id]
    assert 'shared contact detail' in found[0]['reasons']


def test_an_e_mail_still_matches_exactly_and_only_exactly(db):
    from app.services import duplicates
    _trip_with_contact('9876543210')
    candidate = CompanionRequest(travel_type='air', trip_type='one_way', role='seeking_help',
                                 flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                                 from_date=date.today() + timedelta(days=30))
    assert duplicates.find(candidate, contact_values=['someone@example.com']) == []


def test_a_sheet_imported_before_keeps_its_import_keys(app):
    """wa.me links are stored with their + now; the import key must still be hashed the old way,
    or every earlier sheet would come back as new rows when uploaded again."""
    import hashlib
    from app.services import importer
    canon = {'origin': 'Hyderabad (HYD)', 'destination': 'Dallas (DFW)', 'start': '2099-12-01',
             'contact': 'https://wa.me/919876543210'}
    with app.app_context():
        r = importer.build_row(canon, 0, 'website')
    assert r['contacts'][0]['value'] == '+919876543210'
    old_basis = '|'.join([r['source_url'], r['flying_from'], r['destination'], r['from_date'] or '',
                          '919876543210'])
    assert r['import_key'] == hashlib.sha1(old_basis.encode('utf-8')).hexdigest()[:64]


def test_a_spaced_number_keeps_its_country_in_the_message_cs_reads(client, db):
    """Typed the way people write it at home -- "076 449 8115" -- the CS message used to show it
    exactly so, with the country it was typed for nowhere in sight."""
    r = client.post('/api/sahayak-apply', json={
        'full_name': 'Asha Menon', 'mobile': '91234 56789', 'mobile_cc': 'IN',
        'whatsapp': '076 449 8115', 'whatsapp_cc': 'SE', 'email': 'asha@example.com',
        'qualification': 'GNM', 'registration_number': 'TNNMC 2231'})
    assert r.status_code == 201
    assert 'WhatsApp: +46 764498115' in ContactMessage.query.one().message
