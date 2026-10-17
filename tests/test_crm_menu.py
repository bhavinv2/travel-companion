"""U2: one menu, one home for every function.

Every page sits in exactly one section; the menu follows the area switches; old role page keys
still work; the data revision rewrites stored roles; and (release 1 must stand alone) no menu line
points at a page that is not there.
"""
import importlib.util
import json
import os
import re

import pytest
import sqlalchemy as sa

from conftest import login, make_user
from app import db as _db
from app.models import Workspace, WorkspaceMember, WorkspaceRole
from app.services import access

SECTION_ORDER = ['overview', 'sales', 'companion', 'insurance', 'sahayak', 'team', 'site', 'help']
SALES_SUBS = ['daily', 'messaging', 'automatic', 'setup']


def labels(groups):
    return {g['label']: [i['label'] for i in g['items']] for g in groups}


def the_menu(client, email, path='/admin/crm/today'):
    login(client, email)
    return client.get(path).get_data(as_text=True)


# ------------------------------------------------------------------ the structure

def test_every_page_is_in_exactly_one_section_in_the_agreed_order():
    assert [s['key'] for s in access.SECTIONS] == SECTION_ORDER
    listed = [k for s in access.SECTIONS for k in s['pages']]
    assert len(listed) == len(set(listed)) and set(listed) == set(access.PAGES)
    assert all(access.PAGES[k]['section'] == s['key'] for s in access.SECTIONS for k in s['pages'])
    sales = next(s for s in access.SECTIONS if s['key'] == 'sales')
    assert [sub['key'] for sub in sales['subs']] == SALES_SUBS
    for s in access.SECTIONS:
        if 'subs' in s:                    # a sub-menu's pages are its section's pages, in order, once each
            assert s['pages'] == tuple(k for sub in s['subs'] for k in sub['pages'])


def test_every_dashboard_and_report_is_in_overview():
    for key in ('dashboard', 'crm_insights', 'crm_tracker', 'metrics'):
        assert access.PAGES[key]['section'] == 'overview', key
    assert access.PAGES['wa_flows']['sub'] == 'automatic'


def test_help_holds_the_read_only_screens_that_explain_the_work():
    help_ = next(s for s in access.SECTIONS if s['key'] == 'help')
    assert help_['pages'] == ('crm_flow', 'crm_process', 'crm_auto')
    assert all('sub' not in access.PAGES[k] for k in help_['pages'])


def test_the_old_page_keys_are_gone_and_the_new_ones_exist():
    for gone in ('wa_overview', 'wa_quick', 'wa_contacts'):
        assert gone not in access.PAGES
    for new in ('crm_people', 'crm_quick', 'wa_tags', 'crm_pipelines', 'crm_sources', 'crm_connection', 'crm_data',
                'crm_export', 'crm_tracker', 'crm_insights', 'ws_roles', 'ws_all'):
        assert new in access.PAGES, new
    assert access.PAGES['crm_export']['nav'] is False and access.PAGES['crm_add']['nav'] is False
    assert access.PAGES['ws_all']['nav'] is False


def test_the_area_labels_and_the_wording_of_the_main_lines():
    mods = {m['key']: m for m in access.MODULES}
    assert mods['crm']['label'] == 'Sales' and mods['whatsapp']['label'] == 'WhatsApp messaging'
    assert mods['crm']['desc'] == 'Leads, follow-ups, contacts, quick replies, the half-hourly check, reports and set-up.'
    want = {'crm_today': 'My day', 'wa_inbox': 'WhatsApp chats', 'crm_board': 'Leads', 'crm_people': 'Contacts',
            'crm_checks': 'Half-hourly check', 'crm_process': 'How we sell', 'crm_quick': 'Quick replies',
            'wa_templates': 'WhatsApp templates', 'wa_broadcasts': 'Broadcasts', 'wa_tags': 'Tags',
            'wa_automations': 'Reply rules', 'wa_flows': 'Chatbot', 'wa_ai': 'AI replies', 'crm_tracker': 'Team today',
            'crm_insights': 'Sales results', 'crm_pipelines': 'Pipelines', 'crm_sources': 'Where leads come from',
            'crm_connection': 'WhatsApp connection', 'wa_settings': 'WhatsApp number',
            'ws_members': 'Team members', 'ws_roles': 'Roles', 'ws_settings': 'Workspace',
            'dashboard': 'Site dashboard', 'home': 'Service to-do', 'metrics': 'Match quality',
            'messages': 'Trip post texts & e-mails', 'crm_add': 'Add a lead'}
    for key, label in want.items():
        assert access.PAGES[key]['label'] == label, key
    assert access.PAGES['metrics']['module'] == 'companion' and access.PAGES['metrics']['section'] == 'overview'
    assert access.PAGES['wa_tags']['module'] == 'whatsapp'


