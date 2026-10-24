"""Sales CRM 2.0, run 3b -- who sees which leads.

    scope      a role sees everyone's leads (the default, NULL), its team's, or only its own; unassigned leads
               are everybody's; admins and supers see all; the most generous role wins; "Working as" narrows
    sweep      an 'own' agent meets no other agent's lead or person on ANY screen or action
    default    a role nobody touched still sees every lead
"""
import json

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmLead, CrmPerson, WorkspaceRole, WorkspaceTeam
from app.services import access, crm, crm_access, crm_money

from test_crm_wa_sync_engine import ti_lead


def words(html):
    import re
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


def staff(email, username, role_name=None, scope=None, extra=()):
    """A sales person in the first workspace with their own role (scope: NULL/'team'/'own')."""
    ws = access.ensure_defaults()
    u = make_user(email, username, role='cs')
    role = None
    if scope is not None or extra:
        role = WorkspaceRole(workspace_id=ws.id, name=role_name or ('Role ' + username),
                             pages=sorted(access.CS_ROLE_PAGES | set(extra)), crm_scope=scope)
        _db.session.add(role)
        _db.session.flush()
        ws.roles.append(role)
    else:
        role = access.system_role(ws, 'cs')
    access.add_member(ws, u, role=role)
    _db.session.commit()
    access._cache().clear()
    return u


def lead_for(name, phone, owner=None):
    l = ti_lead(phone=phone, name=name)
    l.owner_id = owner.id if owner is not None else None
    _db.session.commit()
    return l


@pytest.fixture
def world(app):
    asha = staff('asha@test.com', 'asha', scope='own', extra=('crm_calendar', 'crm_forecast', 'crm_export', 'crm_tracker'))
    bela = staff('bela@test.com', 'bela')
    chitra = staff('chitra@test.com', 'chitra')
    mine = lead_for('Ownerone Mine', '+919876500001', asha)
    other = lead_for('Otherwoman Hidden', '+919876500002', bela)
    free = lead_for('Nobodyyet Free', '+919876500003', None)
    return dict(asha=asha, bela=bela, chitra=chitra, mine=mine, other=other, free=free)


# ====================================================================================== the rules

def test_a_role_nobody_touched_sees_everyones_leads(app, world):
    ws = access.ensure_defaults()
    assert all(r.crm_scope is None for r in ws.roles if r.system_key)          # the built-in roles are untouched
    for u in (world['bela'], world['chitra']):
        assert crm_access.scope_of(u) == 'all'
        assert crm_access.lead_filter(u) is None
        assert crm_access.can_see_lead(u, world['mine']) and crm_access.can_see_lead(u, world['other'])


def test_own_sees_own_and_unassigned(app, world):
    a = world['asha']
    assert crm_access.scope_of(a) == 'own'
    assert crm_access.can_see_lead(a, world['mine'])
    assert crm_access.can_see_lead(a, world['free'])
    assert not crm_access.can_see_lead(a, world['other'])
    ids = {l.id for l in CrmLead.query.filter(crm_access.lead_filter(a)).all()}
    assert ids == {world['mine'].id, world['free'].id}


def test_team_sees_the_leads_of_everyone_in_their_teams(app):
    ws = access.ensure_defaults()
    dev = staff('dev@test.com', 'dev', scope='team')
    mate = staff('mate@test.com', 'mate')
    stranger = staff('stranger@test.com', 'stranger')
    team = WorkspaceTeam(workspace_id=ws.id, name='North')
    _db.session.add(team)
    _db.session.flush()
    team.users.extend([dev, mate])
    _db.session.commit()
    access._cache().clear()
    a, b, c = (lead_for('Devlead One', '+919876500011', dev), lead_for('Matelead Two', '+919876500012', mate),
               lead_for('Strangerlead Three', '+919876500013', stranger))
    assert crm_access.scope_of(dev) == 'team'
    assert crm_access.can_see_lead(dev, a) and crm_access.can_see_lead(dev, b)
    assert not crm_access.can_see_lead(dev, c)
    assert crm_access.scope_of(mate) == 'all'                        # the teammate's own role is untouched


