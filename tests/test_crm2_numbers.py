"""Sales CRM 2.0, phase 2 -- one set of numbers.

    registry   every number on Results / Team today has a definition, said once (crm_numbers.METRICS)
    agree      the same value on a Results card, the Results download and Team today for the same scope
    snapshots  saved days add up to what counting live gives, for every event metric; the job is safe to repeat;
               a period that ends today is part saved, part live; 'Recalculate' rebuilds
    speed      the number of queries behind Results does not grow with the people
"""
import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event

from conftest import login, make_user
from app import db as _db
from app.models import (CrmDailyStat, CrmLead, CrmPipeline, CrmStage, CrmStageChange, CrmTask, CrmTouchpoint,
                        CrmCurrencyRate)
from app.services import access, crm, crm_kpi, crm_numbers, crm_reports, crm_results

from test_crm_wa_sync_engine import ti_lead

NOON = timedelta(hours=6, minutes=30)           # 12:00 in India, as UTC


def at(day, extra=timedelta()):
    """A UTC moment inside India day `day`."""
    return datetime.combine(day, datetime.min.time()) + NOON + extra


def today():
    return crm_numbers.today_ist()


def span(days_back_first, days_back_last):
    """UTC bounds of the India days (today - first) .. (today - last), inclusive."""
    a, b = today() - timedelta(days=days_back_first), today() - timedelta(days=days_back_last)
    return crm_kpi.utc_bounds(a, b)


def touch(lead, day, direction='out', channel='whatsapp', via=None, agent=None, code=None, outcome=None, status=None,
          extra=timedelta()):
    t = CrmTouchpoint(lead_id=lead.id, person_id=lead.person_id, channel=channel, direction=direction, via=via,
                      agent_id=agent, code=code, outcome=outcome, status=status, body='x', created_at=at(day, extra))
    _db.session.add(t)
    return t


@pytest.fixture
def staff(app):
    return (make_user('one@test.com', 'one', role='cs'), make_user('two@test.com', 'two', role='cs'),
            make_user('three@test.com', 'three', role='cs'))


@pytest.fixture
def busy(app, staff):
    """Ten days of work by three people in the first pipeline (and a second pipeline), enough to make every event
    number non-zero somewhere."""
    one, two, three = staff
    crm.ensure_defaults()
    pipes = CrmPipeline.query.order_by(CrmPipeline.id).all()
    stages = {s.id: s for s in CrmStage.query.all()}
    open_stage = next(s for s in stages.values() if s.kind == 'open')
    quoted_stage = next(s for s in stages.values() if s.role == 'pipeline')
    owners = [one, two, three]
    leads = []
    for n in range(10):
        day = today() - timedelta(days=10 - n)                        # 10 .. 1 days ago
        lead = ti_lead(phone='+91987650%04d' % n, name='Lead %d' % n)
        lead.owner_id = owners[n % 3].id
        lead.created_by_id = owners[(n + 1) % 3].id
        lead.created_at = at(day, timedelta(hours=-1))
        if n % 4 == 3 and len(pipes) > 1:
            lead.pipeline_id = pipes[1].id
        _db.session.flush()
        for t in CrmTask.query.filter_by(lead_id=lead.id).all():
            t.due_at = at(day)
            if n % 2:
                t.status, t.done_at, t.done_by_id = 'done', at(day, timedelta(hours=1)), owners[n % 3].id
        touch(lead, day, 'in', 'whatsapp', extra=timedelta(minutes=-30))
        touch(lead, day, 'out', 'whatsapp', via='person', agent=owners[n % 3].id, code='TI #1')
        touch(lead, day, 'out', 'whatsapp', via='automation', code='TI #2', extra=timedelta(minutes=5))
        if n % 3 == 0:
            touch(lead, day, 'out', 'whatsapp', via='broadcast', extra=timedelta(minutes=6))
        if n % 2 == 0:
            touch(lead, day, 'out', 'call', via='person', agent=owners[n % 3].id, outcome='connected')
            touch(lead, day, 'out', 'whatsapp', via='person', agent=owners[n % 3].id, code='Q')
        if n % 4 == 1:
            touch(lead, day, 'out', 'whatsapp', via='person', agent=owners[n % 3].id, code='PLS')
        _db.session.add(CrmStageChange(lead_id=lead.id, from_stage_id=lead.stage_id, to_stage_id=open_stage.id,
                                       by_id=owners[n % 3].id, created_at=at(day, timedelta(hours=2))))
        if n % 3 == 1:
            _db.session.add(CrmStageChange(lead_id=lead.id, from_stage_id=lead.stage_id, to_stage_id=quoted_stage.id,
                                           by_id=owners[n % 3].id, created_at=at(day, timedelta(hours=2, minutes=5))))
        if n in (4, 6, 8):
            lead.status, lead.closed_at = 'won', at(day, timedelta(hours=3))
            lead.amount, lead.currency, lead.revenue = Decimal('10000.00') * (n - 3), 'INR', Decimal('500.00')
        if n in (5, 9):
            lead.status, lead.closed_at, lead.fallout_reason = 'lost', at(day, timedelta(hours=3)), 'Too expensive'
        leads.append(lead)
    _db.session.commit()
    return leads


