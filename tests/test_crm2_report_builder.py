"""Sales CRM 2.0, run 4b -- the report builder.

    choices    only whitelisted keys reach a query; rubbish is an error in plain words or falls back to a default
    numbers    leads / people / activities, by one or two groups, counted, summed, averaged, in the reporting currency
    filters    dates on created / closed / close date, pipeline, person, status, source
    safe       removed leads never count; a scoped viewer's report, a saved one and a pinned one hold only their leads
    saved      save, share, pin to Sales results (in saved order), move, delete; download for Excel
    page       in Overview after Forecast, with its "How this works" bullets; the chart is HTML and CSS
"""
import csv
import io
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from flask import g

from conftest import login, logout, make_user
from app import db as _db
from app.models import (CrmLead, CrmPerson, CrmSavedReport, CrmTask, CrmTouchpoint, WorkspaceRole, WorkspaceTeam)
from app.services import access, crm, crm_bin, crm_money
from app.services import crm_report_builder as rb

from test_crm_wa_sync_engine import ti_lead

TODAY = (datetime.utcnow() + crm.IST).date()


def as_user(client, user):
    logout(client)
    g.pop('_login_user', None)
    _db.session.expire_all()
    return login(client, user.email)


def words(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


@pytest.fixture
def agents(app):
    return make_user('asha@test.com', 'asha', role='cs'), make_user('bela@test.com', 'bela', role='cs')


def mk(name, phone, owner, amount=None, currency='INR', **kw):
    l = ti_lead(phone=phone, name=name)
    l.owner_id = owner.id if owner is not None else None
    l.amount, l.currency = (Decimal(amount) if amount is not None else None), (currency if amount is not None else None)
    for k, v in kw.items():
        setattr(l, k, v)
    CrmTask.query.filter_by(lead_id=l.id).delete()
    _db.session.commit()
    return l


def cfg(**kw):
    return rb.clean_config(kw)


def table(res):
    return {r['label']: r['total'] for r in res['rows']}


@pytest.fixture
def world(app, agents, admin_user):
    asha, bela = agents
    crm_money.set_rate('USD', '80')
    a1 = mk('Report Ria', '+919876700001', asha, '1000', 'INR')
    a2 = mk('Report Raj', '+919876700002', asha, '2000', 'INR')
    b1 = mk('Report Ravi', '+919876700003', bela, '10', 'USD')
    b2 = mk('Report Rani', '+919876700004', bela, None)
    n1 = mk('Report Nobody', '+919876700005', None, '500', 'INR')
    won_stage = next(s for s in a2.pipeline.stages if s.kind == 'won')
    crm.move_stage(a2, won_stage, user=asha, reason='Paid')
    a2.revenue = Decimal('400')
    a1.person.country, b1.person.country = 'IN', 'US'
    CrmTask.query.delete()                           # the follow-ups planned for the new leads are not what is counted here
    _db.session.commit()
    return dict(asha=asha, bela=bela, a1=a1, a2=a2, b1=b1, b2=b2, n1=n1, admin=admin_user)


# ====================================================================================== the choices

def test_only_whitelisted_choices_get_through(app):
    ok = rb.clean_config({'what': 'leads', 'measure': 'value', 'group': 'stage', 'group2': 'owner', 'pipeline': '12',
                          'owner': 'mine', 'status': 'won', 'from': '2026-01-01', 'to': '2026-02-01'})
    assert ok['group'] == 'stage' and ok['group2'] == 'owner' and ok['pipeline'] == '12' and ok['status'] == 'won'
    for bad in ({'what': 'users'}, {'measure': 'sum(amount)'}, {'what': 'people', 'measure': 'value'},
                {'group': 'owner', 'group2': 'owner'}, {'group2': 'password'}, {'from': '2026-13-45'},
                {'from': '2026-05-01', 'to': '2026-01-01'}, {'status': "won' OR 1=1"}):
        with pytest.raises(rb.ReportError):
            rb.clean_config(bad)
    # an unknown "group by" falls back to the first choice; ids are digits only, whatever was typed
    got = rb.clean_config({'group': 'owner; DROP TABLE crm_leads', 'pipeline': '1 OR 1=1', 'source': "x'", 'owner': '7;--'})
    assert got['group'] == 'owner' and got['pipeline'] == '' and got['source'] == '' and got['owner'] == ''


def test_the_groups_are_the_ones_the_spec_names(app):
    assert list(rb.GROUPS['leads']) == ['owner', 'team', 'stage', 'phase', 'pipeline', 'product', 'source', 'forecast',
                                        'rating', 'country', 'lost_reason', 'created_month', 'closed_month', 'close_month',
                                        'campaign']                       # run 5b: the campaign (Marketing activities)
    assert 'channel' in rb.GROUPS['activities'] and list(rb.MEASURES) == ['count', 'value', 'revenue', 'average']


def test_a_hostile_value_never_reaches_the_database(app, client, admin_user):
    as_user(client, admin_user)
    page = client.get("/admin/crm/reports/build?run=1&what=leads&group=owner';DROP TABLE crm_leads;--&pipeline=1%27%20OR%201=1")
    assert page.status_code == 200
    assert CrmLead.query.count() >= 0
    bad = client.get("/admin/crm/reports/build?run=1&what=leads&measure=x%27;DROP%20TABLE%20crm_leads")
    assert bad.status_code == 200 and 'Choose how to measure it' in bad.get_data(as_text=True)


# ====================================================================================== the numbers

def test_count_leads_by_owner_money_in_the_reporting_currency(app, world):
    admin = world['admin']
    res = rb.run(cfg(what='leads', measure='count', group='owner'), admin)
    assert table(res) == {'Asha': 2, 'Bela': 2, 'Nobody yet': 1} and res['total'] == 5
    res = rb.run(cfg(what='leads', measure='value', group='owner'), admin)
    assert table(res) == {'Asha': Decimal('3000'), 'Bela': Decimal('800'), 'Nobody yet': Decimal('500')}
    assert res['unit'] == 'money' and res['currency'] == 'INR'
    res = rb.run(cfg(what='leads', measure='average', group='owner'), admin)
    assert res['rows'][0]['label'] == 'Asha' and table(res)['Asha'] == Decimal('1500')
    assert table(res)['Bela'] == Decimal('800')                       # Rani has no value and is left out of the average
    res = rb.run(cfg(what='leads', measure='revenue', group='status'.replace('status', 'forecast')), admin)
    assert sum(table(res).values()) == Decimal('1000') + Decimal('400') + Decimal('800') + Decimal('500')


def test_two_groups_make_a_table_with_columns(app, world):
    res = rb.run(cfg(what='leads', measure='count', group='owner', group2='forecast'), world['admin'])
    assert res['cols'] and 'Closed won' in res['cols']
    row = {r['label']: dict(zip(res['cols'], r['cells'])) for r in res['rows']}
    assert row['Asha']['Closed won'] == 1 and sum(row['Asha'].values()) == 2
    assert sum(res['col_totals']) == res['total'] == 5


def test_groups_by_stage_phase_pipeline_product_source_rating_country_lost_and_months(app, world):
    admin = world['admin']
    lost = world['b2']
    lost_stage = next(s for s in lost.pipeline.stages if s.kind == 'lost')
    crm.move_stage(lost, lost_stage, user=world['bela'], fallout_reason='Too expensive')
    world['a1'].likelihood = 'hot'
    CrmTask.query.delete()
    _db.session.commit()
    for group in rb.GROUPS['leads']:
        res = rb.run(cfg(what='leads', group=group), admin)
        assert res['total'] == 5, group
    assert table(rb.run(cfg(group='lost_reason'), admin))['Too expensive'] == 1
    by_country = table(rb.run(cfg(group='country'), admin))
    assert by_country['India'] == 4 and by_country['United States'] == 1
    assert table(rb.run(cfg(group='rating'), admin))['Ready to buy'] == 1
    phases = table(rb.run(cfg(group='phase'), admin))
    assert phases['Won'] == 1 and phases['Lost'] == 1
    months = [r['label'] for r in rb.run(cfg(group='created_month'), admin)['rows']]
    assert months == [TODAY.strftime('%b %Y')]
    assert not any(re.fullmatch(r'[A-Z]{2}', l) for l in table(rb.run(cfg(group='country'), admin)))       # no codes on screen


def test_filters_narrow_the_leads(app, world):
    admin = world['admin']
    crm_cfg = lambda **kw: rb.run(cfg(group='owner', **kw), admin)['total']       # noqa: E731
    assert crm_cfg() == 5
    assert crm_cfg(status='won') == 1 and crm_cfg(status='open') == 4
    assert crm_cfg(owner=str(world['asha'].id)) == 2 and crm_cfg(owner='none') == 1
    assert crm_cfg(pipeline=str(world['a1'].pipeline_id)) == 5 and crm_cfg(pipeline='9999') == 0
    assert crm_cfg(source=str(world['a1'].source_id)) == 5
    assert crm_cfg(**{'from': TODAY.isoformat(), 'to': TODAY.isoformat()}) == 5
    assert crm_cfg(**{'from': (TODAY + timedelta(days=1)).isoformat()}) == 0
    assert crm_cfg(date='closed', **{'from': TODAY.isoformat()}) == 1                      # only the won one has a closed day
    world['a1'].close_date = date(2031, 3, 5)
    _db.session.commit()
    assert crm_cfg(date='close_date', **{'from': '2031-03-01', 'to': '2031-03-31'}) == 1


def test_people_and_activities(app, world):
    admin = world['admin']
    world['a1'].person.consent_whatsapp = True
    _db.session.commit()
    res = rb.run(cfg(what='people', group='permission'), admin)
    assert table(res) == {'Agreed to WhatsApp messages': 1, 'No permission yet': 4}
    assert rb.run(cfg(what='people', group='country'), admin)['total'] == 5
    crm.log_touch(world['a1'], 'call', 'out', body='Called', user=world['asha'])
    crm.log_touch(world['a1'], 'call', 'out', body='Called again', user=world['asha'])
    crm.log_touch(world['b1'], 'email', 'out', body='Wrote', user=world['bela'])
    t = CrmTask(lead=world['b1'], title='Follow up', channel='call', due_at=datetime.utcnow(), owner_id=world['bela'].id,
                status='open', kind='todo')
    _db.session.add(t)
    _db.session.commit()
    res = rb.run(cfg(what='activities', group='owner'), admin)
    assert table(res)['Asha'] == 2 and table(res)['Bela'] == 2
    chan = table(rb.run(cfg(what='activities', group='channel'), admin))
    assert chan['Call'] == 2 and chan['E-mail'] == 1 and chan['Task'] == 1 and 'System' not in chan and 'Form' not in chan
    assert rb.run(cfg(what='activities', group='owner', owner=str(world['asha'].id)), admin)['total'] == 2


def test_a_currency_with_no_rate_is_named_and_counts_as_nothing(app, world):
    world['b1'].currency = 'CHF'
    _db.session.commit()
    res = rb.run(cfg(group='owner', measure='value'), world['admin'])
    assert any('CHF' in n for n in res['notes']) and table(res)['Bela'] == Decimal('0')


# ====================================================================================== removed and hidden leads

def test_removed_leads_never_count(app, world):
    admin = world['admin']
    assert rb.run(cfg(group='owner'), admin)['total'] == 5
    crm_bin.remove(world['a1'], admin)
    assert rb.run(cfg(group='owner'), admin)['total'] == 4
    crm.log_touch(world['a1'], 'call', 'out', body='from a removed lead', user=world['asha'])
    _db.session.commit()
    assert rb.run(cfg(what='activities', group='owner'), admin)['total'] == 0
    crm_bin.restore(crm_bin.get_removed(world['a1'].id), admin)
    assert rb.run(cfg(what='activities', group='owner'), admin)['total'] == 1


def scoped(app):
    ws = access.ensure_defaults()
    role = WorkspaceRole(workspace_id=ws.id, name='Own only', pages=sorted(access.CS_ROLE_PAGES | {'crm_insights', 'crm_export'}),
                         crm_scope='own')
    _db.session.add(role)
    _db.session.flush()
    ws.roles.append(role)
    asha = make_user('scoped@test.com', 'scoped', role='cs')
    access.add_member(ws, asha, role=role)
    _db.session.commit()
    access._cache().clear()
    return asha


def test_a_scoped_viewer_gets_only_their_own_numbers_in_every_report(app, client, world):
    sc = scoped(app)
    mine = mk('Scoped Mine', '+919876700011', sc, '700')
    free = mk('Scoped Free', '+919876700012', None, '50')
    crm.log_touch(mine, 'call', 'out', body='x', user=sc)
    crm.log_touch(world['b1'], 'call', 'out', body='hidden', user=world['bela'])
    crm.log_touch(world['b2'], 'note', 'none', body='hidden note')
    person_only = CrmTask(person=world['b1'].person, title='Hidden task', channel='call', due_at=datetime.utcnow(),
                          owner_id=world['bela'].id, status='open', kind='todo')
    _db.session.add(person_only)
    _db.session.commit()
    for what in ('leads', 'people', 'activities'):
        full = rb.run(cfg(what=what, group='created_month'), world['admin'])['total']
        mine_only = rb.run(cfg(what=what, group='created_month'), sc)['total']
        assert 0 < mine_only < full, what
    assert rb.run(cfg(what='leads', group='owner'), sc)['total'] == 3                  # theirs and the two unassigned ones
    assert table(rb.run(cfg(what='leads', measure='value', group='owner'), sc)) == {'Scoped': Decimal('700'), 'Nobody yet': Decimal('550')}
    as_user(client, sc)
    page = words(client.get('/cs/crm/reports/build?run=1&what=leads&group=owner').get_data(as_text=True))
    assert 'Scoped' in page and 'Asha' not in page.split('Saved reports')[0].split('Number of leads')[1] and 'Bela' not in page


def test_a_saved_and_a_pinned_report_hold_the_viewers_leads_only(app, client, world):
    sc = scoped(app)
    mk('Scoped Own Lead', '+919876700021', sc, '300')
    rep = rb.create(world['admin'], 'Everything by owner', cfg(group='owner', measure='value'), shared=True)
    rb.set_pinned(world['admin'], rep.id, True)
    pinned_admin = rb.pinned_for(world['admin'])
    pinned_scoped = rb.pinned_for(sc)
    assert [p['report'].id for p in pinned_scoped] == [rep.id]
    assert pinned_admin[0]['result']['total'] > pinned_scoped[0]['result']['total']
    assert set(table(pinned_scoped[0]['result'])) <= {'Scoped', 'Nobody yet'}
    as_user(client, sc)
    page = client.get('/cs/crm/reports/build?run=1&what=leads&group=owner').get_data(as_text=True)
    assert 'Everything by owner' in page                                              # a shared report is listed for them
    assert 'Bela' not in words(page)


# ====================================================================================== saved reports

def test_save_share_pin_move_and_delete(app, client, world):
    admin, asha = world['admin'], world['asha']
    as_user(client, admin)
    save = lambda name, **extra: client.post('/admin/crm/reports/save', data={'name': name, 'c_what': 'leads', 'c_measure': 'count',   # noqa: E731
                                                                                'c_group': 'stage', **extra})
    assert save('By stage').status_code == 302
    assert save('By stage').status_code == 302                                         # same name: refused, nothing doubled
    save('By owner', c_group='owner', shared='on')
    assert [r.name for r in CrmSavedReport.query.order_by(CrmSavedReport.id)] == ['By stage', 'By owner']
    one, two = CrmSavedReport.query.order_by(CrmSavedReport.id).all()
    assert one.config['group'] == 'stage' and not one.shared and two.shared
    client.post('/admin/crm/reports/%d/pin' % one.id, data={'pinned': '1'})
    client.post('/admin/crm/reports/%d/pin' % two.id, data={'pinned': '1'})
    _db.session.expire_all()
    assert [p['report'].name for p in rb.pinned_for(admin)] == ['By stage', 'By owner']
    client.post('/admin/crm/reports/%d/move' % two.id, data={'dir': 'up'})
    _db.session.expire_all()
    assert [p['report'].name for p in rb.pinned_for(admin)] == ['By owner', 'By stage']
    # on Sales results, at the bottom, in that order
    html = client.get('/admin/crm/insights').get_data(as_text=True)
    blocks = html.split('class="card rb-pinned"')
    assert len(blocks) == 3 and 'By owner' in blocks[1] and 'By stage' in blocks[2]
    assert html.index('Why we lost leads') < html.index('class="card rb-pinned"')
    # a private report is another person's secret; a shared one is listed
    as_user(client, asha)
    assert [r.name for r in rb.listing(asha)['shared']] == ['By owner']
    assert [p['report'].name for p in rb.pinned_for(asha)] == ['By owner']             # the private pinned one does not show
    assert rb.get_for(asha, one.id) is None
    with pytest.raises(rb.SavedError):
        rb.delete(asha, two.id)
    as_user(client, admin)
    client.post('/admin/crm/reports/%d/pin' % two.id, data={'pinned': '0'})
    client.post('/admin/crm/reports/%d/delete' % one.id)
    _db.session.expire_all()
    assert rb.pinned_for(admin) == [] and CrmSavedReport.query.count() == 1


def test_a_pinned_report_that_no_longer_runs_does_not_break_sales_results(app, client, world):
    rep = rb.create(world['admin'], 'Broken', cfg(group='owner'), shared=False)
    rep.config = {'what': 'galaxies'}
    rep.pinned = True
    _db.session.commit()
    as_user(client, world['admin'])
    assert client.get('/admin/crm/insights').status_code == 200


def test_download_for_excel_is_the_table_on_the_screen(app, client, world):
    as_user(client, world['admin'])
    r = client.get('/admin/crm/reports/build.csv?what=leads&measure=value&group=owner&reason=backup')
    assert r.status_code == 200 and 'text/csv' in r.headers['Content-Type']
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True).lstrip('﻿'))))
    assert rows[0] == ['Total value of leads by who looks after it']
    assert rows[1][0] == 'Who looks after it' and 'INR' in rows[1][1]
    body = {x[0]: x[1] for x in rows[2:]}
    assert body['Asha'] == '3000' and body['Total'] == '4300'
    bad = client.get('/admin/crm/reports/build.csv?what=nope&reason=backup', follow_redirects=True)
    assert 'Choose what to count' in bad.get_data(as_text=True)


