"""+ New workspace in one flow, and the header switcher showing each workspace's business WhatsApp number.

    flow      name & areas, people & roles, teams, WhatsApp number -- checked whole, made in one go
    switcher  every workspace with its number (live from the WhatsApp CRM, or "to be connected"), + New workspace
"""
import json
from html import unescape

from conftest import login, make_user
from app import db as _db
from app.models import User, Workspace, WorkspaceMember, WorkspaceTeam
from app.services import access, mailer, wacrm_team

NEW = '/admin/workspace/new'


def plan(**kw):
    p = {'name': 'Sahayak Care', 'description': 'Home care', 'modules': ['crm', 'sahayak'], 'phone': '+91 98765 43210',
         'people': [], 'invites': [], 'teams': [], 'send_links': True}
    p.update(kw)
    return {'plan': json.dumps(p)}


def test_a_whole_workspace_is_made_in_one_go(client, app, admin_user, user, monkeypatch):
    access.ensure_defaults()
    sent = []
    monkeypatch.setattr(mailer, 'send', lambda subject, to, body, **kw: sent.append(to) or True)
    login(client, admin_user.email)
    assert 'Business WhatsApp number' in client.get(NEW).data.decode()
    r = client.post(NEW, data=plan(
        people=[{'id': user.id, 'role': 'lead'}],
        invites=[{'email': 'nurse@test.com', 'first_name': 'Nurse', 'role': 'cs'}],
        teams=[{'name': 'Visits', 'role': '', 'members': ['u%d' % user.id, 'enurse@test.com', 'me']}]))
    assert r.status_code == 302 and r.headers['Location'].endswith('/admin/workspace/members')
    ws = Workspace.query.filter_by(name='Sahayak Care').one()
    assert ws.whatsapp_phone == '+919876543210' and set(ws.modules) >= {'crm', 'sahayak'}
    mem = {m.user.email: m for m in WorkspaceMember.query.filter_by(workspace_id=ws.id)}
    assert mem['admin@test.com'].is_owner
    assert mem['bob@test.com'].role.name == 'Team lead' and mem['nurse@test.com'].role.system_key == 'cs'
    team = WorkspaceTeam.query.filter_by(workspace_id=ws.id, name='Visits').one()
    assert {u.email for u in team.users} == {'bob@test.com', 'nurse@test.com', 'admin@test.com'}
    assert User.query.filter_by(email='nurse@test.com').one().is_cs and sent == [['nurse@test.com']]


def test_nothing_is_made_when_part_of_the_plan_is_wrong(client, app, admin_user):
    access.ensure_defaults()
    login(client, admin_user.email)
    before = Workspace.query.count()
    r = client.post(NEW, data=plan(phone='12', invites=[{'email': 'not-an-email', 'role': 'cs'}],
                                   teams=[{'name': 'A', 'members': []}, {'name': 'a', 'members': []}]))
    page = unescape(r.data.decode())
    assert r.status_code == 400 and 'Nothing was made yet' in page
    assert '"not-an-email" is not an e-mail address' in page and 'Two teams are called' in page and 'WhatsApp number' in page
    assert Workspace.query.count() == before and User.query.filter_by(email='not-an-email').count() == 0
    r = client.post(NEW, data={'plan': 'nonsense'})
    assert r.status_code == 400 and Workspace.query.count() == before


def test_the_switcher_shows_each_workspaces_whatsapp_number(client, app, admin_user):
    ws = access.ensure_defaults()
    ws.wacrm = {'account_id': 'acc-1', 'name': ws.name, 'phone': '+919812340000'}
    other = access.create_workspace('Sahayak Care', by=admin_user)
    other.whatsapp_phone = '+919876543210'
    third = access.create_workspace('Empty', by=admin_user)
    _db.session.commit()
    assert wacrm_team.number_of(ws) == {'phone': '+919812340000', 'state': 'live'}
    assert wacrm_team.number_of(other) == {'phone': '+919876543210', 'state': 'planned'}
    assert wacrm_team.number_of(third) == {'phone': None, 'state': 'none'}
    login(client, admin_user.email)
    html = unescape(client.get('/admin/crm/today').data.decode())
    menu = html.split('id="siteSwMenu"', 1)[1].split('</div>\n      </div>', 1)[0]
    assert 'Sahayak Care' in menu and 'to be connected' in menu and 'No WhatsApp number yet' in menu
    assert '/admin/workspace/new' in menu and 'New workspace' in menu
    ws.wacrm = {'account_id': 'acc-1', 'name': ws.name}                   # linked, number not reported yet
    _db.session.commit()
    assert wacrm_team.number_of(ws) == {'phone': None, 'state': 'live'}
    assert 'WhatsApp linked' in unescape(client.get('/admin/crm/today').data.decode())


def test_the_number_the_crm_reports_is_kept_for_the_switcher(app, admin_user, monkeypatch):
    ws = access.ensure_defaults()
    monkeypatch.setattr(wacrm_team, 'workspace_info',
                        lambda: {'account_id': 'acc-1', 'name': ws.name, 'whatsapp': {'display_phone': '+1 555 0100'}})
    monkeypatch.setattr(wacrm_team, 'list_members', lambda: [])
    monkeypatch.setattr(wacrm_team, '_push', lambda m: True)
    wacrm_team.link(ws)
    assert (ws.wacrm or {}).get('phone') == '+1 555 0100'


def test_only_those_who_may_create_workspaces_get_the_flow(client, app, admin_user):
    ws = access.ensure_defaults()
    agent = make_user('agent@test.com', 'agent', role='cs')
    access.add_member(ws, agent, role=access.system_role(ws, 'cs'))
    login(client, agent.email)
    assert client.get(NEW).status_code == 302
    client.post(NEW, data=plan())
    assert Workspace.query.filter_by(name='Sahayak Care').count() == 0
