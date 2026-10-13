"""Workspaces, modules, pages, roles and teams: who may open what, decided on screens.

    workspace -> modules switched on -> pages;  role -> pages;  person -> own role + team roles

The checks open addresses directly rather than looking for menu links: hiding a link is not
access control.
"""
import json

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import User, Workspace, WorkspaceMember, WorkspaceRole, WorkspaceTeam
from app.services import access, wacrm_team


@pytest.fixture()
def ws(app, admin_user, cs_user):
    return access.ensure_defaults()


def member(ws, user):
    return WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=user.id).one()


def role(ws, name, pages):
    r = WorkspaceRole(workspace_id=ws.id, name=name, pages=pages)
    _db.session.add(r)
    _db.session.commit()
    return r


# ============================================================================== the first workspace

def test_the_first_workspace_is_written_from_how_the_site_already_works(app, admin_user, cs_user):
    narrow = make_user('narrow@test.com', 'narrow', role='cs')
    narrow.cs_access = ['home', 'insurance']
    _db.session.commit()
    ws = access.ensure_defaults()
    assert ws.name == 'NRI Parent Service' and ws.modules is None
    assert {r.system_key for r in ws.roles} >= {'admin', 'cs'}
    a, c, n = member(ws, admin_user), member(ws, cs_user), member(ws, narrow)
    assert a.is_owner and a.role.system_key == 'admin'
    assert c.role.system_key == 'cs' and not c.is_owner
    assert sorted(n.role.pages) == ['home', 'insurance'] and n.role.name.startswith('Customer service: ')
    assert access.ensure_defaults().id == ws.id                      # never twice
    assert Workspace.query.count() == 1


def test_nothing_changes_for_anybody_when_it_is_made(client, app, admin_user, cs_user):
    """Same doors open before and after: the roles are the old rules written down."""
    login(client, 'cs@test.com')
    before = [client.get(p).status_code for p in ('/cs/', '/cs/posts', '/cs/crm/today', '/admin/landing', '/cs/scraper/')]
    access.ensure_defaults()
    after = [client.get(p).status_code for p in ('/cs/', '/cs/posts', '/cs/crm/today', '/admin/landing', '/cs/scraper/')]
    assert before == after == [200, 200, 200, 302, 302]


# ============================================================================== roles

def test_a_role_opens_exactly_its_pages(client, ws, cs_user):
    member(ws, cs_user).role = role(ws, 'Insurance desk', ['insurance', 'voices_insurance', 'landing'])
    _db.session.commit()
    login(client, 'cs@test.com')
    assert client.get('/cs/insurance-quotes').status_code == 200
    assert client.get('/admin/landing').status_code == 200            # an admin screen, given by a role
    r = client.get('/cs/posts')
    assert r.status_code == 302                                        # not theirs
    assert client.get('/cs/sahayak').status_code == 302
    nav = client.get('/cs/insurance-quotes').data.decode().split('admin-nav-items', 1)[1].split('</nav>', 1)[0]
    assert 'Quote leads' in nav and 'Landing page' in nav and 'All posts' not in nav and 'Bookings' not in nav


def test_a_team_adds_its_roles_pages(client, ws, cs_user):
    m = member(ws, cs_user)
    m.role = role(ws, 'Queues only', ['home'])
    team = WorkspaceTeam(workspace_id=ws.id, name='Sahayak desk', role=role(ws, 'Sahayak', ['sahayak']))
    team.users.append(cs_user)
    _db.session.add(team)
    _db.session.commit()
    login(client, 'cs@test.com')
    assert client.get('/cs/sahayak').status_code == 200
    assert client.get('/cs/').status_code == 200
    assert client.get('/cs/insurance-quotes').status_code == 302


def test_a_module_switched_off_closes_its_pages(client, ws, cs_user):
    ws.modules = ['console', 'insurance']
    _db.session.commit()
    login(client, 'cs@test.com')
    assert client.get('/cs/insurance-quotes').status_code == 200
    assert client.get('/cs/crm/today').status_code == 302


def test_the_owner_and_site_admins_open_everything(client, ws, admin_user):
    ws.modules = ['console']
    _db.session.commit()
    login(client, 'admin@test.com')
    for path in ('/admin/landing', '/cs/crm/setup', '/admin/workspace/roles', '/cs/scraper/'):
        assert client.get(path).status_code in (200, 307), path