def values(since, until, scope=None, keys=None):
    keys = keys or crm_numbers.SNAP_KEYS
    return {k: crm_numbers.compute(k, since, until, scope) for k in keys}


# ======================================================================================================= registry

def test_every_number_has_one_plain_sentence_and_a_kind(app):
    assert len(crm_numbers.METRICS) >= 25
    for key, m in crm_numbers.METRICS.items():
        assert m.key == key and m.label
        assert m.definition.endswith('.') and 20 < len(m.definition) < 260, key
        assert m.unit in ('count', 'money', 'minutes', 'percent')
        assert m.kind in ('event', 'state')
    for key in ('new_leads', 'replied', 'first_contact_minutes', 'reply_minutes', 'waiting_now', 'quoted',
                'payment_links', 'won', 'won_value', 'revenue', 'lost', 'lost_by_reason', 'messages_people',
                'messages_auto', 'messages_broadcast', 'followups_due', 'followups_done', 'calls', 'open_leads',
                'late_followups'):
        assert key in crm_numbers.METRICS


def test_only_event_metrics_are_saved_and_never_a_median(app):
    for key in crm_numbers.SNAP_KEYS:
        m = crm_numbers.METRICS[key]
        assert m.kind == 'event' and m.unit in ('count', 'money')
    for key in ('first_contact_minutes', 'reply_minutes', 'waiting_now', 'open_leads', 'late_followups'):
        assert key not in crm_numbers.SNAP_KEYS


def test_the_numbers_on_results_and_team_today_read_their_tip_from_the_registry(app, client, admin_user, busy):
    login(client, admin_user.email)
    results = client.get('/admin/crm/insights').get_data(as_text=True)
    team = client.get('/admin/crm/tracker').get_data(as_text=True)
    import html
    results, team = html.unescape(results), html.unescape(team)
    for card in crm_numbers.CARD_METRIC:
        assert crm_numbers.card_definition(card) in results, card
    for key in ('won_value', 'revenue'):
        assert crm_numbers.definition(key) in results
    for key in ('open_leads', 'late_followups', 'waiting_now', 'whatsapp_replies', 'unanswered', 'reply_minutes',
                'calls', 'checks', 'last_active', 'followups_done_of_due'):
        assert crm_numbers.definition(key) in team, key
    forecast = html.unescape(client.get('/admin/crm/forecast').get_data(as_text=True))
    for key in ('forecast_won', 'forecast_commit', 'forecast_best_case', 'forecast_gap'):
        assert crm_numbers.definition(key) in forecast, key


def test_results_says_days_before_today_are_saved_and_admin_can_recalculate(app, client, admin_user, cs_user):
    login(client, admin_user.email)
    page = client.get('/admin/crm/insights').get_data(as_text=True)
    assert "later changes to old leads don&#39;t rewrite them" in page and 'Recalculate the last 90 days' in page


# ======================================================================================================= agree

