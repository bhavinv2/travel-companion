"""Team -> Menu builder: a workspace arranges its own staff menu.

    layout    sections, sub-menus, the order of lines, names, lines left off -- saved on the workspace
    roles     still decide who sees a line; the builder only decides where it sits
    whole     a saved layout never loses a line: one it does not place goes back where the code puts it
    way in    where a refused person lands follows the order in code, not the arranged menu
"""
import json

from conftest import login, logout
from app import db as _db
from app.models import Workspace
from app.services import access

BUILDER = '/admin/workspace/menu'


def custom():
    """The standard menu with: a Favourites section first holding Visual flow, Leads moved into Overview,
    My day renamed Today, Match quality left off and the Sales section renamed Sales."""
    lay = access.default_layout()
    for s in lay['sections']:
        for holder in s.get('subs') or [s]:
            for k in ('crm_flow', 'crm_board'):
                if k in holder['pages']:
                    holder['pages'].remove(k)
        if s['key'] == 'overview':
            s['pages'].append('crm_board')
        if s['key'] == 'sales':
            s['label'] = 'Sales'
    lay['sections'].insert(0, {'key': 'favourites', 'label': 'Favourites', 'icon': 'fa-star', 'pages': ['crm_flow']})
    lay['labels'] = {'crm_today': 'Today'}
    lay['hidden'] = ['metrics']
    return lay


def menu(client, path):
    html = client.get(path).data.decode()
    return html.split('admin-nav-items', 1)[1].split('</nav>', 1)[0]


# ============================================================================================ the layout

def test_the_standard_menu_is_the_one_in_code(app, admin_user):
    ws = access.ensure_defaults()
    assert ws.menu is None and access.menu_layout(ws) == access.default_layout()
    assert access.clean_layout(access.default_layout()) == access.default_layout()
    placed = [k for s in access.default_layout()['sections'] for h in (s.get('subs') or [s]) for k in h['pages']]
    assert sorted(placed) == sorted(access.MENU_PAGES) and len(placed) == len(set(placed))


def test_a_saved_layout_is_cleaned_and_never_loses_a_line():
    lay = {'sections': [
        {'key': 'Mine!', 'label': '  My   things ' + 'x' * 60, 'icon': 'javascript:alert(1)',
         'pages': ['crm_today', 'crm_today', 'made-up', 'crm_add']},
        {'key': 'mine', 'label': '', 'icon': 'fa-star', 'subs': [{'key': 'a', 'label': 'A', 'pages': ['wa_inbox']}]},
    ], 'labels': {'crm_today': 'Today', 'wa_inbox': 'WhatsApp chats', 'made-up': 'x'}, 'hidden': ['wa_inbox', 'nope']}
    out = access.clean_layout(lay)
    first, second = out['sections'][0], out['sections'][1]
    assert first['key'] == 'mine' and second['key'] == 'mine2'                   # keys made safe and unique
    assert first['label'].startswith('My things') and len(first['label']) == access.MENU_LABEL_MAX
    assert first['icon'] == 'fa-folder' and second['label'] == 'Menu'           # bad icon / empty name replaced
    assert first['pages'] == ['crm_today']                                       # no repeats, no unknown, no buttons
    assert second['subs'][0]['pages'] == ['wa_inbox']
    assert out['labels'] == {'crm_today': 'Today'}                               # a name equal to the usual one is dropped
    assert out['hidden'] == ['wa_inbox']
    placed = [k for s in out['sections'] for h in (s.get('subs') or [s]) for k in h['pages']]
    assert sorted(placed) == sorted(access.MENU_PAGES)                           # everything else came back
    sales = next(s for s in out['sections'] if s['key'] == 'sales')
    assert 'crm_board' in next(b for b in sales['subs'] if b['key'] == 'daily')['pages']
    assert access.clean_layout('nonsense') is None and access.clean_layout({'sections': 'x'}) is None


# ============================================================================================ the screen

def test_an_admin_arranges_the_menu_and_everybody_sees_it(client, app, admin_user, cs_user):
    ws = access.ensure_defaults()
    login(client, admin_user.email)
    page = client.get(BUILDER).data.decode()
    assert 'Menu builder' in page and 'id="mnu-data"' in page
    r = client.post(BUILDER + '/save', data={'layout': json.dumps(custom())})
    assert r.status_code == 302
    assert _db.session.get(Workspace, ws.id).menu is not None
    nav = menu(client, '/admin/crm/today')
    assert nav.index('data-group="favourites"') < nav.index('data-group="overview"')
    overview = nav.split('data-group="overview"', 1)[1].split('data-group=', 1)[0]
    assert 'data-title="Leads"' in overview and 'data-title="Match quality"' not in nav
    assert 'data-title="Today"' in nav and 'data-title="My day"' not in nav and '<span>Sales</span>' in nav
    assert client.get('/cs/metrics').status_code == 200                          # left off the menu, still opens
    logout(client)
    login(client, cs_user.email)                                                   # the agent: same layout, their lines
    nav = menu(client, '/cs/crm/today')
    assert 'data-title="Today"' in nav and 'data-group="favourites"' in nav and 'Pipelines' not in nav


def test_saving_the_standard_menu_keeps_following_the_code_and_reset_goes_back(client, app, admin_user):
    ws = access.ensure_defaults()
    login(client, admin_user.email)
    client.post(BUILDER + '/save', data={'layout': json.dumps(access.default_layout())})
    assert _db.session.get(Workspace, ws.id).menu is None
    client.post(BUILDER + '/save', data={'layout': json.dumps(custom())})
    assert _db.session.get(Workspace, ws.id).menu is not None
    client.post(BUILDER + '/reset')
    _db.session.expire_all()
    assert _db.session.get(Workspace, ws.id).menu is None
    client.post(BUILDER + '/save', data={'layout': 'not json'})
    _db.session.expire_all()
    assert _db.session.get(Workspace, ws.id).menu is None                        # nothing changed


def test_the_preview_shows_one_roles_menu(client, app, admin_user):
    ws = access.ensure_defaults()
    login(client, admin_user.email)
    cs_role = access.system_role(ws, 'cs')
    out = client.post(BUILDER + '/preview', json={'layout': custom(), 'role': cs_role.id}).get_json()
    labels = [i['label'] for g in out['groups'] for i in g['items']]
    assert out['groups'][0]['label'] == 'Favourites' and 'Today' in labels
    assert 'Pipelines' not in labels and 'Menu builder' not in labels           # not the agent's
    admin = client.post(BUILDER + '/preview', json={'layout': None, 'role': access.system_role(ws, 'admin').id}).get_json()
    assert 'Pipelines' in [i['label'] for g in admin['groups'] for i in g['items']]


def test_only_people_whose_role_has_it_arrange_the_menu(client, app, admin_user, cs_user):
    ws = access.ensure_defaults()
    login(client, cs_user.email)
    assert client.get(BUILDER).status_code == 302
    client.post(BUILDER + '/save', data={'layout': json.dumps(custom())})
    assert _db.session.get(Workspace, ws.id).menu is None
    assert client.post(BUILDER + '/preview', json={}).status_code in (302, 403)


def test_where_a_refused_person_lands_does_not_follow_the_arranged_menu(client, app, admin_user, cs_user):
    ws = access.ensure_defaults()
    ws.menu = access.clean_layout(custom())                       # Visual flow first in the arranged menu
    _db.session.commit()
    login(client, cs_user.email)
    assert client.get('/cs/crm/insights').headers['Location'].endswith('/cs/crm/today')
