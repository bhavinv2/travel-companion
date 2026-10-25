"""Sales CRM 2.0, run 4b -- quotes and payments.

    migration  u6crm022 up, down, up on SQLite
    quotes     + Quote, Mark as sent (logs the stage's own Quote-sent line, the stage moves like the old button),
               accepted / declined, text for the message box (nothing is sent)
    payments   + Payment link (logs the Payment-link-sent line), Mark as paid (lead won, "Paid", value and close date
               filled, a stage's entry rules do not block it)
    approval   a quote below the product's price less its biggest discount waits for an approver; bell + My day card
    webhook    signed, 404 when unset, 403 when wrong, idempotent
    numbers    the milestone line wins: a quote and its line count once; a pipeline without the button counts the row
    safe       visibility, recycle bin, purge, erase and merge handle quotes and payments
"""
import hashlib
import hmac
import json
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from flask import g

from conftest import login, logout, make_user
from app import db as _db
from app.models import (CrmAudit, CrmLead, CrmPayment, CrmPerson, CrmProduct, CrmQuote, CrmStage, CrmStageChange,
                        CrmTouchpoint, Notification, WorkspaceRole, WorkspaceTeam)
from app.services import access, crm, crm_access, crm_audit, crm_bin, crm_money, crm_numbers, crm_people, crm_quotes

from test_crm_wa_sync_engine import ti_lead

SECRET = 'whsec-payments-test'


