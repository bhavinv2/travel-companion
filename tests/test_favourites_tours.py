"""Favourites, saved views of any staff page shared with one's team only, and the tour guide (2026-10-27).

    favourites  the header's star keeps a screen with its filters, once; only a staff screen one's role opens, never
                a download or another site; rename / move / remove are one's own; the rail lists them; a favourite
                of a page one's role lost is hidden, not deleted
    views       "This page" saves a list's filters as a view of that page (not of one record, not of Leads, whose
                own Views menu does it); it is seen by the owner and their team only; anybody who can open it can
                star it; deleting it takes the stars with it; an admin's view opens in an agent's console
    tours       each role gets its own tour and the common ones; steps only on screens they may open; the question
                ten seconds in is asked once a sign-in until "Don't ask again" or a finished tour
    plumbing    every endpoint is open to all staff (and to no traveller); a look-only role still keeps favourites
"""
import re
from datetime import datetime, timedelta

from flask import g

from conftest import login, logout, make_user, same_team
from app import db as _db
from app.models import CrmView, StaffFavourite, User, WorkspaceRole
from app.routes.favourites import ENDPOINTS, my_bp
from app.services import access, crm_views, favourites, role_rights, tours


def as_user(client, user):
    logout(client)
    g.pop('_login_user', None)
    _db.session.expire_all()
    access._cache().clear()
    return login(client, user.email)


def give(ws, user, name, pages, rights=None):
    r = WorkspaceRole(workspace_id=ws.id, name=name, pages=sorted(pages), rights=rights)
    _db.session.add(r)
    _db.session.flush()
    access.add_member(ws, user, role=r)
    _db.session.commit()
    access._cache().clear()
    return r


def agent_with(profile, email, name):
    ws = access.ensure_defaults()
    u = make_user(email, name, role='cs')
    p = role_rights.PROFILE_BY_KEY[profile]
    give(ws, u, '%s %s' % (p['label'], name), role_rights.profile_pages(p),
         rights={'profile': profile, 'view': [], 'remove': True, 'mask': False})
    return u


def rail(html):
    return html.split('data-group="fav"', 1)[1].split('</div>\n    </div>', 1)[0]


# ============================================================================================ favourites

def test_the_star_keeps_a_screen_with_its_filters_once(app, client, admin_user):
    login(client, admin_user.email)
    r = client.post('/my/favourites/add', data={'next': '/admin/crm/inbox?who=mine&ch=whatsapp&page=3',
                                                'label': 'My WhatsApp chats'}, follow_redirects=True)
    assert 'Added “My WhatsApp chats” to your favourites' in r.get_data(as_text=True)
    f = StaffFavourite.query.one()
    assert f.endpoint == 'admin_crm.inbox' and f.params == {'who': 'mine', 'ch': 'whatsapp'}     # not the page number
    client.post('/my/favourites/add', data={'next': '/admin/crm/inbox?ch=whatsapp&who=mine', 'label': 'Again'})
    assert StaffFavourite.query.count() == 1                                                       # the same screen
    html = client.get('/admin/crm/inbox?who=mine&ch=whatsapp').get_data(as_text=True)
    assert 'My WhatsApp chats' in rail(html)                                                       # on the rail
    assert 'In your favourites as <b>My WhatsApp chats</b>' in html                                 # the star says so
    assert 'fa-solid fa-star' in html.split('id="favDD"', 1)[1][:600]


def test_only_a_screen_your_role_opens_can_be_a_favourite(app, client, admin_user):
    agent = agent_with('sales_agent', 'sa@test.com', 'sa')
    login(client, agent.email)
    for bad in ('https://evil.example/cs/crm/', '//evil.example/x', '/cs/crm/export/leads?owner=all',
                '/auth/logout', '/admin/health', '/no/such/page', '/my/favourites'):
        assert client.post('/my/favourites/add', data={'next': bad}).status_code == 302, bad
    assert StaffFavourite.query.count() == 0
    client.post('/my/favourites/add', data={'next': '/cs/crm/?owner=mine&status=open', 'label': 'Mine open'})
    assert StaffFavourite.query.one().endpoint == 'crm.board'


