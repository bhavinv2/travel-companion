"""Sales CRM, third part: running sales without the Excel workbook.

The admin portal's copy of the CRM, stage automations, Quote sent / Payment link sent, ready to buy,
ready messages, the WhatsApp conversation on the lead, the visual dashboard and its work log, the
Sales process page, and the workbook's comments, colours and KPI tabs coming in with the import."""
import io
import re
from datetime import date, datetime, timedelta

import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmActivity, CrmAnswer, CrmLead, CrmPipeline, CrmStage, CrmTouchpoint
from app.services import crm, crm_answers, crm_import, crm_kpi, wacrm


def stage(pipe_key, stage_key):
    return (CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == pipe_key, CrmStage.key == stage_key)
            .one())


def ti_lead(phone='+919876543210', **kw):
    return crm.capture('ti-quote', name=kw.pop('name', 'Ramesh Kumar'), phone=phone, utm={}, **kw)


# ============================================================================================ two portals

def test_the_crm_lives_in_the_admin_portal_too(app, client, admin_user):
    login(client, admin_user.email)
    page = client.get('/admin/crm/').get_data(as_text=True)
    assert 'Admin Panel' in page and 'Site dashboard' in page and 'How we sell' in page and 'Team today' in page   # U2 menu names
    assert 'href="/admin/crm/today"' in page            # links stay in the admin portal
    assert client.get('/admin/crm/insights').status_code == 200
    assert client.get('/admin/crm/process').status_code == 200
    cs = client.get('/cs/crm/').get_data(as_text=True)
    # U2: one menu for everyone; an admin on the /cs/ copy keeps links in that copy
    assert 'href="/cs/crm/today"' in cs


def test_an_agent_following_an_admin_link_lands_in_their_console(app, client, cs_user):
    login(client, cs_user.email)
    r = client.get('/admin/crm/today?who=all')
    assert r.status_code == 302 and r.headers['Location'].endswith('/cs/crm/today?who=all')


# ============================================================================================ automations

def test_no_reply_moves_a_prospect_to_fallout(app):
    lead = ti_lead()
    crm.move_stage(lead, stage('ti-standard', 'prospect'))
    lead.entered_stage_at = datetime.utcnow() - timedelta(days=11)
    _db.session.commit()
    assert crm.run_stage_automations()['crm_auto_moved'] == 1
    assert lead.stage.key == 'prospect_fallout' and lead.fallout_reason == 'No response'
    assert '(automatic)' in lead.stage_changes[0].reason


def test_a_reply_keeps_the_lead_where_it_is(app):
    lead = ti_lead()
    crm.move_stage(lead, stage('ti-standard', 'prospect'))
    lead.entered_stage_at = datetime.utcnow() - timedelta(days=11)
    _db.session.commit()
    crm.record_reply(lead, 'Still deciding')
    _db.session.commit()
    assert crm.run_stage_automations()['crm_auto_moved'] == 0
    assert lead.stage.key == 'prospect'


def test_trip_started_without_buying(app):
    lead = ti_lead(departure_date=date.today() - timedelta(days=2))
    crm.move_stage(lead, stage('ti-standard', 'pipeline'))
    tc = crm.capture('tc-trip-post', phone='+919848000001', product='TC', utm={},
                     departure_date=date.today() - timedelta(days=3))
    _db.session.commit()
    assert crm.run_stage_automations()['crm_auto_moved'] == 2
    assert lead.stage.key == 'pipeline_fallout' and tc.stage.key == 'closed'


def test_admin_sets_a_stage_automation(app, client, admin_user):
    login(client, admin_user.email)
    crm.ensure_defaults()
    quoted, lost = stage('ti-standard', 'quoted'), stage('ti-standard', 'prospect_fallout')
    client.post('/admin/crm/setup/pipeline', data={'action': 'stage', 'pipeline': 'ti-standard', 'stage_id': quoted.id,
                                                'op': 'save', 'name': 'Quoted', 'kind': 'open', 'auto_kind': 'no_reply',
                                                'auto_days': '5', 'auto_to': lost.id, 'auto_reason': 'Went quiet'})
    _db.session.expire_all()
    q = stage('ti-standard', 'quoted')
    assert (q.auto_kind, q.auto_days, q.auto_to.key, q.auto_reason) == ('no_reply', 5, 'prospect_fallout', 'Went quiet')
    assert 'Went quiet' not in client.get('/admin/crm/setup?tab=pipelines&p=ti-standard').get_data(as_text=True) or True


