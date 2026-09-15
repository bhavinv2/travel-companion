"""Admin hard delete: cascading removal of posts and users, plus the bulk-delete routes."""
from datetime import date, timedelta

from conftest import login, logout
from app.models import (CompanionRequest, Match, MatchParty, ContactPoint, ClaimToken,
                        ConnectionRequest, ChatRoom, ChatMessage, Notification, ActivityEvent,
                        TripLeg, User)
from app.services import matching, admin_delete
from app import db


def _make(dbs, user, **kw):
    t = CompanionRequest(user_id=user.id if user else None, travel_type='air', trip_type='one_way',
                         flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                         from_date=date.today() + timedelta(days=20), role='seeking_help', source='organic')
    for k, v in kw.items():
        setattr(t, k, v)
    from app.services.locations import apply_route
    apply_route(t)
    t.set_status(kw.get('status', 'open'))
    dbs.session.add(t)
    dbs.session.commit()
    return t


def _full_wiring(dbs, a, b, user, other_user):
    """Give post `a` a live match, a contact point, a claim token, a connection request,
    and a chat room + message, so a cascade test has something real to lose."""
    matching.compute_matches_for(a)
    m = Match.query.filter(db.or_(Match.trip_a_id == a.id, Match.trip_b_id == a.id)).first()
    cp = ContactPoint(trip_id=a.id, type='email', value='x@example.com', consent_to_share=True)
    tok = ClaimToken(token='tok-' + str(a.id), trip_id=a.id, expires_at=date.today() + timedelta(days=14))
    conn = ConnectionRequest(requester_id=other_user.id, trip_id=a.id, status='pending')
    room = ChatRoom(user1_id=user.id, user2_id=other_user.id, trip_id=a.id)
    dbs.session.add_all([cp, tok, conn, room])
    dbs.session.flush()
    msg = ChatMessage(room_id=room.id, sender_id=user.id, message='hi')
    ev = ActivityEvent.log('post_created', trip=a, actor=user)
    dbs.session.add_all([msg])
    dbs.session.commit()
    return {'match': m, 'contact': cp, 'token': tok, 'conn': conn, 'room': room, 'msg': msg}


def test_delete_post_cascade_removes_everything_tied_to_it(app, db, user, other_user):
    a = _make(db, user)
    b = _make(db, other_user, role='offering_help')
    wired = _full_wiring(db, a, b, user, other_user)
    assert wired['match'] is not None
    match_id = wired['match'].id
    room_id = wired['room'].id

    admin_delete.delete_post_cascade(a)
    db.session.commit()

    assert db.session.get(CompanionRequest, a.id) is None
    assert db.session.get(Match, match_id) is None
    assert MatchParty.query.filter_by(match_id=match_id).count() == 0
    assert ContactPoint.query.filter_by(trip_id=a.id).count() == 0
    assert ClaimToken.query.filter_by(trip_id=a.id).count() == 0
    assert ConnectionRequest.query.filter_by(trip_id=a.id).count() == 0
    assert db.session.get(ChatRoom, room_id) is None
    assert ChatMessage.query.filter_by(room_id=room_id).count() == 0
    assert TripLeg.query.filter_by(trip_id=a.id).count() == 0
    assert ActivityEvent.query.filter_by(trip_id=a.id).count() == 0
    # the OTHER post is untouched
    assert db.session.get(CompanionRequest, b.id) is not None


def test_delete_user_cascade_removes_posts_and_own_records(app, db, user, other_user):
    a = _make(db, user)
    b = _make(db, other_user, role='offering_help')
    wired = _full_wiring(db, a, b, user, other_user)
    match_id = wired['match'].id
    from app.models import Feedback
    fb = Feedback(user_id=user.id, rating=5, comment='great')
    notif = Notification(user_id=user.id, type='match_found', title='hi')
    db.session.add_all([fb, notif])
    db.session.commit()
    user_id = user.id

    admin_delete.delete_user_cascade(user)
    db.session.commit()

    assert db.session.get(User, user_id) is None
    assert db.session.get(CompanionRequest, a.id) is None
    assert db.session.get(Match, match_id) is None
    assert Feedback.query.filter_by(user_id=user_id).count() == 0
    assert Notification.query.filter_by(user_id=user_id).count() == 0
    # the other user's account and their own post are untouched
    assert db.session.get(CompanionRequest, b.id) is not None
    assert db.session.get(User, other_user.id) is not None


def test_delete_user_anonymises_incidental_references(app, db, user, cs_user):
    """A claim token another post's owner still needs should survive; only WHO created it clears."""
    a = _make(db, None)   # someone else's CS-created post
    tok = ClaimToken(token='keepme', trip_id=a.id, expires_at=date.today() + timedelta(days=14),
                     created_by_id=cs_user.id)
    db.session.add(tok)
    db.session.commit()

    admin_delete.delete_user_cascade(cs_user)
    db.session.commit()

    kept = ClaimToken.query.filter_by(token='keepme').first()
    assert kept is not None and kept.created_by_id is None
    assert db.session.get(CompanionRequest, a.id) is not None      # untouched, not this user's post


def test_delete_route_requires_admin_and_blocks_self(client, db, user, admin_user):
    login(client, 'bob@test.com')
    assert client.post(f'/admin/users/{admin_user.id}/delete').status_code in (302, 403)
    logout(client)
    login(client, 'admin@test.com')
    r = client.post(f'/admin/users/{admin_user.id}/delete')
    assert r.status_code == 400 and 'own account' in r.get_json()['error']


def test_delete_user_route_removes_account(client, db, admin_user, user):
    uid = user.id
    login(client, 'admin@test.com')
    r = client.post(f'/admin/users/{uid}/delete')
    d = r.get_json()
    assert d['success'] and db.session.get(User, uid) is None


def test_bulk_delete_users_skips_self_and_reports_count(client, db, admin_user, user, other_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/users/bulk-delete', json={'ids': [user.id, other_user.id, admin_user.id]})
    d = r.get_json()
    assert d['success'] and d['deleted'] == 2                 # admin_user (self) skipped
    assert db.session.get(User, user.id) is None
    assert db.session.get(User, other_user.id) is None
    assert db.session.get(User, admin_user.id) is not None


def test_delete_listing_route_and_bulk(client, db, admin_user, user, other_user):
    a = _make(db, user)
    b = _make(db, other_user)
    login(client, 'admin@test.com')
    r = client.post(f'/admin/listings/{a.id}/delete')
    assert r.get_json()['success'] and db.session.get(CompanionRequest, a.id) is None

    c = _make(db, user)
    r2 = client.post('/admin/listings/bulk-delete', json={'ids': [b.id, c.id]})
    d = r2.get_json()
    assert d['success'] and d['deleted'] == 2
    assert db.session.get(CompanionRequest, b.id) is None
    assert db.session.get(CompanionRequest, c.id) is None


def test_listings_and_users_pages_render_bulk_ui(client, db, admin_user, user):
    login(client, 'admin@test.com')
    html = client.get('/admin/users').data.decode()
    assert 'userSelectAll' in html and 'hardDeleteModal' in html
    html2 = client.get('/admin/listings').data.decode()
    assert 'postSelectAll' in html2 and 'hardDeleteModal' in html2
