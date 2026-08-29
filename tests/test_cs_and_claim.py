import io

from conftest import login, logout
from app.models import CompanionRequest, ClaimToken, User, Notification

CS_FORM = {
    'source': 'facebook', 'source_url': 'https://facebook.com/groups/x/posts/1',
    'poster_name': 'Ravi Kumar', 'traveler_name': 'Lakshmi', 'on_behalf_of': 'mother',
    'role': 'seeking_help', 'trip_type': 'one_way',
    'flying_from': 'Hyderabad (HYD)', 'destination': 'Dallas (DFW)', 'from_date': '2099-12-02',
    'airline': 'Qatar Airways', 'traveller_needs': ['wheelchair', 'immigration'],
    'preferred_languages': ['Telugu'], 'traveler_age_group': '60_plus', 'traveler_gender': 'female',
    'pref_gender': 'female',
    'contact_type': ['auto', 'auto'], 'contact_value': ['ravi@example.com', 'https://facebook.com/ravi.k'],
    'contact_label': ['', ''],
}


def _create_cs_post(client, **overrides):
    r = client.post('/cs/posts/new', data={**CS_FORM, **overrides})
    assert r.status_code == 302, r.data[:300]
    return int(r.headers['Location'].rstrip('/').split('/')[-1])


def test_cs_console_requires_cs_role(client, user, cs_user):
    assert client.get('/cs/').status_code == 302                      # anonymous -> login
    login(client, 'bob@test.com')
    r = client.get('/cs/')
    assert r.status_code == 302 and r.headers['Location'].endswith('/')  # plain user -> home
    logout(client)
    login(client, 'cs@test.com')
    assert client.get('/cs/').status_code == 200
    assert client.get('/cs/posts').status_code == 200
    assert client.get('/cs/posts/new').status_code == 200


def test_cs_post_starts_unconfirmed_and_hidden_from_public(client, cs_user, db):
    login(client, 'cs@test.com')
    tid = _create_cs_post(client)
    trip = db.session.get(CompanionRequest, tid)
    assert trip.status == 'unconfirmed' and trip.user_id is None and trip.created_by_id == cs_user.id
    assert trip.origin_metro == 'Hyderabad' and trip.dest_metro == 'Dallas'
    assert trip.contact_types == ['email', 'facebook'] and trip.consented_contact_types == []
    assert client.post('/api/search', json={}).get_json()['count'] == 0
    assert client.get(f'/cs/posts/{tid}').status_code == 200
    assert client.get(f'/cs/posts/{tid}/edit').status_code == 200


def test_cs_form_rejects_unknown_airport(client, cs_user, db):
    login(client, 'cs@test.com')
    r = client.post('/cs/posts/new', data={**CS_FORM, 'flying_from': 'Atlantis'})
    assert r.status_code == 200 and CompanionRequest.query.count() == 0


def test_cs_publish_now_publishes_immediately(client, cs_user, db):
    login(client, 'cs@test.com')
    tid = _create_cs_post(client, publish_now='on', contact_consent=['0'])
    trip = db.session.get(CompanionRequest, tid)
    assert trip.status == 'open' and trip.consented_contact_types == ['email']
    assert client.post('/api/search', json={}).get_json()['count'] == 1