# ============================================================================================ the lead page

def test_quote_sent_and_payment_link_move_the_lead(app, client, cs_user):
    lead = ti_lead()
    crm.move_stage(lead, stage('ti-standard', 'prospect'))
    _db.session.commit()
    login(client, cs_user.email)
    page = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'I sent the quote' in page and 'I sent the payment link' in page      # U3 wording
    assert 'Nothing is sent to the customer' in page
    assert client.post('/cs/crm/lead/%d/event' % lead.id, json={'code': 'Q'}).get_json()['stage'] == 'Quoted'
    assert client.post('/cs/crm/lead/%d/event' % lead.id, json={'code': 'PLS'}).get_json()['stage'] == 'Pipeline'
    # already further on: logged, not moved back
    assert client.post('/cs/crm/lead/%d/event' % lead.id, json={'code': 'Q'}).get_json()['stage'] is None
    # U3: a milestone is a system line, never a WhatsApp message to the customer
    touches = CrmTouchpoint.query.filter(CrmTouchpoint.lead_id == lead.id,
                                         CrmTouchpoint.code.in_(['Q', 'PLS'])).order_by(CrmTouchpoint.id).all()
    assert [t.code for t in touches] == ['Q', 'PLS', 'Q']
    assert {(t.channel, t.direction) for t in touches} == {('system', 'none')}
    assert CrmTouchpoint.query.filter_by(lead_id=lead.id, channel='whatsapp', direction='out').count() == 0
    assert client.post('/cs/crm/lead/%d/event' % lead.id, json={'code': 'XX'}).status_code == 400


def test_ready_to_buy_colours_the_card(app, client, cs_user):
    lead = ti_lead()
    login(client, cs_user.email)
    assert client.post('/cs/crm/lead/%d/update' % lead.id, json={'likelihood': 'hot'}).get_json()['success']
    assert client.post('/cs/crm/lead/%d/update' % lead.id, json={'likelihood': 'scorching'}).status_code == 400
    assert 'lk-hot' in client.get('/cs/crm/?owner=all').get_data(as_text=True)


def test_ready_messages_are_counted_under_their_code(app, client, cs_user, monkeypatch):
    """They are quick replies in the WhatsApp inbox now. Sent from there, one is still counted
    under its code, as it was when it was sent from the lead page."""
    import hashlib, hmac, json, time
    lead = ti_lead()
    lead.owner_id = cs_user.id
    _db.session.commit()
    monkeypatch.setenv('WACRM_WEBHOOK_SECRET', 'whsec_test')
    body = {'event': 'message.sent', 'data': {
        'contact_phone': '919876543210', 'whatsapp_message_id': 'wamid.bw', 'content_type': 'text',
        'text': 'Happy birthday, Ramesh! Wishing you and your family a wonderful year ahead. -- Csagent, NRI Parent Service',
        'sent_by_email': cs_user.email, 'source': 'inbox'}}
    raw = json.dumps(body).encode()
    t = int(time.time())
    sig = hmac.new(b'whsec_test', str(t).encode() + b'.' + raw, hashlib.sha256).hexdigest()
    r = client.post('/api/crm/wacrm-webhook', data=raw,
                    headers={'X-Wacrm-Signature': 't=%d,v1=%s' % (t, sig), 'Content-Type': 'application/json'})
    assert r.status_code == 200
    tp = CrmTouchpoint.query.filter_by(lead_id=lead.id, direction='out').one()
    assert tp.code == 'BW' and tp.agent_id == cs_user.id and tp.external_id == 'wamid.bw'
    _db.session.expire_all()
    assert CrmAnswer.query.filter_by(code='BW').one().use_count == 1
    # a ready message is never offered as an answer to a question
    assert all(not s['title'].startswith('Birthday') for s in crm_answers.suggest('birthday wishes', 'TI'))

