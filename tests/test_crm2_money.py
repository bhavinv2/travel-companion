"""Sales CRM 2.0, phase 1 -- money, forecasts and targets.

    data       what we earn on a product, exchange rates, the forecast category of a stage and of a lead
    defaults   a new lead's amount and close date; a lead won today closes today
    lead       the dialog amount, the value form (a history line, nothing sent to the customer)
    leads      card value, column totals, list columns and filters, the Excel download
    set-up     product money fields, exchange rates, the stage's forecast and chance
    targets    save, upsert, copy last month, a team lead's reach
    forecast   the numbers for a small team, who sees whom, the links, the My day bar, Results
"""
import csv
import io
import re
from html import unescape
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import (ActivityEvent, CrmCurrencyRate, CrmLead, CrmPipeline, CrmProduct, CrmStage, CrmTarget,
                        CrmTouchpoint, WorkspaceRole, WorkspaceTeam)
from app.services import access, crm, crm_editor, crm_money, crm_products, settings

from test_crm_wa_sync_engine import ti_lead

D = Decimal


def words(html):
    html = re.sub(r'<(script|style).*?</\1>', '', html, flags=re.S)
    return ' '.join(unescape(re.sub(r'<[^>]+>', ' ', html)).split())


def table_words(html):
    """The words in the tables only (not the pickers above them)."""
    return words(' '.join(re.findall(r'<table.*?</table>', html, flags=re.S)))


def stage(key, pipe='ti-standard'):
    crm.ensure_defaults()
    return CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == pipe, CrmStage.key == key).one()


def product(code='TI', **values):
    crm.ensure_defaults()
    p = CrmProduct.query.filter_by(code=code).one()
    for k, v in values.items():
        setattr(p, k, v)
    _db.session.commit()
    crm_products.invalidate()
    return p


def today_ist():
    return (datetime.utcnow() + crm.IST).date()


def member(email, name, role='cs'):
    """A person in the workspace with the Sales & service role (or the named system role)."""
    ws = access.ensure_defaults()
    u = make_user(email, name, role='cs')
    r = access.system_role(ws, 'cs') if role == 'cs' else WorkspaceRole.query.filter_by(
        workspace_id=ws.id, name=role).one()
    access.add_member(ws, u, role=r)
    _db.session.commit()
    access._cache().clear()
    return u


_phone = [0]


def lead_of(owner, amount=None, stage_key=None, close=None, currency='INR', **kw):
    _phone[0] += 1
    lead = ti_lead(phone='+9198100%05d' % _phone[0], name='Lead %d' % _phone[0], **kw)
    lead.owner_id = owner.id if owner else None
    lead.amount = D(str(amount)) if amount is not None else None
    lead.currency = currency if amount is not None else None
    lead.close_date = close
    if stage_key:
        crm.move_stage(lead, stage(stage_key), plan=False, sync=False)
        lead.close_date = close
    _db.session.commit()
    return lead


# ================================================================================================ data

def test_what_we_earn_on_a_product_whole_fixed_or_a_percentage(app):
    whole = CrmProduct(code='W1', name='W', currency='INR')
    fixed = CrmProduct(code='F1', name='F', currency='INR', revenue_kind='fixed', revenue_value=D('1500'))
    pct = CrmProduct(code='P1', name='P', currency='INR', revenue_kind='percent', revenue_value=D('12.5'))
    assert crm_money.revenue_for(D('20000'), 'INR', whole) == D('20000')
    assert crm_money.revenue_for(D('20000'), 'INR', fixed) == D('1500.00')
    assert crm_money.revenue_for(D('20000'), 'INR', pct) == D('2500.00')
    assert crm_money.revenue_for(None, 'INR', pct) is None
    assert crm_money.revenue_for(D('20000'), 'INR', None) == D('20000')


def test_a_fixed_amount_is_converted_into_the_leads_currency_and_a_missing_rate_gives_nothing(app):
    fixed = CrmProduct(code='F2', name='F', currency='INR', revenue_kind='fixed', revenue_value=D('1500'))
    _db.session.add(CrmCurrencyRate(code='USD', rate=D('83.5')))
    _db.session.commit()
    assert crm_money.revenue_for(D('400'), 'USD', fixed) == (D('1500') / D('83.5')).quantize(D('0.01'))
    assert crm_money.revenue_for(D('400'), 'EUR', fixed) is None             # no rate for euros


def test_money_is_added_up_in_the_reporting_currency_and_a_missing_rate_counts_as_nothing(app):
    _db.session.add(CrmCurrencyRate(code='USD', rate=D('80')))
    _db.session.commit()
    rates = crm_money.rates()
    assert crm_money.to_base(D('10'), 'USD', rates) == D('800')
    assert crm_money.to_base(D('10'), 'INR', rates) == D('10')
    assert crm_money.to_base(D('10'), 'GBP', rates) == D('0')
    assert 'GBP' in crm_money.rate_warning({'GBP': 3}) and '3 leads in GBP' in crm_money.rate_warning({'GBP': 3})
    settings.set_setting('crm.currency', 'USD')
    assert crm_money.reporting_currency() == 'USD'
    assert crm_money.to_base(D('10'), 'USD') == D('10')


def test_money_reads_the_way_staff_write_it(app):
    assert crm_money.money(D('120000'), 'INR') == '₹1,20,000'
    assert crm_money.money(D('1234567'), 'INR') == '₹12,34,567'
    assert crm_money.money_c(D('120000'), 'INR') == '₹1.2 L'
    assert crm_money.money_c(D('12000'), 'INR') == '₹12,000'
    assert crm_money.money(D('350'), 'USD') == '$350'
    assert crm_money.money(None, 'INR') == ''


