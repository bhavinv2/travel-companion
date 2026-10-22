"""Overview's reports are one menu line, and Team today says what each half-hourly check covered.

    All reports   one line first in Overview for every report (Sales results, Forecast, Report builder, Team today,
                  Site dashboard, Match quality); it opens the first one the person may open, and each report shows
                  the others as tabs; a person with one report sees that line and no strip of one; an area switched
                  off takes its reports out of the line and the tabs
    what checked  for each team and half hour: each inbox, who ticked it and at what time, late when ticked after the
                  half hour, "Tick all" when one press ticked several, the inboxes not checked, and what the team did
                  then; each inbox's half hours; and a person's own day lists each check with its inboxes
"""
import re
from datetime import date, datetime, timedelta

from conftest import login, make_user
from app import db as _db
from app.models import CrmChannelCheck, WorkspaceRole, WorkspaceTeam
from app.services import access, crm, crm_reports

PAST = date.today() - timedelta(days=2)          # a past day: every half hour is over


def words(html):
    return ' '.join(re.sub(r'<[^>]+>', ' ', html).split())


def strip(html):
    m = re.search(r'<nav class="subtabs"[^>]*>(.*?)</nav>', html, re.S)
    return re.findall(r'>([^<]+)</a>', m.group(1)) if m else []


# ====================================================================================== All reports

def test_the_reports_are_one_line_that_opens_the_first_and_shows_the_rest_as_tabs(app, client, admin_user):
    access.ensure_defaults()
    login(client, admin_user.email)
    html = client.get('/admin/crm/today').get_data(as_text=True)
    nav = html.split('admin-nav-items', 1)[1] if 'admin-nav-items' in html else html
    assert 'All reports' in nav
    for gone in ('Sales results', 'Forecast', 'Report builder', 'Team today', 'Site dashboard', 'Match quality'):
        assert '>%s<' % gone not in nav.split('</nav>', 1)[0], gone
    r = client.get('/admin/reports')
    assert r.status_code == 302 and r.headers['Location'].endswith('/admin/crm/insights')
    tabs = ['Sales results', 'Forecast', 'Report builder', 'Team today', 'Site dashboard', 'Match quality']
    for path in ('/admin/crm/insights', '/admin/crm/forecast', '/admin/crm/reports/build', '/admin/crm/tracker', '/admin/'):
        page = client.get(path, follow_redirects=True).get_data(as_text=True)
        assert strip(page) == tabs, path
    assert strip(client.get('/cs/metrics').get_data(as_text=True)) == tabs


def test_somebody_with_one_report_has_the_line_and_no_strip_of_one(app, client):
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
    page = client.get('/cs/crm/tracker', follow_redirects=True).get_data(as_text=True)      # it lives in /admin
    assert 'All reports' in page and strip(page) == []


def test_an_area_switched_off_takes_its_reports_out(app, client, admin_user):
    ws = access.ensure_defaults()
    ws.modules = ['console', 'companion']
    _db.session.commit()
    access._cache().clear()
    login(client, admin_user.email)
    r = client.get('/admin/reports')
    assert r.status_code == 302 and r.headers['Location'].endswith('/admin/')          # Sales is off: the dashboard
    assert strip(client.get('/admin/').get_data(as_text=True)) == ['Site dashboard', 'Match quality']


# ====================================================================================== what was checked

def tick(user, slot, channel, at):
    _db.session.add(CrmChannelCheck(day=PAST, slot=slot, channel=channel, user_id=user.id if user else None,
                                    checked_at=at))
    _db.session.commit()


def start_of(slot, minute=0):
    return datetime.combine(PAST, datetime.min.time()) + timedelta(minutes=30 * slot + minute) - crm_reports.IST


def test_each_half_hour_says_who_ticked_each_inbox_when_and_what_was_missed(app, admin_user):
    crm.ensure_defaults()
    ws = access.ensure_defaults()
    channels = crm.crm_settings()['check_channels']
    a, b = (make_user('%s@test.com' % n, n, role='cs') for n in ('asha', 'bala'))
    team = WorkspaceTeam(workspace_id=ws.id, name='North')
    team.users.extend([a, b])
    _db.session.add(team)
    _db.session.commit()
    first = crm_reports.slots()[0]
    t0 = start_of(first, 10)
    for i, ch in enumerate(channels[:3]):                     # Asha: three inboxes in one press of Tick all
        tick(a, first, ch, t0 + timedelta(seconds=i))
    tick(b, first, channels[3], start_of(first, 45))           # Bala: one, after the half hour was over
    sheet = {a.id: {'timeline': [(start_of(first, 12), None, 'fa-paper-plane', 'Sent'),
                                 (start_of(first, 14), None, 'fa-paper-plane', 'Sent'),
                                 (start_of(first, 20), None, 'fa-phone', 'Called')]},
             b.id: {'timeline': [(start_of(first, 20), None, 'fa-check', 'Did')]}}
    g = crm_reports.checks_by_team(PAST, [a, b], channels, [team], sheet=sheet)[0]
    row = next(e for e in g['log'] if e['slot'] == first)
    cells = {c['channel']: c for c in row['cells']}
    assert cells[channels[0]]['who'] == a.full_name and cells[channels[0]]['state'] == 'ok'
    assert cells[channels[0]]['at'] == (t0 + crm_reports.IST).strftime('%H:%M') and cells[channels[0]]['bulk']
    assert cells[channels[3]]['who'] == b.full_name and cells[channels[3]]['state'] == 'late'
    assert all(cells[ch]['state'] == 'miss' for ch in channels[4:])
    assert row['bulk'] == [a.full_name] and not row['full']
    assert row['work'] == '2 messages · 1 call · 1 follow-up done'
    assert g['log'][0]['slot'] > g['log'][-1]['slot']                                      # newest first
    by = {i['channel']: i for i in g['inboxes']}
    assert by[channels[0]]['done'] == 1 and by[channels[-1]]['done'] == 0 and by[channels[0]]['due'] == g['due']
    rows = {r['user'].id: r for r in g['rows']}
    assert channels[0] in rows[a.id]['detail'][first]


def test_a_persons_day_lists_each_check_with_its_inboxes(app, admin_user):
    crm.ensure_defaults()
    channels = crm.crm_settings()['check_channels']
    a = make_user('asha@test.com', 'asha', role='cs')
    first = crm_reports.slots()[0]
    tick(a, first, channels[0], start_of(first, 5))
    tick(a, first + 2, channels[1], start_of(first + 2, 50))                                  # late
    lines = [t for _w, _l, icon, t in crm_reports.day_sheet(PAST, [a])[a.id]['timeline'] if icon == 'fa-clipboard-check']
    label = crm_reports.slot_label
    assert lines == ['Checked %s for %s–%s' % (channels[0], label(first), label(first + 1)),
                     'Checked %s for %s–%s (late, after %s)' % (channels[1], label(first + 2), label(first + 3),
                                                                label(first + 3))]


def test_team_today_shows_what_was_checked(app, client, admin_user):
    crm.ensure_defaults()
    access.ensure_defaults()
    channels = crm.crm_settings()['check_channels']
    first = crm_reports.slots()[0]
    tick(admin_user, first, channels[0], start_of(first, 7))
    login(client, admin_user.email)
    html = client.get('/admin/crm/tracker?day=%s' % PAST.isoformat()).get_data(as_text=True)
    t = words(html)
    assert 'What was checked, half hour by half hour' in t and '✗ not checked' in t
    assert (start_of(first, 7) + crm_reports.IST).strftime('%H:%M') in t
    assert '%s 1/' % channels[0] in t                                                      # the inbox's half hours
