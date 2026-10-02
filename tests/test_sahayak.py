"""Sahayak home healthcare: the public page, booking requests, and the queue staff work.

This phase is a request desk, not a dispatch system, and these tests hold that line: a booking
is something a human picks up, the catalogue is admin-managed, and nothing clinical is stored
here yet. The last of those is the one worth guarding — a vitals field appearing in this table
later should be a deliberate decision with retention and access rules behind it, not a drift.
"""
from datetime import datetime, timedelta

import pytest

from conftest import login, logout
from app import db as _db
from app.models import SahayakBooking, SAHAYAK_STATUSES
from app.services import help_center, sahayak

GOOD = {'service': 'phlebotomy', 'patient_name': 'Lakshmi Rao', 'patient_age': '68',
        'phone': '+91 90000 00000', 'email': 'child@example.com',
        'address': '12 Green Park, New Delhi', 'pincode': '110016',
        'access_notes': 'Ring twice', 'when_type': 'asap',
        'notes': 'Fasting lipid profile, the doctor asked for it'}


def book(client, **over):
    return client.post('/api/sahayak-booking', json={**GOOD, **over})


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def injected(client):
    """What the page hands the bundle. The catalogue is no longer rendered as HTML -- the page
    is a React bundle now (frontend/sahayak), so what is worth asserting is the data it is
    given, which is the same thing the markup used to be built from."""
    import json
    import re
    html = client.get('/sahayak').data.decode()
    m = re.search(r'window\.__SAHAYAK__ = (\{.*?\});', html, re.S)
    assert m, 'the page should inject its data'
    return json.loads(m.group(1)), html


def test_the_page_hands_the_bundle_the_catalogue_with_prices(client, db):
    data, html = injected(client)
    assert '<div id="root">' in html, 'the bundle needs somewhere to mount'
    assert [s['key'] for s in data['services']] == sahayak.keys()
    by_name = {s['name']: s for s in data['services']}
    assert by_name['Blood draw (phlebotomy)']['price'] == '149'


def test_the_page_follows_the_admin_catalogue(client, db):
    sahayak.save([{'key': 'night_care', 'name': 'Overnight attendant', 'blurb': 'Someone stays the night.',
                   'price': '1200', 'duration': '10 hours', 'icon': 'fa-moon'}])
    data, _ = injected(client)
    assert [(s['name'], s['price']) for s in data['services']] == [('Overnight attendant', '1200')]


def test_the_bundle_is_told_where_to_post(client, db):
    """Both forms on the page reach our own endpoints: the API we read the catalogue from is
    read-only, so a booking is still ours to store."""
    data, _ = injected(client)
    assert data['bookingUrl'].endswith('/api/sahayak-booking')
    assert data['applyUrl'].endswith('/api/sahayak-apply')
    assert data['csrfToken']


def test_the_published_helplines_reach_it(client, db):
    """The design shipped with [YOUR HELPLINE NUMBER] in the footer. It comes from the admin
    screen like every other number on the site."""
    from app.services import offices
    data, _ = injected(client)
    assert [p['digits'] for p in data['phones']] == [n['digits'] for n in offices.numbers('sahayak')]
    assert data['supportEmail'] == offices.email('sahayak')


def test_questions_come_from_this_products_help_screen(client, db):
    """Sahayak has its own questions and its own screen. They used to be a category inside the
    companion app's list, which is why nobody could find where to write one."""
    help_center.save([{'key': sahayak.FAQ_CATEGORY, 'title': 'Sahayak',
                       'icon': 'fa-house-medical', 'blurb': 'Home visits'}],
                     [{'id': 'sk1', 'category': sahayak.FAQ_CATEGORY,
                       'question': 'Can I book for my parents from abroad?',
                       'answer': 'Yes. You book and we call them to confirm.'}],
                     site='sahayak')
    html = client.get('/sahayak').data.decode()
    assert 'Can I book for my parents from abroad?' in html
    other = help_center.faqs('companion')
    assert other and other[0]['question'] not in html      # only this product's questions


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------

def test_a_booking_is_stored_with_everything_needed_to_turn_up(client, db):
    r = book(client)
    assert r.status_code == 201 and r.get_json()['success']

    b = SahayakBooking.query.one()
    assert (b.service_name, b.quoted_price) == ('Blood draw (phlebotomy)', '149')
    assert (b.patient_name, b.patient_age, b.phone) == ('Lakshmi Rao', 68, '+91 90000 00000')
    assert b.pincode == '110016' and b.access_notes == 'Ring twice'
    assert b.status == 'new' and b.when_display == 'As soon as possible'