def words(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


@pytest.fixture
def agent(app):
    return make_user('agent@test.com', 'agent', role='cs')


@pytest.fixture
def lead(app, agent):
    l = ti_lead(phone='+919876522222', name='Quotable Qamar')
    l.owner_id = agent.id
    _db.session.commit()
    return l


def as_user(client, user):
    """Sign `user` in on this client; the app keeps the last user on `g` for the test."""
    logout(client)
    g.pop('_login_user', None)
    _db.session.expire_all()
    return login(client, user.email)


def quote_form(**over):
    d = {'title': 'Travel insurance, 30 days', 'amount': '18500', 'currency': 'INR', 'valid_until': '2030-01-15',
         'details': 'Covers hospital stays up to 5 lakh.'}
    d.update(over)
    return d


def new_quote(client, lead, **over):
    r = client.post('/cs/crm/lead/%d/quote' % lead.id, data=quote_form(**over))
    assert r.status_code == 302
    _db.session.expire_all()
    return CrmQuote.query.filter_by(lead_id=lead.id).order_by(CrmQuote.id.desc()).first()


def stage_names(lead):
    return [c.to_stage.name for c in sorted(lead.stage_changes, key=lambda c: c.id)]


# ====================================================================================== the migration

def test_migration_u6crm022_goes_up_down_up_on_sqlite(tmp_path):
    import importlib.util
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations', 'versions',
                        'u6crm022_quotes_views_reports.py')
    spec = importlib.util.spec_from_file_location('u6crm022', path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig.revision == 'u6crm022' and mig.down_revision == 'u5crm021'
    engine = sa.create_engine('sqlite:///%s' % (tmp_path / 'm.db'))
    meta = sa.MetaData()
    for name in ('users', 'crm_leads', 'crm_products'):
        sa.Table(name, meta, sa.Column('id', sa.Integer, primary_key=True), sa.Column('name', sa.String(20)))
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO crm_products (id, name) VALUES (1, 'old product')"))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig.upgrade()
        insp = sa.inspect(conn)
        assert {'crm_quotes', 'crm_payments', 'crm_views', 'crm_saved_reports'} <= set(insp.get_table_names())
        assert 'max_discount_pct' in {c['name'] for c in insp.get_columns('crm_products')}
        assert {'lead_id', 'title', 'amount', 'currency', 'valid_until', 'status', 'needs_approval', 'approved_by_id',
                'approved_at', 'sent_at'} <= {c['name'] for c in insp.get_columns('crm_quotes')}
        assert {'lead_id', 'quote_id', 'link_url', 'provider', 'reference', 'status', 'paid_at'} <= \
            {c['name'] for c in insp.get_columns('crm_payments')}
        assert conn.execute(sa.text('SELECT max_discount_pct FROM crm_products WHERE id = 1')).scalar() is None
        with Operations.context(ctx):
            mig.downgrade()
        insp = sa.inspect(conn)
        assert not ({'crm_quotes', 'crm_payments', 'crm_views', 'crm_saved_reports'} & set(insp.get_table_names()))
        assert 'max_discount_pct' not in {c['name'] for c in insp.get_columns('crm_products')}
        assert conn.execute(sa.text('SELECT name FROM crm_products WHERE id = 1')).scalar() == 'old product'
        with Operations.context(ctx):
            mig.upgrade()
        assert 'crm_quotes' in sa.inspect(conn).get_table_names()


# ====================================================================================== quotes

def test_a_quote_starts_from_the_leads_value_and_the_products_price(app, client, agent, lead):
    prod = CrmProduct.query.filter_by(code=lead.product).first()
    prod.price, prod.currency = Decimal('18500'), 'INR'
    lead.amount = None
    _db.session.commit()
    d = crm_quotes.defaults(lead)
    assert d['amount'] == '18500' and d['currency'] == 'INR' and d['title']
    lead.amount, lead.currency = Decimal('21000'), 'INR'
    _db.session.commit()
    assert crm_quotes.defaults(lead)['amount'] == '21000'
    as_user(client, agent)
    page = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'Quotes &amp; payments' in page and 'data-dlg-open="qp-new-quote"' in page        # opens the quote's dialog


def test_saving_a_quote_sends_nothing_and_logs_nothing_to_the_customer(app, client, agent, lead):
    as_user(client, agent)
    q = new_quote(client, lead)
    assert q.status == 'draft' and q.amount == Decimal('18500.00') and q.currency == 'INR'
    assert q.valid_until == date(2030, 1, 15) and q.created_by_id == agent.id and not q.needs_approval
    assert CrmTouchpoint.query.filter_by(lead_id=lead.id, code='Q').count() == 0
    assert not any(t.direction == 'out' and t.channel == 'whatsapp' for t in lead.touchpoints)


def test_a_bad_amount_is_refused_in_plain_words(app, client, agent, lead):
    as_user(client, agent)
    r = client.post('/cs/crm/lead/%d/quote' % lead.id, data=quote_form(amount='lots'), follow_redirects=True)
    assert 'Type the amount as a number' in r.get_data(as_text=True)
    assert CrmQuote.query.count() == 0


def test_mark_as_sent_logs_the_quote_line_and_moves_the_stage_like_the_old_button(app, client, agent, lead):
    # the old button on one lead ...
    twin = ti_lead(phone='+919876533333', name='Button Twin')
    twin.owner_id = agent.id
    _db.session.commit()
    crm.mark_event(twin, 'Q', user=agent)
    twin_stage = twin.stage.name
    # ... and Mark as sent on the other
    as_user(client, agent)
    q = new_quote(client, lead)
    r = client.post('/cs/crm/quote/%d/status' % q.id, data={'action': 'sent'})
    assert r.status_code == 302
    _db.session.expire_all()
    q = _db.session.get(CrmQuote, q.id)
    lead = _db.session.get(CrmLead, lead.id)
    assert q.status == 'sent' and q.sent_at is not None and q.sent_touch_id
    line = _db.session.get(CrmTouchpoint, q.sent_touch_id)
    assert line.code == 'Q' and line.channel == 'system' and line.direction == 'none'
    assert lead.stage.name == twin_stage
    assert [c for c in stage_names(lead) if c == twin_stage]
    assert not any(t.channel == 'whatsapp' and t.direction == 'out' for t in lead.touchpoints)      # nothing was sent


def test_a_sent_quote_fills_an_empty_lead_value_and_keeps_a_value_that_is_there(app, client, agent, lead):
    lead.amount = None
    _db.session.commit()
    as_user(client, agent)
    q = new_quote(client, lead, amount='9000')
    client.post('/cs/crm/quote/%d/status' % q.id, data={'action': 'sent'})
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).amount == Decimal('9000.00')
    other = ti_lead(phone='+919876544444', name='Has Value')
    other.owner_id, other.amount, other.currency = agent.id, Decimal('5000'), 'INR'
    _db.session.commit()
    q2 = new_quote(client, other, amount='7000')
    client.post('/cs/crm/quote/%d/status' % q2.id, data={'action': 'sent'})
    _db.session.expire_all()
    assert _db.session.get(CrmLead, other.id).amount == Decimal('5000.00')


def test_a_sent_quote_cannot_be_edited_or_sent_again_but_can_be_accepted_or_declined(app, client, agent, lead):
    as_user(client, agent)
    q = new_quote(client, lead)
    client.post('/cs/crm/quote/%d/status' % q.id, data={'action': 'sent'})
    r = client.post('/cs/crm/quote/%d/edit' % q.id, data=quote_form(title='Changed'), follow_redirects=True)
    assert 'cannot be changed' in r.get_data(as_text=True)
    r = client.post('/cs/crm/quote/%d/status' % q.id, data={'action': 'sent'}, follow_redirects=True)
    assert 'already sent' in r.get_data(as_text=True)
    client.post('/cs/crm/quote/%d/status' % q.id, data={'action': 'accepted'})
    _db.session.expire_all()
    assert _db.session.get(CrmQuote, q.id).status == 'accepted'
    html = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'Accepted' in html


def test_the_words_for_the_message_box_are_ready_and_the_page_never_sends(app, client, agent, lead):
    as_user(client, agent)
    q = new_quote(client, lead)
    text = crm_quotes.quote_text(q, agent)
    assert 'Hi Quotable' in text and '₹18,500' in text and 'Covers hospital stays' in text and '15 Jan 2030' in text
    page = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'data-qp-box' in page and 'data-qp-copy' in page and 'Put in the message box' in page
    assert 'id="box"' in page and 'data-box-input' in page              # the agent's own box, where Send stays
    assert 'crm-quotes.js' in page


