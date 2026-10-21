"""Sales CRM 2.0, run 5b -- lead scoring (Set-up > Pipelines & products > Scoring).

    off       a starter set is written the first time the tab opens, and nothing is scored or re-rated until
              "Turn scoring on"
    on        every open lead is scored; "Ready to buy?" follows the score -- never over a rating a person picked;
              clearing the pick lets the score decide again
    signals   replied / quote sent / payment link sent are the numbers registry's own; trip within days, no reply
              for days, has a value, source, a detail
    when      after a save that touched the lead (after the commit), and once a night in the jobs runner
    screens   the lead card says "Score 72 — They replied +20 ..."; the board card has a small chip; the tab edits
              lines and thresholds
    workspace scoring on in one workspace leaves another's leads alone
"""
import re
from datetime import date, datetime, timedelta

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmLead, CrmPipeline, CrmScoreRule, CrmSource, CrmStage
from app.services import access, crm, crm_numbers, crm_scope, crm_scoring, jobs

from test_crm_wa_sync_engine import ti_lead


def words(html):
    return re.sub(r'\s+', ' ', re.sub(r'<script.*?</script>|<[^>]+>', ' ', html, flags=re.S))


def fresh(lead_id):
    _db.session.expire_all()
    return _db.session.get(CrmLead, lead_id)


def stage(key):
    return CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == 'ti-standard', CrmStage.key == key).one()


def turn_on(client=None, admin=None):
    if client is not None:
        login(client, admin.email)
        return client.post('/admin/crm/pipelines/scoring/switch', data={'on': '1'})
    crm_scoring.ensure_starter()
    crm_scoring.save_state(on=True)
    return crm_scoring.recalc_all()


def test_the_tab_writes_a_starter_set_and_scoring_stays_off(app, client, admin_user):
    crm.ensure_defaults()
    lead = ti_lead()
    crm.record_reply(lead, 'Yes please send it')
    _db.session.commit()
    login(client, admin_user.email)
    page = client.get('/admin/crm/pipelines?tab=scoring').get_data(as_text=True)
    text = words(page)
    assert 'Scoring is off' in text and 'Turn scoring on' in text and '(?) How this works' in page
    names = [l.name for l in CrmScoreRule.query.order_by(CrmScoreRule.position)]
    assert names[:3] == ['They replied', 'A quote was sent', 'A payment link was sent'] and len(names) == 6
    assert 'The trip is within 14 days' in text and '-20' in text
    # off: nothing is scored, no rating moves, the lead card says nothing about a score
    crm.record_reply(fresh(lead.id), 'And another')
    _db.session.commit()
    l = fresh(lead.id)
    assert l.score is None and l.likelihood is None
    assert 'Score ' not in words(client.get('/admin/crm/lead/%d' % lead.id).get_data(as_text=True))
    # opening the tab again does not write the starter set twice, even after somebody deleted the lines
    CrmScoreRule.query.delete()
    _db.session.commit()
    client.get('/admin/crm/pipelines?tab=scoring')
    assert CrmScoreRule.query.count() == 0


def test_turning_it_on_scores_every_open_lead_and_the_rating_follows(app, client, admin_user):
    crm.ensure_defaults()
    today = (datetime.utcnow() + crm_scoring.IST).date()
    hot = ti_lead(phone='+919800000801', name='Hot Harini')
    crm.record_reply(hot, 'Yes')
    crm.mark_event(hot, 'Q', amount='25000')
    hot.departure_date = today + timedelta(days=9)
    warm = ti_lead(phone='+919800000802', name='Warm Wasim')
    crm.record_reply(warm, 'Maybe')
    warm.amount = 1000
    picked = ti_lead(phone='+919800000803', name='Picked Pooja')
    picked.likelihood, picked.likelihood_manual = 'cold', True
    crm.record_reply(picked, 'Yes yes')
    crm.mark_event(picked, 'Q')
    _db.session.commit()
    r = turn_on(client, admin_user)
    assert r.status_code == 302
    h, w, p = fresh(hot.id), fresh(warm.id), fresh(picked.id)
    assert h.score == 20 + 25 + 20 + 10 and h.likelihood == 'hot'          # replied, quote, trip in 9 days, value
    assert w.score == 30 and w.likelihood == 'warm'                        # replied, value
    assert p.score == 45 and p.likelihood == 'cold'                        # a person picked it: it stays
    # the lead card says why
    card = words(client.get('/admin/crm/lead/%d' % hot.id).get_data(as_text=True))
    assert 'Score 75 — They replied +20 · A quote was sent +25 · trip in 9 days +20 · It has a value +10' in card
    assert 'Picked by a person' in words(client.get('/admin/crm/lead/%d' % picked.id).get_data(as_text=True))
    # clearing the pick: the score decides again (after the commit)
    client.post('/admin/crm/lead/%d/update' % picked.id, json={'likelihood': ''})
    p = fresh(picked.id)
    assert p.likelihood_manual is False and p.likelihood == 'warm'
    # a person's new pick sticks
    client.post('/admin/crm/lead/%d/update' % picked.id, json={'likelihood': 'hot'})
    p = fresh(picked.id)
    assert p.likelihood == 'hot' and p.likelihood_manual is True
    # the board shows a small chip
    assert 'class="sc-chip"' in client.get('/admin/crm/?p=ti-standard').get_data(as_text=True)


