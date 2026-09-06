"""Global notification switches (admin) and per-user preferences: all / partial / per user."""
from conftest import login, logout, make_user, TRIP_JSON
from app import db
from app.models import Notification, ContactPoint, Match, AppSetting
from app.services import settings, notify, mailer, matching, bridge
from test_matching import _make, _post, FUTURE


def _off(**kw):
    return settings.set_notification_switches(kw)


# ---------------------------------------------------------------------------
# Global switches
# ---------------------------------------------------------------------------

def test_defaults_everything_on(app):
    sw = settings.notification_switches()
    assert sw['enabled'] and all(sw['channels'].values()) and all(sw['categories'].values())
    assert notify.allowed('match_alerts', 'email') and notify.allowed('account', 'email')


def test_master_switch_stops_inapp_and_email(client, user, other_user, db):
    mailer.OUTBOX.clear()
    _off(enabled=False, note='paused')
    login(client, 'bob@test.com')
    _post(client, contact_points=[{'type': 'auto', 'value': 'bob@test.com'}])
    logout(client)
    login(client, 'alice@test.com')
    _post(client, role='offering_help', contact_points=[{'type': 'auto', 'value': 'alice@test.com'}])
    assert Notification.query.count() == 0                     # no match alert for bob
    assert mailer.OUTBOX == []                                 # and no e-mail
    assert any(s['category'] == 'match_alerts' for s in notify.SUPPRESSED)
    # notify both: neither side is flagged for CS, both stay pending with a 'suppressed' event
    m = Match.query.first()
    parties, problems = bridge.notify_match(m)
    assert problems == [] and all(p.status == 'pending' for p in parties)
    assert m.needs_cs_attention is False
    assert 'notification_suppressed' in [e.event for t in (m.trip_a, m.trip_b) for e in t.events]
    # switch back on -> a new match alerts bob
    _off(enabled=True)
    logout(client)
    make_user('carol@test.com', 'carol')
    login(client, 'carol@test.com')
    _post(client, role='offering_help', contact_points=[{'type': 'auto', 'value': 'carol@test.com'}])
    assert Notification.query.filter_by(user_id=user.id, type='match_found').count() == 1
    assert any(o['category'] == 'match_alerts' for o in mailer.OUTBOX)


def test_partial_by_category(client, user, other_user, db):
    mailer.OUTBOX.clear()
    _off(enabled=True, categories={'match_alerts': False})
    login(client, 'bob@test.com')
    a = _post(client)
    logout(client)
    login(client, 'alice@test.com')
    _post(client, role='offering_help', contact_points=[{'type': 'auto', 'value': 'alice@test.com'}])
    assert Notification.query.filter_by(user_id=user.id, type='match_found').count() == 0   # alerts off
    r = client.post(f"/api/connect/{a['trip']['id']}", json={})
    assert r.status_code == 200
    assert Notification.query.filter_by(user_id=user.id, type='connection_request').count() == 1  # connection on


def test_partial_by_channel_email_off(client, user, other_user, db):
    mailer.OUTBOX.clear()
    _off(enabled=True, channels={'email': False, 'inapp': True})
    a = _make(db, user)
    b = _make(db, other_user, role='offering_help')
    db.session.add(ContactPoint(trip=b, type='email', value='alice@test.com', consent_to_share=True))
    db.session.commit()
    m = matching.compute_matches_for(a)[0]
    parties, problems = bridge.notify_match(m)
    by_trip = {p.trip_id: p for p in parties}
    assert by_trip[a.id].status == 'sent' and by_trip[a.id].channel == 'inapp'      # in-app still flows
    assert by_trip[b.id].status == 'pending' and by_trip[b.id].channel == 'email'   # e-mail suppressed, not failed
    assert m.needs_cs_attention is False and mailer.OUTBOX == []


def test_account_emails_have_their_own_switch(client, user, db):
    mailer.OUTBOX.clear()
    _off(enabled=True, categories={'match_alerts': False, 'chat': False})
    login(client, 'bob@test.com')
    client.post('/auth/resend-verification', data={})
    assert mailer.OUTBOX and mailer.OUTBOX[-1]['category'] == 'account'
    mailer.OUTBOX.clear()
    _off(enabled=True, categories={'account': False})
    client.post('/auth/resend-verification', data={})
    assert mailer.OUTBOX == []