def test_history_says_it_in_plain_words(app, client, agent, lead):
    as_user(client, agent)
    q = new_quote(client, lead)
    client.post('/cs/crm/quote/%d/status' % q.id, data={'action': 'sent'})
    _db.session.expire_all()
    said = [h['what'] for h in crm_audit.history_for('lead', lead.id, 'INR')]
    assert any(w.startswith('wrote the quote') for w in said)
    assert any('marked the quote ₹18,500 as sent' in w for w in said)
    page = words(client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True))
    assert 'marked the quote ₹18,500 as sent' in page


def test_a_draft_quote_can_be_edited_and_deleted_in_page(app, client, agent, lead):
    as_user(client, agent)
    q = new_quote(client, lead)
    client.post('/cs/crm/quote/%d/edit' % q.id, data=quote_form(title='Plan B', amount='20000'))
    _db.session.expire_all()
    q = _db.session.get(CrmQuote, q.id)
    assert q.title == 'Plan B' and q.amount == Decimal('20000.00')
    page = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'Yes, delete' in page and 'confirm(' not in page.split('id="quotes"')[1].split('</section>')[0]
    client.post('/cs/crm/quote/%d/delete' % q.id)
    assert CrmQuote.query.count() == 0


# ====================================================================================== payments

def test_a_payment_link_logs_the_payment_line_and_moves_the_stage(app, client, agent, lead):
    twin = ti_lead(phone='+919876555551', name='Pay Twin')
    twin.owner_id = agent.id
    _db.session.commit()
    crm.mark_event(twin, 'PLS', user=agent)
    twin_stage = twin.stage.name
    as_user(client, agent)
    r = client.post('/cs/crm/lead/%d/payment' % lead.id, data={
        'link_url': 'https://pay.example/abc', 'amount': '18500', 'currency': 'INR', 'provider': 'Razorpay',
        'reference': 'order_123'})
    assert r.status_code == 302
    _db.session.expire_all()
    p = CrmPayment.query.filter_by(lead_id=lead.id).one()
    assert p.status == 'pending' and p.reference == 'order_123' and p.provider == 'Razorpay' and p.link_touch_id
    assert _db.session.get(CrmTouchpoint, p.link_touch_id).code == 'PLS'
    assert _db.session.get(CrmLead, lead.id).stage.name == twin_stage


def test_a_payment_link_must_be_a_web_address(app, client, agent, lead):
    as_user(client, agent)
    r = client.post('/cs/crm/lead/%d/payment' % lead.id, data={'link_url': 'javascript:alert(1)', 'amount': '1'},
                    follow_redirects=True)
    assert 'should start with http' in r.get_data(as_text=True)
    assert CrmPayment.query.count() == 0


def test_mark_as_paid_wins_the_lead_with_the_reason_paid_and_fills_value_and_date(app, client, agent, lead):
    lead.amount, lead.currency, lead.close_date = None, None, None
    # an entry rule on the won stage must not stop a payment (it is a system move)
    won = next(s for s in lead.pipeline.stages if s.kind == 'won')
    won.requires = ['departure_date']
    _db.session.commit()
    as_user(client, agent)
    client.post('/cs/crm/lead/%d/payment' % lead.id, data={'amount': '12000', 'currency': 'INR', 'reference': 'r1'})
    _db.session.expire_all()
    p = CrmPayment.query.filter_by(lead_id=lead.id).one()
    r = client.post('/cs/crm/payment/%d/status' % p.id, data={'action': 'paid'})
    assert r.status_code == 302
    _db.session.expire_all()
    lead = _db.session.get(CrmLead, lead.id)
    p = _db.session.get(CrmPayment, p.id)
    assert p.status == 'paid' and p.paid_at is not None
    assert lead.status == 'won' and lead.stage.kind == 'won'
    assert lead.amount == Decimal('12000.00') and lead.close_date == (datetime.utcnow() + crm.IST).date()
    last = sorted(lead.stage_changes, key=lambda c: c.id)[-1]
    assert last.reason == 'Paid' and last.to_stage_id == won.id


def test_paying_twice_changes_nothing_more(app, client, agent, lead):
    as_user(client, agent)
    client.post('/cs/crm/lead/%d/payment' % lead.id, data={'amount': '100', 'reference': 'r2'})
    p = CrmPayment.query.filter_by(lead_id=lead.id).one()
    client.post('/cs/crm/payment/%d/status' % p.id, data={'action': 'paid'})
    _db.session.expire_all()
    n = CrmStageChange.query.filter_by(lead_id=lead.id).count()
    client.post('/cs/crm/payment/%d/status' % p.id, data={'action': 'paid'})
    _db.session.expire_all()
    assert CrmStageChange.query.filter_by(lead_id=lead.id).count() == n
    assert 'Yes, they paid' not in client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True).split('payment-%d' % p.id)[1].split('</article>')[0]