def test_making_and_changing_a_role_on_the_screen(client, ws, admin_user, cs_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/workspace/roles/save', data={'name': 'Sales', 'description': 'Selling',
                                                          'pages': ['crm_today', 'crm_board', 'made-up', 'wa_inbox']})
    assert r.status_code == 302
    sales = WorkspaceRole.query.filter_by(name='Sales').one()
    assert sales.pages == ['crm_today', 'crm_board', 'wa_inbox']      # unknown pages are not stored
    # the Administrator role cannot be narrowed
    admin_role = access.system_role(ws, 'admin')
    client.post('/admin/workspace/roles/save', data={'role_id': admin_role.id, 'name': 'Administrator', 'pages': ['home']})
    assert access.role_pages(_db.session.get(WorkspaceRole, admin_role.id)) == access.ALL_PAGES
    # give it to the agent on the member screen
    m = member(ws, cs_user)
    client.post('/admin/workspace/members/%d' % m.id, data={'role_id': sales.id})
    _db.session.expire_all()
    assert member(ws, cs_user).role_id == sales.id
    page = client.get('/admin/workspace/roles').data.decode()
    assert 'Sales' in page and 'Customer service' in page


def test_a_role_cannot_be_made_twice_or_built_ins_deleted(client, ws, admin_user):
    login(client, 'admin@test.com')
    client.post('/admin/workspace/roles/save', data={'name': 'customer SERVICE'})
    assert WorkspaceRole.query.filter_by(workspace_id=ws.id).count() == 2
    cs = access.system_role(ws, 'cs')
    client.post('/admin/workspace/roles/%d/delete' % cs.id)
    assert _db.session.get(WorkspaceRole, cs.id) is not None


def test_deleting_a_role_leaves_its_people_on_their_teams(client, ws, admin_user, cs_user):
    temp = role(ws, 'Temp', ['home'])
    member(ws, cs_user).role = temp
    _db.session.commit()
    login(client, 'admin@test.com')
    client.post('/admin/workspace/roles/%d/delete' % temp.id)
    _db.session.expire_all()
    assert member(ws, cs_user).role_id is None
    assert access._member_pages(member(ws, cs_user)) == frozenset()


# ============================================================================== members

def test_adding_somebody_new_makes_a_staff_account(client, ws, admin_user):
    login(client, 'admin@test.com')
    sales = role(ws, 'Sales', ['crm_today'])
    client.post('/admin/workspace/members/add', data={'email': 'New.Person@Example.com', 'first_name': 'Neha',
                                                       'role_id': sales.id})
    u = User.query.filter_by(email='new.person@example.com').one()
    assert u.is_cs and not u.is_admin and u.first_name == 'Neha'
    assert member(ws, u).role_id == sales.id
    client.post('/auth/logout')


def test_adding_an_existing_traveller_makes_them_staff(client, ws, admin_user, user):
    login(client, 'admin@test.com')
    client.post('/admin/workspace/members/add', data={'email': 'bob@test.com', 'role_id': access.system_role(ws, 'cs').id})
    _db.session.expire_all()
    bob = User.query.filter_by(email='bob@test.com').one()
    assert bob.is_cs and member(ws, bob)


def test_removing_somebody_ends_their_staff_access(client, ws, admin_user, cs_user):
    login(client, 'admin@test.com')
    m = member(ws, cs_user)
    client.post('/admin/workspace/members/%d/remove' % m.id)
    _db.session.expire_all()
    agent = User.query.filter_by(email='cs@test.com').one()
    assert not WorkspaceMember.query.filter_by(user_id=agent.id).count()
    assert not agent.is_cs
    client.post('/auth/logout')
    login(client, 'cs@test.com')
    assert client.get('/cs/').status_code == 302


def test_nobody_locks_themselves_out(client, ws, admin_user, cs_user):
    manager = make_user('m@test.com', 'manager', role='cs')
    access.add_member(ws, manager, role=role(ws, 'Manager', ['ws_members', 'ws_roles', 'home']))
    login(client, 'm@test.com')
    me = member(ws, manager)
    client.post('/admin/workspace/members/%d' % me.id, data={'role_id': access.system_role(ws, 'cs').id})
    client.post('/admin/workspace/members/%d/remove' % me.id)
    _db.session.expire_all()
    assert member(ws, manager).role.name == 'Manager'
    owner = member(ws, User.query.filter_by(email='admin@test.com').one())
    client.post('/admin/workspace/members/%d/remove' % owner.id)
    assert _db.session.get(WorkspaceMember, owner.id) is not None       # the owner stays


