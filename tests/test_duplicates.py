"""Submit-time duplicate detection on both post forms.

The rule these tests pin down: the check never refuses a post. It reports what the new post
looks like, and a confirmed second submit stores it. The other half is privacy -- the
traveller-facing form may only ever describe that traveller's own posts back to them.
"""
from datetime import date, timedelta

import pytest

from conftest import login, logout, TRIP_JSON
from test_cs_and_claim import CS_FORM
from app import db as _db
from app.models import ActivityEvent, CompanionRequest
from app.services import duplicates

FAR = (date.today() + timedelta(days=400)).isoformat()


def post(client, **over):
    return client.post('/api/post-trip', json={**TRIP_JSON, **over})


# ---------------------------------------------------------------------------
# Traveller-facing form
# ---------------------------------------------------------------------------

def test_second_identical_post_is_held_back_and_describes_the_first(client, user, db):
    login(client, 'bob@test.com')
    first = post(client).get_json()['trip']['id']

    r = post(client)
    body = r.get_json()
    assert r.status_code == 409 and body['success'] is False and body['duplicate'] is True
    assert CompanionRequest.query.count() == 1          # nothing was stored
    assert body['error']                                # a line the modal can show

    d = body['duplicates'][0]
    assert d['id'] == first
    assert d['departs'] == TRIP_JSON['from_date'] and d['flight'] == 'QR573'
    assert d['route'] and d['status_label'] == 'Open' and d['role'] == 'Seeking help'
    assert 'same account and route' in d['reasons']


def test_confirming_posts_it_anyway_and_records_what_was_shown(client, user, db):
    login(client, 'bob@test.com')
    first = post(client).get_json()['trip']['id']
    assert post(client).status_code == 409

    r = post(client, confirm_duplicate=True)
    assert r.status_code == 201
    second = r.get_json()['trip']['id']
    assert CompanionRequest.query.count() == 2

    # the audit trail says which live posts they were shown and posted over anyway
    ev = ActivityEvent.query.filter_by(trip_id=second, event='post_created').one()
    assert ev.meta['confirmed_over'] == [first]
    # ...and the first, honest post carries no such claim
    assert ActivityEvent.query.filter_by(trip_id=first, event='post_created').one().meta['confirmed_over'] is None


def test_a_trip_too_far_off_to_ever_match_is_not_a_duplicate(client, user, db):
    """Outside the matcher's window the two posts can never pair, so they are two trips."""
    login(client, 'bob@test.com')
    post(client)
    r = post(client, from_date=FAR)
    assert r.status_code == 201 and CompanionRequest.query.count() == 2


def test_another_account_on_the_same_route_is_a_match_not_a_duplicate(client, user, other_user, db):
    """Bob's post must never be described back to Alice -- and she is his companion, not a copy."""
    login(client, 'bob@test.com')
    post(client)
    logout(client)
    login(client, 'alice@test.com')
    r = post(client)                                    # identical, contact detail included
    assert r.status_code == 201, r.get_json()
    assert CompanionRequest.query.count() == 2


def test_a_closed_post_does_not_stand_in_the_way(client, user, db):
    login(client, 'bob@test.com')
    tid = post(client).get_json()['trip']['id']
    client.delete('/api/trip/%s' % tid, json={'reason': 'travelled'})
    assert post(client).status_code == 201               # travelled already: post the next one freely


def test_the_check_reports_every_reason_it_found(client, user, db):
    login(client, 'bob@test.com')
    post(client)
    d = post(client).get_json()['duplicates'][0]
    # the public form stamps the poster's own name, so the name rule fires here too
    assert set(d['reasons']) == {'same account and route', 'same traveller, route and date',
                                 'same flight, date and role', 'shared contact detail'}


# ---------------------------------------------------------------------------
# CS console
# ---------------------------------------------------------------------------

