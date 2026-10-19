"""Team members -> Add: pick people who already have an account (staff or travellers), several at once, and/or
invite somebody new by e-mail; Admin -> Users sends ticked accounts straight to that form.
"""
from html import unescape

from conftest import login, make_user
from app import db as _db
from app.models import User, WorkspaceMember
from app.services import access

MEMBERS = '/admin/workspace/members'


def member(ws, u):
    return WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=u.id).first()


def test_picked_accounts_join_with_the_chosen_role_and_travellers_become_staff(client, app, admin_user, user, other_user):
    ws = access.ensure_defaults()
    cs_role = access.system_role(ws, 'cs')
    login(client, admin_user.email)
    r = client.post(MEMBERS + '/add', data={'user_ids': [user.id, other_user.id], 'role_id': cs_role.id},
                    follow_redirects=True)
    page = unescape(r.data.decode())
    assert 'Added Bob, Alice' in page or 'Added Alice, Bob' in page
    for u in (user, other_user):
        m = member(ws, u)
        assert m is not None and m.role_id == cs_role.id
        fresh = _db.session.get(User, u.id)
        assert fresh.is_cs and 'user' in fresh.role_keys                        # staff now, still a traveller too


def test_a_pick_and_a_new_address_in_one_go_and_nobody_twice(client, app, admin_user, user):
    ws = access.ensure_defaults()
    login(client, admin_user.email)
    page = unescape(client.post(MEMBERS + '/add', data={'user_ids': [user.id], 'email': 'new.agent@test.com',
                                                        'first_name': 'Nina'}, follow_redirects=True).data.decode())
    nina = User.query.filter_by(email='new.agent@test.com').one()
    assert member(ws, user) and member(ws, nina) and nina.is_cs
    assert 'Added' in page
    again = unescape(client.post(MEMBERS + '/add', data={'user_ids': [user.id], 'email': 'BOB@test.com'},
                                 follow_redirects=True).data.decode())
    assert 'Already a member: Bob' in again
    assert WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=user.id).count() == 1


def test_nothing_picked_and_no_address_adds_nobody(client, app, admin_user):
    ws = access.ensure_defaults()
    login(client, admin_user.email)
    before = WorkspaceMember.query.filter_by(workspace_id=ws.id).count()
    page = client.post(MEMBERS + '/add', data={'role_id': ''}, follow_redirects=True).data.decode()
    assert 'Pick somebody from the list' in page
    assert WorkspaceMember.query.filter_by(workspace_id=ws.id).count() == before


def test_the_search_lists_active_accounts_not_in_the_team(client, app, admin_user, user, other_user, cs_user):
    ws = access.ensure_defaults()                                                  # cs_user is a member from the start
    gone = make_user('gone@test.com', 'gonebob')
    gone.is_active = False
    _db.session.commit()
    login(client, admin_user.email)
    names = lambda q: [i['name'] for i in client.get(MEMBERS + '/find', query_string={'q': q}).get_json()['items']]  # noqa: E731
    assert 'Bob' in names('bob') and 'Gonebob' not in names('bob')
    assert names('alice@test') == ['Alice']
    assert 'Csagent' not in names('csagent')                                      # already in the team
    assert names('b') == []
    item = client.get(MEMBERS + '/find?q=bob').get_json()['items'][0]
    assert item['email'] == 'bob@test.com' and item['staff'] is False


def test_users_sends_ticked_accounts_to_the_add_form(client, app, admin_user, user, other_user):
    access.ensure_defaults()
    login(client, admin_user.email)
    users_page = client.get('/admin/users').data.decode()
    assert 'id="userBulkTeamBtn"' in users_page
    assert '/admin/workspace/members?add=1&amp;user=%d#add' % user.id in users_page
    form = client.get(MEMBERS + '?add=1&user=%d&user=%d' % (user.id, other_user.id)).data.decode()
    assert '<details class="card" id="add" open' in form
    assert form.count('name="user_ids"') == 2 and 'value="%d"' % user.id in form


def test_only_people_whose_role_has_team_members_can_add(client, app, admin_user, user):
    ws = access.ensure_defaults()
    agent = make_user('agent@test.com', 'agent', role='cs')
    access.add_member(ws, agent, role=access.system_role(ws, 'cs'))
    login(client, agent.email)
    assert client.get(MEMBERS + '/find?q=bob').status_code in (302, 403)
    client.post(MEMBERS + '/add', data={'user_ids': [user.id]})
    assert member(ws, user) is None
