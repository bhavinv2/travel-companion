"""What a role may DO on its pages, and the six ready-made profiles (Staff Console 2.0, 2026-10-26).

    look only   a page the role opens only to look: every request that changes something there is refused, unless
                another page of theirs may change it; reading marks and previews still work
    remove      a role that may not remove leads cannot, even on its own leads
    generous    several roles: the most generous answer; an Administrator and the owner are never limited
    profiles    the role form offers the profiles; "Add the ready-made roles" makes the missing ones; saving keeps
                the rights; a role from before rights behaves as before
"""
import json

from conftest import login, logout, make_user
from app import db as _db
from app.models import WorkspaceRole
from app.services import access, crm, role_rights


def give(ws, user, name, pages, rights=None, scope=None):
    r = WorkspaceRole(workspace_id=ws.id, name=name, pages=pages, rights=rights, crm_scope=scope)
    _db.session.add(r)
    _db.session.flush()
    m = next((m for m in ws.members if m.user_id == user.id), None)
    if m is None:
        access.add_member(ws, user, role=r)
    else:
        m.role = r
    _db.session.commit()
    access._cache().clear()
    return r


def my_lead(owner, name='Rights Ravi', phone='+919811100301'):
    crm.ensure_defaults()
    l = crm.capture('ti-quote', name=name, phone=phone, utm={})
    l.owner_id = owner.id
    _db.session.commit()
    return l


def test_a_look_only_page_opens_but_nothing_on_it_changes(app, client):
    ws = access.ensure_defaults()
    agent = make_user('look@test.com', 'look', role='cs')
    give(ws, agent, 'Looker', ['crm_board'], rights={'view': ['crm_board'], 'remove': True, 'mask': False})
    lead = my_lead(agent)
    login(client, agent.email)
    assert client.get('/cs/crm/lead/%d' % lead.id).status_code == 200                       # it opens
    assert 'Only to look' in client.get('/cs/crm/').get_data(as_text=True)                  # and says so
    r = client.post('/cs/crm/lead/%d/note' % lead.id, json={'text': 'Called them'})
    assert r.status_code == 403 and r.get_json()['error'] == role_rights.LOOK_ONLY
    r = client.post('/cs/crm/lead/%d/note' % lead.id, data={'text': 'x'}, headers={'Referer': 'http://localhost/cs/crm/'})
    assert r.status_code == 302                                                              # a form: back, with the words
    with app.test_request_context():
        assert role_rights.may_change(agent, 'cs.voice_read')                               # reading marks still work


def test_another_page_that_may_change_it_wins(app, client):
    ws = access.ensure_defaults()
    agent = make_user('both@test.com', 'both', role='cs')
    give(ws, agent, 'Board looker, my day worker', ['crm_board', 'crm_today'],
         rights={'view': ['crm_board'], 'remove': True, 'mask': False})
    lead = my_lead(agent, phone='+919811100302')
    login(client, agent.email)
    assert client.post('/cs/crm/lead/%d/note' % lead.id, json={'text': 'Called them'}).get_json()['success']


def test_a_role_that_may_not_remove_cannot_remove_its_own_lead(app, client):
    ws = access.ensure_defaults()
    agent = make_user('keep@test.com', 'keep', role='cs')
    give(ws, agent, 'Keeper', sorted(access.CS_ROLE_PAGES), rights={'view': [], 'remove': False, 'mask': False})
    lead = my_lead(agent, phone='+919811100303')
    login(client, agent.email)
    r = client.post('/cs/crm/lead/%d/remove' % lead.id)
    assert r.status_code == 403 and 'Your role does not remove leads' in r.get_json()['error']
    with app.test_request_context():
        assert crm.can_remove(lead, agent) is False


