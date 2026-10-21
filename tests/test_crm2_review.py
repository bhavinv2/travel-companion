"""Sales CRM 2.0 -- what the final review (a click-through in a real browser) found and put right.

    move       an amount typed in "Did you send the quote?" answers a stage's "Value": it is not asked for twice;
               the form says which currency the value is in; a move answers with the lead's value in the reporting
               currency so the board's column totals follow a drag without a reload
    board      cards carry their value, columns their count and sum; a won / lost column says "Last 30 days" under
               its head instead of inside it (one line)
    history    a value changed together with its currency reads "from $350 to ₹25,000", not "from ₹350"
    targets    Targets comes with Team today (team-lead roles saved before Phase 1 have it), and stays grantable
    e-mail     Messages has the e-mail sender (crm.email_from): name and reply-to, checked; the composer uses it
    whatsapp   a second workspace while nothing is linked says WhatsApp isn't linked to it yet (no other name)
    no confirm the pages and scripts of CRM 2.0 ask on the page, never with the browser's confirm box
"""
import os
import re
from datetime import timedelta
from decimal import Decimal as D

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmCurrencyRate, CrmLead, CrmPipeline, CrmStage, User, WorkspaceRole
from app.services import access, crm, crm_audit, crm_email, crm_money, crm_scope, settings

from test_crm_wa_sync_engine import ti_lead


def words(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))


def stage(key):
    return CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == 'ti-standard', CrmStage.key == key).one()


@pytest.fixture
def agent(app):
    return make_user('agent@test.com', 'agent', role='cs')


@pytest.fixture
def lead(app, agent):
    l = ti_lead(phone='+919876544441', name='Review Rani')
    l.owner_id = agent.id
    l.amount = l.close_date = None
    _db.session.commit()
    return l


def rate(code, value):
    _db.session.add(CrmCurrencyRate(code=code, rate=D(value)))
    _db.session.commit()


# ====================================================================================== the move

def test_an_amount_from_the_quote_dialog_answers_the_value_the_stage_asks_for(app, client, lead, agent):
    quoted = stage('quoted')
    quoted.requires = ['amount', 'close_date']
    _db.session.commit()
    login(client, agent.email)
    r = client.post('/cs/crm/lead/%d/move' % lead.id,
                    json={'stage_id': quoted.id, 'log_milestone': True, 'amount': '15000'})
    assert r.status_code == 400
    assert [m['key'] for m in r.get_json()['need_fields']] == ['close_date']          # only what is still missing
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).amount is None                           # nothing kept until it moves
    r = client.post('/cs/crm/lead/%d/move' % lead.id,
                    json={'stage_id': quoted.id, 'log_milestone': True, 'amount': '15000',
                          'fields': {'close_date': '2031-02-01'}})
    assert r.status_code == 200, r.get_data(as_text=True)
    _db.session.expire_all()
    l = _db.session.get(CrmLead, lead.id)
    assert l.stage_id == quoted.id and l.amount == D('15000') and str(l.close_date) == '2031-02-01'


def test_the_form_says_which_currency_the_value_is_in(app, client, lead, agent):
    quoted = stage('quoted')
    quoted.requires = ['amount']
    lead.currency = 'USD'
    _db.session.commit()
    login(client, agent.email)
    need = client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': quoted.id}).get_json()['need_fields']
    assert need == [{'key': 'amount', 'label': 'Value', 'type': 'money', 'options': [], 'currency': 'USD'}]


def test_a_move_answers_with_the_value_in_the_reporting_currency(app, client, lead, agent):
    rate('USD', '84')
    lead.amount, lead.currency = D('200'), 'USD'
    _db.session.commit()
    login(client, agent.email)
    d = client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': stage('prospect').id}).get_json()
    assert d['success'] and d['value'] == '16800'
    lead2 = ti_lead(phone='+919876544442', name='No Value Nalini')
    lead2.amount = None
    _db.session.commit()
    d = client.post('/cs/crm/lead/%d/move' % lead2.id, json={'stage_id': stage('prospect').id}).get_json()
    assert d['value'] == '0'


# ====================================================================================== the board