def test_a_stage_counts_in_the_forecast_by_itself_unless_it_says_otherwise(app):
    crm.ensure_defaults()
    assert crm_money.stage_forecast(stage('cold')) == 'pipeline' and crm_money.stage_probability(stage('cold')) == 10
    assert crm_money.stage_forecast(stage('prospect')) == 'pipeline' and crm_money.stage_probability(stage('prospect')) == 25
    assert crm_money.stage_forecast(stage('quoted')) == 'best_case' and crm_money.stage_probability(stage('quoted')) == 50
    # the payment-link stage of the seeded travel insurance pipeline (button code PLS)
    assert stage('pipeline').button_code == 'PLS'
    assert crm_money.stage_forecast(stage('pipeline')) == 'commit' and crm_money.stage_probability(stage('pipeline')) == 80
    assert crm_money.stage_forecast(stage('customer')) == 'won' and crm_money.stage_probability(stage('customer')) == 100
    assert crm_money.stage_forecast(stage('prospect_fallout')) == 'lost'
    # a button that mentions payment commits too, whatever its code
    q = stage('quoted')
    q.button_code, q.button_label = 'X9', 'Payment promised'
    assert crm_money.stage_forecast(q) == 'commit'
    q.button_code, q.button_label = 'Q', 'I sent the quote'
    # the stage overrides
    q.forecast, q.probability = 'pipeline', 33
    _db.session.commit()
    assert crm_money.stage_forecast(q) == 'pipeline' and crm_money.stage_probability(q) == 33


def test_a_lead_follows_its_stage_unless_the_agent_overrides_it(app):
    lead = lead_of(None, 1000, 'pipeline')
    assert lead.forecast_category == 'commit' and lead.win_chance == 80 and lead.expected == D('800.00')
    lead.forecast = 'best_case'
    assert lead.forecast_category == 'best_case'
    lead.forecast = 'bogus'
    assert lead.forecast_category == 'commit'                                  # rubbish falls back to the stage
    crm.move_stage(lead, stage('customer'), plan=False, sync=False)
    lead.forecast = 'pipeline'
    assert lead.forecast_category == 'won' and lead.win_chance == 100 and lead.expected == D('1000.00')


# ================================================================================================ defaults

def test_a_new_lead_takes_the_products_price_and_a_close_date(app):
    product(price=D('18500'), revenue_kind='percent', revenue_value=D('10'), close_days=None)
    lead = ti_lead(phone='+919810000001', name='Priced')
    assert lead.amount == D('18500.00') and lead.currency == 'INR' and lead.revenue == D('1850.00')
    assert lead.close_date == lead.created_at.date() + timedelta(days=14)


def test_the_close_date_follows_the_trip_or_the_products_usual_days(app):
    product(price=D('1000'), close_days=30)
    far = date.today() + timedelta(days=60)
    trip = ti_lead(phone='+919810000002', name='Trip', departure_date=far)
    assert trip.close_date == far - timedelta(days=3)
    soon = ti_lead(phone='+919810000003', name='Soon', departure_date=date.today() + timedelta(days=1))
    assert soon.close_date == date.today()                                     # never before today
    plain = ti_lead(phone='+919810000004', name='Plain')
    assert plain.close_date == plain.created_at.date() + timedelta(days=30)


def test_an_importer_gets_no_amount_and_no_close_date(app):
    product(price=D('18500'))
    lead = ti_lead(phone='+919810000005', name='Imported', imported=True, plan=False, notify=False, sync=False)
    assert lead.amount is None and lead.close_date is None and lead.currency is None


def test_asking_again_keeps_the_amount_already_on_the_lead(app):
    product(price=D('18500'))
    lead = ti_lead(phone='+919810000006', name='Again')
    lead.amount = D('9000')
    _db.session.commit()
    again = ti_lead(phone='+919810000006', name='Again')
    assert again.id == lead.id and again.amount == D('9000.00')


def test_winning_a_lead_without_a_close_date_closes_it_today_and_leaves_the_value_alone(app):
    lead = lead_of(None, None)
    lead.close_date = None
    crm.move_stage(lead, stage('customer'), plan=False, sync=False)
    _db.session.commit()
    assert lead.status == 'won' and lead.close_date == today_ist() and lead.amount is None


def test_changing_the_product_recalculates_what_we_earn(app):
    product('TI', revenue_kind=None)
    sh = product('SH', revenue_kind='percent', revenue_value=D('50'))
    lead = lead_of(None, 2000)
    assert crm_money.recalc_revenue(lead) == D('2000')
    crm.set_product(lead, 'SH')
    assert lead.revenue == D('1000.00') and sh.code == 'SH'


# ================================================================================================ the lead page

def test_the_quote_dialog_amount_is_saved_and_noted(app, client, admin_user):
    lead = lead_of(admin_user, 5000)
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/event' % lead.id, json={'code': 'Q', 'amount': '18,500'})
    assert r.status_code == 200 and r.get_json()['stage'] == 'Quoted'
    _db.session.refresh(lead)
    assert lead.amount == D('18500.00')
    lines = [t.body for t in CrmTouchpoint.query.filter_by(lead_id=lead.id, channel='system')]
    assert any(l.startswith('Value ₹5,000 → ₹18,500') for l in lines)
    assert client.post('/admin/crm/lead/%d/event' % lead.id, json={'code': 'Q', 'amount': 'lots'}).status_code == 400


def test_moving_into_the_quote_stage_can_change_the_amount_too(app, client, admin_user):
    lead = lead_of(admin_user, 5000)
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/move' % lead.id,
                    json={'stage_id': stage('quoted').id, 'log_milestone': True, 'amount': '7000'})
    assert r.status_code == 200 and r.get_json()['logged'] is True
    _db.session.refresh(lead)
    assert lead.amount == D('7000.00')