def test_rename_move_and_remove_are_your_own(app, client, admin_user):
    login(client, admin_user.email)
    for path, label in (('/admin/crm/inbox?who=mine', 'One'), ('/admin/crm/?status=won', 'Two'), ('/admin/health', 'Three')):
        client.post('/my/favourites/add', data={'next': path, 'label': label})
    one, two, three = StaffFavourite.query.order_by(StaffFavourite.position).all()
    client.post('/my/favourites/%d/move' % three.id, data={'dir': 'up'})
    client.post('/my/favourites/%d/rename' % one.id, data={'label': '  First   one '})
    html = client.get('/my/favourites').get_data(as_text=True).split('<main', 1)[1]
    assert html.index('First one') < html.index('Three') < html.index('Two')
    other = make_user('nosy@test.com', 'nosy', role='cs')
    as_user(client, other)
    r = client.post('/my/favourites/%d/remove' % one.id, follow_redirects=True)
    assert 'not yours' in r.get_data(as_text=True) and StaffFavourite.query.count() == 3
    as_user(client, admin_user)
    client.post('/my/favourites/%d/remove' % one.id)
    assert StaffFavourite.query.count() == 2


def test_a_favourite_of_a_page_the_role_lost_is_hidden_not_deleted(app, client):
    ws = access.ensure_defaults()
    u = make_user('loses@test.com', 'loses', role='cs')
    role = give(ws, u, 'Calendar and contacts', ['crm_calendar', 'crm_people'])
    login(client, u.email)
    client.post('/my/favourites/add', data={'next': '/cs/crm/contacts?wa=optout', 'label': 'Opted out'})
    assert 'Opted out' in rail(client.get('/cs/crm/calendar').get_data(as_text=True))
    role.pages = ['crm_calendar']
    _db.session.commit()
    access._cache().clear()
    with app.test_request_context():
        assert 'crm_people' not in access.pages_for(_db.session.get(User, u.id))
    assert 'Opted out' not in rail(client.get('/cs/crm/calendar').get_data(as_text=True))
    assert StaffFavourite.query.count() == 1


# ============================================================================================ views

def test_this_page_saves_its_filters_as_a_view_for_my_team_only(app, client, admin_user):
    ann = agent_with('sales_agent', 'ann@test.com', 'ann')
    ben = agent_with('sales_agent', 'ben@test.com', 'ben')
    cat = agent_with('sales_agent', 'cat@test.com', 'cat')
    team = same_team(ann, ben)
    same_team(cat, name='Team B')
    login(client, ann.email)
    html = client.get('/cs/crm/inbox?who=mine&ch=whatsapp').get_data(as_text=True)
    assert 'Save these filters as a view' in html and 'Me and my team: Team A' in html
    r = client.post('/my/views/save', data={'next': '/cs/crm/inbox?who=mine&ch=whatsapp', 'name': 'Our chats',
                                            'team': str(team.id), 'star': 'on'}, follow_redirects=True)
    assert 'Saved the view “Our chats” for you and Team A' in r.get_data(as_text=True)
    v = CrmView.query.one()
    assert (v.scope, v.endpoint, v.params, v.team_id, v.shared) == ('crm_inbox', 'crm.inbox',
                                                                    {'who': 'mine', 'ch': 'whatsapp'}, team.id, True)
    assert StaffFavourite.query.filter_by(user_id=ann.id, view_id=v.id).count() == 1            # "also star it"
    # Ben, in the team, finds it on the page and stars it; Cat, in another team, never sees it
    as_user(client, ben)
    html = client.get('/cs/crm/inbox').get_data(as_text=True)
    assert 'Our chats' in html.split('id="favDD"', 1)[1]
    client.post('/my/views/%d/star' % v.id, data={'next': '/cs/crm/inbox'})
    assert 'Our chats' in rail(client.get('/cs/crm/').get_data(as_text=True))
    as_user(client, cat)
    assert 'Our chats' not in client.get('/cs/crm/inbox').get_data(as_text=True)
    r = client.post('/my/views/%d/star' % v.id, data={'next': '/cs/crm/inbox'}, follow_redirects=True)
    assert 'not shared with you' in r.get_data(as_text=True)
    assert 'Our chats' not in client.get('/my/favourites').get_data(as_text=True)
    # only the owner changes it; deleting it takes the stars with it
    r = client.post('/my/views/%d/delete' % v.id, follow_redirects=True)
    assert 'not yours' in r.get_data(as_text=True)
    as_user(client, ann)
    client.post('/my/views/%d/delete' % v.id)
    assert CrmView.query.count() == 0 and StaffFavourite.query.count() == 0


