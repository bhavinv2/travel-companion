"""The admin/CS Notifications management screen: list, search, filters, send, row actions."""
from conftest import login
from app.models import Notification


def _mk(db, user, title='Hello', ntype='match_found', is_read=False):
    n = Notification(user_id=user.id, type=ntype, title=title, body='body text', is_read=is_read)
    db.session.add(n)
    db.session.commit()
    return n


def test_admin_notification_log_lists_searches_and_filters(client, db, admin_user, user):
    _mk(db, user, title='Alpha match', ntype='match_found', is_read=False)
    _mk(db, user, title='Beta connection', ntype='connection_request', is_read=True)
    login(client, 'admin@test.com')

    html = client.get('/admin/notification-log').data.decode()
    assert client.get('/admin/notification-log').status_code == 200
    assert 'Alpha match' in html and 'Beta connection' in html

    # search matches title but not the other row
    only_alpha = client.get('/admin/notification-log?q=Alpha').data.decode()
    assert 'Alpha match' in only_alpha and 'Beta connection' not in only_alpha

    # unread filter
    unread = client.get('/admin/notification-log?status=unread').data.decode()
    assert 'Alpha match' in unread and 'Beta connection' not in unread

    # category filter (match_alerts groups the 'match_found' type)
    assert 'Alpha match' in client.get('/admin/notification-log?category=match_alerts').data.decode()
    assert 'Beta connection' not in client.get('/admin/notification-log?category=match_alerts').data.decode()

    # filter by a specific user id
    assert 'Alpha match' in client.get(f'/admin/notification-log?user_id={user.id}').data.decode()


def test_admin_send_notification_to_user_and_group(client, db, admin_user, user, other_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/notification-log/send', json={'title': 'Hi bob', 'body': 'msg', 'user': 'bob'})
    assert r.status_code == 200 and r.get_json()['sent'] == 1
    assert Notification.query.filter_by(user_id=user.id, title='Hi bob').count() == 1

    # unknown user and missing body are rejected
    assert client.post('/admin/notification-log/send', json={'title': 'x', 'body': 'y', 'user': 'ghost'}).status_code == 400
    assert client.post('/admin/notification-log/send', json={'title': 'x', 'body': ''}).status_code == 400

    # group send reaches everyone active
    r = client.post('/admin/notification-log/send', json={'title': 'All hands', 'body': 'msg', 'group': 'all'})
    assert r.get_json()['sent'] >= 2


def test_admin_toggle_read_and_delete(client, db, admin_user, user):
    n = _mk(db, user, is_read=False)
    login(client, 'admin@test.com')
    assert client.post(f'/admin/notification-log/{n.id}/read', json={}).get_json()['is_read'] is True
    assert client.post(f'/admin/notification-log/{n.id}/read', json={}).get_json()['is_read'] is False
    assert client.post(f'/admin/notification-log/{n.id}/delete', json={}).get_json()['success'] is True
    assert db.session.get(Notification, n.id) is None


def test_cs_can_view_and_send_but_not_delete(client, db, cs_user, user):
    _mk(db, user, title='Gamma note', ntype='message')
    login(client, 'cs@test.com')
    assert 'Gamma note' in client.get('/cs/notifications').data.decode()
    assert client.post('/cs/notifications/send', json={'title': 'Hey', 'body': 'msg', 'user': 'bob'}).get_json()['sent'] == 1
    # CS has no delete route at all
    assert client.post('/cs/notifications/1/delete', json={}).status_code == 404


def test_notifications_screen_requires_staff(client, db, user):
    login(client, 'bob@test.com')
    assert client.get('/admin/notification-log').status_code in (302, 403)
    assert client.get('/cs/notifications').status_code in (302, 403)
