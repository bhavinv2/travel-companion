"""Overview › Health, and the menu around it (2026-10-24).

    Health        the master screen (services/health.py): what needs somebody now, worst first; one part per
                  product -- open leads, not given to anyone, customers waiting, late follow-ups, leads a day,
                  where they came from, how they came, by stage and by owner; users and new accounts a day;
                  Travel Companion, Travel Insurance, Sahayak, Service to-do, System. Site owners land on it.
    Reports       a menu of its own, by product: Sales results (Forecast behind a switch at the top right),
                  Team today (Team analysis behind the same switch), Report builder; the Site dashboard
    Help          one line, the Help centre: each product's help (How we sell, Match quality, the three Help & FAQ
                  pages), then every screen by product, from access.py -- a role decides what opens there
    Downloads     every sales download in one place (Reports › Downloads)
    Check         the Half-hourly check is a menu line again, with big tiles for this half hour
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
                                                                'Downloads', 'Site dashboard']
    assert groups['help']['subs'] == [] and [i['label'] for i in groups['help']['items']] == ['Help centre']
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
                          ('Match quality', 'Help › Help centre'), ('Bookings', 'Sahayak'),
                          ('Quote leads', 'Travel Insurance'), ('Health', 'Overview')):
        assert screen in text and where in text, screen
    assert 'Help centre' not in re.findall(r'<h3>([^<]+)', html)             # it does not list itself
    # each product's help on top: How we sell, Match quality, the three Help & FAQ pages
    top = html.split('id="sg-all"', 1)[0]
    for want in ('Help by product', 'How we sell', 'Match quality', 'href="/admin/help"', 'site=insurance', 'site=sahayak'):
        assert want in top, want
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


# ================================================================================================ Downloads

def test_downloads_gathers_every_sales_download(app, client, admin_user):
    from app.services import crm_report_builder as rb
    access.ensure_defaults()
    crm.ensure_defaults()
    rb.create(admin_user, 'Leads by source', rb.clean_config({'what': 'leads', 'group': 'source'}))
    login(client, admin_user.email)
    html = client.get('/admin/crm/downloads').get_data(as_text=True)
    for want in ('/admin/crm/insights.csv?days=7', '/admin/crm/insights.csv?days=90', 'insights-people.csv?days=30',
                 'forecast.csv', 'forecast.csv?span=quarter', 'format=csv', 'owner=none', 'export/contacts',
                 'Leads by source', '/reports/build.csv?'):
        assert want in html, want
    r = client.get('/admin/crm/insights.csv?days=7')
    assert r.status_code == 200 and r.headers['Content-Type'].startswith('text/csv')
    assert 'Downloads' in nav_of(client.get('/admin/crm/insights').get_data(as_text=True))


def test_downloads_is_for_whoever_may_download(app, client, cs_user):
    access.ensure_defaults()
    login(client, cs_user.email)
    assert client.get('/cs/crm/downloads').status_code == 302          # Sales & service does not download


# ================================================================================================ the check

def test_the_half_hourly_check_has_a_big_tile_per_inbox(app, client, cs_user, monkeypatch):
    from app.services import crm_reports
    monkeypatch.setattr(crm_reports, 'ist_now', lambda: datetime(2026, 10, 12, 10, 18))     # slot 20, 12 min left
    login(client, cs_user.email)
    channels = crm.crm_settings()['check_channels']
    html = client.get('/cs/crm/checks').get_data(as_text=True)
    assert 'Now: 10:00–10:30' in html and '12 min' in html
    assert len(re.findall(r'class="hc-tile[ "]', html)) == len(channels) and 'data-tile' in html
    assert client.post('/cs/crm/checks/tick', json={'slot': 20, 'channel': channels[0]}).get_json()['ticked']
    html = client.get('/cs/crm/checks').get_data(as_text=True)
    assert html.count('class="hc-tile on"') == 1 and '1 of %d inboxes looked at' % len(channels) in html
    assert 'Half-hourly check' in nav_of(html)                          # a line of its own again


# ================================================================================================ activities

def test_marketing_activities_are_cards_by_platform_with_what_each_campaign_brought(app, client, admin_user):
    from app.models import CrmCampaign
    crm.ensure_defaults()
    login(client, admin_user.email)
    html = client.get('/admin/crm/sources?tab=activities').get_data(as_text=True)
    assert 'Add an activity' in html and 'act-sum' in html and html.count('class="act-card') >= 10
    assert re.search(r'fa-brands fa-facebook"></i> Facebook', html) and 'st-run' in html     # Ongoing is running
    lead = ti_lead()
    lead.utm = {'utm_campaign': 'diwali-ti'}
    _db.session.add(CrmCampaign(platform='Google', name='Diwali ads', status='Ongoing', utm_campaign='diwali-ti',
                                cost=5000, currency='INR', position=0, created_at=datetime.utcnow()))
    _db.session.commit()
    html = client.get('/admin/crm/sources?tab=activities').get_data(as_text=True)
    card = html.split('Diwali ads', 1)[1].split('</article>', 1)[0]
    assert 'act-nums' in card and re.search(r'<dt>Leads</dt><dd>1</dd>', card)


def test_the_check_runs_round_the_clock_from_24_october(app, monkeypatch):
    from datetime import date
    from app.services import crm_reports
    assert crm_reports.slots(date(2026, 10, 23)) == list(range(14, 48))          # 07:00 to midnight before
    assert crm_reports.slots(date(2026, 10, 24)) == list(range(48))              # every half hour from then on
    monkeypatch.setattr(crm_reports, 'ist_now', lambda: datetime(2026, 10, 25, 2, 40))       # 02:40 at night
    day, slot = crm_reports.current()
    assert slot == 5 and crm_reports.can_tick(day, 5) and not crm_reports.can_tick(day, 6)
    assert crm_reports.coverage(day, ['Tawk'])['due'] == 5                        # 00:00 to 02:30 are over


# ================================================================================================ the clock switch

def test_the_clock_knows_india_us_zones_with_daylight_saving_and_utc(app):
    from app.services import clock
    summer, winter = datetime(2026, 7, 1, 12, 0), datetime(2026, 12, 1, 12, 0)
    assert clock.fmt(summer, '%H:%M', 'IST') == '17:30' and clock.label(summer, 'IST') == 'IST'
    assert clock.fmt(summer, '%H:%M', 'ET') == '08:00' and clock.label(summer, 'ET') == 'EDT'
    assert clock.fmt(winter, '%H:%M', 'ET') == '07:00' and clock.label(winter, 'ET') == 'EST'
    assert clock.fmt(winter, '%H:%M', 'PT') == '04:00' and clock.label(summer, 'PT') == 'PDT'
    assert clock.fmt(summer, '%H:%M', 'UTC') == '12:00'
    # 2026: daylight saving from 8 March 07:00 UTC (2 am EST) to 1 November 06:00 UTC (2 am EDT)
    assert clock.label(datetime(2026, 3, 8, 6, 59), 'ET') == 'EST' and clock.label(datetime(2026, 3, 8, 7, 0), 'ET') == 'EDT'
    assert clock.label(datetime(2026, 11, 1, 5, 59), 'ET') == 'EDT' and clock.label(datetime(2026, 11, 1, 6, 0), 'ET') == 'EST'
    for z in clock.ZONES:                                                    # what is typed is what is shown
        assert clock.to_utc(clock.local(summer, z), z) == summer and clock.to_utc(clock.local(winter, z), z) == winter


def test_the_switch_moves_every_shown_time_and_a_typed_one(app, client, admin_user):
    from app.services import crm_tasks
    access.ensure_defaults()
    lead = ti_lead()
    login(client, admin_user.email)
    html = client.get('/admin/health').get_data(as_text=True)
    assert 'id="tzDD"' in html and 'US Eastern' in html and 'nav-cal' in html          # the switch and the Calendar
    client.set_cookie('tz', 'ET')
    html = client.get('/admin/health').get_data(as_text=True)
    assert re.search(r'class="tz-cur">E[DS]T<', html)
    with app.test_request_context(headers={'Cookie': 'tz=ET'}):
        due = crm_tasks.parse_when('2026-12-01T10:00')                      # 10 am in New York
        assert due == datetime(2026, 12, 1, 15, 0) and crm_tasks.input_value(due) == '2026-12-01T10:00'
    with app.test_request_context():
        assert crm_tasks.input_value(datetime(2026, 12, 1, 15, 0)) == '2026-12-01T20:30'      # India by default
    page = client.get('/admin/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert ' EST' in page or ' EDT' in page                                  # "came in …" says its zone