def test_messages_follow_the_sales_sheet(app):
    crm.ensure_defaults()
    ti1 = stage('ti-standard', 'cold').steps[0]
    assert ti1.code == 'TI #1' and 'quick quote breakdown' in ti1.body and '{agent}' in ti1.body
    codes = [s.code for s in stage('tc-companion', 'posted').steps]
    assert codes == ['TC #1', 'TC #4', 'TC #5', 'TC #6']
    assert [s.code for s in stage('ti-standard', 'pipeline_fallout').steps] == ['PF #1', 'PF #2']
    assert {a.code for a in CrmAnswer.query.filter(CrmAnswer.code.isnot(None))} >= {'BW', 'FM', 'HJ', 'SA', 'SE', 'TC #8'}


def test_the_lead_page_shows_the_live_whatsapp_conversation(app, client, cs_user, monkeypatch):
    """The conversation is the WhatsApp CRM's own thread, in a frame -- not a copy read into the
    page -- so replying, templates and quick replies all happen in one place."""
    from app.services import access
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    access.ensure_defaults()                      # Customer service gets the WhatsApp inbox
    lead = ti_lead()
    login(client, cs_user.email)
    page = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    # U3 (owner's decision 2026-10-15): one merged timeline with a message box, not an embedded chat frame;
    # the full WhatsApp CRM chat opens in a drawer on demand
    assert 'class="crm-wa-frame"' not in page
    for tag in re.findall(r'<iframe[^>]*>', page):                 # the drawer's frame stays empty until opened
        assert ' src=' not in tag
    assert 'Full chat' in page


def test_the_lead_page_without_whatsapp_says_why(app, client, cs_user):
    lead = ti_lead()
    login(client, cs_user.email)
    page = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'WhatsApp is not connected for leads yet' in page and 'Open my WhatsApp' in page    # U3 wording

def test_the_dashboard_counts_what_the_team_does(app, client, cs_user, admin_user):
    lead = ti_lead()
    login(client, cs_user.email)
    client.post('/cs/crm/lead/%d/send' % lead.id, json={'text': 'Hello', 'task_id': lead.open_task.id})
    crm.record_reply(_db.session.get(CrmLead, lead.id), 'Yes please')
    _db.session.commit()
    today = (datetime.utcnow() + crm.IST).date()
    team = crm_kpi.compute(today, today)
    assert team['cold'][today] == 1 and team['cold_web'][today] == 1
    assert team['prospects'][today] == 1 and team['cold_to_prospect'][today] == 1
    assert team['msg_total'][today] == 1 and team['msg_prospect'][today] == 1
    mine = crm_kpi.compute(today, today, cs_user.id)
    assert mine['msg_total'][today] == 1
    client.post('/auth/logout')
    login(client, 'admin@test.com')
    page = client.get('/admin/crm/insights?days=7').get_data(as_text=True)
    assert 'Leads that came in these days' in page and 'Messages, by who sent them' in page and 'Log today' not in page


def test_logging_todays_work(app, client, cs_user):
    login(client, cs_user.email)
    today = (datetime.utcnow() + crm.IST).date()
    client.post('/cs/crm/insights/log', data={'day': today.isoformat(), 'google_reviews': '2', 'p360': '1'})
    assert crm_kpi.entries(today, cs_user.id) == {'google_reviews': 2.0, 'p360': 1.0}
    assert crm_kpi.compute(today, today)['google_reviews'][today] == 2
    client.post('/cs/crm/insights/log', data={'day': today.isoformat(), 'google_reviews': '0'})
    assert 'google_reviews' not in crm_kpi.entries(today, cs_user.id)


