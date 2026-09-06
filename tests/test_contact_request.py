"""Request contact details from a matched traveller - inbox notification like the connect flow."""
from conftest import login, logout, make_user
from app.models import Notification, CompanionRequest
from app.services import matching
from test_matching import _make


def test_request_contact_details_flow(client, db, user, other_user):
    a = _make(db, user)
    b = _make(db, other_user, role='offering_help')
    m = matching.compute_matches_for(a)[0]
    login(client, 'bob@test.com')
    r = client.post(f'/api/matches/{m.id}/request-contact', json={})
    assert r.status_code == 200 and r.get_json()['success'] and r.get_json()['delivered']
    n = Notification.query.filter_by(user_id=other_user.id, type='contact_request').one()
    assert 'bob' in n.title and 'exchange contact details' in n.title
    # throttled for 24h per match per requester
    assert client.post(f'/api/matches/{m.id}/request-contact', json={}).status_code == 429
    # the other side can still send their own request
    logout(client)
    login(client, 'alice@test.com')
    assert client.post(f'/api/matches/{m.id}/request-contact', json={}).status_code == 200
    assert Notification.query.filter_by(user_id=user.id, type='contact_request').count() == 1
    # outsiders are rejected
    logout(client)
    make_user('eve@test.com', 'eve')
    login(client, 'eve@test.com')
    assert client.post(f'/api/matches/{m.id}/request-contact', json={}).status_code == 403


def test_request_contact_cs_side_and_dismissed(client, db, user, other_user):
    a = _make(db, user)
    cs_post = _make(db, None, role='offering_help', source='facebook', poster_name='FB Poster')
    ms = matching.compute_matches_for(a)
    target = next(m for m in ms if m.other_trip(a.id).id == cs_post.id)
    login(client, 'bob@test.com')
    r = client.post(f'/api/matches/{target.id}/request-contact', json={})
    assert r.status_code == 400 and 'team' in r.get_json()['error']
    b = _make(db, other_user, role='offering_help')
    m2 = next(m for m in matching.compute_matches_for(a) if m.other_trip(a.id).id == b.id)
    client.post(f'/api/matches/{m2.id}/dismiss', json={'reason': 'not_suitable'})
    assert client.post(f'/api/matches/{m2.id}/request-contact', json={}).status_code == 400