def test_the_board_carries_what_its_totals_need_and_keeps_finish_heads_on_one_line(app, client, admin_user, lead):
    rate('USD', '84')
    lead.amount, lead.currency = D('100'), 'USD'
    won = CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == 'ti-standard', CrmStage.kind == 'won').first()
    _db.session.commit()
    login(client, admin_user.email)
    page = client.get('/admin/crm/?p=ti-standard&view=board&owner=all').get_data(as_text=True)
    assert 'data-lead="%d"' % lead.id in page and 'data-value="8400"' in page
    assert 'data-currency="INR"' in page and 'data-col-count=' in page and 'data-col-sum=' in page
    assert 'data-strip="%d"' % won.id in page
    assert '· 30 days' not in page and 'Last 30 days</p>' in page                    # under the head, not inside it
    assert 'title="Moved here in the last 30 days"' in page
    js = open(os.path.join('app', 'static', 'js', 'crm.js'), encoding='utf-8').read()
    assert 'recount(card' in js and 'dataset.colCount' in js and 'dataset.colSum' in js


def test_the_base_amount_helper(app):
    from app.routes.crm import base_amount
    rate('USD', '83.5')
    assert base_amount(D('10'), 'USD') == '835'
    assert base_amount(None, 'USD') == '0' and base_amount(D('5'), 'XYZ') == '0'


# ====================================================================================== history

def test_a_value_changed_with_its_currency_reads_in_each_currency(app, client, lead, agent):
    lead.amount, lead.currency = D('350'), 'USD'
    _db.session.commit()
    login(client, agent.email)
    r = client.post('/cs/crm/lead/%d/money' % lead.id, json={'amount': '25000', 'currency': 'INR'})
    assert r.status_code == 200, r.get_data(as_text=True)
    lines = [h['what'] for h in crm_audit.history_for('lead', lead.id, 'INR')]
    assert 'changed the value from $350 to ₹25,000' in lines
    assert 'changed the currency from USD to INR' in lines
    assert 'set the value to ₹25,000' not in lines


def test_the_amount_sides_walk_back_over_currency_changes(app):
    from datetime import datetime
    from types import SimpleNamespace as R
    t = datetime(2031, 1, 1, 12)
    rows = [R(id=5, at=t + timedelta(hours=2), user_id=1, field='amount', old='100', new='200'),          # INR, later
            R(id=4, at=t + timedelta(seconds=1), user_id=1, field='currency', old='USD', new='INR'),
            R(id=3, at=t, user_id=1, field='amount', old='50', new='100'),
            R(id=2, at=t - timedelta(days=1), user_id=None, field='amount', old=None, new='50')]
    sides = crm_audit._amount_sides(rows, 'INR')
    assert sides == {5: ('INR', 'INR'), 3: ('USD', 'INR'), 2: ('USD', 'USD')}


# ====================================================================================== targets

def test_targets_come_with_team_today_and_stay_grantable(app):
    assert access.PAGES['crm_targets']['with'] == frozenset({'crm_tracker'})
    assert access.PAGES['crm_targets']['grant'] is True
    ws = access.ensure_defaults()
    old_lead = WorkspaceRole(workspace_id=ws.id, name='Team lead (before Phase 1)',
                             pages=sorted(access.CS_ROLE_PAGES | {'crm_tracker', 'crm_insights'}))
    plain = WorkspaceRole(workspace_id=ws.id, name='Plain sales', pages=sorted(access.CS_ROLE_PAGES))
    _db.session.add_all([old_lead, plain])
    _db.session.commit()
    a, b = make_user('tl@test.com', 'tl', role='cs'), make_user('ps@test.com', 'ps', role='cs')
    access.add_member(ws, a, role=old_lead)
    access.add_member(ws, b, role=plain)
    _db.session.commit()
    access._cache().clear()
    assert access.can(a, 'crm_targets') and not access.can(b, 'crm_targets')


def test_an_old_team_lead_role_opens_targets(app, client):
    ws = access.ensure_defaults()
    role = WorkspaceRole(workspace_id=ws.id, name='Old team lead', pages=sorted(access.CS_ROLE_PAGES | {'crm_tracker'}))
    _db.session.add(role)
    _db.session.commit()
    u = make_user('oldtl@test.com', 'oldtl', role='cs')
    access.add_member(ws, u, role=role)
    _db.session.commit()
    access._cache().clear()
    login(client, u.email)
    r = client.get('/admin/crm/targets', follow_redirects=True)
    assert r.status_code == 200 and 'Save targets' in r.get_data(as_text=True)


# ====================================================================================== the e-mail sender