def test_changing_the_value_writes_a_history_line_and_sends_nothing(app, client, admin_user, monkeypatch):
    lead = lead_of(admin_user, 12000)
    login(client, admin_user.email)
    marked, sent = [], []
    monkeypatch.setattr(crm, 'mark_wa_due', lambda *a, **k: marked.append(a) or False)
    monkeypatch.setattr(crm, 'send_whatsapp', lambda *a, **k: sent.append(a))
    before = CrmTouchpoint.query.filter(CrmTouchpoint.lead_id == lead.id, CrmTouchpoint.direction == 'out').count()
    r = client.post('/admin/crm/lead/%d/money' % lead.id,
                    json={'amount': '18500', 'currency': 'INR', 'close_date': '2031-11-12', 'forecast': 'commit'})
    assert r.status_code == 200 and len(r.get_json()['changed']) == 3
    _db.session.refresh(lead)
    assert lead.amount == D('18500.00') and lead.close_date == date(2031, 11, 12) and lead.forecast == 'commit'
    line = CrmTouchpoint.query.filter_by(lead_id=lead.id, channel='system', body='Value ₹12,000 → ₹18,500').one()
    assert line.direction == 'none'
    assert not marked and not sent
    assert CrmTouchpoint.query.filter(CrmTouchpoint.lead_id == lead.id,
                                      CrmTouchpoint.direction == 'out').count() == before
    # back to automatic; nothing changes when nothing changed
    again = client.post('/admin/crm/lead/%d/money' % lead.id, json={'forecast': ''}).get_json()
    assert again['changed'] == ['Counts in the forecast as: Committed → Automatic']
    assert client.post('/admin/crm/lead/%d/money' % lead.id, json={'forecast': ''}).get_json()['changed'] == []
    assert client.post('/admin/crm/lead/%d/money' % lead.id, json={'amount': '-5'}).status_code == 400
    assert client.post('/admin/crm/lead/%d/money' % lead.id, json={'close_date': 'soon'}).status_code == 400
    assert client.post('/admin/crm/lead/%d/money' % lead.id, json={'forecast': 'won'}).status_code == 400


def test_the_lead_header_shows_value_close_date_and_category(app, client, admin_user):
    lead = lead_of(admin_user, 18500, 'pipeline', close=date(2031, 11, 12))
    login(client, admin_user.email)
    t = words(client.get('/admin/crm/lead/%d' % lead.id).get_data(as_text=True))
    assert '₹18,500' in t and 'closes 12 Nov' in t and 'Committed' in t
    assert 'Counts in the forecast as' in t and 'Automatic (Committed)' in t
    assert 'Nothing is sent to' in t


def test_add_a_lead_takes_the_typed_amount_and_close_date(app, client, admin_user):
    product(price=D('18500'))
    login(client, admin_user.email)
    page = client.get('/admin/crm/add').get_data(as_text=True)
    assert 'data-add-amount' in page and 'data-price="18500"' in page
    r = client.post('/admin/crm/add', data={'product': 'TI', 'name': 'Typed Amount', 'phone': '+919810009001',
                                           'phone_cc': 'IN', 'source': 'call', 'owner': 'me',
                                           'amount': '21000', 'currency': 'INR', 'close_date': '2031-05-02'})
    assert r.status_code == 302
    lead = CrmLead.query.join(CrmLead.person).filter_by(name='Typed Amount').one()
    assert lead.amount == D('21000.00') and lead.close_date == date(2031, 5, 2)
    # left empty: the product's price and an automatic date
    client.post('/admin/crm/add', data={'product': 'TI', 'name': 'Plain Add', 'phone': '+919810009002',
                                       'phone_cc': 'IN', 'source': 'call', 'owner': 'me'})
    plain = CrmLead.query.join(CrmLead.person).filter_by(name='Plain Add').one()
    assert plain.amount == D('18500.00') and plain.close_date is not None


# ================================================================================================ board and list

def test_a_card_shows_its_value_and_a_column_its_total(app, client, admin_user):
    _db.session.add(CrmCurrencyRate(code='USD', rate=D('80')))
    _db.session.commit()
    a = lead_of(admin_user, 120000, 'quoted')
    b = lead_of(admin_user, 1000, 'quoted', currency='USD')                 # ₹80,000
    c = lead_of(admin_user, 5000, 'quoted', currency='GBP')                 # no rate: counted as 0
    login(client, admin_user.email)
    html = client.get('/admin/crm/?p=ti-standard&view=board&owner=all').get_data(as_text=True)
    assert '₹1.2 L' in html and '$1,000' in html
    col = re.search(r'data-col="%d".*?data-col-value[^>]*>(.*?)</small>' % stage('quoted').id, html, flags=re.S)
    assert col and '₹2 L' in col.group(1)
    # a card keeps the whole name and the Late badge sits with the next step
    assert 'late-badge' not in re.search(r'<div class="top">.*?</div>', html, flags=re.S).group(0)
    from app.services import crm as crm_svc
    data = crm_svc.board(CrmPipeline.query.filter_by(key='ti-standard').one())
    quoted = next(c for c in data['columns'] if c['stage'].key == 'quoted')
    assert quoted['value'] == D('200000') and a.id and b.id and c.id


def test_the_list_has_value_closes_and_next_step_columns(app, client, admin_user):
    lead = ti_lead(phone='+919810007001', name='Has Step')               # a new lead has its first follow-up planned
    lead.owner_id = admin_user.id
    lead.amount, lead.currency, lead.close_date = D('18500'), 'INR', date(2031, 11, 12)
    _db.session.commit()
    assert lead.open_task is not None
    login(client, admin_user.email)
    html = client.get('/admin/crm/?p=ti-standard&view=list&owner=all').get_data(as_text=True)
    t = words(html)
    assert 'Value' in t and 'Closes' in t and 'Next step' in t
    assert '₹18,500' in t and '12 Nov' in t
    assert re.search(r'class="due-chip due-(today|past|next)"', html)


def test_the_list_filters_by_close_month_forecast_and_missing_values(app, client, admin_user):
    nov = lead_of(admin_user, 1000, 'pipeline', close=date(2031, 11, 12))
    dec = lead_of(admin_user, 2000, 'quoted', close=date(2031, 12, 1))
    novalue = lead_of(admin_user, None, None, close=date(2031, 11, 20))
    noclose = lead_of(admin_user, 300, None, close=None)
    login(client, admin_user.email)

    def names(query):
        html = client.get('/admin/crm/?p=all&view=list&owner=all&' + query).get_data(as_text=True)
        return {l.id for l in (nov, dec, novalue, noclose) if 'lead/%d"' % l.id in html}

    assert names('closes=2031-11') == {nov.id, novalue.id}
    assert names('closes=2031-Q4') == {nov.id, dec.id, novalue.id}
    assert names('forecast=commit') == {nov.id}
    assert names('forecast=best_case&closes=2031-12') == {dec.id}
    assert names('forecast=pipeline') == {novalue.id, noclose.id}
    assert names('no_value=1') == {novalue.id}
    assert names('no_close=1') == {noclose.id}
    html = client.get('/admin/crm/?p=all&view=list&owner=all&closes=2031-11&forecast=commit').get_data(as_text=True)
    t = words(html)
    assert 'Closes in November 2031' in t and 'Counts as: Committed' in t        # removable chips
    assert 'Clear all' in t                                                     # the filter bar