def test_a_results_card_the_download_and_team_today_say_the_same(app, client, admin_user, staff, busy):
    one = staff[0]
    since, until = span(30, 0)
    me = crm_numbers.scope(owner_ids=[one.id])
    card = crm_results.cards(since, until, None, one.id)
    for card_key, metric in (('new_leads', 'new_leads'), ('replied', 'replied'), ('quoted', 'quoted_leads'),
                             ('won', 'won'), ('waiting_now', 'waiting_now')):
        assert card[card_key] == crm_numbers.compute(metric, since, until, me), card_key
    assert crm_numbers.by_owner('new_leads', since, until)[one.id] == card['new_leads']
    # Team today: the number of customers waiting is the card's, for the same person
    team = crm_reports.team_numbers(today(), [one])
    assert team[one.id]['waiting'] == card['waiting_now']
    # the download
    login(client, admin_user.email)
    rows = list(csv.reader(io.StringIO(client.get('/admin/crm/insights.csv?days=30&who=%d&reason=backup' % one.id)
                                       .get_data(as_text=True).lstrip('﻿'))))
    by_label = {}
    for r in rows:
        if r:
            by_label.setdefault(r[0], r)                      # the card is the first 'New leads' row
    assert int(by_label['New leads'][1]) == card['new_leads']
    assert int(by_label['Replied'][1]) == card['replied']
    assert int(by_label['Won in these days'][1]) == card['won']
    assert int(by_label['Customers waiting now'][1]) == card['waiting_now']
    assert by_label['New leads'][4] == crm_numbers.card_definition('new_leads')
    page = client.get('/admin/crm/insights?days=30&who=%d' % one.id).get_data(as_text=True)
    assert 'New leads' in page


def test_the_per_person_download_uses_the_registry(app, staff, busy):
    one = staff[0]
    totals, daily = crm_reports.kpis(at(today() - timedelta(days=11)), at(today() + timedelta(days=1)))
    since, until = at(today() - timedelta(days=11)), at(today() + timedelta(days=1))
    me = crm_numbers.scope(owner_ids=[one.id])
    assert totals[one.id]['leads'] == crm_numbers.compute('new_leads', since, until, me)
    assert totals[one.id]['won'] == crm_numbers.compute('won', since, until, me)
    assert totals[one.id]['calls'] == crm_numbers.compute('calls', since, until, me)
    assert totals[one.id]['codes']['TI'] >= 1
    assert sum(d.get('leads', 0) for d in daily[one.id].values()) == totals[one.id]['leads']


def test_a_team_is_its_members(app, staff, busy):
    from app.models import WorkspaceTeam
    one, two, _ = staff
    ws = access.ensure_defaults()
    team = WorkspaceTeam(workspace_id=ws.id, name='Pair')
    team.users = [one, two]
    _db.session.add(team)
    _db.session.commit()
    since, until = span(30, 0)
    both = crm_numbers.compute('new_leads', since, until, crm_numbers.scope(team_id=team.id))
    parts = sum(crm_numbers.compute('new_leads', since, until, crm_numbers.scope(owner_ids=[u.id])) for u in (one, two))
    assert both == parts and both > 0


def test_the_pipeline_filter_narrows_the_number(app, staff, busy):
    since, until = span(30, 0)
    pipes = CrmPipeline.query.order_by(CrmPipeline.id).all()
    whole = crm_numbers.compute('new_leads', since, until)
    parts = sum(crm_numbers.compute('new_leads', since, until, crm_numbers.scope(pipeline_id=p.id)) for p in pipes)
    assert whole == parts == 10


# ======================================================================================================= snapshots

def snapshot_all(first_back=11, last_back=1):
    for back in range(first_back, last_back - 1, -1):
        crm_numbers.snapshot_day(today() - timedelta(days=back))


def test_saved_days_give_the_same_answer_as_counting_live(app, staff, busy):
    snapshot_all()
    one = staff[0]
    pipes = CrmPipeline.query.order_by(CrmPipeline.id).all()
    scopes = [None, crm_numbers.scope(owner_ids=[one.id]), crm_numbers.scope(pipeline_id=pipes[0].id),
              crm_numbers.scope(pipeline_id=pipes[0].id, owner_ids=[one.id, staff[1].id])]
    periods = [span(11, 1), span(7, 1), span(5, 3), span(1, 1)]
    seen_nonzero = set()
    for sc in scopes:
        for since, until in periods:
            saved = values(since, until, sc)
            live = values(since, until, dict(sc or {}, live=True))
            assert saved == live, (sc, since)
            seen_nonzero |= {k for k, v in saved.items() if v}
    # the data really exercises every saved number
    assert set(crm_numbers.SNAP_KEYS) - seen_nonzero == set()
    # and per person
    since, until = span(11, 1)
    for key in crm_numbers.SNAP_KEYS:
        assert (crm_numbers.by_owner(key, since, until) ==
                crm_numbers.by_owner(key, since, until, {'live': True})), key


