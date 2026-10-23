"""Overview › Health, and the menu around it (2026-10-24).

    Health        the master screen (services/health.py): what needs somebody now, worst first; one part per
                  product -- open leads, not given to anyone, customers waiting, late follow-ups, leads a day,
                  where they came from, how they came, by stage and by owner; users and new accounts a day;
                  Travel Companion, Travel Insurance, Sahayak, Service to-do, System. Site owners land on it.
    Reports       a menu of its own, by product: Sales results (Forecast behind a switch at the top right),
                  Team today (Team analysis behind the same switch), Report builder; the Site dashboard
    Help          a menu of its own: the Screen guide (every screen, by product, from access.py), How we sell,
                  Match quality and the three Help & FAQ pages
"""
import re
from datetime import datetime, timedelta

from conftest import login, make_user
from app import db as _db
from app.models import CompanionRequest, CrmTask, SahayakBooking, WorkspaceRole
from app.services import access, crm, health

from test_crm_wa_sync_engine import ti_lead


def words(html):
    return ' '.join(re.sub(r'<[^>]+>', ' ', html).split())


def nav_of(html):
    """The staff menu's text, section by section."""
    return words(html.split('admin-nav-items', 1)[1].split('</nav>', 1)[0]) if 'admin-nav-items' in html else ''


def switch_of(html):
    m = re.search(r'<nav class="seg ui-switch"[^>]*>(.*?)</nav>', html, re.S)
    return re.findall(r'>([^<]+)</a>', m.group(1)) if m else []


# ================================================================================================ Health

def test_a_site_owner_lands_on_health_and_it_says_what_needs_somebody(app, client, admin_user, cs_user):
    access.ensure_defaults()
    a = ti_lead()                                         # nothing set on the source: nobody has it
    b = ti_lead(phone='+919876500002', name='Sita Rao')
    b.owner_id = cs_user.id
    crm.log_touch(b, 'whatsapp', 'in', body='Hello, any update?', status='received')
    _db.session.add(CrmTask(lead_id=b.id, title='Call back', kind='call', status='open', owner_id=cs_user.id,
                            due_at=datetime.utcnow() - timedelta(hours=3)))
    _db.session.add(SahayakBooking(service_key='nurse', service_name='Nurse visit', patient_name='Lakshmi',
                                   phone='+919800000000', address='Hyderabad', status='new',
                                   created_at=datetime.utcnow() - timedelta(days=2)))
    _db.session.commit()
    assert a.owner_id is None
    login(client, admin_user.email)
    assert access.home_url(admin_user).endswith('/admin/health')
    r = client.get('/admin/health')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    text = words(html)
    assert 'Health' in text and 'things need somebody' in text
    late = CrmTask.query.filter(CrmTask.status == 'open', CrmTask.due_at <= datetime.utcnow()).count()
    assert late == 3                                     # each lead's first step, due now, and the call back
    for want in ('1 open lead not given to anyone', '1 customer waiting for a reply', '3 follow-ups late',
                 '1 Sahayak request waiting for somebody (the oldest 2 days)'):
        assert want in text, (want, re.findall(r'hl-what">([^<]*)', html))
    # the urgent ones first: a customer waiting and a request a day old are red, before the amber
    first = html.index('hl-list')
    assert html.index('customer waiting', first) < html.index('follow-ups late', first)
    # every part, and the leads' spread
    for part in ('Sales CRM', 'Users &amp; team', 'Travel Companion', 'Travel Insurance', 'Sahayak', 'Service to-do', 'System'):
        assert 'hl-' in html and part in html, part
    for box in ('New leads a day', 'Where they came from', 'How they came', 'Product', 'Open leads by stage',
                'Who has the open leads', 'New accounts a day'):
        assert box in text, box
    assert 'owner=none' in html                          # "Not given to anyone" opens exactly those leads
    assert 'Not given to anyone' in text and 'Organic' in text
    assert client.get('/admin/health?days=7').status_code == 200
    assert 'New in 7 days' in words(client.get('/admin/health?days=7').get_data(as_text=True))


def test_health_with_nothing_waiting_says_all_good(app, client, admin_user, monkeypatch):
    from app.services import crm_reports
    monkeypatch.setattr(crm_reports, 'current_slot_done', lambda channels: True)     # whatever the time of day
    access.ensure_defaults()
    login(client, admin_user.email)
    assert health.build(admin_user, 30)['attention'] == []
    text = words(client.get('/admin/health').get_data(as_text=True))
    assert 'All good: nothing is waiting' in text and 'every open lead has somebody' in text


def test_a_column_a_day_counts_india_days(app):
    class R:
        days = 3
        today = datetime(2026, 10, 24).date()
    # 20:00 UTC on the 23rd is 01:30 on the 24th in India
    c = health.columns([datetime(2026, 10, 23, 20, 0), datetime(2026, 10, 23, 10, 0), datetime(2026, 10, 22, 9, 0)], R)
    assert [p['n'] for p in c['points']] == [1, 1, 1] and c['total'] == 3 and c['top'] == 4
    assert c['first'] == 'Thu 22 Oct' and c['last'] == 'Sat 24 Oct'


