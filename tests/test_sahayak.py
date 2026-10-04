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
from app.services import help_center, preventia, sahayak

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
    # Stored as E.164, not as typed: every other number on the site is stored that way, and a
    # column holding two shapes of the same number is one nobody can scan. The spacing is put
    # back when it is shown.
    assert (b.patient_name, b.patient_age, b.phone) == ('Lakshmi Rao', 68, '+919000000000')
    from app.services import phone as phone_svc
    assert phone_svc.pretty(b.phone) == '+91 90000 00000'
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


# What Preventia sends, and what the page makes of it
# ---------------------------------------------------------------------------

# Trimmed from a live GET /service-categories, keeping the fields the page reads.
REMOTE_SAMPLE = [
    {'id': '9a332a7d-1b81-3ccc-c996-25418794f59e', 'code': 'WELLNESS_SCREEN',
     'providerType': 'SAHAYAK', 'name': 'Wellness Screen',
     'description': 'Category code: SAHAYAK_WELLNESS',
     'pricing': {'configured': True, 'currency': 'INR', 'baseFare': 250.0}},
    {'id': '4531e2a5-431e-ad47-5e57-4727a83ed7a4', 'code': 'PHARMACY_DELIVERY',
     'providerType': 'SAHAYAK', 'name': 'Pharmacy Delivery',
     'description': 'Category code: SAHAYAK_PHARMACY_DELIVERY',
     'pricing': {'configured': True, 'currency': 'INR', 'baseFare': 100.0}},
    {'id': 'ffffffff-0000-0000-0000-000000000000', 'code': 'SOMETHING_NEW',
     'providerType': 'SAHAYAK', 'name': 'Something New',
     'description': 'Category code: SAHAYAK_NEW', 'pricing': {'configured': False}},
]


def test_their_names_and_prices_win():
    """The whole reason the API comes first: a price edited there and not here is a customer
    quoted the wrong number."""
    rows = sahayak.decorate(preventia.as_catalogue(REMOTE_SAMPLE))
    by_key = {r['key']: r for r in rows}
    assert by_key['wellness_screen']['name'] == 'Wellness Screen'
    assert by_key['wellness_screen']['price'] == '250'
    assert by_key['pharmacy_delivery']['price'] == '100'
    # and the id, so a booking can be tied back to their catalogue
    assert by_key['wellness_screen']['remote_id'] == '9a332a7d-1b81-3ccc-c996-25418794f59e'


def test_their_descriptions_never_reach_the_page():
    """Every category's description comes back as its own internal code. Printed on a public
    page that reads as a leak, so ours replaces it -- matched on their code, not on the name,
    which is theirs to reword."""
    rows = sahayak.decorate(preventia.as_catalogue(REMOTE_SAMPLE))
    for r in rows:
        assert 'Category code:' not in (r['blurb'] or ''), r['key']
    by_key = {r['key']: r for r in rows}
    assert by_key['wellness_screen']['blurb'].startswith('A full home check')
    assert by_key['wellness_screen']['duration'] == '60–75 min'


def test_a_category_we_have_no_words_for_still_appears():
    """They can add one tomorrow. It should show up priced and bookable, just plainer -- not
    vanish, and not carry their placeholder text."""
    rows = sahayak.decorate(preventia.as_catalogue(REMOTE_SAMPLE))
    new = [r for r in rows if r['key'] == 'something_new'][0]
    assert new['name'] == 'Something New'
    assert new['blurb'] == ''
    assert new['price'] == ''        # pricing not configured: say nothing rather than invent


def test_the_page_uses_the_remote_catalogue_when_it_answers(app, monkeypatch):
    monkeypatch.setenv('PREVENTIA_API_URL', 'https://example.invalid/api/v1')
    monkeypatch.setenv('PREVENTIA_API_KEY', 'pv_test_key')
    monkeypatch.setattr(preventia, 'service_categories', lambda role=preventia.ROLE: REMOTE_SAMPLE)
    with app.app_context():
        names = [s['name'] for s in sahayak.services()]
    assert names == ['Wellness Screen', 'Pharmacy Delivery', 'Something New']


def test_a_silent_api_falls_back_rather_than_emptying_the_page(app, monkeypatch):
    """None is "could not ask" and must not be read as "no services"."""
    monkeypatch.setenv('PREVENTIA_API_URL', 'https://example.invalid/api/v1')
    monkeypatch.setenv('PREVENTIA_API_KEY', 'pv_test_key')
    monkeypatch.setattr(preventia, 'service_categories', lambda role=preventia.ROLE: None)
    with app.app_context():
        assert len(sahayak.services()) == len(sahayak.DEFAULT_SERVICES)