def test_saved_days_are_really_what_is_read(app, staff, busy):
    snapshot_all()
    since, until = span(11, 1)
    before = crm_numbers.compute('new_leads', since, until)
    # a lead changes afterwards: the saved past is kept as it was
    lead = CrmLead.query.first()
    lead.imported = True
    _db.session.commit()
    assert crm_numbers.compute('new_leads', since, until) == before
    assert crm_numbers.compute('new_leads', since, until, {'live': True}) == before - 1
    # 'Recalculate' brings the saved days up to date
    crm_numbers.recalculate(days=12, now_days=12)
    assert crm_numbers.compute('new_leads', since, until) == before - 1


def test_a_period_that_ends_today_is_saved_days_plus_today_live(app, staff, busy):
    snapshot_all()
    lead = CrmLead.query.first()
    touch(lead, today(), 'out', 'whatsapp', via='person', agent=staff[0].id, code='Q')
    _db.session.commit()
    since, until = crm_kpi.utc_bounds(today() - timedelta(days=11), today())
    assert (CrmDailyStat.query.filter_by(day=today()).count()) == 0
    mixed = crm_numbers.compute('quoted', since, until)
    live = crm_numbers.compute('quoted', since, until, {'live': True})
    assert mixed == live
    only_saved = crm_numbers.compute('quoted', *span(11, 1))
    assert mixed == only_saved + 1


def test_a_period_with_a_missing_day_is_counted_live(app, staff, busy):
    snapshot_all()
    CrmDailyStat.query.filter_by(day=today() - timedelta(days=5)).delete()
    _db.session.commit()
    since, until = span(11, 1)
    assert values(since, until) == values(since, until, {'live': True})


def test_an_odd_start_time_is_counted_live_at_the_edges(app, staff, busy):
    snapshot_all()
    since, until = at(today() - timedelta(days=6)), at(today() - timedelta(days=2))
    assert values(since, until) == values(since, until, {'live': True})


def test_the_job_saves_a_few_days_a_run_and_is_safe_to_repeat(app, staff, busy):
    assert CrmDailyStat.query.count() == 0
    out = crm_numbers.snapshot_missing_days(limit_days=3)
    assert out == {'crm_snapshot_days': 3}
    days = {d for (d,) in _db.session.query(CrmDailyStat.day).distinct()}
    assert days == {today() - timedelta(days=n) for n in (1, 2, 3)}          # yesterday and the days before it
    again = crm_numbers.snapshot_missing_days(limit_days=3)
    assert again == {'crm_snapshot_days': 3}
    assert {d for (d,) in _db.session.query(CrmDailyStat.day).distinct()} == {today() - timedelta(days=n) for n in range(1, 7)}
    # a day done twice is not doubled
    n = CrmDailyStat.query.count()
    crm_numbers.snapshot_day(today() - timedelta(days=1))
    assert CrmDailyStat.query.count() == n
    keys = _db.session.query(CrmDailyStat.day, CrmDailyStat.metric, CrmDailyStat.user_id, CrmDailyStat.pipeline_id).all()
    assert len(keys) == len(set(keys))


def test_the_job_is_part_of_the_jobs_runner(app, monkeypatch):
    from app.services import jobs
    called = []
    monkeypatch.setattr(crm_numbers, 'snapshot_missing_days', lambda limit_days=5: called.append(limit_days) or {'crm_snapshot_days': 0})
    out = jobs.run_all()
    assert called == [5] and out.get('crm_snapshot_days') == 0


def test_the_command_saves_the_days_at_once(app, staff, busy):
    runner = app.test_cli_runner()
    result = runner.invoke(args=['crm-snapshot', '--days', '12'])
    assert result.exit_code == 0 and '12 days saved' in result.output
    assert len(crm_numbers._present_days([today() - timedelta(days=n) for n in range(1, 13)])) == 12