def test_a_paid_payment_cannot_be_deleted_and_a_pending_one_can(app, client, agent, lead):
    as_user(client, agent)
    client.post('/cs/crm/lead/%d/payment' % lead.id, data={'amount': '100', 'reference': 'r3'})
    p = CrmPayment.query.filter_by(lead_id=lead.id).one()
    client.post('/cs/crm/payment/%d/status' % p.id, data={'action': 'paid'})
    r = client.post('/cs/crm/payment/%d/delete' % p.id, follow_redirects=True)
    assert 'stays on the record' in r.get_data(as_text=True) and CrmPayment.query.count() == 1


# ====================================================================================== approval

def priced(lead, price='20000', pct='10'):
    prod = CrmProduct.query.filter_by(code=lead.product).first()
    prod.price, prod.currency, prod.max_discount_pct = Decimal(price), 'INR', Decimal(pct)
    crm_money.crm_products.invalidate()
    _db.session.commit()


def test_a_quote_inside_the_allowed_discount_needs_no_approval(app, client, agent, lead):
    priced(lead)
    as_user(client, agent)
    assert not new_quote(client, lead, amount='18000').needs_approval         # exactly 10% off: allowed
    assert not new_quote(client, lead, amount='25000').needs_approval         # above the price


def test_a_quote_below_the_limit_waits_for_an_approver_and_rings_them(app, client, agent, lead, admin_user):
    priced(lead)
    as_user(client, agent)
    q = new_quote(client, lead, amount='15000')
    assert q.needs_approval and q.approved_at is None
    bells = Notification.query.filter_by(user_id=admin_user.id, type='crm_approval').all()
    assert len(bells) == 1 and 'needs your approval' in bells[0].title and bells[0].link.endswith('/lead/%d' % lead.id)
    assert not Notification.query.filter_by(user_id=agent.id, type='crm_approval').count()
    r = client.post('/cs/crm/quote/%d/status' % q.id, data={'action': 'sent'}, follow_redirects=True)
    assert 'needs an approval' in r.get_data(as_text=True)
    _db.session.expire_all()
    assert _db.session.get(CrmQuote, q.id).status == 'draft'
    # the agent cannot approve their own
    client.post('/cs/crm/quote/%d/approve' % q.id)
    _db.session.expire_all()
    assert _db.session.get(CrmQuote, q.id).approved_at is None


def test_an_admin_approves_it_on_the_lead_page_and_then_it_can_be_sent(app, client, agent, lead, admin_user):
    priced(lead)
    as_user(client, agent)
    q = new_quote(client, lead, amount='15000')
    as_user(client, admin_user)
    page = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'Needs approval' in page and '>Approve<' in page
    client.post('/cs/crm/quote/%d/approve' % q.id)
    _db.session.expire_all()
    q = _db.session.get(CrmQuote, q.id)
    assert q.approved_by_id == admin_user.id and q.approved_at
    assert Notification.query.filter_by(user_id=agent.id, type='crm_approval').count() == 1       # the writer is told
    as_user(client, agent)
    client.post('/cs/crm/quote/%d/status' % q.id, data={'action': 'sent'})
    _db.session.expire_all()
    assert _db.session.get(CrmQuote, q.id).status == 'sent'


def test_changing_the_amount_of_an_approved_quote_asks_again(app, client, agent, lead, admin_user):
    priced(lead)
    as_user(client, agent)
    q = new_quote(client, lead, amount='15000')
    as_user(client, admin_user)
    client.post('/cs/crm/quote/%d/approve' % q.id)
    as_user(client, agent)
    client.post('/cs/crm/quote/%d/edit' % q.id, data=quote_form(amount='14000'))
    _db.session.expire_all()
    q = _db.session.get(CrmQuote, q.id)
    assert q.needs_approval and q.approved_at is None


def test_the_approval_list_is_a_card_on_my_day_for_approvers_only(app, client, agent, lead, admin_user):
    priced(lead)
    as_user(client, agent)
    new_quote(client, lead, amount='15000')
    assert 'Waiting for your approval' not in client.get('/cs/crm/today').get_data(as_text=True)
    as_user(client, admin_user)
    page = client.get('/cs/crm/today').get_data(as_text=True)
    assert 'Waiting for your approval (1)' in page and 'Quotable Qamar' in page
    client.post('/cs/crm/quote/%d/approve' % CrmQuote.query.first().id, data={'next': '/cs/crm/today'})
    assert 'Waiting for your approval' not in client.get('/cs/crm/today').get_data(as_text=True)


