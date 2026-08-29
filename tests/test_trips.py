from conftest import login, logout, TRIP_JSON
from app.models import CompanionRequest, Notification


def test_post_trip_requires_login(client):
    assert client.post('/api/post-trip', json=TRIP_JSON).status_code in (302, 401)


def test_post_trip_validates_required_fields(client, user):
    login(client, 'bob@test.com')
    r = client.post('/api/post-trip', json={'trip_type': 'one_way'})
    assert r.status_code == 400
    assert 'flying from' in r.get_json()['error'].lower()


def test_post_trip_creates_contact_points_and_normalises_route(client, user, db):
    login(client, 'bob@test.com')
    r = client.post('/api/post-trip', json=TRIP_JSON)
    assert r.status_code == 201, r.get_json()
    t = r.get_json()['trip']
    assert t['origin_iata'] == 'HYD' and t['dest_iata'] == 'DFW'
    assert t['role'] == 'seeking_help' and t['status'] == 'open' and t['is_own'] is True
    assert sorted(t['contact_types']) == ['inapp_chat', 'mobile']
    trip = db.session.get(CompanionRequest, t['id'])
    assert trip.source == 'organic' and trip.claimed_at is not None
    assert {cp.type: cp.consent_to_share for cp in trip.contact_points} == {'inapp_chat': True, 'mobile': True}
    assert trip.events.first().event == 'post_created'


def test_post_trip_without_consent_keeps_contact_private(client, user, db):
    login(client, 'bob@test.com')
    r = client.post('/api/post-trip', json={**TRIP_JSON, 'contact_consent': False})
    t = r.get_json()['trip']
    assert t['contact_types'] == ['inapp_chat']   # mobile stored but not shareable


def test_anonymous_trip_hides_user_id_from_others(client, user, other_user):
    login(client, 'bob@test.com')
    r = client.post('/api/post-trip', json={**TRIP_JSON, 'is_anonymous': True, 'additional_comments': 'secret'})
    assert r.status_code == 201
    logout(client)
    login(client, 'alice@test.com')
    res = client.post('/api/search', json={'limit': 10}).get_json()['results']
    assert len(res) == 1
    assert res[0]['user_id'] is None and res[0]['author']['username'] == 'Anonymous'
    assert res[0]['additional_comments'] is None and res[0]['is_own'] is False


def test_search_filters_role_and_bounds_limit(client, user):
    login(client, 'bob@test.com')
    client.post('/api/post-trip', json=TRIP_JSON)
    client.post('/api/post-trip', json={**TRIP_JSON, 'role': 'offering_help'})
    assert client.post('/api/search', json={'role': 'offering_help'}).get_json()['count'] == 1
    assert client.post('/api/search', json={'limit': 'abc'}).status_code == 200
    assert client.post('/api/search', json={'q': 'HYD'}).get_json()['count'] == 2
    assert client.post('/api/search', json={'q': 'ZZZ'}).get_json()['count'] == 0


def test_close_trip_soft_closes_and_hides_from_search(client, user, db):
    login(client, 'bob@test.com')
    tid = client.post('/api/post-trip', json=TRIP_JSON).get_json()['trip']['id']
    r = client.delete(f'/api/trip/{tid}', json={'reason': 'travelled'})
    assert r.get_json()['success']
    trip = db.session.get(CompanionRequest, tid)
    assert trip.status == 'closed' and trip.closed_reason == 'travelled' and trip.is_active is False
    assert client.post('/api/search', json={}).get_json()['count'] == 0
    mine = client.get('/api/my-trips').get_json()['trips']
    assert mine[0]['status'] == 'closed'


def test_other_user_cannot_close_or_read_trip(client, user, other_user):
    login(client, 'bob@test.com')
    tid = client.post('/api/post-trip', json=TRIP_JSON).get_json()['trip']['id']
    logout(client)
    login(client, 'alice@test.com')
    assert client.delete(f'/api/trip/{tid}').status_code == 403
    assert client.get(f'/api/trip/{tid}').status_code == 403


def test_connection_request_flow_creates_notifications(client, user, other_user, db):
    login(client, 'bob@test.com')
    tid = client.post('/api/post-trip', json=TRIP_JSON).get_json()['trip']['id']
    logout(client)
    login(client, 'alice@test.com')
    r = client.post(f'/api/connect/{tid}', json={'anonymous': False})
    assert r.status_code == 200
    cid = r.get_json()['connection_id']
    assert client.post(f'/api/connect/{tid}', json={}).status_code == 409
    logout(client)
    login(client, 'bob@test.com')
    unread = client.get('/api/unread-count').get_json()
    assert unread['pending_connections'][0]['requester'] == 'alice'
    assert client.post(f'/api/connect/{cid}/respond', json={'action': 'accept'}).get_json()['success']
    assert Notification.query.filter_by(user_id=other_user.id, type='connection_accepted').count() == 1
    # accepted + both non-anonymous -> chat room exists
    assert len(client.get('/api/rooms').get_json()['rooms']) == 1


def test_notifications_api(client, user, db):
    login(client, 'bob@test.com')
    db.session.add(Notification(user_id=user.id, type='broadcast', title='Hello', body='World', link='/'))
    db.session.commit()
    data = client.get('/api/notifications').get_json()
    assert data['unread'] == 1 and data['notifications'][0]['title'] == 'Hello'
    nid = data['notifications'][0]['id']
    assert client.post(f'/api/notifications/{nid}/read', json={}).get_json()['success']
    assert client.get('/api/notifications').get_json()['unread'] == 0