def test_recalculate_forgets_and_rebuilds_the_newest_days_first(app, staff, busy):
    snapshot_all()
    out = crm_numbers.recalculate(days=11, now_days=4)
    assert out == {'forgotten': 11, 'rebuilt_now': 4, 'left_for_tonight': 7}
    present = crm_numbers._present_days([today() - timedelta(days=n) for n in range(1, 12)])
    assert present == {today() - timedelta(days=n) for n in range(1, 5)}
    # meanwhile nothing is missing or wrong
    since, until = span(11, 1)
    assert values(since, until) == values(since, until, {'live': True})


def test_only_an_admin_can_recalculate(app, client, admin_user, cs_user, busy):
    access.ensure_defaults()
    login(client, cs_user.email)
    r = client.post('/cs/crm/insights/recalculate')
    assert r.status_code in (302, 403, 404)
    assert CrmDailyStat.query.count() == 0
    client.post('/auth/logout')
    login(client, admin_user.email)
    r = client.post('/admin/crm/insights/recalculate', data={'days': 30})
    assert r.status_code == 302
    assert CrmDailyStat.query.count() > 0


def test_money_is_added_up_the_same_way_saved_or_live(app, staff, busy):
    _db.session.add(CrmCurrencyRate(code='USD', rate=Decimal('83.25')))
    lead = CrmLead.query.filter_by(status='won').first()
    lead.currency, lead.amount, lead.revenue = 'USD', Decimal('100.00'), Decimal('10.00')
    _db.session.commit()
    snapshot_all()
    since, until = span(11, 1)
    for key in ('won_value', 'revenue'):
        got = crm_numbers.compute(key, since, until)
        assert isinstance(got, Decimal) and got > 0
        assert got == crm_numbers.compute(key, since, until, {'live': True})


def test_lost_reasons_and_state_numbers_are_always_live(app, staff, busy):
    snapshot_all()
    since, until = span(11, 1)
    assert crm_numbers.compute('lost_by_reason', since, until) == [('Too expensive', 2)]
    assert crm_numbers.compute('open_leads', since, until) == 5
    assert 'lost_by_reason' not in {r.metric for r in CrmDailyStat.query.all()}
    assert crm_results.lost_reasons(since, until) == [('Too expensive', 2)]


def test_results_reads_the_same_with_and_without_saved_days(app, client, admin_user, staff, busy):
    login(client, admin_user.email)
    live = client.get('/admin/crm/insights?days=30').get_data(as_text=True)
    snapshot_all(first_back=30)
    saved = client.get('/admin/crm/insights?days=30').get_data(as_text=True)
    import re
    strip = lambda h: re.sub(r'(csrf|value="[^"]{20,}")[^>]*', '', h)             # noqa: E731
    cards = lambda h: re.findall(r'<div class="kpi-card">.*?</div>', h, flags=re.S)  # noqa: E731
    assert cards(live) == cards(saved) and cards(live)


# ======================================================================================================= speed

class Counter:
    def __init__(self, engine):
        self.engine, self.n = engine, 0

    def __enter__(self):
        event.listen(self.engine, 'before_cursor_execute', self._count)
        return self

    def __exit__(self, *a):
        event.remove(self.engine, 'before_cursor_execute', self._count)

    def _count(self, *a):
        self.n += 1


def test_results_costs_a_fixed_number_of_queries_however_many_owners(app, client, admin_user, staff, busy):
    login(client, admin_user.email)
    snapshot_all(first_back=30)
    client.get('/admin/crm/insights?days=30')                 # warm the caches
    one = staff[0]
    with Counter(_db.engine) as c1:
        r = client.get('/admin/crm/insights?days=30&who=%d' % one.id)
    assert r.status_code == 200
    with Counter(_db.engine) as c3:
        r = client.get('/admin/crm/insights?days=30')
    assert r.status_code == 200
    assert c3.n < 120, c3.n
    assert abs(c3.n - c1.n) < 15, (c1.n, c3.n)


def test_the_per_person_numbers_cost_one_query_per_number_not_per_person(app, staff, busy):
    since, until = span(11, 1)
    ids = [u.id for u in staff]
    with Counter(_db.engine) as one:
        crm_numbers.by_owner('new_leads', since, until, {'live': True, 'owner_ids': ids[:1]})
    with Counter(_db.engine) as three:
        crm_numbers.by_owner('new_leads', since, until, {'live': True, 'owner_ids': ids})
    assert one.n == three.n == 1
    with Counter(_db.engine) as team:
        crm_reports.team_numbers(today(), list(staff))
    assert team.n < 25, team.n
