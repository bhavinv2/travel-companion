"""Team analysis (Overview › All reports): the sales people side by side over a period -- services/crm_team.py,
routes/crm.py team_analysis.

    period     today, yesterday, the last 7 or 30 days, this month, or custom dates (never past today, at most
               three months, either order)
    checks     the half-hourly check over the days: per person and day (half hours, started late, Tick all, first
               tick), per day for the team, per half hour of the day (when it gets missed), per inbox
    working    each person's first and last action each day
    the page   people on the left by team, ticked to compare (?p=), a scorecard, the checks, day by day, a download;
               an admin sees every team, a team lead their own; it comes with Team today, which links to it
"""
import csv
import io
from datetime import date, datetime, timedelta

from conftest import login, logout, make_user
from app import db as _db
from app.models import CrmChannelCheck, CrmTouchpoint, WorkspaceRole, WorkspaceTeam
from app.services import access, crm, crm_reports, crm_team

from test_crm_wa_sync_engine import ti_lead

TODAY = crm_reports.current()[0]
PAST = TODAY - timedelta(days=3)


def at(day, slot, minute=0, second=0):
    """The UTC moment `minute` minutes into half hour `slot` of India day `day`."""
    return datetime.combine(day, datetime.min.time()) + timedelta(minutes=30 * slot + minute, seconds=second) - crm_reports.IST


def tick(user, day, slot, channel, minute=5, second=0):
    _db.session.add(CrmChannelCheck(day=day, slot=slot, channel=channel, user_id=user.id if user else None,
                                    checked_at=at(day, slot, minute, second)))
    _db.session.commit()


def setup_teams(ws):
    a, b, c = (make_user('%s@test.com' % n, n, role='cs') for n in ('asha', 'bala', 'chitra'))
    for u in (a, b, c):
        access.add_member(ws, u, role=access.system_role(ws, 'cs'))
    north = WorkspaceTeam(workspace_id=ws.id, name='North')
    north.users.extend([a, b])
    south = WorkspaceTeam(workspace_id=ws.id, name='South')
    south.users.append(c)
    _db.session.add_all([north, south])
    _db.session.commit()
    return a, b, c


# ====================================================================================== the period

def test_the_periods():
    t = date(2026, 10, 23)
    assert [(p['first'], p['last']) for p in (crm_team.period(k, today=t) for k in ('today', 'yesterday', '7d', '30d', 'month'))] == [
        (t, t), (t - timedelta(1), t - timedelta(1)), (t - timedelta(6), t), (t - timedelta(29), t), (date(2026, 10, 1), t)]
    p = crm_team.period('custom', date(2026, 10, 20), date(2026, 10, 10), today=t)                  # either order
    assert (p['first'], p['last'], len(p['days'])) == (date(2026, 10, 10), date(2026, 10, 20), 11)
    assert crm_team.period('custom', date(2026, 10, 20), date(2026, 12, 1), today=t)['last'] == t    # never past today
    assert len(crm_team.period('custom', date(2025, 1, 1), t, today=t)['days']) == crm_team.MAX_DAYS
    assert crm_team.period('nonsense', today=t)['key'] == 'today' and crm_team.period('custom', today=t)['key'] == 'today'
    p = crm_team.period('7d', today=t)
    assert p['until'] - p['since'] == timedelta(days=7) and p['label'] == 'Last 7 days'


# ====================================================================================== the check, over days

