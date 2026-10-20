"""Admin -> Users -> Manage: one account in a side panel -- account roles, its place in the team, sign-in, a
set-password e-mail, delete -- each change posting to the route that owns it, which answers the panel in JSON.
"""
from html import unescape

from conftest import login, logout, make_user
from app import db as _db
from app.models import User, WorkspaceMember, WorkspaceTeam
from app.services import access, mailer

JSON = {'Accept': 'application/json'}


def panel(client, u):
    r = client.get('/admin/users/%d/panel' % u.id)
    assert r.status_code == 200
    return unescape(r.data.decode())


def member(ws, u):
    return WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=u.id).first()


def test_the_table_has_a_manage_button_and_tidy_role_chips(client, app, admin_user, user):
    access.ensure_defaults()
    login(client, admin_user.email)
    page = client.get('/admin/users').data.decode()
    assert 'data-manage="%d"' % user.id in page and 'id="userPanel"' in page
    assert 'class="role-select"' not in page and 'data-owner=' not in page             # the old inline controls
    assert 'ur-chip super' in page                                                      # the Super admin's row


def test_a_traveller_is_added_to_the_team_from_the_panel(client, app, admin_user, user):
    ws = access.ensure_defaults()
    team = WorkspaceTeam(workspace_id=ws.id, name='North')
    _db.session.add(team)
    _db.session.commit()
    login(client, admin_user.email)
    p = panel(client, user)
    assert 'Account roles' in p and 'Add to %s' % ws.name in p and 'Traveller' in p
    r = client.post('/admin/workspace/members/add', headers=JSON,
                    data={'user_ids': [user.id], 'role_id': access.system_role(ws, 'cs').id, 'team_ids': [team.id]})
    assert r.status_code == 200 and r.get_json()['success'] and 'Added Bob' in r.get_json()['message']
    m = member(ws, user)
    assert m is not None and access.teams_of(m) == [team]
    p = panel(client, user)
    assert 'Save role and teams' in p and 'Remove from %s' % ws.name in p


def test_the_team_role_and_removal_answer_the_panel(client, app, admin_user, user):
    ws = access.ensure_defaults()
    access.add_member(ws, user, role=access.system_role(ws, 'cs'))
    lead = next(r for r in ws.roles if r.name == 'Team lead')
    login(client, admin_user.email)
    m = member(ws, user)
    r = client.post('/admin/workspace/members/%d' % m.id, headers=JSON, data={'role_id': lead.id})
    assert r.get_json() == {'success': True, 'message': 'Saved Bob.'}
    assert member(ws, user).role_id == lead.id
    r = client.post('/admin/workspace/members/%d/remove' % m.id, headers=JSON)
    assert r.get_json()['success'] and member(ws, user) is None


def test_sign_in_and_a_set_password_email_from_the_panel(client, app, admin_user, user, monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, 'send', lambda subject, to, body, **kw: sent.append((subject, to, body)) or True)
    login(client, admin_user.email)
    r = client.post('/admin/users/%d/send-reset' % user.id)
    assert r.get_json()['success'] and sent and sent[0][1] == ['bob@test.com'] and '/auth/reset/' in sent[0][2]
    assert client.post('/admin/users/%d/toggle' % user.id).get_json()['is_active'] is False
    assert 'Enable sign-in' in panel(client, user)


def test_what_the_panel_lets_each_admin_do(client, app, admin_user, user):
    access.ensure_defaults()
    plain = make_user('admin2@test.com', 'admin2', role='admin')
    login(client, plain.email)
    p = panel(client, admin_user)                                     # a Super admin, seen by a plain admin
    assert "Only a Super admin can change a Super admin's account" in p
    assert 'Save account roles' not in p and 'data-toggle-active' not in p and 'user-del' not in p
    p = panel(client, user)
    assert 'Save account roles' in p and 'value="superadmin" disabled' in p          # cannot give it
    p = panel(client, plain)
    assert 'This is you' in p and 'Save account roles' not in p
    logout(client)
    assert client.get('/admin/users/%d/panel' % user.id).status_code == 302           # signed out
    login(client, user.email)
    assert client.get('/admin/users/%d/panel' % user.id).status_code == 302           # a traveller
    assert client.post('/admin/users/%d/send-reset' % user.id).status_code == 302
    assert _db.session.get(User, user.id).is_active