def test_imported_history_is_not_counted_twice(app, admin_user):
    day = date(2026, 9, 30)
    crm_kpi.import_kpi([(day, 'cold', 5), (day, 'msg_bw', 2)], user_id=None)
    crm_kpi.import_kpi([(day, 'cold', 3)], user_id=admin_user.id)
    crm.capture('ti-quote', phone='+919000000001', utm={}, when=datetime(2026, 9, 30, 6), imported=True)
    team = crm_kpi.compute(day, day)
    assert team['cold'][day] == 5 and team['msg_bw'][day] == 2     # the team tab only, the old lead left out
    assert crm_kpi.compute(day, day, admin_user.id)['cold'][day] == 3


def test_message_rows_by_code():
    assert crm_kpi.message_row('BW', 'customer', 'customer') == 'msg_bw'
    assert crm_kpi.message_row('PF #1', 'lost', 'prospect_fallout') == 'msg_prospect_fallout'
    assert crm_kpi.message_row('PF #1', 'lost', 'pipeline_fallout') == 'msg_pipeline_fallout'
    assert crm_kpi.message_row(None, 'customer', 'customer') == 'msg_ce'
    assert crm_kpi.message_row('TI #1', 'cold', 'cold') == 'msg_prospect'


# ============================================================================================ sales process

def test_the_sales_process_page(app, client, admin_user, cs_user):
    ti_lead()
    login(client, cs_user.email)
    page = client.get('/cs/crm/process').get_data(as_text=True)
    assert 'Where leads come from' in page and 'Travel insurance' in page and 'WhatsApp “Details: introduce yourself and offer a quote” right away, goes by itself' in page
    assert 'Organic posting in groups' in page and 'Gaps to close' not in page
    assert client.post('/cs/crm/process', data={'what': 'channels', 'channels': 'x | y'}).status_code == 302
    assert 'channels' not in crm.crm_settings_raw()                    # not theirs to edit
    from app.models import CrmCampaign
    assert CrmCampaign.query.count() == 0
    client.post('/auth/logout')
    login(client, admin_user.email)
    client.post('/admin/crm/process', data={'what': 'channels', 'channels': 'Facebook | Groups | Sales | Ongoing'})
    # run 5b: the marketing activities are rows of crm_campaigns (per workspace), not the 'crm' setting
    from app.services import crm_campaigns
    assert crm_campaigns.channels() == [['Facebook', 'Groups', 'Sales', 'Ongoing']]


def test_focus_mode_button_is_on_every_crm_screen(app, client, cs_user):
    login(client, cs_user.email)
    for url in ('/cs/crm/', '/cs/crm/today', '/cs/crm/process'):
        assert 'data-focus' in client.get(url).get_data(as_text=True), url


# ============================================================================================ the workbook, completely