def test_a_team_lead_approves_for_their_teams_owner_only(app, client, agent, lead):
    ws = access.ensure_defaults()
    boss = make_user('boss@test.com', 'boss', role='cs')
    role = WorkspaceRole(workspace_id=ws.id, name='Lead role', pages=sorted(access.CS_ROLE_PAGES | {'crm_tracker'}))
    _db.session.add(role)
    _db.session.flush()
    ws.roles.append(role)
    access.add_member(ws, boss, role=role)
    outsider = make_user('out@test.com', 'outsider', role='cs')
    access.add_member(ws, outsider, role=role)
    team = WorkspaceTeam(workspace_id=ws.id, name='South')
    _db.session.add(team)
    _db.session.flush()
    team.users.extend([agent, boss])
    _db.session.commit()
    access._cache().clear()
    priced(lead)
    as_user(client, agent)
    q = new_quote(client, lead, amount='15000')
    assert crm_quotes.can_approve(boss, lead) and not crm_quotes.can_approve(outsider, lead)
    assert not crm_quotes.can_approve(agent, lead)
    assert any(r['quote'].id == q.id for r in crm_quotes.waiting_for(boss))
    assert not crm_quotes.waiting_for(outsider)
    assert Notification.query.filter_by(user_id=boss.id, type='crm_approval').count() == 1
    assert not Notification.query.filter_by(user_id=outsider.id, type='crm_approval').count()


def test_the_products_tab_has_the_discount_field(app, client, admin_user, lead):
    as_user(client, admin_user)
    prod = CrmProduct.query.filter_by(code=lead.product).first()
    page = client.get('/admin/crm/pipelines?tab=products&edit=%d' % prod.id).get_data(as_text=True)
    assert 'Biggest discount without approval' in page
    r = client.post('/admin/crm/pipelines/products', data={'id': prod.id, 'name': prod.name, 'currency': 'INR',
                                                       'code': prod.code, 'price': '20000', 'max_discount_pct': '12.5',
                                                       'offered': 'on'}, follow_redirects=True)
    _db.session.expire_all()
    assert _db.session.get(CrmProduct, prod.id).max_discount_pct == Decimal('12.50'), r.status_code
    client.post('/admin/crm/pipelines/products', data={'id': prod.id, 'name': prod.name, 'currency': 'INR', 'code': prod.code,
                                                   'price': '20000', 'max_discount_pct': 'a lot', 'offered': 'on'})
    _db.session.expire_all()
    assert _db.session.get(CrmProduct, prod.id).max_discount_pct == Decimal('12.50')      # a rubbish value is refused


# ====================================================================================== the webhook

def hook(client, body, secret=SECRET, sign=True):
    raw = json.dumps(body).encode()
    headers = {'X-Signature': hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()} if sign else {}
    return client.post('/api/crm/payment-webhook', data=raw, headers=headers, content_type='application/json')


def pending(lead, ref='ref-9', amount='5000'):
    p = CrmPayment(lead=lead, amount=Decimal(amount), currency='INR', reference=ref, status='pending',
                   provider='Razorpay')
    _db.session.add(p)
    _db.session.commit()
    return p


def test_the_webhook_is_not_found_while_its_secret_is_unset(app, client, lead, monkeypatch):
    monkeypatch.delenv('CRM_PAYMENT_WEBHOOK_SECRET', raising=False)
    assert hook(client, {'reference': 'x', 'status': 'paid'}).status_code == 404


def test_the_webhook_refuses_a_missing_or_wrong_signature(app, client, lead, monkeypatch):
    monkeypatch.setenv('CRM_PAYMENT_WEBHOOK_SECRET', SECRET)
    pending(lead)
    assert hook(client, {'reference': 'ref-9', 'status': 'paid'}, sign=False).status_code == 403
    assert hook(client, {'reference': 'ref-9', 'status': 'paid'}, secret='someone-elses').status_code == 403
    _db.session.expire_all()
    assert CrmPayment.query.one().status == 'pending'


def test_a_signed_paid_message_wins_the_lead_and_a_repeat_changes_nothing(app, client, lead, monkeypatch, agent):
    monkeypatch.setenv('CRM_PAYMENT_WEBHOOK_SECRET', SECRET)
    lead.amount = None
    _db.session.commit()
    pending(lead, amount='5000')
    r = hook(client, {'reference': 'ref-9', 'status': 'paid', 'amount': '5000', 'currency': 'INR'})
    assert r.status_code == 200 and r.get_json()['result'] == 'paid'
    _db.session.expire_all()
    lead = _db.session.get(CrmLead, lead.id)
    assert lead.status == 'won' and lead.amount == Decimal('5000.00')
    assert CrmPayment.query.one().status == 'paid'
    moves = CrmStageChange.query.filter_by(lead_id=lead.id).count()
    again = hook(client, {'reference': 'ref-9', 'status': 'paid'})
    assert again.status_code == 200 and again.get_json()['result'] == 'already'
    _db.session.expire_all()
    assert CrmStageChange.query.filter_by(lead_id=lead.id).count() == moves
    assert Notification.query.filter_by(user_id=agent.id, type='crm_paid').count() == 1