def test_a_won_filter_counts_the_month_it_was_won(app, client, admin_user):
    this_month = today_ist().strftime('%Y-%m')
    won = lead_of(admin_user, 4000, 'customer')
    old = lead_of(admin_user, 4000, 'customer')
    old.closed_at = datetime.utcnow() - timedelta(days=90)
    _db.session.commit()
    login(client, admin_user.email)
    html = client.get('/admin/crm/?p=all&view=list&owner=all&forecast=won&closes=%s' % this_month).get_data(as_text=True)
    assert 'lead/%d"' % won.id in html and 'lead/%d"' % old.id not in html


def test_the_leads_download_has_the_money_columns(app, client, admin_user):
    lead = lead_of(admin_user, 18500, 'pipeline', close=date(2031, 11, 12))
    product('TI', revenue_kind='percent', revenue_value=D('10'))
    crm_money.recalc_revenue(lead)
    _db.session.commit()
    login(client, admin_user.email)
    r = client.get('/admin/crm/export/leads?p=ti-standard&owner=all&win=all&forecast=commit&reason=backup')
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True).lstrip('﻿'))))
    head = rows[0]
    for col in ('Amount', 'Currency', 'What we earn', 'Closes on', 'Counts in the forecast as'):
        assert col in head
    row = dict(zip(head, rows[1]))
    assert row['Amount'] == '18500.00' and row['Currency'] == 'INR' and row['What we earn'] == '1850.00'
    assert row['Closes on'] == '2031-11-12' and row['Counts in the forecast as'] == 'Committed'
    assert len(rows) == 2


# ================================================================================================ set-up

def test_the_product_form_saves_the_money_fields_and_refuses_rubbish(app, client, admin_user):
    p = product('TI')
    login(client, admin_user.email)
    base = {'id': p.id, 'name': p.name, 'code': p.code, 'currency': 'INR', 'icon': p.icon, 'offered': 'on'}
    r = client.post('/admin/crm/pipelines/products', data={**base, 'price': '18,500', 'revenue_kind': 'percent',
                                                           'revenue_value': '12', 'close_days': '21'})
    assert r.status_code == 302
    _db.session.refresh(p)
    assert (p.price, p.revenue_kind, p.revenue_value, p.close_days) == (D('18500.00'), 'percent', D('12.00'), 21)
    bad = client.post('/admin/crm/pipelines/products', data={**base, 'price': 'cheap', 'revenue_kind': 'percent',
                                                             'revenue_value': '140', 'close_days': '9999'})
    assert bad.status_code == 400
    t = words(bad.get_data(as_text=True))
    assert 'Type the usual amount as a number' in t and 'between 0 and 100' in t and 'between 1 and 365' in t
    # "the whole amount" clears the rule
    client.post('/admin/crm/pipelines/products', data={**base, 'price': '', 'revenue_kind': '', 'revenue_value': '',
                                                       'close_days': ''})
    _db.session.refresh(p)
    assert p.price is None and p.revenue_kind is None and p.revenue_value is None and p.close_days is None


def test_exchange_rates_are_listed_for_the_currencies_in_use_and_saved(app, client, admin_user):
    product('TI', currency='USD')
    lead_of(admin_user, 100, None, currency='GBP')
    login(client, admin_user.email)
    page = client.get('/admin/crm/pipelines?tab=products').get_data(as_text=True)
    t = words(page)
    assert 'Exchange rates' in t and '1 USD =' in t and '1 GBP =' in t and 'Set a rate' in t
    assert 'rate_INR' not in page                                                # not for the reporting currency
    r = client.post('/admin/crm/pipelines/rates', data={'reporting_currency': 'INR', 'rate_USD': '83.5',
                                                        'rate_GBP': ''})
    assert r.status_code == 302
    assert _db.session.get(CrmCurrencyRate, 'USD').rate == D('83.5')
    assert _db.session.get(CrmCurrencyRate, 'GBP') is None
    client.post('/admin/crm/pipelines/rates', data={'reporting_currency': 'INR', 'rate_USD': 'free'})
    assert _db.session.get(CrmCurrencyRate, 'USD').rate == D('83.5')                   # a bad rate saves nothing
    client.post('/admin/crm/pipelines/rates', data={'reporting_currency': 'AED', 'rate_USD': '22.7'})
    assert crm_money.reporting_currency() == 'AED' and _db.session.get(CrmCurrencyRate, 'USD').rate == D('22.7')


def test_a_stage_saves_its_forecast_category_and_chance_from_the_editor(app, client, admin_user):
    from test_crm_pipelines_custom import posted, save
    crm.ensure_defaults()
    pipe = CrmPipeline.query.filter_by(key='ti-standard').one()
    login(client, admin_user.email)
    t = words(client.get('/admin/crm/pipelines/%d' % pipe.id).get_data(as_text=True))
    assert 'Counts in the forecast as' in t and 'Automatic (Committed)' in t and 'Chance to win' in t
    quoted = stage('quoted')
    data = posted(pipe)
    for s in data['stages']:
        if s['id'] == quoted.id:
            s['forecast'], s['probability'] = 'commit', '65'
    r = save(client, pipe, data)
    assert r.status_code == 200, r.get_data(as_text=True)
    _db.session.expire_all()
    assert stage('quoted').forecast == 'commit' and stage('quoted').probability == 65
    # a payload that says nothing about it leaves it alone; empty goes back to automatic
    assert save(client, pipe, posted(pipe)).status_code == 200
    _db.session.expire_all()
    assert stage('quoted').forecast == 'commit'
    data = posted(pipe)
    for s in data['stages']:
        if s['id'] == quoted.id:
            s['forecast'], s['probability'] = '', ''
    assert save(client, pipe, data).status_code == 200
    _db.session.expire_all()
    assert stage('quoted').forecast is None and stage('quoted').probability is None