def test_cs_new_post_shows_the_dialog_then_creates_on_confirm(client, cs_user, db):
    login(client, 'cs@test.com')
    first = client.post('/cs/posts/new', data=CS_FORM)
    assert first.status_code == 302
    tid = int(first.headers['Location'].rstrip('/').split('/')[-1])

    r = client.post('/cs/posts/new', data=CS_FORM)
    html = r.data.decode()
    assert r.status_code == 200
    assert CompanionRequest.query.count() == 1           # not created
    assert 'id="csDupModal"' in html and 'Post #%s' % tid in html
    assert 'same traveller, route and date' in html and 'same source page' in html
    assert '/cs/posts/%s' % tid in html                  # CS can open the other post

    r = client.post('/cs/posts/new', data={**CS_FORM, 'confirm_duplicate': '1'})
    assert r.status_code == 302 and CompanionRequest.query.count() == 2
    new_id = int(r.headers['Location'].rstrip('/').split('/')[-1])
    ev = ActivityEvent.query.filter_by(trip_id=new_id, event='post_created').one()
    assert ev.meta['confirmed_over'] == [tid]


def test_cs_sees_signals_the_traveller_form_would_hide(client, cs_user, other_user, db):
    """CS gets no owner filter: a stranger's post sharing a contact detail is a real signal."""
    login(client, 'alice@test.com')
    post(client, contact_points=[{'type': 'auto', 'value': 'ravi@example.com', 'label': ''}])
    logout(client)
    login(client, 'cs@test.com')
    r = client.post('/cs/posts/new', data=CS_FORM)
    assert r.status_code == 200 and 'shared contact detail' in r.data.decode()


# ---------------------------------------------------------------------------
# The rules themselves
# ---------------------------------------------------------------------------

def _stored(**kw):
    trip = CompanionRequest(travel_type='air', trip_type='one_way', role='seeking_help', **kw)
    trip.set_status('open')
    _db.session.add(trip)
    _db.session.commit()
    return trip


def test_checking_an_unsaved_candidate_never_stores_it(app, db, user):
    """The whole point of running at submit time: the post does not exist yet."""
    stored = _stored(user_id=user.id, flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                     from_date=date(2099, 12, 1))
    candidate = CompanionRequest(travel_type='air', trip_type='one_way', user_id=user.id,
                                 role='seeking_help', flying_from='Hyderabad (HYD)',
                                 destination='Dallas (DFW)', from_date=date(2099, 12, 1))
    candidate.set_status('open')

    found = duplicates.find(candidate, owner_id=user.id)
    assert [d['id'] for d in found] == [stored.id]
    assert CompanionRequest.query.count() == 1           # the queries did not flush the candidate in
    assert candidate.id is None


def test_two_different_people_on_one_flight_are_companions(app, db):
    """The case the site exists for: same flight, same day, neither one a double entry."""
    _stored(poster_name='Ravi Kumar', traveler_name='Lakshmi', flying_from='Hyderabad (HYD)',
            destination='Dallas (DFW)', from_date=date(2099, 12, 1), flight_number='QR573')
    candidate = CompanionRequest(travel_type='air', trip_type='one_way', role='seeking_help',
                                 poster_name='Sita Devi', traveler_name='Sita Devi',
                                 flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                                 from_date=date(2099, 12, 1), flight_number='QR573')
    candidate.set_status('open')
    assert duplicates.find(candidate) == []


def test_the_same_traveller_twice_on_one_flight_is_a_duplicate(app, db):
    same = _stored(poster_name='Ravi Kumar', traveler_name='Lakshmi', flying_from='Hyderabad (HYD)',
                   destination='Dallas (DFW)', from_date=date(2099, 12, 1), flight_number='QR573')
    candidate = CompanionRequest(travel_type='air', trip_type='one_way', role='seeking_help',
                                 poster_name='Ravi Kumar', traveler_name='Lakshmi',
                                 flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                                 from_date=date(2099, 12, 1), flight_number='QR573')
    candidate.set_status('open')
    found = duplicates.find(candidate)
    assert [d['id'] for d in found] == [same.id]
    assert 'same traveller, route and date' in found[0]['reasons']


@pytest.mark.parametrize('days, expected', [(0, True), (7, True), (8, False), (60, False)])
def test_the_same_route_counts_as_a_duplicate_only_inside_the_match_window(app, db, user, days, expected):
    _stored(user_id=user.id, flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
            from_date=date(2099, 12, 1))
    candidate = CompanionRequest(travel_type='air', trip_type='one_way', user_id=user.id,
                                 role='seeking_help', flying_from='Hyderabad (HYD)',
                                 destination='Dallas (DFW)',
                                 from_date=date(2099, 12, 1) + timedelta(days=days))
    candidate.set_status('open')
    assert bool(duplicates.find(candidate, owner_id=user.id)) is expected