def test_admins_supers_and_the_workspace_owner_always_see_everything(app, admin_user):
    ws = access.ensure_defaults()
    other = lead_for('Anybody Else', '+919876500021', staff('x@test.com', 'x', scope='own'))
    assert crm_access.scope_of(admin_user) == 'all' and crm_access.can_see_lead(admin_user, other)
    admin_role = access.system_role(ws, 'admin')
    admin_role.crm_scope = 'own'                                       # even a tampered Administrator role
    _db.session.commit()
    access._cache().clear()
    assert crm_access.scope_of(admin_user) == 'all'


def test_the_most_generous_role_wins_and_working_as_narrows(app, world, client):
    ws = access.ensure_defaults()
    a = world['asha']
    team_role = WorkspaceRole(workspace_id=ws.id, name='Everyone', pages=sorted(access.CS_ROLE_PAGES))
    _db.session.add(team_role)
    team = WorkspaceTeam(workspace_id=ws.id, name='Wide', role=team_role)
    _db.session.add(team)
    _db.session.flush()
    team.users.append(a)
    _db.session.commit()
    access._cache().clear()
    assert crm_access.scope_of(a) == 'all'                              # own role: own; team role: everyone's
    login(client, a.email)
    own_role = next(r for r in ws.roles if r.crm_scope == 'own')
    with client.session_transaction() as s:
        s[access.ACT_KEY] = own_role.id
    r = client.get('/cs/crm/?p=all&view=list&owner=all')
    assert r.status_code == 200
    t = words(r.get_data(as_text=True))
    assert 'Ownerone Mine' in t and 'Otherwoman Hidden' not in t       # working as the narrow role


def test_person_visibility(app, world):
    a = world['asha']
    assert crm_access.can_see_person(a, world['mine'].person)
    assert not crm_access.can_see_person(a, world['other'].person)
    lonely = CrmPerson(name='Noenquiry Person', email='lonely@x.com')
    _db.session.add(lonely)
    _db.session.commit()
    assert crm_access.can_see_person(a, lonely)                          # no leads: everybody's
    # a person with a lead of mine AND a lead of somebody else's is visible
    both = lead_for('Both Sides', '+919876500031', world['bela'])
    both2 = crm.capture('ti-quote', name='Both Sides', phone='+919876500031', utm={}, product='SH')
    both2.owner_id = a.id
    _db.session.commit()
    assert crm_access.can_see_person(a, both.person)


# ====================================================================================== the sweep