# ====================================================================================== the page

def test_the_page_is_a_line_of_reports_and_comes_with_sales_results(app):
    page = access.PAGES['crm_report_builder']
    assert 'crm_insights' in page['with'] and 'crm.report_builder' in page['endpoints'] and page['nav']
    reports = {s['key']: s for s in access.SECTIONS}['reports']['pages']
    # then the site's own dashboards, and the Promotion dashboard's designer (2026-10-29)
    assert reports[-4:] == ('crm_report_builder', 'dashboard', 'promo', 'mkt_design')
    assert access.PAGES['crm_export']['section'] == 'setup'             # Downloads: Set-up › Data


def test_the_page_explains_itself_and_draws_the_chart_without_a_library(app, client, world):
    as_user(client, world['admin'])
    html = client.get('/admin/crm/reports/build?run=1&what=leads&measure=count&group=owner&group2=forecast').get_data(as_text=True)
    assert '(?) How this works' in html and 'Report builder' in html
    assert 'rb-bar' in html and 'rb-table' in html and 'Download for Excel' in html
    assert not re.search(r'chart(\.min)?\.js|d3\.|plotly|echarts|highcharts', html, re.I)
    plain = words(html)
    assert 'Number of leads by who looks after it and counts in the forecast as'.lower() in plain.lower() or 'Number of leads' in plain
    assert 'Removed leads are never counted' in plain
    first = client.get('/admin/crm/reports/build').get_data(as_text=True)
    assert 'Show the report' in first and 'rb-bar' not in first


def test_the_menu_shows_the_page_for_whoever_holds_sales_results(app, client, world):
    sc = scoped(app)
    as_user(client, sc)
    assert client.get('/cs/crm/reports/build').status_code == 200
    plain = make_user('plain@test.com', 'plain', role='cs')
    ws = access.ensure_defaults()
    access.add_member(ws, plain, role=access.system_role(ws, 'cs'))
    _db.session.commit()
    as_user(client, plain)
    assert client.get('/cs/crm/reports/build').status_code in (302, 403, 404)