def test_old_role_page_keys_are_read_as_the_pages_they_became():
    assert access.expand_page_keys(['wa_contacts', 'wa_quick', 'wa_overview']) == {'crm_people', 'crm_quick'}
    assert access.expand_page_keys(['crm_setup']) == {'crm_pipelines', 'crm_sources', 'crm_connection', 'crm_data',
                                                      'crm_export'}
    assert 'wa_tags' in access.expand_page_keys(['wa_settings'])                   # Tags came with the number
    assert 'wa_tags' not in access.expand_page_keys(['wa_settings', 'crm_people'])   # a list already on the new keys
    assert access.expand_page_keys(['made-up', 'crm_today']) == {'crm_today'}
    assert access.expand_page_keys(None) == frozenset()


def test_a_stored_role_with_old_keys_still_opens_the_right_pages(app):
    ws = access.ensure_defaults()
    r = WorkspaceRole(workspace_id=ws.id, name='Old', pages=['home', 'wa_contacts', 'crm_setup'])
    _db.session.add(r)
    _db.session.commit()
    assert {'crm_people', 'crm_pipelines', 'crm_connection', 'home'} <= access.role_pages(r)
    assert access.role_pages(access.system_role(ws, 'admin')) == access.ALL_PAGES


def test_built_in_roles(app):
    assert access.CS_ROLE_PAGES == access.CS_DEFAULT_PAGES | {'wa_inbox', 'crm_people', 'crm_quick'}
    ws = access.ensure_defaults()
    roles = {r.name: r for r in WorkspaceRole.query.filter_by(workspace_id=ws.id)}
    assert 'Sales & service' in roles and 'Administrator' in roles and 'Customer service' not in roles
    if 'Team lead' in roles:
        lead = access.role_pages(roles['Team lead'])
        assert lead >= access.role_pages(roles['Sales & service']) | {'crm_tracker', 'crm_insights', 'wa_broadcasts'}
        assert 'crm_pipelines' not in lead and 'ws_roles' not in lead


# ------------------------------------------------------------------ what each person sees

def test_an_agent_sees_the_days_work_and_nothing_to_manage(app, cs_user):
    flat = [l for ls in labels(_nav_for(app, cs_user)).values() for l in ls]
    for line in ('My day', 'Leads', 'Half-hourly check', 'How we sell'):
        assert line in flat, line
    for line in ('Team today', 'Sales results', 'Where leads come from', 'Pipelines', 'WhatsApp connection', 'Roles',
                 'Team members', 'Tags', 'Broadcasts'):
        assert line not in flat, line


def test_one_sub_menu_is_shown_as_plain_lines(app, cs_user):
    """An agent's Sales CRM is only Daily work: a "Daily work" heading over all of it would be one click too many."""
    sales = next(g for g in _nav_for(app, cs_user) if g['key'] == 'sales')
    assert sales['subs'] == [] and 'My day' in [i['label'] for i in sales['items']]
    help_ = next(g for g in _nav_for(app, cs_user) if g['key'] == 'help')
    assert [i['label'] for i in help_['items']] == ['Visual flow', 'How we sell']      # What goes out: admins