def test_sweep_an_own_agent_meets_no_other_agents_lead_anywhere(app, client, world):
    a, other, mine, free = world['asha'], world['other'], world['mine'], world['free']
    login(client, a.email)
    hid = 'Otherwoman'
    seen = ('Ownerone', 'Nobodyyet')

    def page(url, ok=200):
        r = client.get(url, follow_redirects=True)
        assert r.status_code == ok, (url, r.status_code)
        return words(r.get_data(as_text=True))

    # board and list (every owner chosen), the unrouted/odd counts included
    t = page('/cs/crm/?p=all&view=list&owner=all')
    assert hid not in t and 'Ownerone' in t
    t = page('/cs/crm/?p=ti-standard&view=board&owner=all')
    assert hid not in t
    r = client.get('/cs/crm/?p=all&view=list&owner=all&q=Otherwoman')
    t = words(r.get_data(as_text=True))
    # the search word comes back in the search box; the lead itself must not
    assert 'Otherwoman Hidden' not in t and 'lead/%d"' % other.id not in r.get_data(as_text=True)
    assert 'value="Otherwoman"' in r.get_data(as_text=True)
    # the owner filter offers the person and not the colleagues they may not see
    r = client.get('/cs/crm/?p=all&view=list&owner=all')
    assert 'Bela' not in re_select(r.get_data(as_text=True), 'owner')

    # the lead page and its parts
    assert client.get('/cs/crm/lead/%d' % other.id).status_code == 404
    assert client.get('/cs/crm/lead/%d' % mine.id).status_code == 200
    assert client.get('/cs/crm/lead/%d' % free.id).status_code == 200
    assert client.get('/cs/crm/lead/%d/live' % other.id).status_code == 404
    # the contact page, and what is done from it
    assert client.get('/cs/crm/contact/%d' % other.person_id).status_code == 404
    assert client.get('/cs/crm/contact/%d/edit' % other.person_id).status_code == 404
    assert client.get('/cs/crm/contact/%d' % mine.person_id).status_code == 200
    # Contacts and its filters
    t = page('/cs/crm/contacts')
    assert hid not in t and 'Ownerone' in t
    t = page('/cs/crm/contacts?enq=yes')
    assert hid not in t
    t = page('/cs/crm/contacts?q=Otherwoman')
    assert hid not in t
    # Find a person (the header box) and Visual Flow's own search
    assert client.get('/cs/crm/find?q=Otherwoman').get_json()['items'] == []
    assert 'Ownerone' in json.dumps(client.get('/cs/crm/find?q=Ownerone').get_json())
    assert client.get('/cs/crm/flow/find?q=Otherwoman').get_json()['items'] == []
    t = page('/cs/crm/flow?person_id=%d&person_id=%d' % (other.person_id, mine.person_id))
    assert hid not in t
    # exports live in the admin console; even so the same query a scoped person would run is limited
    for url in ('/admin/crm/export/leads?p=all&owner=all&win=all', '/admin/crm/export/contacts'):
        r = client.get(url)
        assert hid not in r.get_data(as_text=True)
    from app.services import crm_people
    names = {p.name for p in crm_people.contacts_filter({}, a).all()}
    assert 'Otherwoman Hidden' not in names and 'Ownerone Mine' in names
    # My day, "everybody's" view included
    for q in ('', '?who=all'):
        assert hid not in page('/cs/crm/today' + q)
    # Calendar (every scope), the List tab too
    for q in ('?who=all', '?who=team', '?tab=list&who=all'):
        assert hid not in page('/cs/crm/calendar' + q)
    # Forecast: the people on it, and the numbers behind the links
    t = page('/cs/crm/forecast')
    assert 'Bela' not in t and 'Chitra' not in t
    # the lead panel beside the WhatsApp inbox
    r = client.get('/messaging/lead-panel?phone=919876500002&conversation=c-hidden')
    assert hid not in words(r.get_data(as_text=True))
    # a suggestion for a lead they may not see leaks nothing of it
    assert client.get('/cs/crm/suggest?q=hello&lead=%d' % other.id).status_code == 200


def test_sweep_control_an_admin_does_meet_them_on_the_same_screens(app, world, admin_user):
    """The sweep above proves absence: this proves the screens do list them, so absence means something."""
    c = app.test_client()
    login(c, admin_user.email)
    for url in ('/cs/crm/?p=all&view=list&owner=all', '/cs/crm/contacts', '/cs/crm/today?who=all'):
        r = c.get(url, follow_redirects=True)
        assert 'Otherwoman' in words(r.get_data(as_text=True)), url
    assert c.get('/cs/crm/find?q=Otherwoman').get_json()['items']
    assert c.get('/cs/crm/lead/%d' % world['other'].id).status_code == 200


def re_select(html, name):
    import re
    m = re.search(r'<select[^>]*name="%s".*?</select>' % name, html, re.S)
    return words(m.group(0)) if m else ''