def test_a_failed_payment_is_marked_noted_and_rings_the_owner_once(app, client, lead, monkeypatch, agent):
    monkeypatch.setenv('CRM_PAYMENT_WEBHOOK_SECRET', SECRET)
    pending(lead)
    r = hook(client, {'reference': 'ref-9', 'status': 'failed'})
    assert r.get_json()['result'] == 'failed'
    _db.session.expire_all()
    assert CrmPayment.query.one().status == 'failed'
    assert _db.session.get(CrmLead, lead.id).status == 'open'
    assert any('failed' in (t.body or '') for t in CrmTouchpoint.query.filter_by(lead_id=lead.id, channel='system'))
    assert Notification.query.filter_by(user_id=agent.id, type='crm_failed').count() == 1
    assert hook(client, {'reference': 'ref-9', 'status': 'failed'}).get_json()['result'] == 'already'
    _db.session.expire_all()
    assert Notification.query.filter_by(user_id=agent.id, type='crm_failed').count() == 1


def test_a_paid_payment_is_not_turned_back_by_a_late_failed_message(app, client, lead, monkeypatch):
    monkeypatch.setenv('CRM_PAYMENT_WEBHOOK_SECRET', SECRET)
    pending(lead)
    hook(client, {'reference': 'ref-9', 'status': 'paid'})
    assert hook(client, {'reference': 'ref-9', 'status': 'failed'}).get_json()['result'] == 'already'
    _db.session.expire_all()
    assert CrmPayment.query.one().status == 'paid'


def test_the_webhook_ignores_an_unknown_reference_and_rubbish(app, client, lead, monkeypatch):
    monkeypatch.setenv('CRM_PAYMENT_WEBHOOK_SECRET', SECRET)
    assert hook(client, {'reference': 'nope', 'status': 'paid'}).get_json()['result'] == 'unknown'
    assert hook(client, {'reference': 'ref', 'status': 'weird'}).status_code == 400
    raw = b'not json'
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert client.post('/api/crm/payment-webhook', data=raw, headers={'X-Signature': sig}).status_code == 400


# ====================================================================================== the numbers

def counts(lead_owner=None):
    start, end = datetime.utcnow() - timedelta(days=1), datetime.utcnow() + timedelta(days=1)
    got = crm_numbers.bundle(['quoted', 'payment_links'], start, end, crm_numbers.scope())
    return got['quoted'], got['payment_links']


def test_a_quote_and_its_milestone_line_count_once(app, client, agent, lead):
    as_user(client, agent)
    q = new_quote(client, lead)
    client.post('/cs/crm/quote/%d/status' % q.id, data={'action': 'sent'})
    client.post('/cs/crm/lead/%d/payment' % lead.id, data={'amount': '1', 'reference': 'n1'})
    assert counts() == (1, 1)
    # the old buttons on top of it are separate acts and count on their own
    other = ti_lead(phone='+919876566661', name='Button Only')
    other.owner_id = agent.id
    _db.session.commit()
    crm.mark_event(other, 'Q', user=agent)
    assert counts() == (2, 1)


def test_without_the_milestone_button_the_row_counts_by_itself(app, client, agent, lead):
    for s in lead.pipeline.stages:
        s.button_label = s.button_code = None
    _db.session.commit()
    as_user(client, agent)
    q = new_quote(client, lead)
    client.post('/cs/crm/quote/%d/status' % q.id, data={'action': 'sent'})
    client.post('/cs/crm/lead/%d/payment' % lead.id, data={'amount': '1', 'reference': 'n2'})
    _db.session.expire_all()
    assert _db.session.get(CrmQuote, q.id).sent_touch_id is None
    assert CrmPayment.query.one().link_touch_id is None
    assert counts() == (1, 1)
    # a draft was never sent: it counts nowhere
    new_quote(client, lead, title='Another')
    assert counts() == (1, 1)


def test_results_shows_the_same_counts_and_never_the_binned_leads(app, client, agent, lead, admin_user):
    for s in lead.pipeline.stages:
        s.button_label = s.button_code = None
    _db.session.commit()
    as_user(client, agent)
    q = new_quote(client, lead)
    client.post('/cs/crm/quote/%d/status' % q.id, data={'action': 'sent'})
    assert counts() == (1, 0)
    crm_bin.remove(_db.session.get(CrmLead, lead.id), admin_user)
    assert counts() == (0, 0)