def test_booking_does_not_require_an_account(client, db):
    """The person arranging care for a parent may not have one, and a sign-up wall loses them."""
    assert book(client).status_code == 201
    assert SahayakBooking.query.one().user_id is None


def test_a_signed_in_booking_is_linked_to_that_account(client, db, user):
    login(client, 'bob@test.com')
    book(client)
    assert SahayakBooking.query.one().user_id == user.id


def test_the_quoted_price_survives_a_catalogue_change(client, db):
    """What somebody was shown at the time is the record; later price edits must not rewrite it."""
    book(client)
    sahayak.save([{'key': 'phlebotomy', 'name': 'Blood draw (phlebotomy)', 'blurb': 'x',
                   'price': '999', 'duration': '10 min', 'icon': 'fa-vial'}])
    b = SahayakBooking.query.one()
    assert b.quoted_price == '149' and b.service_name == 'Blood draw (phlebotomy)'


def test_a_scheduled_visit_keeps_its_time(client, db):
    when = (datetime.now() + timedelta(days=3)).replace(second=0, microsecond=0)
    r = book(client, when_type='scheduled', scheduled_for=when.strftime('%Y-%m-%dT%H:%M'))
    assert r.status_code == 201
    b = SahayakBooking.query.one()
    assert b.when_type == 'scheduled' and b.scheduled_for.date() == when.date()
    assert 'As soon as possible' not in b.when_display


@pytest.mark.parametrize('bad, why', [
    ({'service': ''}, 'no service'),
    ({'service': 'not_a_service'}, 'unknown service'),
    ({'patient_name': ''}, 'nobody to visit'),
    ({'phone': ''}, 'no phone, and the team calls to confirm'),
    ({'phone': 'call me'}, 'phone with no digits'),
    ({'address': ''}, 'no address to go to'),
    ({'email': 'nope'}, 'malformed email'),
    ({'when_type': 'scheduled', 'scheduled_for': ''}, 'scheduled with no time'),
    ({'when_type': 'scheduled', 'scheduled_for': '2020-01-01T10:00'}, 'a time in the past'),
])
def test_an_unusable_request_is_refused_and_stored_nowhere(client, db, bad, why):
    r = book(client, **bad)
    assert r.status_code == 400, why
    assert SahayakBooking.query.count() == 0


def test_nothing_clinical_is_stored_by_a_booking(db):
    """This phase records where to go and who to ask for, and no health information.

    Vitals, wound photographs and medication records carry retention, consent and access
    obligations that have not been decided yet. If a column for any of them appears here, that
    decision should have been made first.
    """
    columns = {c.name for c in SahayakBooking.__table__.columns}
    for clinical in ('vitals', 'temperature', 'blood_pressure', 'glucose', 'diagnosis',
                     'medication', 'photo', 'wound', 'spo2'):
        assert not any(clinical in c for c in columns), clinical


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('who, url', [
    ('cs@test.com', '/cs/sahayak'),
    ('admin@test.com', '/admin/sahayak'),
])
def test_both_consoles_see_the_queue(client, db, cs_user, admin_user, who, url):
    book(client)
    login(client, who)
    r = client.get(url)
    assert r.status_code == 200
    html = r.data.decode()
    assert 'Lakshmi Rao' in html and '110016' in html
    assert 'Ring twice' in html                       # the agent needs to know how to get in


def test_the_queue_is_staff_only(client, db, user):
    book(client)
    assert client.get('/cs/sahayak').status_code in (301, 302)
    login(client, 'bob@test.com')
    assert client.get('/cs/sahayak').status_code in (302, 403)


def test_cs_assigns_then_completes_a_booking(client, db, cs_user):
    book(client)
    bid = SahayakBooking.query.one().id
    login(client, 'cs@test.com')

    r = client.post('/cs/sahayak/%d/update' % bid,
                    json={'status': 'assigned', 'assigned_to_name': 'Priya S'})
    assert r.status_code == 200 and r.get_json()['status'] == 'assigned'
    b = _db.session.get(SahayakBooking, bid)
    assert b.assigned_to_name == 'Priya S' and b.assigned_at is not None
    assert b.assigned_by_id == cs_user.id

    r = client.post('/cs/sahayak/%d/update' % bid, json={'status': 'completed'})
    assert r.status_code == 200
    assert _db.session.get(SahayakBooking, bid).completed_at is not None