def test_health_is_a_page_roles_give(app, client):
    ws = access.ensure_defaults()
    u = make_user('agent@test.com', 'agent', role='cs')
    access.add_member(ws, u, role=access.system_role(ws, 'cs'))
    access._cache().clear()
    login(client, u.email)
    assert client.get('/admin/health').status_code == 302             # Sales & service does not include it
    role = WorkspaceRole(workspace_id=ws.id, name='Owner view', pages=['health', 'crm_board'])
    _db.session.add(role)
    _db.session.commit()
    access.add_member(ws, u, role=role)
    access._cache().clear()
    html = client.get('/admin/health').get_data(as_text=True)
    assert 'Sales CRM' in html and 'id="hl-sahayak"' not in html     # only the parts they have screens in


# ================================================================================================ the menu

def test_reports_and_help_are_menus_of_their_own(app, client, admin_user):
    access.ensure_defaults()
    login(client, admin_user.email)
    groups = {g['key']: g for g in access.nav(admin_user)}
    assert list(groups)[:2] == ['overview', 'reports'] and list(groups)[-3:] == ['help', 'team', 'site']
    assert [i['label'] for i in groups['overview']['items']][0] == 'Health'
    assert [s['label'] for s in groups['reports']['subs']] == ['Sales CRM', 'Whole site']
    assert [i['label'] for i in groups['reports']['items']] == ['Sales results', 'Team today', 'Report builder',
                                                                'Site dashboard']
    assert [s['label'] for s in groups['help']['subs']] == ['Every screen', 'Sales CRM', 'Travel Companion',
                                                            'Travel Insurance', 'Sahayak']
    assert [i['label'] for i in groups['help']['items']] == ['Screen guide', 'How we sell', 'Match quality',
                                                             'Help & FAQ', 'Help & FAQ', 'Help & FAQ']
    # nothing informative is left in the products' own menus
    for key in ('companion', 'insurance', 'sahayak'):
        assert 'Help & FAQ' not in [i['label'] for i in groups[key]['items']], key
    r = client.get('/admin/reports')                    # an old "All reports" link: the first report
    assert r.status_code == 302 and r.headers['Location'].endswith('/admin/crm/insights')


def test_results_and_forecast_swap_at_the_top_right_and_so_do_team_today_and_analysis(app, client, admin_user):
    access.ensure_defaults()
    login(client, admin_user.email)
    for path in ('/admin/crm/insights', '/admin/crm/forecast'):
        html = client.get(path).get_data(as_text=True)
        assert switch_of(html) == ['Sales results', 'Forecast'], path
        assert 'class="subtabs"' not in html
    for path in ('/admin/crm/tracker', '/admin/crm/analysis'):
        assert switch_of(client.get(path).get_data(as_text=True)) == ['Team today', 'Team analysis'], path
    # the switch lights the one line it belongs to
    html = client.get('/admin/crm/forecast').get_data(as_text=True)
    assert re.search(r'class="[^"]*active[^"]*"[^>]*>\s*<i[^>]*></i>\s*<span[^>]*>Sales results', html) or \
        'aria-current="page">Forecast' in html
    assert switch_of(client.get('/admin/crm/reports/build').get_data(as_text=True)) == []


def test_somebody_with_only_team_today_gets_no_forecast_switch(app, client):
    ws = access.ensure_defaults()
    u = make_user('lead@test.com', 'teamlead', role='cs')
    role = WorkspaceRole(workspace_id=ws.id, name='Tracker only', pages=['crm_today', 'crm_board', 'crm_tracker'])
    _db.session.add(role)
    _db.session.commit()
    access.add_member(ws, u, role=role)
    access._cache().clear()
    login(client, u.email)
    r = client.get('/cs/reports')
    assert r.status_code == 302 and r.headers['Location'].endswith('/crm/tracker')
    page = client.get('/cs/crm/tracker', follow_redirects=True).get_data(as_text=True)
    assert switch_of(page) == ['Team today', 'Team analysis'] and 'Report builder' not in nav_of(page)


# ================================================================================================ Screen guide

def test_the_screen_guide_lists_every_screen_by_product(app, client, admin_user):
    access.ensure_defaults()
    login(client, admin_user.email)
    html = client.get('/admin/help/screens').get_data(as_text=True)
    text = words(html)
    for area in ('Sales', 'Travel Companion', 'Travel Insurance', 'Sahayak', 'WhatsApp messaging', 'Site settings'):
        assert 'id="sg-' in html and area in text, area
    for screen, where in (('Forecast', 'Reports › Sales CRM › Sales results (switch at the top right)'),
                          ('Match quality', 'Help › Travel Companion'), ('Bookings', 'Sahayak'),
                          ('Quote leads', 'Travel Insurance'), ('Health', 'Overview')):
        assert screen in text and where in text, screen
    assert 'Screen guide' not in re.findall(r'<h3>([^<]+)', html)            # it does not list itself
    guide = access.screen_guide(admin_user)
    pages = [p for a in guide for p in a['pages']]
    assert all(p['says'] for p in pages) and all(p['url'] for p in pages if p['key'] != 'scraper')


def test_the_screen_guide_comes_with_any_page_and_opens_only_yours(app, client):
    ws = access.ensure_defaults()
    u = make_user('agent@test.com', 'agent', role='cs')
    access.add_member(ws, u, role=access.system_role(ws, 'cs'))
    access._cache().clear()
    login(client, u.email)
    assert access.can(u, 'guide')
    html = client.get('/admin/help/screens').get_data(as_text=True)
    assert html.count('class="sg-item"') >= 5 and 'sg-item off' in html     # Users, say, is not theirs
    assert 'href="/admin/users"' not in html