def test_the_check_over_several_days(app, admin_user):
    crm.ensure_defaults()
    channels = crm.crm_settings()['check_channels']
    a, b = make_user('asha@test.com', 'asha', role='cs'), make_user('bala@test.com', 'bala', role='cs')
    first = crm_reports.slots()[0]
    d1, d2 = PAST - timedelta(days=1), PAST
    for i, ch in enumerate(channels):                        # day 1: Asha ticks every inbox in one press
        tick(a, d1, first, ch, minute=4, second=0)
    tick(b, d1, first + 1, channels[0], minute=40)           # Bala: one inbox, only after the half hour was over
    tick(a, d2, first + 2, channels[0], minute=8)
    days = [d1, d2]
    r = crm_team.checks(days, [a.id, b.id], channels)
    assert r['person'][a.id][d1]['slots'] == 1 and r['person'][a.id][d1]['bulk'] == 1 and r['person'][a.id][d1]['late'] == 0
    assert r['person'][a.id][d1]['first'] == at(d1, first, 4)
    assert r['person'][b.id][d1] == {'slots': 1, 'late': 1, 'bulk': 0, 'first': at(d1, first + 1, 40)}
    assert r['person'][a.id][d2]['slots'] == 1 and d2 not in r['person'][b.id]
    team = {t['day']: t for t in r['team']}
    assert team[d1]['full'] == 1 and team[d1]['due'] == len(crm_reports.slots()) and team[d2]['full'] == 0
    slot = {s['slot']: s for s in r['by_slot']}
    assert slot[first]['full'] == 1 and slot[first]['due'] == 2 and slot[first]['pct'] == 50
    assert slot[first + 1]['full'] == 0 and slot[first + 1]['pct'] == 0
    inbox = {i['channel']: i for i in r['inboxes']}
    assert inbox[channels[0]]['done'] == 3 and inbox[channels[1]]['done'] == 1 and inbox[channels[0]]['due'] == 2 * len(crm_reports.slots())


def test_working_hours_come_from_any_action(app, admin_user):
    crm.ensure_defaults()
    channels = crm.crm_settings()['check_channels']
    a = make_user('asha@test.com', 'asha', role='cs')
    lead = ti_lead()
    first = crm_reports.slots()[0]
    tick(a, PAST, first + 4, channels[0], minute=10)                                       # 09:10
    _db.session.add(CrmTouchpoint(lead_id=lead.id, person_id=lead.person_id, channel='whatsapp', direction='out',
                                  agent_id=a.id, body='x', created_at=at(PAST, first + 20, 15)))   # 17:15
    _db.session.commit()
    per = crm_team.period('custom', PAST, PAST)
    spans = crm_team.working(per['since'], per['until'], [a.id])
    assert spans[a.id][PAST] == [at(PAST, first + 4, 10), at(PAST, first + 20, 15)]
    v = crm_team.analysis(per, [a], channels)['people'][0]['values']
    assert v['days_active'] == 1 and v['start_avg'] == '09:10' and v['end_avg'] == '17:15' and v['hours_avg'] == 8.1
    assert v['chk_slots'] == 1 and v['chk_first'] == '09:10' and v['messages_by_agent'] == 1


def test_the_scorecard_adds_up_and_days_are_text_for_the_page(app, admin_user):
    crm.ensure_defaults()
    channels = crm.crm_settings()['check_channels']
    a, b = make_user('asha@test.com', 'asha', role='cs'), make_user('bala@test.com', 'bala', role='cs')
    first = crm_reports.slots()[0]
    tick(a, PAST, first, channels[0])
    tick(b, PAST, first + 1, channels[0])
    tick(b, PAST, first + 2, channels[1])
    r = crm_team.analysis(crm_team.period('custom', PAST - timedelta(days=1), PAST), [a, b], channels)
    assert [p['values']['chk_slots'] for p in r['people']] == [1, 2] and r['team']['chk_slots'] == 3
    assert r['daily_json']['days'] == [(PAST - timedelta(days=1)).isoformat(), PAST.isoformat()]
    assert r['daily_json']['people'][1]['daily']['chk_slots'] == {PAST.isoformat(): 2.0}
    assert r['day'] is None                                                              # several days: no strips
    rows = crm_team.csv_rows(r)
    assert rows[0][0] == 'Person' and 'Half hours checked' in rows[0] and len(rows) == 3


# ====================================================================================== the page