def _nav_for(app, user):
    with app.test_request_context('/cs/crm/today'):
        from flask_login import login_user
        login_user(user)
        return access.nav(user)


def test_the_administrator_sees_every_section_in_order(app, admin_user):
    groups = _nav_for(app, admin_user)
    keys = [g['key'] for g in groups]
    assert keys == [k for k in SECTION_ORDER if k in keys]
    for k in ('overview', 'sales', 'team'):
        assert k in keys, k
    sales = next(g for g in groups if g['key'] == 'sales')
    assert [s['key'] for s in sales['subs']] == ['sales.' + k for k in SALES_SUBS]
    assert [i['label'] for i in sales['subs'][0]['items']][:2] == ['My day', 'WhatsApp chats']
    help_ = next(g for g in groups if g['key'] == 'help')
    assert [i['label'] for i in help_['items']] == ['Visual flow', 'How we sell', 'What goes out by itself']
    overview = [i['label'] for i in next(g for g in groups if g['key'] == 'overview')['items']]
    assert {'Site dashboard', 'Sales results', 'Team today', 'Match quality'} <= set(overview)
    flat = [l for ls in labels(groups).values() for l in ls]
    for line in ('Dashboard', 'Queues', 'Promotion'):
        assert line not in flat
    for line in ('Site dashboard', 'My day', 'Leads', 'Tags', 'Reply rules', 'Chatbot', 'AI replies', 'Team today',
                 'Sales results', 'Pipelines', 'Where leads come from', 'WhatsApp connection', 'WhatsApp number',
                 'Team members', 'Teams', 'Roles', 'Workspace'):
        assert line in flat, line
    # lines with no menu entry: reachable from the page that needs them
    # Contacts is on the menu from U7 (the portal's own page)
    assert 'Contacts' in flat
    for hidden in ('Add a lead', 'Download lists of leads and contacts', 'Auto', 'All workspaces'):
        assert hidden not in flat, hidden


def test_switching_an_area_off_removes_its_lines(app, admin_user):
    ws = access.ensure_defaults()
    ws.modules = ['console']
    _db.session.commit()
    access._cache().clear()
    flat = [l for ls in labels(_nav_for(app, admin_user)).values() for l in ls]
    assert 'My day' not in flat and 'Pipelines' not in flat and 'Chatbot' not in flat


def test_where_each_person_lands(app, client, cs_user, admin_user):
    with app.test_request_context('/'):
        assert access.home_url(cs_user).endswith('/crm/today')            # staff who work leads: My day
        assert access.home_url(admin_user).endswith('/admin/crm/insights')  # the site owner: Results
    ws = access.ensure_defaults()
    ws.modules = ['console']
    _db.session.commit()
    access._cache().clear()
    with app.test_request_context('/'):
        assert access.home_url(admin_user) == '/admin/'          # Sales is off: the site dashboard


def test_the_promotion_link_is_not_in_the_site_owners_menu(app, client, admin_user):
    html = the_menu(client, admin_user.email)
    side = html.split('Admin Panel', 1)[1] if 'Admin Panel' in html else html
    assert 'Promotion' not in re.sub(r'<[^>]+>', ' ', side.split('<main', 1)[0]).replace('Promotion dashboard', '')


# ------------------------------------------------------------------ release 1 stands alone

def test_every_menu_line_opens_something(app, client, admin_user):
    """No line may point at a page that is not built yet (release 2 pages stay hidden)."""
    login(client, admin_user.email)
    seen = []
    for g in _nav_for_client(client):
        for i in g['items']:
            r = client.get(i['url'])
            assert r.status_code < 400, '%s (%s) answered %s' % (i['label'], i['url'], r.status_code)
            seen.append(i['label'])
    assert 'My day' in seen and 'Leads' in seen and 'Pipelines' in seen and len(seen) > 20