def test_the_editor_refuses_a_forecast_that_does_not_fit_the_stage_or_a_chance_out_of_range(app, client, admin_user):
    from test_crm_pipelines_custom import posted, save
    crm.ensure_defaults()
    pipe = CrmPipeline.query.filter_by(key='ti-standard').one()
    login(client, admin_user.email)
    for key, forecast, chance, said in (('quoted', 'won', '', 'cannot count as won or lost'),
                                        ('customer', 'commit', '', 'always counts as won or lost'),
                                        ('quoted', 'commit', '150', 'between 0 and 100'),
                                        ('quoted', 'maybe', '', 'Choose how the forecast counts')):
        data = posted(pipe)
        sid = stage(key).id
        for s in data['stages']:
            if s['id'] == sid:
                s['forecast'], s['probability'] = forecast, chance
        r = save(client, pipe, data)
        assert r.status_code in (400, 422), (key, forecast, r.status_code)
        assert said in r.get_data(as_text=True), (key, forecast)
    _db.session.expire_all()
    assert stage('quoted').forecast is None


# ================================================================================================ targets

def test_a_target_is_saved_replaced_and_removed_in_one_place(app):
    u = make_user('t1@test.com', 't1', role='cs')
    month = '2031-11'
    crm_money.save_target(month, user_id=u.id, amount='300000', deals='12', leads='80')
    crm_money.save_target(month, user_id=u.id, amount='350,000', deals='12')
    _db.session.commit()
    rows = CrmTarget.query.filter_by(period=month, user_id=u.id).all()
    assert len(rows) == 1 and rows[0].amount == D('350000.00') and rows[0].leads is None
    crm_money.save_target(month, user_id=u.id, pipeline_id=1 and CrmPipeline.query.first() and CrmPipeline.query.first().id)
    crm_money.save_target(month, user_id=u.id, amount=None, deals=None, leads=None)       # empty: the row goes
    _db.session.commit()
    assert CrmTarget.query.filter_by(period=month, user_id=u.id, pipeline_id=None).count() == 0
    crm_money.save_target(month, leads='1000')                                             # the company's new-leads target
    _db.session.commit()
    assert CrmTarget.query.filter_by(period=month, user_id=None, team_id=None).one().leads == 1000
    with pytest.raises(ValueError):
        crm_money.save_target(month, user_id=u.id, amount='-1')
    with pytest.raises(ValueError):
        crm_money.save_target('November', user_id=u.id, amount='1')


def test_the_targets_page_saves_each_row_and_copies_last_month(app, client, admin_user):
    a = member('a@test.com', 'anita')
    ws = access.ensure_defaults()
    team = WorkspaceTeam(workspace_id=ws.id, name='North')
    _db.session.add(team)
    _db.session.commit()
    login(client, admin_user.email)
    page = client.get('/admin/crm/targets?month=2031-11').get_data(as_text=True)
    t = words(page)
    assert 'November 2031' in t and 'Anita' in t and 'North' in t and 'The whole company' in t
    r = client.post('/admin/crm/targets/save', data={
        'month': '2031-11', 'pipeline': '', 'u%d_amount' % a.id: '3,00,000', 'u%d_deals' % a.id: '12',
        'u%d_leads' % a.id: '', 't%d_amount' % team.id: '500000', 'c_leads': '1000'})
    assert r.status_code == 302
    got = crm_money.targets_for('2031-11')
    assert got[('u', a.id)].amount == D('300000.00') and got[('u', a.id)].deals == 12
    assert got[('t', team.id)].amount == D('500000.00') and got[('c', None)].leads == 1000
    # saving again replaces, it does not add a row
    client.post('/admin/crm/targets/save', data={'month': '2031-11', 'u%d_amount' % a.id: '320000',
                                                 'u%d_deals' % a.id: '12'})
    assert CrmTarget.query.filter_by(period='2031-11', user_id=a.id).count() == 1
    assert crm_money.targets_for('2031-11')[('u', a.id)].amount == D('320000.00')
    # a bad number saves nothing
    client.post('/admin/crm/targets/save', data={'month': '2031-11', 'u%d_amount' % a.id: 'lots'})
    assert crm_money.targets_for('2031-11')[('u', a.id)].amount == D('320000.00')
    # copy last month: only into empty rows
    client.post('/admin/crm/targets/save', data={'month': '2031-10', 'u%d_amount' % a.id: '100000',
                                                 'u%d_deals' % a.id: '5', 't%d_amount' % team.id: '900000'})
    client.post('/admin/crm/targets/copy', data={'month': '2031-11'})
    nov = crm_money.targets_for('2031-11')
    assert nov[('u', a.id)].amount == D('320000.00')                               # not overwritten
    assert nov[('t', team.id)].amount == D('500000.00')
    client.post('/admin/crm/targets/copy', data={'month': '2031-12'})
    assert crm_money.targets_for('2031-12')[('u', a.id)].amount == D('320000.00')


def test_a_pipeline_target_is_kept_apart_from_the_all_pipelines_one(app):
    a = make_user('p@test.com', 'pia', role='cs')
    crm.ensure_defaults()
    pipe = CrmPipeline.query.first()
    crm_money.save_target('2031-11', user_id=a.id, amount='100')
    crm_money.save_target('2031-11', user_id=a.id, pipeline_id=pipe.id, amount='40')
    _db.session.commit()
    assert crm_money.targets_for('2031-11')[('u', a.id)].amount == D('100.00')
    assert crm_money.targets_for('2031-11', pipe.id)[('u', a.id)].amount == D('40.00')


