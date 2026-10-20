"""Super admin: the only people who delete for good.

    who      an account role (Users screen); a workspace's owner gets it when the workspace is made
    what     every permanent delete -- the bin buttons and bulk deletes, Erase this person, notifications,
             reports, airports and airlines, scraper recipes -- and nothing a workspace role can give
    guard    only a Super admin gives it, takes it away, or changes a Super admin's account
"""
from conftest import login, logout, make_user
from app import db as _db
from app import options
from app.models import ContactMessage, User, WorkspaceRole
from app.services import access


def enquiry():
    m = ContactMessage(name='Asha', email='a@example.com', topic='general', status='new', message='please call')
    _db.session.add(m)
    _db.session.commit()
    return m


def plain_admin():
    return make_user('admin2@test.com', 'admin2', role='admin')


def test_only_a_super_admin_deletes(client, app, admin_user):
    other = plain_admin()
    m = enquiry()
    login(client, other.email)
    r = client.post('/admin/delete/contact_message/%d' % m.id, json={})
    assert r.status_code in (302, 403) and _db.session.get(ContactMessage, m.id) is not None
    page = client.get('/admin/voices?tab=contact').data.decode()
    assert 'hd-check' not in page and 'hd-bulk-del' not in page                 # no button that cannot work
    target = make_user('trav@test.com', 'trav')
    assert 'user-del' not in client.get('/admin/users/%d/panel' % target.id).data.decode()
    logout(client)
    login(client, admin_user.email)                                               # the Super admin
    assert 'hd-check' in client.get('/admin/voices?tab=contact').data.decode()
    assert 'user-del' in client.get('/admin/users/%d/panel' % target.id).data.decode()
    assert client.post('/admin/delete/contact_message/%d' % m.id, json={}).status_code == 200
    _db.session.expire_all()
    assert _db.session.get(ContactMessage, m.id) is None


def test_every_permanent_delete_is_a_super_admins(app):
    owners = {ep: access.ENDPOINT_PAGES.get(ep) for ep in (
        'admin.hard_delete', 'admin.hard_delete_bulk', 'admin.delete_user', 'admin.bulk_delete_users',
        'admin.delete_listing', 'admin.bulk_delete_listings', 'crm.contact_erase', 'admin.notification_log_delete',
        'admin.notification_log_delete_matching', 'admin.airports_delete', 'admin.airlines_delete',
        'scraper.delete_recipe')}
    assert all(o == {'delete_records'} for o in owners.values()), owners
    assert access.SUPER_ONLY == {'delete_records'}


def test_no_role_gives_delete_not_even_administrator(client, app, admin_user):
    ws = access.ensure_defaults()
    other = plain_admin()
    agent = make_user('agent@test.com', 'agent', role='cs')
    old = WorkspaceRole(workspace_id=ws.id, name='Old delete role', pages=['home', 'delete_records'])
    _db.session.add(old)
    _db.session.commit()
    access.add_member(ws, agent, role=old)
    access.add_member(ws, other, role=access.system_role(ws, 'admin'))
    for u in (agent, other):
        assert 'delete_records' not in access.pages_anywhere(u), u.email
    login(client, admin_user.email)
    page = client.get('/admin/workspace/roles/%d' % old.id).data.decode()
    assert 'value="delete_records"' not in page                                  # not on the Roles screen
    client.post('/admin/workspace/roles/save', data={'name': 'Deleters', 'pages': ['home', 'delete_records']})
    assert WorkspaceRole.query.filter_by(name='Deleters').one().pages == ['home']


def test_only_a_super_admin_gives_takes_or_touches_super_admin(client, app, admin_user):
    other = plain_admin()
    target = make_user('agent@test.com', 'agent', role='cs')
    login(client, other.email)
    r = client.post('/admin/users/%d/roles' % target.id, json={'roles': ['cs', 'superadmin']})
    assert r.status_code == 403 and not _db.session.get(User, target.id).is_super
    assert client.post('/admin/users/%d/roles' % admin_user.id, json={'roles': ['admin']}).status_code == 403
    assert client.post('/admin/users/%d/toggle' % admin_user.id).status_code == 403
    assert _db.session.get(User, admin_user.id).is_active
    logout(client)
    login(client, admin_user.email)
    assert client.post('/admin/users/%d/roles' % target.id, json={'roles': ['cs', 'superadmin']}).status_code == 200
    assert _db.session.get(User, target.id).is_super
    r = client.post('/admin/users/%d/roles' % admin_user.id, json={'roles': ['admin']})
    assert r.status_code == 400 and _db.session.get(User, admin_user.id).is_super    # not your own


def test_the_first_workspace_owner_becomes_super_admin(app):
    first = make_user('owner@test.com', 'owner', role='admin')
    second = make_user('second@test.com', 'second', role='admin')
    access.ensure_defaults()
    assert _db.session.get(User, first.id).is_super and not _db.session.get(User, second.id).is_super


def test_super_admin_is_a_role_even_in_a_list_saved_before_it_existed(app):
    options.set_list('roles', [{'key': 'user', 'label': 'Traveller'}, {'key': 'cs', 'label': 'CS'},
                                {'key': 'admin', 'label': 'Admin'}])
    assert 'superadmin' in {r['key'] for r in options.role_defs()}
    assert options.role_level('superadmin') == 'admin'
