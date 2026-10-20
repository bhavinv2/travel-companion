"""Team today -> "Half-hourly checks, team by team": a team lead sees their own teams' people half hour by half
hour, an admin sees every team (and whoever is in none), each team with the half hours its people covered.
"""
from datetime import date, timedelta

from conftest import login, logout, make_user
from app import db as _db
from app.models import CrmChannelCheck, WorkspaceTeam
from app.services import access, crm, crm_reports

YESTERDAY = date.today() - timedelta(days=2)          # a past day: every half hour is over


def tick(user, slot, channel, day=YESTERDAY):
    _db.session.add(CrmChannelCheck(day=day, slot=slot, channel=channel, user_id=user.id if user else None))
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
    return a, b, c, north, south


def test_each_person_and_each_team_by_half_hour(app, admin_user):
    crm.ensure_defaults()
    ws = access.ensure_defaults()
    a, b, c, north, south = setup_teams(ws)
    channels = crm.crm_settings()['check_channels']
    first = crm_reports.slots()[0]
    for ch in channels:                                   # North covers the first half hour between two people
        tick(a if ch == channels[0] else b, first, ch)
    tick(c, first + 1, channels[0])                       # South: one inbox only in the second
    out = {g['name']: g for g in crm_reports.checks_by_team(YESTERDAY, [a, b, c, admin_user], channels, [north, south])}
    assert list(out) == ['North', 'South', 'Not in a team']
    rows = {r['user'].id: r for r in out['North']['rows']}
    assert rows[a.id]['by_slot'] == {first: 1} and rows[b.id]['total'] == len(channels) - 1
    assert first in out['North']['covered_slots'] and out['North']['covered'] == 1
    assert out['South']['covered'] == 0 and out['South']['rows'][0]['by_slot'] == {first + 1: 1}
    assert out['North']['due'] == len(crm_reports.slots())
    assert [r['user'].id for r in out['Not in a team']['rows']] == [admin_user.id]


def test_a_connected_inbox_ticking_itself_covers_every_team(app, admin_user):
    crm.ensure_defaults()
    ws = access.ensure_defaults()
    a, b, c, north, south = setup_teams(ws)
    channels = crm.crm_settings()['check_channels']
    first = crm_reports.slots()[0]
    for ch in channels:
        tick(None, first, ch)
    out = crm_reports.checks_by_team(YESTERDAY, [a, b, c], channels, [north, south])
    assert all(first in g['covered_slots'] for g in out)
    assert all(r['total'] == 0 for g in out for r in g['rows'])            # nobody's own tick


def test_the_admin_sees_every_team_and_a_lead_only_theirs(client, app, admin_user):
    crm.ensure_defaults()
    ws = access.ensure_defaults()
    a, b, c, north, south = setup_teams(ws)
    lead_role = next(r for r in ws.roles if r.name == 'Team lead')
    m = next(m for m in ws.members if m.user_id == a.id)
    m.role = lead_role
    _db.session.commit()
    day = YESTERDAY.isoformat()
    login(client, admin_user.email)
    page = client.get('/admin/crm/tracker?day=%s' % day).data.decode()
    assert 'Half-hourly checks, team by team' in page and '<h3>North' in page and '<h3>South' in page
    logout(client)
    login(client, a.email)
    page = client.get('/cs/crm/tracker?day=%s' % day, follow_redirects=True).data.decode()
    assert '<h3>North' in page and '<h3>South' not in page and 'Chitra' not in page