def test_a_view_needs_filters_and_a_list_screen(app, client, admin_user):
    login(client, admin_user.email)
    html = client.get('/admin/crm/inbox').get_data(as_text=True)
    assert 'Set some filters on this page, then save them as a view' in html
    r = client.post('/my/views/save', data={'next': '/admin/crm/inbox', 'name': 'Nothing'}, follow_redirects=True)
    assert 'Choose at least one filter' in r.get_data(as_text=True)
    client.post('/my/views/save', data={'next': '/admin/crm/lead/1?x=1', 'name': 'One lead'})
    assert 'cannot be saved as a view' in client.get('/admin/crm/inbox').get_data(as_text=True)
    assert CrmView.query.count() == 0
    # Leads keeps its views in its own Views menu: the star points there
    html = client.get('/admin/crm/?status=open').get_data(as_text=True)
    assert 'Views of this page are in its own <b>Views</b> menu' in html


def test_the_leads_views_menu_shares_with_one_team_and_has_stars(app, client, admin_user):
    ann = agent_with('sales_agent', 'ann@test.com', 'ann')
    team = same_team(ann)
    login(client, ann.email)
    html = client.get('/cs/crm/').get_data(as_text=True)
    assert 'name="team"' in html.split('class="vw-menu"', 1)[1] and 'Share with the team' not in html
    client.post('/cs/crm/views/save', data={'scope': 'crm_leads', 'name': 'Hot ones', 'f_status': 'open',
                                            'team': str(team.id)})
    v = CrmView.query.one()
    assert v.team_id == team.id and v.shared
    html = client.get('/cs/crm/').get_data(as_text=True)
    assert 'action="/my/views/%d/star"' % v.id in html
    client.post('/cs/crm/views/%d/rename' % v.id, data={'scope': 'crm_leads', 'name': 'Hot ones', 'team': 'me'})
    _db.session.expire_all()
    assert _db.session.get(CrmView, v.id).team_id is None and not _db.session.get(CrmView, v.id).shared


def test_a_view_an_admin_saved_opens_in_an_agents_console(app, client, admin_user):
    ann = agent_with('sales_agent', 'ann@test.com', 'ann')
    same_team(admin_user, ann)
    login(client, admin_user.email)
    client.post('/my/views/save', data={'next': '/admin/crm/inbox?who=waiting', 'name': 'Waiting',
                                        'team': str(same_team(admin_user).id)})
    v = CrmView.query.one()
    as_user(client, ann)
    html = client.get('/cs/crm/inbox').get_data(as_text=True)
    assert re.search(r'href="/cs/crm/inbox\?who=waiting"[^>]*>Waiting<', html)


# ============================================================================================ tours

def test_each_role_gets_its_own_tour_and_the_common_ones(app, client, admin_user):
    agent = agent_with('sales_agent', 'sa@test.com', 'sa')
    login(client, agent.email)
    d = client.get('/my/tours').get_json()
    groups = {t['key']: t['group'] for t in d['tours']}
    assert d['profile'] == 'Sales agent' and d['recommended'] == 'sales_agent'
    assert groups['sales_agent'] == 'you'
    assert {k for k, gr in groups.items() if gr == 'common'} == {'basics', 'favourites', 'screens'}
    assert 'admin' not in groups and 'owner' not in groups and 'content_editor' not in groups
    for t in d['tours']:
        for s in t['steps']:
            assert s['url'] is None or s['url'].startswith('/'), s
    # the screens are only ones they may open
    urls = [p['url'] for a in d['screens'] for p in a['pages']]
    assert urls and all(u for u in urls) and not any(u.startswith('/admin/security') for u in urls)
    as_user(client, admin_user)
    d = client.get('/my/tours').get_json()
    groups = {t['key']: t['group'] for t in d['tours']}
    assert groups['admin'] == groups['owner'] == 'you'
    assert groups['sales_agent'] == groups['content_editor'] == 'more'