def _team_world(admin_user):
    """Anita and Bhanu in team North with their lead Tara; Charan alone in no team."""
    ws = access.ensure_defaults()
    # agents who were also given Forecast (it is grantable on its own)
    sales = WorkspaceRole(workspace_id=ws.id, name='Sales with Forecast',
                          pages=sorted(access.CS_ROLE_PAGES | {'crm_forecast'}))
    _db.session.add(sales)
    _db.session.commit()
    lead = member('tara@test.com', 'tara', role='Team lead')
    a, b, c = (member('a@test.com', 'anita', role=sales.name), member('b@test.com', 'bhanu', role=sales.name),
               member('c@test.com', 'charan', role=sales.name))
    north = WorkspaceTeam(workspace_id=ws.id, name='North')
    _db.session.add(north)
    _db.session.flush()
    north.users.extend([lead, a, b])
    _db.session.commit()
    access._cache().clear()
    return lead, a, b, c, north


def test_a_team_lead_sets_targets_for_their_own_team_only(app, client, admin_user):
    lead, a, b, c, north = _team_world(admin_user)
    login(client, lead.email)
    page = client.get('/cs/crm/targets?month=2031-11', follow_redirects=True).get_data(as_text=True)
    t = words(page)
    assert 'Anita' in t and 'Bhanu' in t and 'Charan' not in t and 'North' in t
    assert 'The whole company' not in t
    client.post('/admin/crm/targets/save', data={'month': '2031-11', 'u%d_amount' % a.id: '100',
                                                 'u%d_amount' % c.id: '999', 'c_leads': '5'})
    got = crm_money.targets_for('2031-11')
    assert ('u', a.id) in got and ('u', c.id) not in got and ('c', None) not in got


# ================================================================================================ forecast

def _forecast_world(admin_user):
    """This month: Anita won 10,000, has 5,000 committed, 3,000 best case; Bhanu has 2,000 in the pipeline and a
    committed lead for next month, and won 7,000 last month. Targets: Anita 20,000, Bhanu 10,000, North 40,000."""
    lead, a, b, c, north = _team_world(admin_user)
    today = today_ist()
    first, last = crm_money.month_range(today.strftime('%Y-%m'))
    leads = {
        'won': lead_of(a, 10000, 'customer'),
        'commit': lead_of(a, 5000, 'pipeline', close=today),
        'best': lead_of(a, 3000, 'quoted', close=today),
        'pipe': lead_of(b, 2000, 'prospect', close=today),
        'next': lead_of(b, 1000, 'pipeline', close=last + timedelta(days=1)),
        'old_won': lead_of(b, 7000, 'customer'),
        'nodate': lead_of(a, 900, 'quoted', close=None),
        'novalue': lead_of(a, None, 'quoted', close=today),
        'won_novalue': lead_of(b, None, 'customer'),
    }
    leads['old_won'].closed_at = datetime.combine(first, datetime.min.time()) - timedelta(days=3)
    _db.session.commit()
    period = today.strftime('%Y-%m')
    crm_money.save_target(period, user_id=a.id, amount='20000', deals='4', leads='50')
    crm_money.save_target(period, user_id=b.id, amount='10000', deals='2')
    crm_money.save_target(period, team_id=north.id, amount='40000')
    crm_money.save_target(period, leads='1000')
    _db.session.commit()
    return lead, a, b, c, north, leads, period


def test_the_forecast_numbers_for_a_small_team(app):
    admin_user = make_user('ad@test.com', 'ad', role='admin')
    lead, a, b, c, north, leads, period = _forecast_world(admin_user)
    first, last = crm_money.month_range(period)
    out = crm_money.forecast(first, last, [a, b, c], months=[period])
    ra, rb, rc = out['rows'][a.id], out['rows'][b.id], out['rows'][c.id]
    assert (ra['target'], ra['won'], ra['commit'], ra['best_case'], ra['pipeline']) == (D('20000.00'), D('10000.00'), D('5000.00'), D('3000.00'), D('0'))
    assert ra['gap'] == D('10000.00') and ra['pct'] == 50 and ra['won_n'] == 1 and ra['deals_target'] == 4
    assert (rb['won'], rb['commit'], rb['best_case'], rb['pipeline']) == (D('0'), D('0'), D('0'), D('2000.00'))
    assert rb['gap'] == D('10000.00') and rb['pct'] == 0 and rb['won_n'] == 1          # won with no value: counted, worth 0
    assert rc['target'] is None and rc['gap'] == D('0') and rc['pct'] is None
    assert out['fix']['no_close'] == 1 and out['fix']['won_no_value'] == 1
    assert out['fix']['no_value'] == 1                                                    # open leads without a value
    assert out['rows'][a.id]['new_leads'] >= 1
    team = crm_money.team_row([ra, rb], {'target': D('40000'), 'deals_target': None, 'leads_target': None})
    assert team['target'] == D('40000') and team['members_target'] == D('30000.00')
    assert team['won'] == D('10000.00') and team['gap'] == D('30000.00') and team['pct'] == 25
    q = crm_money.quarter_months(period)
    assert period in q and len(q) == 3


def test_the_forecast_page_for_an_admin_shows_everybody_with_links(app, client, admin_user):
    lead, a, b, c, north, leads, period = _forecast_world(admin_user)
    login(client, admin_user.email)
    html = client.get('/admin/crm/forecast').get_data(as_text=True)
    t = words(html)
    for name in ('Anita', 'Bhanu', 'Charan', 'Tara'):
        assert name in t
    assert 'Target' in t and 'Closed won' in t and 'Committed' in t and 'Best case' in t and 'Gap to target' in t
    assert '₹10,000' in t and '₹5,000' in t and '₹3,000' in t
    assert 'Team target ₹40,000' in t and "members' targets" in t                      # both numbers for a team
    assert 'New leads:' in t and 'of 1,000' in t
    # every number opens the leads behind it
    assert 'forecast=commit' in html and 'forecast=won' in html and 'closes=%s' % period in html
    assert 'owner=%d' % a.id in html
    # the fix-me list
    assert '1 open lead has no close date' in t and '1 won lead has no value' in t
    assert 'no value' in t
    # the quarter shows the same month inside it
    q = words(client.get('/admin/crm/forecast?span=quarter&month=%s' % period).get_data(as_text=True))
    assert 'Q' in q and '₹10,000' in q