def _nav_for_client(client):
    html = client.get('/admin/crm/today').get_data(as_text=True)
    items = []
    start = html.split('admin-nav-items', 1)[1] if 'admin-nav-items' in html else html
    links = []
    for tag in re.findall(r'<a [^>]*>', start.split('</nav>', 1)[0]):
        href = re.search(r'href="(/[^"#]*)"', tag)
        title = re.search(r'data-title="([^"]*)"', tag)
        if href:
            links.append((href.group(1), title.group(1) if title else ''))
    seen = set()
    for u, t in links:
        if u in seen:
            continue
        seen.add(u)
        items.append({'label': t or u, 'url': u})
    return [{'items': items}]


def test_release_two_pages_are_not_offered_yet(app, client, admin_user):
    html = the_menu(client, admin_user.email)
    text = re.sub(r'<[^>]+>', ' ', html)
    for later in ('Automatic follow-ups', 'Pipeline builder'):
        assert later not in text, later
    assert 'crm_auto' in access.PAGES      # U8 built the page, so it is no longer reserved


def test_the_old_setup_links_still_land_on_the_right_page(app, client, admin_user):
    login(client, admin_user.email)
    for old, new in (('sources', '/sources'), ('pipelines', '/pipelines'), ('answers', '/quick-replies'),
                     ('connect', '/connection'), ('import', '/data')):
        r = client.get('/admin/crm/setup?tab=%s' % old)
        assert r.status_code == 302 and new in r.headers['Location'], old


def test_every_set_up_page_draws(app, client, admin_user):
    """Includes the WhatsApp connection page: it once failed with 'multiple values for keyword argument wa_mode'."""
    login(client, admin_user.email)
    for url in ('/admin/crm/pipelines', '/admin/crm/sources', '/admin/crm/quick-replies', '/admin/crm/connection',
                '/admin/crm/data', '/admin/crm/insights', '/admin/crm/tracker', '/admin/crm/process',
                '/admin/crm/checks', '/admin/crm/add', '/admin/crm/today', '/admin/crm/'):
        r = client.get(url)
        assert r.status_code == 200, '%s answered %s' % (url, r.status_code)


def test_the_connection_page_switches_the_mode_and_shows_its_words(app, client, admin_user):
    login(client, admin_user.email)
    r = client.post('/admin/crm/setup/whatsapp', data={'action': 'mode', 'mode': 'contacts'}, follow_redirects=True)
    assert r.status_code == 200 and 'Saved: Keep contacts in step.' in r.get_data(as_text=True)


# ------------------------------------------------------------------ the data revision

def _load(name):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations', 'versions', name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_one_menu_revision_rewrites_roles_and_reverses(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    mod = _load('s2crm006_one_menu.py')
    engine = sa.create_engine('sqlite:///' + str(tmp_path / 'm.db').replace(os.sep, '/'))
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE workspace_roles (id INTEGER PRIMARY KEY, workspace_id INTEGER, name VARCHAR, '
                             'description VARCHAR, pages JSON, system_key VARCHAR, created_at DATETIME)')
        ins = ("INSERT INTO workspace_roles (workspace_id, name, pages, system_key) VALUES (?, ?, ?, ?)")
        conn.exec_driver_sql(ins, (1, 'Customer service', json.dumps(['home', 'wa_inbox', 'wa_contacts', 'wa_quick', 'wa_overview']), 'cs'))
        conn.exec_driver_sql(ins, (1, 'Admins', json.dumps(['crm_setup', 'wa_settings']), None))
        conn.exec_driver_sql(ins, (2, 'Customer service', json.dumps(['home']), 'cs'))
        conn.exec_driver_sql(ins, (2, 'Sales & service', json.dumps(['home']), None))     # name already taken there
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()
        rows = {(r[0], r[1]): json.loads(r[2]) for r in conn.exec_driver_sql('SELECT workspace_id, name, pages FROM workspace_roles')}
        assert rows[(1, 'Sales & service')] == ['home', 'wa_inbox', 'crm_people', 'crm_quick']
        assert rows[(1, 'Admins')] == ['crm_pipelines', 'crm_sources', 'crm_connection', 'crm_data', 'crm_export',
                                       'wa_settings', 'wa_tags']
        assert (2, 'Customer service') in rows and (2, 'Sales & service') in rows         # never a duplicate name
        for ws in (1, 2):
            assert (ws, 'Team lead') in rows and {'crm_tracker', 'crm_insights', 'wa_broadcasts'} <= set(rows[(ws, 'Team lead')])
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()                                                              # twice: nothing doubles
        assert conn.exec_driver_sql("SELECT count(*) FROM workspace_roles WHERE name = 'Team lead'").scalar() == 2
        with Operations.context(MigrationContext.configure(conn)):
            mod.downgrade()
        back = {(r[0], r[1]): json.loads(r[2]) for r in conn.exec_driver_sql('SELECT workspace_id, name, pages FROM workspace_roles')}
        assert (1, 'Customer service') in back and back[(1, 'Customer service')][:2] == ['home', 'wa_inbox']
        assert 'wa_contacts' in back[(1, 'Customer service')] and 'wa_quick' in back[(1, 'Customer service')]