def test_the_page_compares_who_is_ticked(app, client, admin_user):
    crm.ensure_defaults()
    ws = access.ensure_defaults()
    a, b, c = setup_teams(ws)
    channels = crm.crm_settings()['check_channels']
    tick(a, PAST, crm_reports.slots()[0], channels[0])
    login(client, admin_user.email)
    html = client.get('/admin/crm/analysis?period=7d&p=%d,%d' % (a.id, c.id)).get_data(as_text=True)
    for part in ('Team analysis', 'Scorecard', 'Inbox checks', 'Day by day', 'Last 7 days', 'Half hours checked',
                 'Follow-ups done', 'Reply time', 'Won value', 'When the check gets missed', 'Fully checked'):
        assert part in html, part
    assert '<b>North</b>' in html and '<b>South</b>' in html
    assert 'value="%d" data-in="1" checked' % a.id in html and 'value="%d" data-in="1" checked' % b.id not in html
    assert 'value="%d" data-in="2" checked' % c.id in html
    r = client.get('/admin/crm/analysis?period=custom&start=%s&end=%s&format=csv&p=%d' % (PAST, PAST, a.id))
    assert r.status_code == 200 and r.mimetype == 'text/csv'
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True).lstrip(chr(0xfeff)))))
    assert rows[0][0] == 'Person' and [x[0] for x in rows[1:]] == [a.full_name]


def test_one_day_shows_each_half_hour(app, client, admin_user):
    crm.ensure_defaults()
    access.ensure_defaults()
    channels = crm.crm_settings()['check_channels']
    first = crm_reports.slots()[0]
    tick(admin_user, PAST, first, channels[0], minute=7)
    login(client, admin_user.email)
    html = client.get('/admin/crm/analysis?period=custom&start=%s&end=%s&tab=checks' % (PAST, PAST)).get_data(as_text=True)
    assert 'half hour by half hour' in html and 'Half hours not fully checked' in html and 'ck-legend' in html
    assert (at(PAST, first, 7) + crm_reports.IST).strftime('%H:%M') in html


def test_an_admin_sees_every_team_and_a_lead_only_theirs(client, app, admin_user):
    crm.ensure_defaults()
    ws = access.ensure_defaults()
    a, b, c = setup_teams(ws)
    lead_role = next(r for r in ws.roles if r.name == 'Team lead')
    next(m for m in ws.members if m.user_id == a.id).role = lead_role
    _db.session.commit()
    login(client, admin_user.email)
    page = client.get('/admin/crm/analysis').get_data(as_text=True)
    assert '<b>North</b>' in page and '<b>South</b>' in page and 'Chitra' in page
    logout(client)
    login(client, a.email)
    page = client.get('/cs/crm/analysis', follow_redirects=True).get_data(as_text=True)
    assert '<b>North</b>' in page and '<b>South</b>' not in page and 'Chitra' not in page


def test_team_analysis_comes_with_team_today_and_team_today_links_to_it(app, client, admin_user):
    ws = access.ensure_defaults()
    agent = make_user('agent@test.com', 'agent', role='cs')
    role = WorkspaceRole(workspace_id=ws.id, name='Leads only', pages=['crm_today', 'crm_board'])
    _db.session.add(role)
    _db.session.commit()
    access.add_member(ws, agent, role=role)
    access._cache().clear()
    login(client, agent.email)
    r = client.get('/cs/crm/analysis')
    assert r.status_code == 302 and '/analysis' not in r.headers['Location']
    logout(client)
    login(client, admin_user.email)
    tracker = client.get('/admin/crm/tracker?day=%s' % PAST).get_data(as_text=True)
    assert '/admin/crm/analysis?period=custom&amp;start=%s&amp;end=%s&amp;tab=checks' % (PAST, PAST) in tracker


def test_a_late_tick_after_midnight_belongs_to_its_own_day(app, admin_user):
    crm.ensure_defaults()
    channels = crm.crm_settings()['check_channels']
    a = make_user('asha@test.com', 'asha', role='cs')
    last = crm_reports.slots()[-1]                                                         # 23:30-24:00
    d1, d2 = PAST - timedelta(days=1), PAST
    tick(a, d1, last - 16, channels[0], minute=0)                                           # 15:30
    tick(a, d1, last, channels[0], minute=40)                                               # 00:10, the next day
    tick(a, d2, last - 16, channels[0], minute=0)                                           # 15:30
    tick(a, d2, last, channels[0], minute=20)                                               # 23:50
    v = crm_team.analysis(crm_team.period('custom', d1, d2), [a], channels)['people'][0]['values']
    assert v['days_active'] == 2 and v['start_avg'] == '15:30' and v['end_avg'] == '00:00'   # not 12:00
    assert v['hours_avg'] == 8.5 and v['chk_late'] == 1