def test_profiles_come_from_the_role_else_from_its_pages(app):
    ws = access.ensure_defaults()
    writer = make_user('writer@test.com', 'writer', role='cs')
    give(ws, writer, 'Words', ['blog_list', 'blog'])                    # no profile stored: guessed from the pages
    lead = agent_with('team_lead', 'tl@test.com', 'tl')
    with app.test_request_context():
        assert tours.profiles(writer) == ['content_editor']
        assert tours.profiles(lead) == ['team_lead']


def test_every_step_names_a_real_page_and_every_tour_a_real_role():
    keys = set(role_rights.PROFILE_BY_KEY)
    for t in tours.TOURS:
        assert t['for'] == 'all' or set(t['for']) <= keys, t['key']
        for s in t['steps']:
            page = s['page']
            if page is None or page in tours.SPECIAL_PAGES:
                continue
            assert page.partition('>')[0] in access.PAGES, (t['key'], page)
            assert s['title'] and s['text'] and len(s['text']) < 260, (t['key'], s['title'])


def test_the_question_is_asked_once_a_sign_in_until_never_or_a_finished_tour(app, client):
    agent = agent_with('sales_agent', 'sa@test.com', 'sa')
    login(client, agent.email)
    assert 'data-ask="1"' in client.get('/cs/crm/').get_data(as_text=True)
    client.post('/my/tours/answer', json={'answer': 'shown'})
    assert 'data-ask="0"' in client.get('/cs/crm/').get_data(as_text=True)          # not again this sign-in
    u = _db.session.get(User, agent.id)
    u.last_login = datetime.utcnow() + timedelta(minutes=1)                          # signed in again since
    _db.session.commit()
    assert 'data-ask="1"' in client.get('/cs/crm/').get_data(as_text=True)
    client.post('/my/tours/answer', json={'answer': 'never'})
    u.last_login = datetime.utcnow() + timedelta(minutes=2)
    _db.session.commit()
    assert 'data-ask="0"' in client.get('/cs/crm/').get_data(as_text=True)
    client.post('/my/tours/answer', json={'answer': 'again'})
    assert 'data-ask="1"' in client.get('/cs/crm/').get_data(as_text=True)
    assert client.post('/my/tours/done', json={'key': 'nonsense'}).get_json()['ok'] is False
    assert client.post('/my/tours/done', json={'key': 'sales_agent'}).get_json()['ok'] is True
    assert 'data-ask="0"' in client.get('/cs/crm/').get_data(as_text=True)
    assert [t['done'] for t in client.get('/my/tours').get_json()['tours'] if t['key'] == 'sales_agent'] == [True]


def test_the_tour_guide_is_on_staff_pages_only(app, client, user, admin_user):
    login(client, admin_user.email)
    html = client.get('/admin/health').get_data(as_text=True)
    assert 'id="tgBtn"' in html and 'js/tour.js' in html and 'css/staff-tools.css' in html
    as_user(client, user)
    html = client.get('/').get_data(as_text=True)
    assert 'id="tgBtn"' not in html and 'id="favDD"' not in html


# ============================================================================================ plumbing

def test_every_endpoint_is_open_to_staff_and_closed_to_travellers(app, client, user):
    with app.test_request_context():
        mine = {r.endpoint for r in app.url_map.iter_rules() if r.endpoint.startswith(my_bp.name + '.')}
    assert mine == set(ENDPOINTS) and mine <= access.STAFF_ANY
    login(client, user.email)
    assert client.get('/my/favourites').status_code == 302
    assert client.get('/my/tours').status_code == 302


def test_a_look_only_role_still_keeps_favourites(app, client):
    ws = access.ensure_defaults()
    u = make_user('looker@test.com', 'looker', role='cs')
    give(ws, u, 'Looker', ['crm_board'], rights={'view': ['crm_board'], 'remove': True, 'mask': False})
    login(client, u.email)
    client.post('/my/favourites/add', data={'next': '/cs/crm/?status=open', 'label': 'Open ones'})
    assert StaffFavourite.query.count() == 1
    assert client.post('/my/tours/answer', json={'answer': 'later'}).get_json()['ok'] is True