# The visit journey
# ---------------------------------------------------------------------------

# One section per stage, as GET /gig-forms returns them (trimmed to the fields we read).
SECTIONS = {'sections': [
    {'gigTypeCode': 'SAHAYAK_CHECKOUT', 'gigTypeName': 'Check-out', 'displaySection': 'Ops',
     'stage': 'POST_DURING', 'required': True},
    {'gigTypeCode': 'BOOKING', 'gigTypeName': 'Booking', 'displaySection': 'Booking',
     'stage': 'PRE', 'required': True},
    {'gigTypeCode': 'SAHAYAK_CHECKIN', 'gigTypeName': 'Check-in', 'displaySection': 'Ops',
     'stage': 'PRE_DURING', 'required': True},
    {'gigTypeCode': 'SAHAYAK_CUSTOMER_RATING', 'gigTypeName': 'Customer Rating',
     'displaySection': 'Feedback', 'stage': 'POST', 'required': False},
    {'gigTypeCode': 'WHATEVER_IS_NEXT', 'gigTypeName': 'Whatever Is Next',
     'displaySection': 'New', 'stage': 'DURING', 'required': True},
]}


def test_the_visit_runs_in_the_order_it_happens(monkeypatch):
    """The API gives each section a stage, not a position, so the stages have to be sequenced
    here or check-out turns up before the Sahayak has arrived."""
    monkeypatch.setattr(preventia, 'gig_forms', lambda *a, **k: SECTIONS)
    steps = preventia.journey('any-id')
    assert [s['key'] for s in steps] == [
        'SAHAYAK_CHECKIN', 'WHATEVER_IS_NEXT', 'SAHAYAK_CHECKOUT', 'SAHAYAK_CUSTOMER_RATING']


def test_the_booking_step_is_not_part_of_what_a_visit_covers(monkeypatch):
    """By the time anybody reads this list they have already filled the booking form in."""
    monkeypatch.setattr(preventia, 'gig_forms', lambda *a, **k: SECTIONS)
    assert 'BOOKING' not in [s['key'] for s in preventia.journey('any-id')]


def test_steps_are_renamed_for_the_person_reading_them(monkeypatch):
    """Their names are written for the Sahayak doing the work. Which steps there are, and
    whether each is optional, stays theirs."""
    monkeypatch.setattr(preventia, 'gig_forms', lambda *a, **k: SECTIONS)
    steps = sahayak.decorate_steps(preventia.journey('any-id'))
    by_key = {s['key']: s for s in steps}
    assert by_key['SAHAYAK_CHECKIN']['title'] == 'Sahayak arrives'
    assert by_key['SAHAYAK_CUSTOMER_RATING']['optional'] is True
    # a step we have no words for keeps theirs rather than vanishing
    assert by_key['WHATEVER_IS_NEXT']['title'] == 'Whatever Is Next'


def test_the_journey_endpoint_says_nothing_rather_than_guessing(client, db):
    """Preventia is off in the tests, so there is no catalogue id to ask about. An empty list
    means "we could not tell you" and the page keeps the steps it shipped with."""
    r = client.get('/api/sahayak-journey?service=wellness_screen')
    assert r.status_code == 200
    assert r.get_json() == {'success': True, 'steps': []}
    assert client.get('/api/sahayak-journey').get_json()['steps'] == []


def test_the_page_never_waits_on_the_journey(client, db):
    """Nine of those calls cold is eleven seconds. The page must not make any of them: the
    bundle asks for one service at a time, when somebody opens it."""
    html = client.get('/sahayak').data.decode()
    assert 'journeyUrl' in html, 'the bundle needs the endpoint to call'
    assert '"steps"' not in html, 'the journey must not be rendered into the page'


# ---------------------------------------------------------------------------
# The copy that goes to Preventia (External API 2.8)
# ---------------------------------------------------------------------------
# Their write half is a review queue, not an account factory, and these tests hold that line.
# 2.5/2.6 create a real account and e-mail it a password the moment they are called; these two
# forms are public and anybody can POST to them, so what leaves here is a lead a human
# approves. The other thing guarded below is that the copy is a copy: the request is already
# committed to our tables before it is attempted, and every way it can fail leaves the visitor
# with the same answer they would have had anyway.