def test_sweep_actions_on_a_lead_they_may_not_see_are_refused(app, client, world):
    a, other = world['asha'], world['other']
    login(client, a.email)
    lid, pid = other.id, other.person_id
    stage = other.stage_id
    for url, body in (
            ('/cs/crm/lead/%d/move' % lid, {'stage_id': stage}),
            ('/cs/crm/lead/%d/note' % lid, {'text': 'hello'}),
            ('/cs/crm/lead/%d/remove' % lid, {}),
            ('/cs/crm/lead/%d/call' % lid, {'outcome': 'connected'}),
            ('/cs/crm/lead/%d/send' % lid, {'text': 'hello'}),
            ('/cs/crm/tasks/add', {'lead_id': lid, 'title': 'x', 'kind': 'todo'}),
            ('/cs/crm/tasks/add', {'person_id': pid, 'title': 'x', 'kind': 'todo'}),
            ('/cs/crm/email/send', {'lead_id': lid, 'subject': 's', 'body': 'b'})):
        r = client.post(url, json=body)
        assert r.status_code == 404, (url, r.status_code)
    assert client.get('/cs/crm/email/compose?lead_id=%d' % lid).status_code == 404
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lid).deleted_at is None            # nothing happened


def test_bulk_actions_only_touch_leads_they_may_see(app, client, world):
    a, other, mine = world['asha'], world['other'], world['mine']
    login(client, a.email)
    r = client.post('/cs/crm/leads/bulk', json={'lead_ids': [other.id, mine.id], 'action': 'give', 'owner_id': world['chitra'].id})
    assert r.status_code == 200
    _db.session.expire_all()
    assert _db.session.get(CrmLead, other.id).owner_id == world['bela'].id        # untouched
    assert _db.session.get(CrmLead, mine.id).owner_id == world['chitra'].id


def test_adding_a_lead_for_somebody_elses_contact_does_not_name_them(app, client, world):
    a = world['asha']
    login(client, a.email)
    r = client.post('/cs/crm/add', data={'name': 'Whoever', 'phone': '+919876500002', 'source': 'call',
                                         'product': 'TI', 'owner': 'me'}, follow_redirects=True)
    t = words(r.get_data(as_text=True))
    assert 'Someone else looks after this person' in t
    assert 'Otherwoman' not in t and '98765 00002' not in t


def test_forecast_lists_only_the_people_the_role_may_see(app, client, world):
    login(client, world['asha'].email)
    t = words(client.get('/cs/crm/forecast').get_data(as_text=True))
    assert 'Asha' in t and 'Bela' not in t


def test_the_roles_screen_sets_the_scope(app, client, admin_user):
    ws = access.ensure_defaults()
    login(client, admin_user.email)
    page = client.get('/admin/workspace/roles/0') if False else None
    from flask import url_for
    with app.test_request_context():
        new_url = url_for('workspace.role', role_id=0)
        save_url = url_for('workspace.save_role')
    html = client.get(new_url).get_data(as_text=True)
    assert 'Which leads can people with this role see?' in html
    assert "Everyone&#39;s" in html and "Their team" in html and 'Only their own' in html
    r = client.post(save_url, data={'name': 'Careful', 'crm_scope': 'own', 'pages': ['crm_today', 'crm_board']})
    assert r.status_code == 302
    role = WorkspaceRole.query.filter_by(name='Careful').one()
    assert role.crm_scope == 'own'
    r = client.post(save_url, data={'role_id': role.id, 'name': 'Careful', 'crm_scope': 'all', 'pages': ['crm_today']})
    _db.session.expire_all()
    assert WorkspaceRole.query.filter_by(name='Careful').one().crm_scope is None       # 'all' is NULL: today's behaviour


def test_calendar_everyone_and_team_stop_at_what_the_role_may_see(app, client, world, admin_user):
    from datetime import date, timedelta
    day = date.today() + timedelta(days=1)
    for l in (world['mine'], world['other']):
        l.departure_date = day
    _db.session.commit()
    url = '/cs/crm/calendar?view=week&on=%s&who=all' % day.isoformat()
    c = app.test_client()
    login(c, admin_user.email)
    t = words(c.get(url).get_data(as_text=True))
    assert 'Otherwoman' in t and 'Ownerone' in t
    _db.session.expire_all()               # a real request has its own session and user; the test shares them
    from flask import g
    g.pop('_login_user', None)
    login(client, world['asha'].email)
    t = words(client.get(url).get_data(as_text=True))
    assert 'Ownerone' in t and 'Otherwoman' not in t