def test_forecast_stays_one_line_per_lead(app, client, agent, lead):
    lead.amount, lead.currency = Decimal('10000'), 'INR'
    lead.close_date = (datetime.utcnow() + crm.IST).date()
    _db.session.commit()
    as_user(client, agent)
    before = crm_money.forecast(lead.close_date, lead.close_date, [agent])['rows'][agent.id]
    for amt in ('10000', '12000'):
        q = new_quote(client, lead, amount=amt)
        client.post('/cs/crm/quote/%d/status' % q.id, data={'action': 'sent'})
    _db.session.expire_all()
    after = crm_money.forecast(lead.close_date, lead.close_date, [agent])['rows'][agent.id]
    total = lambda r: r['commit'] + r['best_case'] + r['pipeline']             # noqa: E731
    assert total(after) == total(before) == Decimal('10000')                     # two quotes, still one lead's value
    assert after['best_case_n'] + after['pipeline_n'] + after['commit_n'] == 1


# ====================================================================================== safe by construction

def scoped_world():
    ws = access.ensure_defaults()
    role = WorkspaceRole(workspace_id=ws.id, name='Own only', pages=sorted(access.CS_ROLE_PAGES), crm_scope='own')
    _db.session.add(role)
    _db.session.flush()
    ws.roles.append(role)
    asha = make_user('asha@test.com', 'asha', role='cs')
    access.add_member(ws, asha, role=role)
    bela = make_user('bela@test.com', 'bela', role='cs')
    access.add_member(ws, bela, role=access.system_role(ws, 'cs'))
    _db.session.commit()
    access._cache().clear()
    mine = ti_lead(phone='+919876577771', name='Visible Vimal')
    theirs = ti_lead(phone='+919876577772', name='Hidden Hari')
    mine.owner_id, theirs.owner_id = asha.id, bela.id
    _db.session.commit()
    return asha, bela, mine, theirs


def test_a_scoped_agent_meets_no_quote_or_payment_of_a_lead_they_cannot_see(app, client):
    asha, bela, mine, theirs = scoped_world()
    q = CrmQuote(lead=theirs, title='Secret plan', amount=Decimal('99999'), currency='INR', status='sent', sent_at=datetime.utcnow())
    p = CrmPayment(lead=theirs, amount=Decimal('99999'), currency='INR', reference='SECRET-REF-1', status='pending')
    _db.session.add_all([q, p])
    _db.session.commit()
    qid, pid = q.id, p.id
    as_user(client, asha)
    assert client.get('/cs/crm/lead/%d' % theirs.id).status_code == 404
    for url, data in (('/cs/crm/lead/%d/quote' % theirs.id, quote_form()), ('/cs/crm/lead/%d/payment' % theirs.id, {'amount': '1'}),
                      ('/cs/crm/quote/%d/status' % qid, {'action': 'accepted'}), ('/cs/crm/quote/%d/approve' % qid, {}),
                      ('/cs/crm/quote/%d/edit' % qid, quote_form()), ('/cs/crm/quote/%d/delete' % qid, {}),
                      ('/cs/crm/payment/%d/status' % pid, {'action': 'paid'}), ('/cs/crm/payment/%d/delete' % pid, {})):
        assert client.post(url, data=data).status_code == 404, url
    _db.session.expire_all()
    assert _db.session.get(CrmQuote, qid).status == 'sent' and _db.session.get(CrmPayment, pid).status == 'pending'
    # Find a person: neither "Q-<id>" nor the payment reference leads to them
    for term in ('Q-%d' % qid, 'SECRET-REF-1', 'secret-ref'):
        found = client.get('/cs/crm/find?q=%s' % term).get_json()
        assert not found['items'], term
    # a visible lead's own reference is found
    q2 = CrmQuote(lead=mine, title='Mine', amount=Decimal('1'), currency='INR', status='draft')
    _db.session.add(q2)
    _db.session.commit()
    found = client.get('/cs/crm/find?q=Q-%d' % q2.id).get_json()
    assert [i['name'] for i in found['items']] == ['Visible Vimal']
    # and an admin-like viewer who sees everything finds the hidden one
    as_user(client, bela)
    assert [i['name'] for i in client.get('/cs/crm/find?q=Q-%d' % qid).get_json()['items']] == ['Hidden Hari']


def test_a_team_lead_who_sees_only_their_own_leads_is_not_shown_a_teammates_quote(app, client):
    ws = access.ensure_defaults()
    pages = sorted(access.CS_ROLE_PAGES | {'crm_tracker'})
    boss_role = WorkspaceRole(workspace_id=ws.id, name='Own-scope lead', pages=pages, crm_scope='own')
    wide_role = WorkspaceRole(workspace_id=ws.id, name='Team-scope lead', pages=pages, crm_scope='team')
    _db.session.add_all([boss_role, wide_role])
    _db.session.flush()
    ws.roles.extend([boss_role, wide_role])
    narrow, wide = make_user('narrow@test.com', 'narrow', role='cs'), make_user('wide@test.com', 'wide', role='cs')
    mate = make_user('mate@test.com', 'mate', role='cs')
    access.add_member(ws, narrow, role=boss_role)
    access.add_member(ws, wide, role=wide_role)
    access.add_member(ws, mate, role=access.system_role(ws, 'cs'))
    team = WorkspaceTeam(workspace_id=ws.id, name='East')
    _db.session.add(team)
    _db.session.flush()
    team.users.extend([narrow, wide, mate])
    _db.session.commit()
    access._cache().clear()
    theirs = ti_lead(phone='+919876599901', name='Mates Lead')
    theirs.owner_id = mate.id
    _db.session.add(CrmQuote(lead=theirs, title='Q', amount=Decimal('1'), currency='INR', status='draft', needs_approval=True))
    _db.session.commit()
    assert [r['lead'].id for r in crm_quotes.waiting_for(wide)] == [theirs.id]          # team scope: the teammate's lead is theirs to see
    assert crm_quotes.waiting_for(narrow) == []                                          # own scope: it is not, so it is not listed
    assert crm_quotes.can_approve(narrow, theirs)                                        # (they are a team lead; the list still hides it)