APPLY = {'full_name': 'Asha Menon', 'mobile': '+91 90000 00001',
         'email': 'asha@example.com', 'experience': '6 years on a cardiology ward',
         'healthcare_qualification': 'B.Sc Nursing', 'languages': 'Malayalam, English',
         'service_city': 'Kochi'}


class Reply:
    """Just enough of a requests.Response for the client to unwrap."""

    def __init__(self, status=200, body=None, text=None):
        self.status_code = status
        self._body = body
        self.text = text if text is not None else ('{}' if body is None else 'x')

    def json(self):
        if self._body is None:
            raise ValueError('not json')
        return self._body


@pytest.fixture
def live(monkeypatch):
    """Preventia switched on, with its POST captured instead of sent.

    Returns the list of (url, json) the code tried to send, so a test can assert on the payload
    without a network and without conftest's guard being weakened for anyone else.
    """
    monkeypatch.setenv('PREVENTIA_API_URL', 'https://example.invalid/api/v1')
    monkeypatch.setenv('PREVENTIA_API_KEY', 'pv_test_key')
    sent = []

    def fake_post(url, json=None, **kw):
        sent.append((url, json))
        return Reply(200, {'success': True, 'data': {'submissionId': 'sub-1'}})

    monkeypatch.setattr(preventia.requests, 'post', fake_post)
    return sent


def test_a_booking_is_copied_to_preventia_as_a_lead(client, db, live):
    """Everything their reviewer needs to act on it, in the shape 2.8 asks for."""
    assert book(client).status_code == 201
    assert len(live) == 1
    url, body = live[0]
    assert url.endswith('/external/v1/submissions')
    assert body['submissionType'] == 'BOOKING_REQUEST'
    assert body['source'] == 'nriparentservice.com'
    assert body['fullName'] == 'Lakshmi Rao'
    # the dialling code travels in its own field, and only once
    assert body['countryCode'] == '+91'
    assert body['phone'] == '9000000000'
    d = body['details']
    assert d['patient'] == 'Lakshmi Rao' and d['pincode'] == '110016'
    assert d['address'] == '12 Green Park, New Delhi'
    assert d['when'] == 'As soon as possible'
    # so a row in their queue can be matched to a row in ours by hand
    booking = SahayakBooking.query.one()
    assert d['ourReference'] == 'sahayak_bookings#%d' % booking.id


def test_a_lead_carries_who_to_ring_not_only_who_the_visit_is_for(client, db, live):
    """An NRI booking for a parent is the person who answers the phone."""
    assert book(client, contact_name='Ravi Rao').status_code == 201
    body = live[0][1]
    assert body['fullName'] == 'Ravi Rao'
    assert body['details']['patient'] == 'Lakshmi Rao'


def test_an_application_is_copied_as_a_sahayak_signup(client, db, live):
    """The same fields CS reads, so the two readers never see different applications."""
    assert client.post('/api/sahayak-apply', json=APPLY).status_code == 201
    url, body = live[0]
    assert url.endswith('/external/v1/submissions')
    assert body['submissionType'] == 'SAHAYAK_SIGNUP'
    assert body['fullName'] == 'Asha Menon'
    assert body['email'] == 'asha@example.com'
    d = body['details']
    assert d['experience'] == '6 years on a cardiology ward'
    assert d['service_city'] == 'Kochi'
    # the number reads the way the rest of the site writes numbers
    assert d['mobile'] == '+91 90000 00001'
    # and nothing empty: a reviewer reading six filled lines beats twenty with fourteen blank
    assert '' not in d.values() and None not in d.values()


def test_a_lead_never_asks_preventia_to_create_an_account(client, db, live):
    """2.5/2.6 mint an account and e-mail a password on the spot. These forms are public and
    unauthenticated, so a copy-pasted key must not be able to reach them from here."""
    book(client)
    client.post('/api/sahayak-apply', json=APPLY)
    assert live, 'something should have been sent'
    for url, _ in live:
        assert '/onboard/' not in url


def test_nothing_is_sent_when_preventia_is_switched_off(client, db, monkeypatch):
    """The usual state on a developer's machine. A booking must work exactly the same."""
    calls = []

    def fake_post(*a, **k):
        calls.append(a)
        return Reply()

    monkeypatch.setattr(preventia.requests, 'post', fake_post)
    assert book(client).status_code == 201
    assert SahayakBooking.query.count() == 1
    assert calls == []