def test_claim_flow_end_to_end(client, cs_user, db):
    login(client, 'cs@test.com')
    tid = _create_cs_post(client)
    d = client.post(f'/cs/posts/{tid}/claim-link', json={}).get_json()
    assert d['success'] and '/claim/' in d['url'] and 'Ravi' in d['dm_text']
    token = d['url'].split('/claim/')[-1]
    logout(client)

    # invalid token -> 404; valid token -> page
    assert client.get('/claim/nope').status_code == 404
    r = client.get(f'/claim/{token}')
    assert r.status_code == 200 and b'Complete your request' in r.data
    assert b'facebook.com/groups' not in r.data          # source is never shown to the person

    # missing consent is rejected
    r = client.post(f'/claim/{token}', data={'name': 'Ravi Kumar', 'contact_type': ['auto'],
                                             'contact_value': ['+1 972 555 0199'], 'contact_label': ['']})
    assert r.status_code == 200
    assert db.session.get(CompanionRequest, tid).status == 'unconfirmed'

    # full claim with account creation
    r = client.post(f'/claim/{token}', data={
        'name': 'Ravi Kumar', 'contact_type': ['auto', 'auto'],
        'contact_value': ['+1 972 555 0199', 'ravi@example.com'], 'contact_label': ['son', ''],
        'consent': 'on', 'create_account': 'on', 'password': 'password123',
    })
    assert r.status_code == 200 and b'Thank you' in r.data
    trip = db.session.get(CompanionRequest, tid)
    assert trip.status == 'open' and trip.claimed_at is not None
    assert trip.consented_contact_types == ['email', 'mobile']
    new_user = User.query.filter_by(email='ravi@example.com').first()
    assert new_user is not None and trip.user_id == new_user.id
    tok = ClaimToken.query.filter_by(token=token).first()
    assert tok.used_at is not None
    assert Notification.query.filter_by(user_id=cs_user.id, type='post_claimed').count() == 1
    assert 'post_claimed' in [e.event for e in trip.events]

    # token reuse shows the "already confirmed" page; post is now public
    assert b'Already confirmed' in client.get(f'/claim/{token}').data
    res = client.post('/api/search', json={}).get_json()['results']
    assert res[0]['id'] == tid and res[0]['contact_types'] == ['email', 'mobile'] and res[0]['is_own'] is True


def test_expired_token_is_rejected(client, cs_user, db):
    from datetime import datetime, timedelta
    login(client, 'cs@test.com')
    tid = _create_cs_post(client)
    token = client.post(f'/cs/posts/{tid}/claim-link', json={}).get_json()['url'].split('/claim/')[-1]
    tok = ClaimToken.query.filter_by(token=token).first()
    tok.expires_at = datetime.utcnow() - timedelta(days=1)
    db.session.commit()
    logout(client)
    assert client.get(f'/claim/{token}').status_code == 410


def test_close_and_reopen_with_reason(client, cs_user, db):
    login(client, 'cs@test.com')
    tid = _create_cs_post(client, publish_now='on')
    assert client.post(f'/cs/posts/{tid}/close', data={'reason': 'bogus'}).status_code == 302
    assert db.session.get(CompanionRequest, tid).status == 'open'
    client.post(f'/cs/posts/{tid}/close', data={'reason': 'information_shared'})
    trip = db.session.get(CompanionRequest, tid)
    assert trip.status == 'closed' and trip.closed_reason == 'information_shared' and trip.closed_by_id == cs_user.id
    client.post(f'/cs/posts/{tid}/reopen', data={})
    assert db.session.get(CompanionRequest, tid).status == 'open'


def test_private_ticket_attachment_access(client, cs_user, user, other_user, db):
    login(client, 'cs@test.com')
    tid = _create_cs_post(client, publish_now='on')
    data = {**CS_FORM, 'ticket_file': (io.BytesIO(b'%PDF-1.4 fake'), 'ticket.pdf')}
    r = client.post(f'/cs/posts/{tid}/edit', data=data, content_type='multipart/form-data')
    assert r.status_code == 302
    trip = db.session.get(CompanionRequest, tid)
    assert trip.ticket_attachment and trip.ticket_attachment.endswith('.pdf')
    key = trip.ticket_attachment
    assert client.get(f'/files/private/{key}').status_code == 200       # CS can read
    logout(client)
    assert client.get(f'/files/private/{key}').status_code in (302, 401)  # anonymous cannot
    login(client, 'alice@test.com')
    assert client.get(f'/files/private/{key}').status_code == 403       # unrelated user cannot
    assert client.get(f'/static/uploads/{key}').status_code == 404      # never under /static


def test_duplicate_contact_is_flagged_on_cs_home(client, cs_user, db):
    login(client, 'cs@test.com')
    _create_cs_post(client)
    _create_cs_post(client, from_date='2099-12-09')
    r = client.get('/cs/')
    assert r.status_code == 200 and b'Same contact on several posts' in r.data


def test_admin_can_change_roles(client, admin_user, user, db):
    login(client, 'admin@test.com')
    r = client.post(f'/admin/users/{user.id}/role', json={'role': 'cs'})
    assert r.get_json()['success']
    assert db.session.get(User, user.id).is_cs
    assert client.post(f'/admin/users/{admin_user.id}/role', json={'role': 'user'}).status_code == 400