def test_the_approval_list_hides_what_the_viewer_may_not_see(app, client, admin_user):
    asha, bela, mine, theirs = scoped_world()
    ws = access.ensure_defaults()
    for l in (mine, theirs):
        _db.session.add(CrmQuote(lead=l, title='Q', amount=Decimal('1'), currency='INR', status='draft', needs_approval=True))
    _db.session.commit()
    assert {r['lead'].id for r in crm_quotes.waiting_for(admin_user)} == {mine.id, theirs.id}
    assert crm_quotes.waiting_for(asha) == [] and crm_quotes.waiting_for(bela) == []      # neither is an approver


def test_a_binned_lead_hides_its_quotes_and_payments_and_purging_deletes_them(app, client, agent, lead, admin_user):
    _db.session.add_all([CrmQuote(lead=lead, title='Q', amount=Decimal('1'), currency='INR', status='draft'),
                         CrmPayment(lead=lead, amount=Decimal('1'), currency='INR', reference='bin-ref', status='pending')])
    _db.session.commit()
    lid = lead.id
    crm_bin.remove(_db.session.get(CrmLead, lid), admin_user)
    _db.session.expire_all()
    assert CrmQuote.query.count() == 0 and CrmPayment.query.count() == 0           # hidden with the lead
    assert CrmQuote.query.execution_options(include_deleted=True).count() == 1
    assert CrmQuote.query.join(CrmLead, CrmLead.id == CrmQuote.lead_id).count() == 0
    crm_bin.restore(crm_bin.get_removed(lid), admin_user)
    _db.session.expire_all()
    assert CrmQuote.query.count() == 1 and CrmPayment.query.count() == 1
    crm_bin.remove(_db.session.get(CrmLead, lid), admin_user)
    crm_bin.purge(crm_bin.get_removed(lid), admin_user)
    _db.session.expire_all()
    assert CrmQuote.query.execution_options(include_deleted=True).count() == 0
    assert CrmPayment.query.execution_options(include_deleted=True).count() == 0


def test_erasing_a_person_deletes_their_quotes_and_payments(app, client, agent, lead, admin_user):
    _db.session.add_all([CrmQuote(lead=lead, title='Q', amount=Decimal('1'), currency='INR', status='draft'),
                         CrmPayment(lead=lead, amount=Decimal('1'), currency='INR', reference='erase-ref', status='pending')])
    _db.session.commit()
    pid = lead.person_id
    crm_people.erase(_db.session.get(CrmPerson, pid), admin_user)
    _db.session.expire_all()
    assert CrmQuote.query.execution_options(include_deleted=True).count() == 0
    assert CrmPayment.query.execution_options(include_deleted=True).count() == 0


def test_merging_two_people_keeps_the_quotes_and_payments_on_the_moved_leads(app, client, agent, lead, admin_user):
    from app.services import crm_merge
    other = ti_lead(phone='+919876588881', name='Quotable Qamar Again')
    _db.session.add_all([CrmQuote(lead=other, title='Moves', amount=Decimal('5'), currency='INR', status='draft'),
                         CrmPayment(lead=other, amount=Decimal('5'), currency='INR', reference='merge-ref', status='pending')])
    _db.session.commit()
    keep, gone = _db.session.get(CrmPerson, lead.person_id), _db.session.get(CrmPerson, other.person_id)
    crm_merge.merge(keep, gone, admin_user)
    _db.session.expire_all()
    assert {q.title for q in CrmQuote.query.join(CrmLead, CrmLead.id == CrmQuote.lead_id)
            .filter(CrmLead.person_id == keep.id)} == {'Moves'}
    assert CrmPayment.query.filter_by(reference='merge-ref').one().lead.person_id == keep.id


def test_every_new_endpoint_is_inside_a_page_a_role_can_hold(app):
    names = ('quote_add', 'quote_edit', 'quote_status', 'quote_approve', 'quote_delete', 'payment_add',
             'payment_status', 'payment_delete', 'view_save', 'view_rename', 'view_delete')
    for n in names:
        assert 'crm.' + n in access.CRM_DAILY and 'admin_crm.' + n in access.CRM_DAILY