@pytest.mark.parametrize('reply, why', [
    # their real answer today: §2.8 is documented but not deployed on care360-api, and it comes
    # back through the ordinary envelope rather than as a transport error
    (Reply(404, {'success': False, 'errorCode': 'NOT_FOUND',
                 'message': 'No route matched this request'}, 'x'), 'the route is not deployed'),
    (Reply(404, text='<html>Not Found</html>'), 'a proxy answered instead of them'),
    (Reply(403, text=''), 'the key was not accepted'),
    (Reply(403, {'success': False, 'errorCode': 'ROLE_OUT_OF_SCOPE'}, 'x'), 'out of scope'),
    (Reply(200, {'success': True, 'data': {}}), 'no submissionId came back'),
])
def test_a_booking_survives_every_way_the_copy_can_fail(client, db, monkeypatch, reply, why):
    """The visitor is already owed an answer by the time this runs. Whatever Preventia says,
    the booking is stored and the reply is the one they would have got anyway."""
    monkeypatch.setenv('PREVENTIA_API_URL', 'https://example.invalid/api/v1')
    monkeypatch.setenv('PREVENTIA_API_KEY', 'pv_test_key')
    monkeypatch.setattr(preventia.requests, 'post', lambda *a, **k: reply)
    r = book(client)
    assert r.status_code == 201, why
    assert r.get_json()['success'] is True
    assert SahayakBooking.query.count() == 1, why


def test_a_booking_survives_preventia_being_unreachable(client, db, monkeypatch):
    import requests as _requests

    monkeypatch.setenv('PREVENTIA_API_URL', 'https://example.invalid/api/v1')
    monkeypatch.setenv('PREVENTIA_API_KEY', 'pv_test_key')

    def boom(*a, **k):
        raise _requests.ConnectionError('no route to host')

    monkeypatch.setattr(preventia.requests, 'post', boom)
    assert book(client).status_code == 201
    assert SahayakBooking.query.count() == 1


def test_a_lead_that_did_not_get_across_is_recorded(client, db, monkeypatch):
    """Otherwise it exists only in a log file nobody reads, and the first anyone knows is a
    Preventia admin asking why their queue is empty."""
    from app.models import ActivityEvent

    monkeypatch.setenv('PREVENTIA_API_URL', 'https://example.invalid/api/v1')
    monkeypatch.setenv('PREVENTIA_API_KEY', 'pv_test_key')
    monkeypatch.setattr(preventia.requests, 'post', lambda *a, **k: Reply(
        404, {'success': False, 'errorCode': 'NOT_FOUND',
              'message': 'No route matched this request'}, 'x'))
    book(client)
    ev = ActivityEvent.query.filter_by(event='preventia_lead_failed').one()
    assert ev.meta['kind'] == 'BOOKING_REQUEST'
    assert ev.meta['booking_id'] == SahayakBooking.query.one().id


def test_a_lead_that_got_across_keeps_their_reference(client, db, live):
    from app.models import ActivityEvent

    book(client)
    ev = ActivityEvent.query.filter_by(event='preventia_lead').one()
    assert ev.meta['submission_id'] == 'sub-1'


def test_a_number_we_cannot_split_is_sent_whole(db):
    """Better an unsplit number their reviewer can still read than an invented country."""
    # +999 is nobody's dialling code, so there is nothing to put in countryCode
    assert preventia.lead_phone('+999 12345678') == ('', '+999 12345678')
    assert preventia.lead_phone('') == ('', '')
    assert preventia.lead_phone('+919000000001') == ('+91', '9000000001')


def test_we_refuse_to_invent_a_submission_type(db):
    """A typo here would be a 400 from their validator and a confusing log line. It is our bug,
    so it is raised rather than swallowed like a network failure."""
    with pytest.raises(ValueError):
        preventia.submit_lead('NURSE_SIGNUP', 'Asha', '+919000000001')


# ---------------------------------------------------------------------------
# Sahayak has its own inbox slice now
# ---------------------------------------------------------------------------

def test_an_application_is_filed_under_sahayak(client, db):
    """It used to land in the general inbox, which is why no Sahayak screen could show it."""
    from app.models import ContactMessage

    assert client.post('/api/sahayak-apply', json=APPLY).status_code == 201
    assert ContactMessage.query.one().topic == 'sahayak'