def test_the_links_from_the_forecast_open_exactly_those_leads(app, client, admin_user):
    lead, a, b, c, north, leads, period = _forecast_world(admin_user)
    login(client, admin_user.email)
    page = client.get('/admin/crm/forecast?pipeline=%d' % leads['won'].pipeline_id).get_data(as_text=True)

    def ids(query):
        html = client.get('/admin/crm/?view=list&p=ti-standard&' + query).get_data(as_text=True)
        return {l.id for l in leads.values() if 'lead/%d"' % l.id in html}

    assert ids('owner=%d&forecast=commit&closes=%s' % (a.id, period)) == {leads['commit'].id}
    assert ids('owner=%d&forecast=best_case&closes=%s' % (a.id, period)) == {leads['best'].id, leads['novalue'].id}
    assert ids('owner=%d&forecast=won&closes=%s' % (b.id, period)) == {leads['won_novalue'].id}
    assert ids('owner=all&no_close=1') == {leads['nodate'].id}
    assert 'owner=%d' % a.id in page and 'p=ti-standard' in page


def test_an_agent_sees_only_their_own_row(app, client, admin_user):
    lead, a, b, c, north, leads, period = _forecast_world(admin_user)
    login(client, a.email)
    html = client.get('/cs/crm/forecast').get_data(as_text=True)
    t = words(html)
    assert 'Anita' in t and 'Bhanu' not in t and 'Charan' not in t and 'By team' not in t
    assert '₹10,000' in t and '₹5,000' in t
    # asking for somebody else's row gets their own
    other = words(client.get('/cs/crm/forecast?who=%d' % b.id).get_data(as_text=True))
    assert 'Bhanu' not in other and 'Anita' in other


def test_a_team_lead_sees_their_team_and_not_the_rest(app, client, admin_user):
    lead, a, b, c, north, leads, period = _forecast_world(admin_user)
    login(client, lead.email)
    t = words(client.get('/cs/crm/forecast', follow_redirects=True).get_data(as_text=True))
    assert 'Anita' in t and 'Bhanu' in t and 'Charan' not in t and 'North' in t


def test_the_forecast_can_be_narrowed_to_a_team_a_person_or_a_pipeline(app, client, admin_user):
    lead, a, b, c, north, leads, period = _forecast_world(admin_user)
    login(client, admin_user.email)
    html = client.get('/admin/crm/forecast?team=%d' % north.id).get_data(as_text=True)
    team = table_words(html)
    assert 'Anita' in team and 'Bhanu' in team and 'Charan' not in team
    assert 'Team target ₹40,000' in words(html)
    one = table_words(client.get('/admin/crm/forecast?who=%d' % b.id).get_data(as_text=True))
    assert 'Bhanu' in one and 'Anita' not in one
    other = CrmPipeline.query.filter(CrmPipeline.key != 'ti-standard').first()
    empty = words(client.get('/admin/crm/forecast?pipeline=%d&who=%d' % (other.id, a.id)).get_data(as_text=True))
    assert '₹10,000' not in empty


def test_the_forecast_warns_about_a_currency_with_no_rate(app, client, admin_user):
    lead, a, b, c, north, leads, period = _forecast_world(admin_user)
    stray = lead_of(a, 500, 'pipeline', close=today_ist(), currency='USD')
    login(client, admin_user.email)
    t = words(client.get('/admin/crm/forecast').get_data(as_text=True))
    assert '1 lead in USD has no exchange rate' in t and 'Pipelines & products' in t
    _db.session.add(CrmCurrencyRate(code='USD', rate=D('80')))
    _db.session.commit()
    t2 = words(client.get('/admin/crm/forecast').get_data(as_text=True))
    assert 'no exchange rate' not in t2 and '₹45,000' in t2 and stray.id           # 5,000 + 500 x 80 committed


def test_the_forecast_download_is_what_the_screen_says(app, client, admin_user):
    lead, a, b, c, north, leads, period = _forecast_world(admin_user)
    login(client, admin_user.email)
    r = client.get('/admin/crm/forecast.csv?reason=backup')
    assert r.status_code == 200 and 'text/csv' in r.headers['Content-Type']
    rows = list(csv.reader(io.StringIO(r.get_data(as_text=True).lstrip('﻿'))))
    head = rows[1]
    anita = dict(zip(head, next(x for x in rows if x and x[0] == 'Anita')))
    assert anita['Closed won'] == '10000' and anita['Committed'] == '5000' and anita['Gap to target'] == '10000'
    assert anita['% of target'] == '50' and anita['Deals won'] == '1'
    assert any(x and x[0] == 'Team: North' for x in rows) and rows[-1][0] == 'Total'
    assert ActivityEvent.query.filter_by(event='crm_export').count() == 1                 # a download is logged


def test_forecast_is_in_the_menu_after_sales_results_and_comes_with_it(app, admin_user):
    from app.services import access as acc
    assert 'crm_forecast' in acc.PAGES and 'crm_insights' in acc.PAGES
    page = acc.PAGES['crm_forecast']
    assert 'crm_insights' in page['with'] and page['grant'] is True
    assert 'crm.forecast' in page['endpoints'] and 'admin_crm.forecast' in page['endpoints']
    sections = {s['key']: s for s in acc.SECTIONS}
    reports = sections['reports']['pages']
    assert reports.index('crm_forecast') == reports.index('crm_insights') + 1
    assert tuple(k for k, _ in acc.TAB_GROUPS['crm_insights']) == ('crm_insights', 'crm_forecast')
    setup = next(s for s in sections['setup']['subs'] if s['key'] == 'sales')['pages']      # Set-up › Sales
    assert setup.index('crm_targets') == setup.index('crm_pipelines') + 1


# ================================================================================================ My day and Results

def test_my_day_shows_a_slim_target_bar_only_when_there_is_a_target(app, client, admin_user):
    lead, a, b, c, north, leads, period = _forecast_world(admin_user)
    login(client, a.email)
    t = words(client.get('/cs/crm/today').get_data(as_text=True))
    month = date.today().strftime('%B')
    assert 'My target for %s' % today_ist().strftime('%B') in t or 'My target for %s' % month in t
    assert '₹10,000 of ₹20,000 won' in t and '₹5,000 committed' in t
    html = client.get('/cs/crm/today').get_data(as_text=True)
    assert 'class="card my-target"' in html and 'forecast' in html          # an agent holding Forecast opens it
    client.post('/auth/logout')
    login(client, c.email)                                                    # no target: nothing at all
    assert 'My target for' not in words(client.get('/cs/crm/today').get_data(as_text=True))