def test_a_role_from_before_rights_works_as_before_and_admins_are_never_limited(app, client, admin_user):
    ws = access.ensure_defaults()
    agent = make_user('old@test.com', 'old', role='cs')
    give(ws, agent, 'Old role', sorted(access.CS_ROLE_PAGES), rights=None)
    with app.test_request_context():
        assert role_rights.rights_of(agent) == {'view': frozenset(), 'remove': True, 'mask': False}
        assert role_rights.rights_of(admin_user) == role_rights.FULL
    lead = my_lead(agent, phone='+919811100304')
    login(client, agent.email)
    assert client.post('/cs/crm/lead/%d/note' % lead.id, json={'text': 'ok'}).get_json()['success']


def test_several_roles_get_the_most_generous_answer(app):
    ws = access.ensure_defaults()
    agent = make_user('two@test.com', 'two', role='cs')
    give(ws, agent, 'Strict', ['crm_board'], rights={'view': ['crm_board'], 'remove': False, 'mask': True})
    from app.models import WorkspaceTeam
    loose = WorkspaceRole(workspace_id=ws.id, name='Loose', pages=['crm_board'],
                          rights={'view': [], 'remove': True, 'mask': False})
    _db.session.add(loose)
    _db.session.flush()
    team = WorkspaceTeam(workspace_id=ws.id, name='Loose team', role_id=loose.id)
    team.users.append(agent)
    _db.session.add(team)
    _db.session.commit()
    access._cache().clear()
    with app.test_request_context():
        got = role_rights.rights_of(agent)
    assert got == {'view': frozenset(), 'remove': True, 'mask': False}


def test_the_role_form_offers_the_profiles_and_saves_the_rights(app, client, admin_user):
    ws = access.ensure_defaults()
    login(client, admin_user.email)
    page = client.get('/admin/workspace/roles/0').get_data(as_text=True)
    for label in ('Sales agent', 'Service agent', 'Team lead', 'Content editor', 'Admin', 'Owner'):
        assert label in page, label
    presets = json.loads(page.split('id="role-presets">', 1)[1].split('</script>', 1)[0])
    sales = next(p for p in presets if p['key'] == 'sales_agent')
    assert {'crm_today', 'crm_board', 'crm_people'} <= set(sales['pages']) and sales['scope'] == 'own' and sales['mask']
    assert not any(k.startswith('ws_') for k in sales['pages'])                       # nothing to manage
    editor = next(p for p in presets if p['key'] == 'content_editor')
    assert 'blog_list' in editor['pages'] and 'crm_board' not in editor['pages'] and not editor['remove']
    r = client.post('/admin/workspace/roles/save', data={
        'name': 'Desk', 'pages': ['crm_today', 'crm_board', 'crm_auto'], 'view': ['crm_auto', 'posts'],
        'right_mask': 'on', 'profile': 'sales_agent', 'crm_scope': 'own'})
    assert r.status_code == 302
    role = WorkspaceRole.query.filter_by(workspace_id=ws.id, name='Desk').one()
    assert role.rights == {'profile': 'sales_agent', 'view': ['crm_auto'], 'remove': False, 'mask': True}
    listing = client.get('/admin/workspace/roles').get_data(as_text=True)
    assert '1 look-only' in listing and 'cannot remove leads' in listing and 'From the Sales agent profile' in listing


def test_add_the_ready_made_roles_makes_only_the_missing_ones(app, client, admin_user):
    ws = access.ensure_defaults()
    login(client, admin_user.email)
    assert 'Ready-made roles' in client.get('/admin/workspace/roles').get_data(as_text=True)
    client.post('/admin/workspace/roles/profiles')
    names = {r.name for r in WorkspaceRole.query.filter_by(workspace_id=ws.id)}
    assert {'Sales agent', 'Service agent', 'Content editor', 'Team lead', 'Administrator'} <= names
    sales = WorkspaceRole.query.filter_by(workspace_id=ws.id, name='Sales agent').one()
    assert sales.crm_scope == 'own' and sales.rights['mask'] is True and sales.rights['profile'] == 'sales_agent'
    before = WorkspaceRole.query.count()
    client.post('/admin/workspace/roles/profiles')                                   # twice: nothing more
    assert WorkspaceRole.query.count() == before
    assert 'Ready-made roles' not in client.get('/admin/workspace/roles').get_data(as_text=True)
    logout(client)