def test_messages_sets_the_e_mail_sender_and_the_composer_uses_it(app, client, admin_user, lead):
    login(client, admin_user.email)
    page = words(client.get('/admin/crm/quick-replies').get_data(as_text=True))
    assert 'E-mails to customers' in page and 'Sender name' in page
    r = client.post('/admin/crm/quick-replies/email-sender', data={'name': '  NRI   Sales ', 'reply_to': 'nope'})
    assert r.status_code == 302 and settings.get_setting(crm_email.SETTING_KEY) is None   # a bad address: nothing saved
    client.post('/admin/crm/quick-replies/email-sender', data={'name': '  NRI   Sales ', 'reply_to': 'sales@example.com'})
    assert settings.get_setting(crm_email.SETTING_KEY) == {'name': 'NRI Sales', 'reply_to': 'sales@example.com'}
    d = client.get('/admin/crm/email/compose?lead_id=%d' % lead.id).get_json()
    assert d['from_name'] == 'NRI Sales' and d['reply_to'] == 'sales@example.com'
    # empty again: the default name, replies to whoever wrote
    client.post('/admin/crm/quick-replies/email-sender', data={'name': '', 'reply_to': ''})
    assert crm_email.sender_for(admin_user) == (crm_email.DEFAULT_NAME, admin_user.email)


def test_only_who_has_the_whatsapp_set_up_changes_the_sender(app, client, agent):
    login(client, agent.email)
    assert 'E-mails to customers' not in client.get('/cs/crm/quick-replies').get_data(as_text=True)
    client.post('/admin/crm/quick-replies/email-sender', data={'name': 'Hacked', 'reply_to': ''})
    assert settings.get_setting(crm_email.SETTING_KEY) is None


# ====================================================================================== WhatsApp in a second workspace

def test_a_second_workspace_says_whatsapp_is_not_linked_to_it_while_nothing_is_linked(app, client):
    a = access.ensure_defaults()
    b = access.create_workspace('Bee Care')
    _db.session.commit()
    ben = make_user('ben@test.com', 'ben', role='cs')
    access.add_member(b, ben, role=access.system_role(b, 'admin'))
    _db.session.commit()
    access._cache().clear()
    with crm_scope.use(b.id):
        crm.ensure_defaults()
    login(client, ben.email)
    from flask import g
    g.pop('_login_user', None)
    page = client.get('/admin/crm/connection').get_data(as_text=True)
    card = words(page.split('data-wa-elsewhere>')[1].split('</section>')[0])
    assert "WhatsApp isn't linked to this workspace yet" in card
    assert 'linked to %s' % a.name not in card and 'switch to' not in card


# ====================================================================================== no confirm()

def test_crm_two_pages_and_scripts_never_use_the_browsers_confirm_box(app):
    root = os.path.join('app')
    for rel in ('templates/cs/crm/insights.html', 'templates/cs/crm/bin.html', 'static/js/crm-activities.js',
                'static/js/crm-quotes.js', 'static/js/crm-files.js', 'static/js/crm-rules.js', 'static/js/crm-ai.js',
                'static/js/crm-targets.js'):
        text = open(os.path.join(root, *rel.split('/')), encoding='utf-8').read()
        assert 'confirm(' not in text.replace('fam-confirm', ''), rel
        assert 'data-confirm' not in text, rel


def test_dialogs_sit_in_the_middle_and_chained_questions_stay_open(app):
    css = open(os.path.join('app', 'static', 'css', 'crm.css'), encoding='utf-8').read()
    assert '.crm-dialog { margin: auto; }' in css                 # style.css's * { margin: 0 } pinned them top-left
    js = open(os.path.join('app', 'static', 'js', 'crm.js'), encoding='utf-8').read()
    assert js.count("function once() { if (dialog.open) return;") == 3


def test_the_rules_editor_hides_the_searchable_dropdowns_too(app):
    js = open(os.path.join('app', 'static', 'js', 'crm-rules.js'), encoding='utf-8').read()
    assert "box.classList.contains('ss')" in js and "addEventListener('DOMContentLoaded', again)" in js
    ss = open(os.path.join('app', 'static', 'js', 'searchselect.js'), encoding='utf-8').read()
    assert 'if (o.hidden) return;' in ss
    # the dropdown's own search box is in no form, so Enter still sends Leads' "Find in these" (no button there)
    assert 'form="ss-no-form"' in ss