def test_a_reply_rescores_the_lead_after_the_commit(app):
    crm.ensure_defaults()
    turn_on()
    lead = ti_lead()
    assert fresh(lead.id).score == 0 and fresh(lead.id).likelihood == 'cold'
    l = fresh(lead.id)
    crm.record_reply(l, 'Interested')
    _db.session.commit()
    assert fresh(lead.id).score == 20
    l = fresh(lead.id)
    crm.mark_event(l, 'PLS')
    assert fresh(lead.id).score == 50 and fresh(lead.id).likelihood == 'warm'


def test_the_signals_are_the_registrys_own(app):
    crm.ensure_defaults()
    a = ti_lead(phone='+919800000901')
    b = ti_lead(phone='+919800000902')
    crm.record_reply(a, 'hi')
    crm.log_touch(b, 'form', 'in', body='a form is not a reply')
    crm.mark_event(a, 'Q')
    _db.session.commit()
    assert crm_numbers.leads_replied([a.id, b.id]) == {a.id}
    assert crm_numbers.leads_marked('Q', [a.id, b.id]) == {a.id}
    # the Replied number counts exactly the same leads
    since, until = datetime.utcnow() - timedelta(days=1), datetime.utcnow() + timedelta(minutes=1)
    assert crm_numbers.compute('replied', since, until) == 1


def test_no_reply_for_days_and_a_source_and_a_detail(app):
    crm.ensure_defaults()
    src = CrmSource.query.filter_by(key='ti-quote').one()
    for name, pts, sig, args in (('Quiet a week', -15, 'no_reply_days', {'days': 7}),
                                 ('From the quote form', 5, 'source_is', {'source_id': src.id}),
                                 ('Insurance', 7, 'field_is', {'field': 'product', 'value': 'ti'})):
        _db.session.add(CrmScoreRule(name=name, points=pts, signal=sig, args=args, active=True))
    _db.session.commit()
    crm_scoring.save_state(on=True, seeded=True)
    old = ti_lead(phone='+919800001001')
    old.created_at = datetime.utcnow() - timedelta(days=10)
    _db.session.commit()
    got = crm_scoring.compute([fresh(old.id)])[old.id]
    assert dict((w, p) for w, p in got[1]) == {'Quiet a week': -15, 'From the quote form': 5, 'Insurance': 7}
    assert got[0] == 0                                       # never below 0


def test_the_night_run_is_once_a_day_and_only_where_it_is_on(app):
    crm.ensure_defaults()
    lead = ti_lead()
    assert jobs.run_all().get('crm_scores_changed') is None          # off: nothing
    turn_on()
    today = (datetime.utcnow() + crm_scoring.IST).date()
    l = fresh(lead.id)
    l.departure_date = today + timedelta(days=5)
    _db.session.commit()
    _db.session.execute(CrmLead.__table__.update().where(CrmLead.__table__.c.id == lead.id).values(score=0))
    _db.session.commit()
    out = jobs.run_all()
    assert out.get('crm_scores_changed') == 1 and fresh(lead.id).score == 20
    assert crm_scoring.nightly() == {}                               # once a day


def test_the_tab_edits_lines_and_thresholds(app, client, admin_user):
    crm.ensure_defaults()
    login(client, admin_user.email)
    client.get('/admin/crm/pipelines?tab=scoring')
    r = client.post('/admin/crm/pipelines/scoring/line', data={'signal': 'trip_within_days', 'days': '3', 'points': '35',
                                                              'name': 'Travels this week', 'active': '1'})
    assert r.status_code == 302
    line = CrmScoreRule.query.filter_by(name='Travels this week').one()
    assert line.args == {'days': 3} and line.points == 35 and line.active
    r = client.post('/admin/crm/pipelines/scoring/line', data={'signal': 'replied', 'points': '0'}, follow_redirects=True)
    assert 'Points go from -100 to 100' in r.get_data(as_text=True)
    client.post('/admin/crm/pipelines/scoring/line/%d/delete' % line.id)
    assert CrmScoreRule.query.filter_by(name='Travels this week').count() == 0
    r = client.post('/admin/crm/pipelines/scoring', data={'hot': '30', 'warm': '50'}, follow_redirects=True)
    assert 'must start below' in r.get_data(as_text=True) and crm_scoring.state()['hot'] == 60
    client.post('/admin/crm/pipelines/scoring', data={'hot': '70', 'warm': '40'})
    assert (crm_scoring.state()['hot'], crm_scoring.state()['warm']) == (70, 40)
    client.post('/admin/crm/pipelines/scoring/switch', data={'on': '0'})
    assert crm_scoring.is_on() is False


def test_scoring_in_one_workspace_leaves_the_other_alone(app):
    a = access.ensure_defaults()
    b = access.create_workspace('Bee Care')
    _db.session.commit()
    for ws in (a, b):
        with crm_scope.use(ws.id):
            crm.ensure_defaults()
    with crm_scope.use(a.id):
        crm_scoring.ensure_starter(a.id)
        crm_scoring.save_state(a.id, on=True)
    with crm_scope.use(b.id):
        assert crm_scoring.is_on(b.id) is False
    la = crm.capture('ti-quote', name='Ay', phone='+919800001101', utm={}, workspace_id=a.id)
    lb = crm.capture('ti-quote', name='Bee', phone='+919800001102', utm={}, workspace_id=b.id)
    for l in (la, lb):
        crm.record_reply(fresh(l.id), 'yes')
        _db.session.commit()
    assert fresh(la.id).score == 20 and fresh(lb.id).score is None and fresh(lb.id).likelihood is None
    # B's lines are its own (none were written for it)
    assert CrmScoreRule.query.execution_options(all_workspaces=True).filter_by(workspace_id=b.id).count() == 0