def test_broadcast_and_blog_respect_switches(client, admin_user, user, db):
    login(client, 'admin@test.com')
    d = client.post('/admin/broadcast', json={'title': 'Hi', 'body': 'there'}).get_json()
    assert d['sent_to'] == 2 and d['skipped'] == 0
    _off(enabled=True, categories={'announcements': False})
    d = client.post('/admin/broadcast', json={'title': 'Hi', 'body': 'again'}).get_json()
    assert d['sent_to'] == 0 and d['skipped'] == 2


# ---------------------------------------------------------------------------
# Per-user preferences
# ---------------------------------------------------------------------------

def test_user_mutes_chat_but_still_gets_connections(client, user, other_user, db):
    user.notify_prefs = {'chat': False}
    db.session.commit()
    login(client, 'bob@test.com')
    a = _post(client)
    logout(client)
    login(client, 'alice@test.com')
    client.post(f"/api/connect/{a['trip']['id']}", json={})
    assert Notification.query.filter_by(user_id=user.id, type='connection_request').count() == 1
    logout(client)
    login(client, 'bob@test.com')
    cid = Notification.query.filter_by(user_id=user.id, type='connection_request').first().connection_id
    client.post(f'/api/connect/{cid}/respond', json={'action': 'accept'})
    room = client.get('/api/rooms').get_json()['rooms'][0]['room_id']
    logout(client)
    login(client, 'alice@test.com')
    client.post(f'/api/messages/{room}', json={'message': 'hello'})
    assert Notification.query.filter_by(user_id=user.id, type='message').count() == 0   # chat muted by bob


def test_user_no_email_and_mute_all(client, user, other_user, db):
    mailer.OUTBOX.clear()
    user.notify_prefs = {'email': False}
    db.session.commit()
    login(client, 'bob@test.com')
    _post(client, contact_points=[{'type': 'auto', 'value': 'bob@test.com'}])
    logout(client)
    login(client, 'alice@test.com')
    _post(client, role='offering_help', contact_points=[{'type': 'auto', 'value': 'alice@test.com'}])
    assert Notification.query.filter_by(user_id=user.id, type='match_found').count() == 1   # in-app yes
    assert not any(o['recipients'] == ['bob@test.com'] for o in mailer.OUTBOX)                # e-mail no
    # account e-mails ignore the user's mute
    user.notify_prefs = {'muted': True}
    db.session.commit()
    mailer.OUTBOX.clear()
    logout(client)
    login(client, 'bob@test.com')
    client.post('/auth/resend-verification', data={})
    assert mailer.OUTBOX and mailer.OUTBOX[-1]['recipients'] == ['bob@test.com']
    make_user('dave@test.com', 'dave')
    logout(client)
    login(client, 'dave@test.com')
    _post(client, role='offering_help', contact_points=[{'type': 'auto', 'value': 'dave@test.com'}])
    assert Notification.query.filter_by(user_id=user.id, type='match_found').count() == 1   # still 1: muted


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def test_admin_switch_page(client, admin_user, user, db):
    login(client, 'bob@test.com')
    assert client.get('/admin/notifications').status_code == 302
    logout(client)
    login(client, 'admin@test.com')
    r = client.get('/admin/notifications')
    assert r.status_code == 200 and b'Notifications enabled' in r.data
    r = client.post('/admin/notifications', data={'channel_email': 'on', 'channel_inapp': 'on',
                                                 'cat_connection': 'on', 'cat_account': 'on', 'note': 'pause'})
    assert r.status_code == 302
    sw = settings.notification_switches()
    assert sw['enabled'] is False and sw['categories']['connection'] and not sw['categories']['chat'] and sw['note'] == 'pause'
    assert db.session.get(AppSetting, settings.NOTIFY_KEY).updated_by_id == admin_user.id
    assert b'All notifications are currently stopped' in client.get('/admin/notifications').data
    r = client.post('/admin/notifications', data={'enabled': 'on', 'channel_email': 'on', 'channel_inapp': 'on',
                                                 **{f'cat_{c}': 'on' for c in sw['categories']}})
    assert settings.notification_switches()['enabled'] is True


def test_user_settings_page(client, user, db):
    login(client, 'bob@test.com')
    r = client.get('/settings/notifications')
    assert r.status_code == 200 and b'Mute everything' in r.data
    r = client.post('/settings/notifications', data={'email': 'on', 'cat_connection': 'on', 'cat_chat': 'on'})
    assert r.status_code == 302
    prefs = notify.user_prefs(db.session.get(type(user), user.id))
    assert prefs['muted'] is False and prefs['email'] is True and prefs['connection'] is True
    assert prefs['match_alerts'] is False and prefs['announcements'] is False