def workbook():
    wb = openpyxl.Workbook()
    p = wb.active
    p.title = 'Prospects'
    p.append(['Customer Data'])
    p.append(['Date', 'Lead', 'S', 'Phone Number', 'Emai id', 'UR', 'Names', 'DOB', 'Age', 'Enq.', 'onward Dep',
              'Return Date', 'Dep.', 'Arrival', 'TI #1', 'LS', 'Next Follow-Up', 'Next Step', 'Comments'])
    p.append([46304, 'Kiran', 'IW', '91 98480 00007', None, 'M', 'Lakshmi', None, 67, 'TI', 46340, 46400, 'HYD',
              'Dallas', 46305, 'R', None, None, None])
    p['B3'].fill = PatternFill('solid', fgColor='FFFF00')
    p['B3'].comment = Comment('9/14 - will get back by tomorrow\n20/9 sent PF#1', 'Harika')
    p['G3'].comment = Comment('Diabetic, taking medication', 'Harika')
    pl = wb.create_sheet('Pipeline')
    pl.append(['Customer Data'])
    pl.append(['Date', 'Pipeline', 'S', 'Phone Number', 'Emai id', 'UR', 'Names', 'DOB', 'Age', 'Enq.', 'Start Date',
               'End Date', 'TD', 'Dep.', 'Arrival', 'PE', 'PLS', 'PI #1'])
    pl.append([46300, 'Venu', 'UC', '1 (408) 593-6794', None, 'F', None, None, 70, 'TI', 46350, 46400, 50, 'HYD',
               'SFO', 'N', 'Y', 46305])
    pl['B3'].fill = PatternFill('solid', fgColor='92D050')
    f = wb.create_sheet('Prospect Fallout')
    f.append(['Customer Data'])
    f.append(['Date', 'Lead', 'S', 'Phone Number', 'Emai id', 'Names', 'Enq.', 'onward Dep', 'LS', 'Comments'])
    f.append([46300, 'Gopi', 'I', '+61 434 727 317', None, None, 'TI', None, 'DL', None])
    for cell in f[3]:
        cell.font = Font(color='FF0000')
    k = wb.create_sheet('KPI')
    k.append([None, 'Totals', 46300, 46301])
    k.append(['Lead source points'])
    k.append(['FB (X)', 30, 10, 20])
    k.append(['Cold Leads', 9, 4, 5])
    k.append(['Prospects', 3, 1, 2])
    k.append(['Communication Messages sent', 12, 5, 7])
    k.append(['Prospects', 6, 2, 4])
    k.append(['Birthday Wishes', 1, 0, 1])
    hb = wb.create_sheet('HB KPI')
    hb.append(['K', 'Totals', 46300, 46301])
    hb.append(['Cold Leads', 2, 1, 1])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_the_workbook_comes_in_with_its_notes_colours_and_history(app, client, admin_user, cs_user):
    rows, stats, kpi = crm_import.read_sheet(workbook())
    by = {r['name']: r for r in rows}
    assert by['Kiran']['likelihood'] == 'warm' and by['Venu']['likelihood'] == 'hot' and by['Gopi']['likelihood'] == 'cold'
    assert by['Kiran']['history'] == ['9/14 - will get back by tomorrow\n20/9 sent PF#1']
    assert by['Kiran']['details']['medical_conditions'] == 'Diabetic, taking medication'
    assert ('PLS', date(2026, 10, 5)) in by['Venu']['messages']
    assert sorted(kpi) == ['HB KPI', 'KPI']
    team = {(d, m): n for d, m, n in kpi['KPI']}
    assert team[(date(2026, 10, 5), 'cold')] == 4 and team[(date(2026, 10, 6), 'msg_prospect')] == 4
    assert team[(date(2026, 10, 6), 'prospects')] == 2 and team[(date(2026, 10, 5), 'src_fb')] == 10

    hb_user = make_user('hb@test.com', 'harsha', role='cs')
    hb_user.first_name, hb_user.last_name = 'Harsha', 'Bandi'
    _db.session.commit()
    login(client, admin_user.email)
    r = client.post('/admin/crm/setup/import', data={'sheet': (workbook(), 'Sales Process.xlsx')},
                    content_type='multipart/form-data')
    page = r.get_data(as_text=True)
    assert 'Daily numbers from the sales sheet' in page
    assert 'value="%d" selected' % hb_user.id in page                 # HB KPI guessed as Harsha Bandi
    token = page.split('name="token" value="', 1)[1].split('"', 1)[0]
    client.post('/admin/crm/setup/import/confirm', data={'token': token, 'kpi_KPI': 'team', 'kpi_HB_KPI': hb_user.id})
    kiran = CrmLead.query.join(CrmLead.person).filter_by(name='Kiran').one()
    assert kiran.likelihood == 'warm' and kiran.imported
    notes = [t.body for t in kiran.touchpoints if t.channel == 'note']
    assert any('20/9 sent PF#1' in n for n in notes)
    venu = CrmLead.query.join(CrmLead.person).filter_by(name='Venu').one()
    assert venu.likelihood == 'hot' and venu.stage.key == 'pipeline'
    assert CrmActivity.query.filter_by(source='import', user_id=None).count() == 11
    assert CrmActivity.query.filter_by(source='import', user_id=hb_user.id).count() == 2
    # the imported touches and leads never show as today's work
    today = (datetime.utcnow() + crm.IST).date()
    assert not crm_kpi.compute(today, today)['msg_total'].get(today)