def test_a_booking_cannot_be_assigned_to_nobody(client, db, cs_user):
    """"Assigned" with no name is a status that tells the next agent nothing."""
    book(client)
    bid = SahayakBooking.query.one().id
    login(client, 'cs@test.com')
    r = client.post('/cs/sahayak/%d/update' % bid, json={'status': 'assigned'})
    assert r.status_code == 400
    assert _db.session.get(SahayakBooking, bid).status == 'new'


def test_cancelling_records_why(client, db, cs_user):
    book(client)
    bid = SahayakBooking.query.one().id
    login(client, 'cs@test.com')
    client.post('/cs/sahayak/%d/update' % bid,
                json={'status': 'cancelled', 'cancelled_reason': 'Family went to a clinic instead'})
    b = _db.session.get(SahayakBooking, bid)
    assert b.status == 'cancelled' and 'clinic' in b.cancelled_reason


def test_an_unknown_status_is_refused(client, db, cs_user):
    book(client)
    bid = SahayakBooking.query.one().id
    login(client, 'cs@test.com')
    assert client.post('/cs/sahayak/%d/update' % bid, json={'status': 'teleported'}).status_code == 400


def test_the_cs_queue_shows_open_work_and_admin_shows_everything(client, db, cs_user, admin_user):
    book(client)
    bid = SahayakBooking.query.one().id
    login(client, 'cs@test.com')
    client.post('/cs/sahayak/%d/update' % bid,
                json={'status': 'assigned', 'assigned_to_name': 'Priya S'})
    client.post('/cs/sahayak/%d/update' % bid, json={'status': 'completed'})

    # done work leaves the CS working queue but is still a filter away
    assert 'Lakshmi Rao' not in client.get('/cs/sahayak').data.decode()
    assert 'Lakshmi Rao' in client.get('/cs/sahayak?status=completed').data.decode()

    logout(client)                      # signing in while already signed in is a no-op
    login(client, 'admin@test.com')
    assert 'Lakshmi Rao' in client.get('/admin/sahayak').data.decode()


def test_internal_notes_never_reach_the_public_page(client, db, cs_user):
    book(client)
    bid = SahayakBooking.query.one().id
    login(client, 'cs@test.com')
    client.post('/cs/sahayak/%d/update' % bid, json={'cs_notes': 'Son is difficult on the phone'})
    assert 'difficult on the phone' not in client.get('/sahayak').data.decode()


# ---------------------------------------------------------------------------
# The catalogue screen
# ---------------------------------------------------------------------------

def test_admin_edits_the_catalogue(client, db, admin_user):
    login(client, 'admin@test.com')
    assert client.get('/admin/sahayak/services').status_code == 200

    r = client.post('/admin/sahayak/services', data={
        'key': ['health_checkup', ''],
        'name': ['Health checkup', ''],
        'blurb': ['Vitals at home.', 'dropped, it has no name'],
        'price': ['349', '100'], 'duration': ['15 min', ''], 'icon': ['fa-heart-pulse', ''],
    }, follow_redirects=True)
    assert r.status_code == 200 and 'Saved 1 service' in r.data.decode()

    saved = sahayak.services()
    assert [s['name'] for s in saved] == ['Health checkup']
    assert saved[0]['price'] == '349'


def test_the_catalogue_screen_is_admin_only(client, db, cs_user):
    login(client, 'cs@test.com')
    assert client.get('/admin/sahayak/services').status_code in (302, 403)


def test_every_status_is_reachable_through_the_endpoint(client, db, cs_user):
    """A status in the model that no screen can set is dead weight; this catches that."""
    login(client, 'cs@test.com')
    for status in SAHAYAK_STATUSES:
        if status == 'new':
            continue                        # where a booking starts
        book(client)
        bid = SahayakBooking.query.order_by(SahayakBooking.id.desc()).first().id
        r = client.post('/cs/sahayak/%d/update' % bid,
                        json={'status': status, 'assigned_to_name': 'Priya S',
                              'cancelled_reason': 'test'})
        assert r.status_code == 200, status
        assert _db.session.get(SahayakBooking, bid).status == status
