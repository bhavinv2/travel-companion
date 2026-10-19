"""Account menu -> "Working as": somebody with more than one role sees and works as exactly one of them until
they switch back. Admins can take any role of the workspace; others only the roles they really have.
"""
from html import unescape

from conftest import login, logout, make_user
from app import db as _db
from app.models import WorkspaceRole, WorkspaceTeam
from app.services import access


def menu(html):
    return html.split('admin-nav-items', 1)[1].split('</nav>', 1)[0]


def test_an_admin_works_as_sales_and_service_and_comes_back(client, app, admin_user):
    ws = access.ensure_defaults()
    sales = access.system_role(ws, 'cs')
    login(client, admin_user.email)
    page = unescape(client.get('/admin/crm/today').data.decode())
    assert 'Working as' in page and 'Super admin (everything)' in page and sales.name in page
    r = client.get('/work-as/%d' % sales.id)
    assert r.status_code == 302 and r.headers['Location'].endswith('/cs/crm/today')
    page = unescape(client.get('/cs/crm/today').data.decode())
    assert 'acting-banner' in page and 'You are working as <b>%s</b>' % sales.name in page
    nav = menu(page)
    assert 'data-title="Pipelines"' not in nav and 'data-title="Users"' not in nav and 'data-title="My day"' in nav
    assert client.get('/admin/users').status_code == 302                         # not this role's
    assert client.get('/admin/workspace/menu').status_code == 302
    client.get('/work-as/0')
    assert client.get('/admin/users').status_code == 200 and 'acting-banner' not in client.get('/admin/users').data.decode()


def test_working_as_administrator_still_cannot_delete(client, app, admin_user):
    ws = access.ensure_defaults()
    login(client, admin_user.email)
    with client.session_transaction() as s:
        s[access.ACT_KEY] = access.system_role(ws, 'admin').id
    assert client.post('/admin/delete/contact_message/1', json={}).status_code in (302, 403)


def test_an_agent_switches_only_between_their_own_roles(client, app, admin_user):
    ws = access.ensure_defaults()
    agent = make_user('agent@test.com', 'agent', role='cs')
    insurance = WorkspaceRole(workspace_id=ws.id, name='Insurance desk', pages=['insurance', 'voices_insurance'])
    _db.session.add(insurance)
    _db.session.commit()
    access.add_member(ws, agent, role=access.system_role(ws, 'cs'))
    login(client, agent.email)
    assert 'Working as' not in client.get('/cs/crm/today').data.decode()         # one role: nothing to switch
    team = WorkspaceTeam(workspace_id=ws.id, name='Insurance', role=insurance)
    team.users.append(agent)
    _db.session.add(team)
    _db.session.commit()
    page = unescape(client.get('/cs/crm/today').data.decode())
    assert 'Working as' in page and 'Insurance desk' in page and 'All my roles' in page
    client.get('/work-as/%d' % insurance.id)
    assert client.get('/cs/crm/today').status_code == 302                        # Sales is not the insurance role
    assert client.get('/cs/insurance-quotes').status_code == 200
    r = client.get('/work-as/%d' % access.system_role(ws, 'admin').id, follow_redirects=True)
    assert 'You cannot work as that role here' in r.data.decode()                # not theirs to take
    logout(client)
    login(client, agent.email)
    assert client.get('/cs/crm/today').status_code == 200                        # signing out forgets it