def test_the_admin_reads_sahayak_requests_on_its_own_screen(client, db, admin_user):
    """The screen the travel companion and insurance sections already have."""
    client.post('/api/sahayak-apply', json=APPLY)
    login(client, admin_user.email)
    html = client.get('/admin/voices?tab=contact&topic=sahayak').data.decode()
    assert 'Asha Menon' in html
    assert 'Sahayak application' in html


def test_the_sahayak_screen_does_not_show_other_products_enquiries(client, db, admin_user):
    from app.models import ContactMessage

    _db.session.add(ContactMessage(name='Someone Else', email='e@example.com',
                                   message='About a travel companion please', topic='companion'))
    _db.session.commit()
    client.post('/api/sahayak-apply', json=APPLY)
    login(client, admin_user.email)
    html = client.get('/admin/voices?tab=contact&topic=sahayak').data.decode()
    assert 'Asha Menon' in html
    assert 'Someone Else' not in html


def test_the_queue_says_whether_the_copy_reached_preventia(client, db, admin_user, live):
    """An integration nobody can see the state of is an integration nobody notices has stopped."""
    book(client)
    login(client, admin_user.email)
    html = client.get('/admin/sahayak').data.decode()
    assert 'sent to Preventia' in html
    assert 'not sent to Preventia' not in html
    # their reference is on the row for matching a queue by hand, not printed at full width
    assert 'sub-1' in html


def test_the_queue_flags_a_copy_that_did_not_get_across(client, db, admin_user, monkeypatch):
    monkeypatch.setenv('PREVENTIA_API_URL', 'https://example.invalid/api/v1')
    monkeypatch.setenv('PREVENTIA_API_KEY', 'pv_test_key')
    monkeypatch.setattr(preventia.requests, 'post', lambda *a, **k: Reply(
        404, {'success': False, 'errorCode': 'NOT_FOUND',
              'message': 'No route matched this request'}, 'x'))
    book(client)
    login(client, admin_user.email)
    assert 'not sent to Preventia' in client.get('/admin/sahayak').data.decode()


def test_a_booking_nobody_tried_to_copy_is_not_marked_at_all(client, db, admin_user):
    """Bookings taken before the integration, and every booking while it is switched off. A red
    mark against those would be a lie about something that was never attempted."""
    book(client)
    login(client, admin_user.email)
    html = client.get('/admin/sahayak').data.decode()
    assert 'Preventia' not in html


def test_the_cs_queue_says_the_same_thing(client, db, cs_user, live):
    book(client)
    login(client, cs_user.email)
    assert 'sent to Preventia' in client.get('/cs/sahayak').data.decode()


def test_the_queue_asks_about_its_own_page_only(client, db, admin_user, live):
    """One query for the rows on screen, not one per row and not the whole log."""
    book(client)
    assert sahayak.lead_state([]) == {}
    assert sahayak.lead_state([999999]) == {}
    booking = SahayakBooking.query.one()
    assert sahayak.lead_state([booking.id])[booking.id]['ok'] is True


def test_an_unforeseen_failure_while_copying_still_leaves_a_booking(client, db, monkeypatch):
    """submit_lead swallows the network; this covers everything after it. A form that worked
    must not answer 500 because the audit row could not be written."""
    from app.models import ActivityEvent

    monkeypatch.setenv('PREVENTIA_API_URL', 'https://example.invalid/api/v1')
    monkeypatch.setenv('PREVENTIA_API_KEY', 'pv_test_key')
    monkeypatch.setattr(preventia, 'submit_lead', lambda *a, **k: 'sub-9')

    real = ActivityEvent.log

    def explode(event, *a, **kw):
        if event.startswith('preventia_lead'):
            raise RuntimeError('the audit table is on fire')
        return real(event, *a, **kw)

    monkeypatch.setattr(ActivityEvent, 'log', staticmethod(explode))
    r = book(client)
    assert r.status_code == 201
    assert SahayakBooking.query.count() == 1


def test_the_confirmation_reads_the_number_back_spaced(client, db):
    """Stored as one E.164 string, shown with the country split off -- the same shape the
    application reply and the console use. "+46764498115" is the one form nobody can check."""
    r = book(client, phone='+46 764498115')
    assert r.status_code == 201
    assert '+46 764498115' in r.get_json()['message']
    assert SahayakBooking.query.one().phone == '+46764498115'