def test_a_role_can_hand_over_running_the_workspace(client, ws, cs_user):
    """Members and roles are pages like any other, so a manager can run the team without being
    a site admin."""
    member(ws, cs_user).role = role(ws, 'Team lead', ['home', 'ws_members', 'ws_teams'])
    _db.session.commit()
    login(client, 'cs@test.com')
    assert client.get('/admin/workspace/members').status_code == 200
    assert client.get('/admin/workspace/teams').status_code == 200
    assert client.get('/admin/workspace/roles').status_code == 302


def test_a_new_agent_from_the_users_screen_joins_the_workspace(client, ws, admin_user, user):
    login(client, 'admin@test.com')
    bob = User.query.filter_by(email='bob@test.com').one()
    client.post('/admin/users/%d/roles' % bob.id, json={'roles': ['user', 'cs']})
    _db.session.expire_all()
    assert member(ws, bob).role.system_key == 'cs'
    client.post('/admin/users/%d/roles' % bob.id, json={'roles': ['user']})
    _db.session.expire_all()
    assert not WorkspaceMember.query.filter_by(user_id=bob.id).count()


# ============================================================================== teams and workspaces

def test_teams_on_the_screen(client, ws, admin_user, cs_user):
    login(client, 'admin@test.com')
    desk = role(ws, 'Desk', ['sahayak'])
    client.post('/admin/workspace/teams/save', data={'name': 'Sahayak desk', 'role_id': desk.id,
                                                      'user_ids': [str(cs_user.id)]})
    team = WorkspaceTeam.query.filter_by(name='Sahayak desk').one()
    assert [u.email for u in team.users] == ['cs@test.com'] and team.role_id == desk.id
    assert 'Sahayak desk' in client.get('/admin/workspace/teams').data.decode()
    client.post('/admin/workspace/teams/%d/delete' % team.id)
    assert WorkspaceTeam.query.count() == 0


def test_a_second_workspace_and_switching(client, ws, admin_user, cs_user):
    login(client, 'admin@test.com')
    client.post('/admin/workspace/create', data={'name': 'Sahayak operations', 'modules': ['console', 'sahayak']})
    ops = Workspace.query.filter_by(name='Sahayak operations').one()
    assert ops.modules == ['console', 'sahayak', 'workspace'] and member(ops, User.query.filter_by(email='admin@test.com').one()).is_owner
    # the agent is in the first workspace only; put them in the second with its CS role
    access.add_member(ops, cs_user, role=access.system_role(ops, 'cs'))
    client.post('/auth/logout')
    login(client, 'cs@test.com')
    html = client.get('/cs/').data.decode()
    assert 'Sahayak operations' in html                                 # offered in the switcher
    client.get('/admin/workspace/switch/%d' % ops.id)
    nav = client.get('/cs/sahayak').data.decode().split('admin-nav-items', 1)[1].split('</nav>', 1)[0]
    assert 'data-group="sahayak"' in nav and 'data-group="crm"' not in nav
    # a link into the other workspace's module switches back to it rather than refusing
    assert client.get('/cs/crm/today').status_code == 200


def test_notifications_go_to_whoever_the_roles_say(app, ws, admin_user, cs_user):
    from app.services import cs_access
    member(ws, cs_user).role = role(ws, 'Sahayak only', ['sahayak'])
    _db.session.commit()
    assert cs_user not in cs_access.recipients('insurance')
    assert cs_user in cs_access.recipients('sahayak')
    assert any(u.email == 'admin@test.com' for u in cs_access.recipients('insurance'))


# ============================================================================== WhatsApp

def test_whatsapp_pages_say_what_is_missing_when_not_connected(client, ws, admin_user, monkeypatch):
    monkeypatch.delenv('WACRM_URL', raising=False)
    monkeypatch.delenv('WACRM_PORTAL_SECRET', raising=False)
    login(client, 'admin@test.com')
    html = client.get('/admin/messaging/inbox').data.decode()
    assert 'not connected to the portal' in html and '<iframe' not in html