def test_the_bar_links_to_the_agents_own_leads_when_they_cannot_open_forecast(app, client, admin_user):
    lead, a, b, c, north, leads, period = _forecast_world(admin_user)
    ws = access.ensure_defaults()
    role = WorkspaceRole(workspace_id=ws.id, name='Only today', pages=['crm_today', 'crm_board'])
    _db.session.add(role)
    _db.session.commit()
    from app.models import WorkspaceMember
    WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=a.id).one().role = role
    _db.session.commit()
    access._cache().clear()
    login(client, a.email)
    html = client.get('/cs/crm/today').get_data(as_text=True)
    href = re.search(r'<a class="card my-target" href="([^"]+)"', html).group(1).replace('&amp;', '&')
    assert 'forecast=commit' in href and 'owner=%d' % a.id in href and '/forecast' not in href


def test_sales_results_has_won_value_our_revenue_and_top_sellers(app, client, admin_user):
    product('TI', revenue_kind='percent', revenue_value=D('10'))
    lead, a, b, c, north, leads, period = _forecast_world(admin_user)
    # last month's win, inside these 30 days whatever today's date (3 days before the 1st is over 30 days ago on the 29th-31st)
    leads['old_won'].closed_at = datetime.utcnow() - timedelta(days=5)
    for l in leads.values():
        crm_money.recalc_revenue(l)
    _db.session.commit()
    login(client, admin_user.email)
    html = client.get('/admin/crm/insights?days=30').get_data(as_text=True)
    t = words(html)
    assert 'Won value' in t and 'Our revenue' in t and '₹17,000' in t and '₹1,700' in t        # 10,000 + 7,000, a tenth of it earned
    assert 'Top sellers' in t and 'Anita' in t
    top = words(re.search(r'Top sellers.*?</section>', html, flags=re.S).group(0))
    assert 'Anita' in top and 'Bhanu' in top and 'Charan' not in top        # only people who won something
    out = crm_money.top_sellers(datetime.utcnow() - timedelta(days=30), datetime.utcnow() + timedelta(days=1), [a, b, c])
    assert [r['user'].id for r in out][:1] == [a.id] and out[0]['amount'] == D('10000.00')
    assert out[0]['pct'] is not None
    csv_rows = list(csv.reader(io.StringIO(client.get('/admin/crm/insights.csv?days=30&reason=backup').get_data(as_text=True).lstrip('﻿'))))
    flat = [r for r in csv_rows if r]
    assert any(r[0].startswith('Won value') for r in flat) and any(r[0].startswith('Our revenue') for r in flat)
    assert any(r[0] == 'Top sellers' for r in flat) and any(r[0] == 'Anita' for r in flat)


def test_results_compare_the_won_value_with_the_period_before(app):
    admin = make_user('x@test.com', 'x', role='admin')
    now = datetime.utcnow()
    won = lead_of(admin, 5000, 'customer')
    prev = lead_of(admin, 2500, 'customer')
    prev.closed_at = now - timedelta(days=45)
    _db.session.commit()
    this = crm_money.won_value(now - timedelta(days=30), now + timedelta(days=1))
    before = crm_money.won_value(now - timedelta(days=60), now - timedelta(days=30))
    assert this['amount'] == D('5000.00') and before['amount'] == D('2500.00') and this['deals'] == 1 and won.id


# ================================================================================================ the database

def test_the_new_columns_and_tables_exist(app):
    from sqlalchemy import inspect
    insp = inspect(_db.engine)
    assert {'price', 'revenue_kind', 'revenue_value', 'close_days'} <= {c['name'] for c in insp.get_columns('crm_products')}
    assert {'forecast', 'probability'} <= {c['name'] for c in insp.get_columns('crm_stages')}
    assert {'amount', 'currency', 'revenue', 'close_date', 'forecast'} <= {c['name'] for c in insp.get_columns('crm_leads')}
    assert {'code', 'rate', 'updated_at', 'updated_by_id'} <= {c['name'] for c in insp.get_columns('crm_currency_rates')}
    assert {'period', 'user_id', 'team_id', 'pipeline_id', 'amount', 'deals', 'leads'} <= {c['name'] for c in insp.get_columns('crm_targets')}


def test_the_migration_adds_and_removes_everything_on_a_plain_database(tmp_path):
    """u1crm017 on an empty SQLite file that only has the tables it alters: up, then down, then up again."""
    import importlib.util
    import os
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations', 'versions',
                        'u1crm017_crm_money.py')
    spec = importlib.util.spec_from_file_location('u1crm017', path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    engine = sa.create_engine('sqlite:///%s' % (tmp_path / 'm.db'))
    meta = sa.MetaData()
    for name in ('users', 'workspace_teams', 'crm_pipelines', 'crm_products', 'crm_stages', 'crm_leads'):
        sa.Table(name, meta, sa.Column('id', sa.Integer, primary_key=True), sa.Column('name', sa.String(20)))
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO crm_leads (id, name) VALUES (1, 'old lead')"))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig.upgrade()
        insp = sa.inspect(conn)
        assert {'amount', 'currency', 'revenue', 'close_date', 'forecast'} <= {c['name'] for c in insp.get_columns('crm_leads')}
        assert {'crm_currency_rates', 'crm_targets'} <= set(insp.get_table_names())
        assert conn.execute(sa.text('SELECT amount FROM crm_leads WHERE id = 1')).scalar() is None      # old rows stay empty
        with Operations.context(ctx):
            mig.downgrade()
        insp = sa.inspect(conn)
        assert 'crm_targets' not in insp.get_table_names()
        assert 'amount' not in {c['name'] for c in insp.get_columns('crm_leads')}
        assert conn.execute(sa.text('SELECT name FROM crm_leads WHERE id = 1')).scalar() == 'old lead'
        with Operations.context(ctx):
            mig.upgrade()