def test_there_is_one_alembic_head_and_the_chain_is_unbroken():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    mig = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations')
    cfg = Config()
    cfg.set_main_option('script_location', mig)
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1
    chain = [r.revision for r in script.walk_revisions()]
    for rev in ('s1crm005', 's2crm006', 's3crm007', 's4crm008'):
        assert rev in chain
    assert script.get_revision('s4crm008').down_revision == 's3crm007'
    assert script.get_revision('s3crm007').down_revision == 's2crm006'


def test_the_lead_page_and_daily_work_revisions_add_their_columns_and_reverse(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine = sa.create_engine('sqlite:///' + str(tmp_path / 'm.db').replace(os.sep, '/'))
    m3, m4 = _load('s3crm007_lead_page.py'), _load('s4crm008_daily_work.py')
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE crm_people (id INTEGER PRIMARY KEY)')
        conn.exec_driver_sql('CREATE TABLE crm_touchpoints (id INTEGER PRIMARY KEY, body VARCHAR)')
        conn.exec_driver_sql('CREATE TABLE crm_leads (id INTEGER PRIMARY KEY)')
        conn.exec_driver_sql('INSERT INTO crm_people (id) VALUES (1)')
        conn.exec_driver_sql("INSERT INTO crm_touchpoints (body) VALUES ('hello')")
        for mod in (m3, m4):
            with Operations.context(MigrationContext.configure(conn)):
                mod.upgrade()
        cols = lambda t: {c['name'] for c in sa.inspect(conn).get_columns(t)}
        assert {'wa_history_at', 'wa_opt_in_due'} <= cols('crm_people') and 'fail_reason' in cols('crm_touchpoints')
        assert {'snoozed_until', 'waiting_alerted_at'} <= cols('crm_leads') and 'via' in cols('crm_touchpoints')
        for mod in (m4, m3):
            with Operations.context(MigrationContext.configure(conn)):
                mod.downgrade()
        assert not {'wa_history_at', 'wa_opt_in_due'} & cols('crm_people')
        assert not {'fail_reason', 'via'} & cols('crm_touchpoints') and not {'snoozed_until'} & cols('crm_leads')
        assert conn.exec_driver_sql('SELECT body FROM crm_touchpoints').scalar() == 'hello'


def test_no_menu_line_frames_a_page_the_whatsapp_crm_retires(app):
    """F1/G3: the WhatsApp CRM retires /contacts inside the portal, so a menu line framing it would bounce
    every click to Leads. Contacts is the portal's own page from U7: on the menu, native."""
    page = access.PAGES['crm_people']
    assert page['nav'] is True
    assert page['links'] == {'admin': 'admin_crm.contacts', 'cs': 'crm.contacts'}
    assert 'crm_people' in access.PAGES
    assert 'crm_people' in access.CS_ROLE_PAGES
    for key, p in access.PAGES.items():
        if p['nav'] and (p['links'].get('admin') == 'messaging.contacts' or p['links'].get('cs') == 'messaging.contacts'):
            raise AssertionError('%s frames the retired Contacts screen' % key)