def test_whatsapp_opens_signed_in_as_the_role_the_pages_give(client, ws, admin_user, cs_user, monkeypatch):
    import base64
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/travel-companions/admin/whatsapp')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    login(client, 'cs@test.com')                          # Customer service: inbox, contacts, quick replies
    html = client.get('/admin/messaging/inbox').data.decode()
    src = html.split('data-wa-frame', 1)[0].rsplit('src="', 1)[1].split('"', 1)[0]
    assert src.startswith('https://crm.example/travel-companions/admin/whatsapp/api/portal/sso?t=')
    token = src.split('t=', 1)[1].replace('&amp;', '&')
    from urllib.parse import unquote
    body, sig = unquote(token).split('.')
    payload = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
    assert payload['purpose'] == 'sso' and payload['email'] == 'cs@test.com'
    assert payload['role'] == 'agent' and payload['next'] == '/inbox' and payload['exp'] - payload['iat'] <= 300
    import hashlib, hmac
    good = base64.urlsafe_b64encode(hmac.new(b'x' * 40, body.encode(), hashlib.sha256).digest()).rstrip(b'=').decode()
    assert hmac.compare_digest(good, sig)
    # templates make somebody a WhatsApp admin; a role without WhatsApp pages gets no frame
    assert client.get('/admin/messaging/templates').status_code == 302
    member(ws, cs_user).role = role(ws, 'No WhatsApp', ['home'])
    _db.session.commit()
    assert client.get('/admin/messaging/inbox').status_code == 302


def test_a_reload_inside_the_frame_stays_where_it_was(client, ws, admin_user, monkeypatch):
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/wa')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    login(client, 'admin@test.com')
    for p, expected in (('/inbox?c=abc', '/inbox?c=abc'), ('//evil.example', '/inbox'), ('https://evil', '/inbox')):
        html = client.get('/admin/messaging/inbox', query_string={'p': p}).data.decode()
        token = html.split('/api/portal/sso?t=', 1)[1].split('"', 1)[0]
        from urllib.parse import unquote
        import base64
        body = unquote(token).split('.')[0]
        assert json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))['next'] == expected


def test_linking_keeps_the_crm_team_in_step(app, ws, admin_user, cs_user, monkeypatch):
    calls = []

    def fake_api(method, path, payload=None, params=None):
        calls.append((method, path, payload))
        if path == 'workspace':
            return {'account_id': 'acc-1', 'name': 'Admin'}
        if path == 'members' and method == 'GET':
            return [{'email': 'old.agent@example.com', 'name': 'Old', 'role': 'agent', 'banned': False},
                    {'email': 'admin@test.com', 'role': 'owner'}]
        return {}
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/wa')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    monkeypatch.setattr(wacrm_team, '_api', fake_api)
    ok, failed = wacrm_team.link(ws)
    assert (ok, failed) == (2, 0)
    pushed = {p['email']: p['role'] for m, path, p in calls if path == 'members' and m == 'POST'}
    assert pushed == {'admin@test.com': 'admin', 'cs@test.com': 'agent'}
    assert ('PATCH', 'workspace', {'name': 'NRI Parent Service'}) in calls
    # somebody the CRM has that the workspace does not is listed, never removed by linking
    assert [x['email'] for x in ws.wacrm['extra']] == ['old.agent@example.com']
    assert not any(path == 'members/remove' for _, path, _ in calls)
    # losing every WhatsApp page takes them out
    calls.clear()
    member(ws, cs_user).role = role(ws, 'Queues', ['home'])
    _db.session.commit()
    wacrm_team.member_changed(member(ws, cs_user))
    assert calls == [('POST', 'members/remove', {'email': 'cs@test.com'})]
    assert member(ws, cs_user).wacrm_role is None


def test_a_crm_that_is_down_never_stops_the_workspace(client, ws, admin_user, monkeypatch):
    def down(*a, **k):
        raise wacrm_team.TeamError('The WhatsApp CRM could not be reached.')
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/wa')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    ws.wacrm = {'account_id': 'acc-1', 'name': 'NRI Parent Service'}
    _db.session.commit()
    monkeypatch.setattr(wacrm_team, '_api', down)
    login(client, 'admin@test.com')
    r = client.post('/admin/workspace/members/add', data={'email': 'late@example.com',
                                                          'role_id': access.system_role(ws, 'cs').id})
    assert r.status_code == 302
    late = member(ws, User.query.filter_by(email='late@example.com').one())
    assert late.wacrm_error and 'could not be reached' in late.wacrm_error
    assert 'Not synced' in client.get('/admin/workspace/members').data.decode()


def test_whatsapp_on_another_site_is_framed_from_there(client, ws, admin_user, monkeypatch):
    """studio.preventia360.com/crm, not this site: the frame loads from there, and only that site may
    tell the page where it is."""
    monkeypatch.setenv('WACRM_URL', 'https://studio.preventia360.com/crm')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    login(client, 'admin@test.com')
    html = client.get('/admin/messaging/inbox').data.decode()
    assert 'src="https://studio.preventia360.com/crm/api/portal/sso?t=' in html
    assert 'var crmOrigin = "https://studio.preventia360.com" ||' in html
    assert 'href="https://studio.preventia360.com/crm/inbox"' in html          # "New tab"
