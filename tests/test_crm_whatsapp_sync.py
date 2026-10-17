"""The Sales CRM and the WhatsApp CRM as one process, without doing anything twice.

    the conversation    the WhatsApp CRM's (its inbox; the lead page and the inbox panel show it)
    the lead            the Sales CRM's (stage, owner, follow-ups, numbers), shown beside the chat
    follow-up messages  WhatsApp templates made from the steps' own words; one click or automatic
    ready answers       WhatsApp quick replies
    in step             stage -> contact tag, owner <-> conversation assignee, agent replies -> numbers
"""
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmAnswer, CrmLead, CrmPipeline, CrmStage, CrmTouchpoint, User
from app.services import access, crm, wa_templates, wacrm, wacrm_team


def stage(pipe_key, stage_key):
    return (CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == pipe_key, CrmStage.key == stage_key)
            .one())


def ti_lead(phone='+919876543210', **kw):
    return crm.capture('ti-quote', name=kw.pop('name', 'Ramesh Kumar'), phone=phone, utm={}, **kw)


@pytest.fixture
def sending(app, monkeypatch):
    """The WhatsApp CRM connected and sending; every call recorded, nothing leaves."""
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'wacrm_live_test')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    wa_templates.forget()
    calls = []

    def fake_call(method, path, payload=None, params=None):
        calls.append((method, path, payload))
        if method == 'POST' and path == '/api/v1/contacts':
            return {'id': 'c-1', 'tags': [{'name': 'vip'}, {'name': 'TI: Cold lead'}]}
        if path == '/api/v1/messages':
            return {'whatsapp_message_id': 'wamid.%d' % len(calls)}
        return {}

    portal = []

    def fake_api(method, path, payload=None, params=None):
        portal.append((method, path, payload))
        if path == 'templates':
            return [{'name': 'nri_ti_2', 'status': 'APPROVED', 'language': 'en'},
                    {'name': 'nri_ti_1', 'status': 'PENDING', 'language': 'en'}]
        if path == 'templates/drafts':
            return {'created': len(payload['items']), 'skipped': []}
        if path == 'quick-replies':
            return {'created': len(payload['items']), 'updated': 0}
        return {}
    monkeypatch.setattr(wacrm, '_call', fake_call)
    monkeypatch.setattr(wacrm_team, '_api', fake_api)
    crm.save_settings(whatsapp_mode='send')
    return calls, portal


def webhook(client, monkeypatch, event, data):
    monkeypatch.setenv('WACRM_WEBHOOK_SECRET', 'whsec_test')
    raw = json.dumps({'event': event, 'data': data}).encode()
    t = int(time.time())
    sig = hmac.new(b'whsec_test', str(t).encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return client.post('/api/crm/wacrm-webhook', data=raw,
                       headers={'X-Wacrm-Signature': 't=%d,v1=%s' % (t, sig), 'Content-Type': 'application/json'})


# ============================================================================== templates from the steps

def test_a_step_becomes_a_template_with_blanks_only_for_the_person(app):
    body, tokens = wa_templates.parts('Hi {name}, {agent} here. Cover for {product}: {insurance_link} -- {name}',
                                      static={'insurance_link': 'https://nri.example/travel-insurance'})
    assert body == 'Hi {{1}}, {{2}} here. Cover for {{3}}: https://nri.example/travel-insurance -- {{1}}'
    assert tokens == ['name', 'agent', 'product']
    assert wa_templates.params('Hi {name}, {agent} here', {'name': 'Asha', 'agent': 'Harsha'}) == ['Asha', 'Harsha']
    assert wa_templates.slug_name('TI #2') == 'nri_ti_2'
    assert 'cannot start or end with a blank' in wa_templates.problems('nri_x', '{{1}} hello', ['name'])[0]
    assert wa_templates.problems('Bad Name', 'Hello', [])


def test_every_whatsapp_step_and_ready_message_has_a_template(app):
    crm.ensure_defaults()
    rows = wa_templates.candidates()
    names = [r['name'] for r in rows]
    assert 'nri_ti_1' in names and 'nri_bw' in names
    assert len(names) == len(set(names))                         # one name per distinct text
    ti1 = next(r for r in rows if r['name'] == 'nri_ti_1')
    assert ti1['body'].startswith('Hi {{1}}, {{2}} here') and ti1['samples'][:2] == ['Priya', 'Harsha']
    assert ti1['category'] == 'MARKETING' and not ti1['problems']
    assert all(r['step'] is None or r['step'].channel == 'whatsapp' for r in rows)   # calls need no template
    csv_text = wa_templates.csv_text(rows)
    assert csv_text.splitlines()[0].startswith('Template name,Category,Language,Body')


# ============================================================================== one way to send a step

def test_the_send_button_picks_template_text_or_link(app, sending):
    calls, _ = sending
    lead = ti_lead()
    task = lead.open_task                                         # TI #1, template pending
    task.step.wa_template = 'nri_ti_1'
    _db.session.commit()
    plan = crm.send_plan(lead, task.step)
    assert plan['mode'] == 'link' and 'pending' in plan['reason']
    # they write on WhatsApp: inside 24 hours free text goes
    crm.record_reply(lead, 'Yes please', channel='whatsapp', external_id='wamid.r1')
    _db.session.commit()
    assert crm.send_plan(lead, task.step)['mode'] == 'text'
    # an approved template goes whenever they last wrote
    step2 = next(s for s in stage('ti-standard', 'prospect').steps if s.code == 'TI #2')
    step2.wa_template = 'nri_ti_2'
    _db.session.commit()
    tp = CrmTouchpoint.query.filter_by(direction='in').first()
    tp.created_at = datetime.utcnow() - timedelta(days=3)
    _db.session.commit()
    plan = crm.send_plan(lead, step2)
    assert plan == {'mode': 'template', 'template': 'nri_ti_2', 'reason': ''}


def test_sending_a_step_through_its_template(app, client, sending, cs_user):
    calls, _ = sending
    lead = ti_lead()
    crm.move_stage(lead, stage('ti-standard', 'prospect'))
    task = lead.open_task
    task.step.wa_template = 'nri_ti_2'
    _db.session.commit()
    login(client, cs_user.email)
    d = client.post('/cs/crm/lead/%d/send' % lead.id, json={'task_id': task.id}).get_json()
    assert d['mode'] == 'sent' and d['via'] == 'template'
    sent = [c for c in calls if c[1] == '/api/v1/messages'][-1][2]
    assert sent['type'] == 'template' and sent['template']['name'] == 'nri_ti_2'
    assert sent['template']['params'][0] == 'Ramesh'
    tp = CrmTouchpoint.query.filter_by(lead_id=lead.id, direction='out').one()
    assert tp.code == 'TI #2' and 'Ramesh' in tp.body           # the history reads like the message


# ============================================================================== in step with the WhatsApp CRM

def test_the_stage_follows_onto_their_contact(app, sending):
    calls, _ = sending
    lead = ti_lead()
    crm.move_stage(lead, stage('ti-standard', 'prospect'))
    _db.session.commit()                                          # told to the WhatsApp CRM after the save
    patches = [c for c in calls if c[0] == 'PATCH']
    assert patches[-1][2] == {'tags': sorted(['vip', 'ti', 'TI: Prospect'])}   # the old stage tag replaced


def test_the_owner_gets_the_conversation(app, client, sending, cs_user, admin_user, monkeypatch):
    _, portal = sending
    answer = {'assignment': 'assigned', 'assignee_email': None}
    team_api = wacrm_team._api

    def fake_api(method, path, payload=None, params=None):
        if path == 'conversation/ensure':
            portal.append((method, path, payload))
            return {'contact_id': 'c-1', 'conversation_id': 'conv-1', 'contact_phone': '919876543210',
                    'assignee_email': answer['assignee_email'] or payload['assign_email'],
                    'assignment': answer['assignment']}
        return team_api(method, path, payload, params)
    monkeypatch.setattr(wacrm_team, '_api', fake_api)
    other = make_user('o@test.com', 'other', role='cs')
    lead = ti_lead()
    first, second = (other, cs_user) if lead.owner_id == cs_user.id else (cs_user, other)
    del portal[:]
    login(client, admin_user.email)
    # the chat was free: WhatsApp gives it to the new owner itself, nothing more to do
    client.post('/admin/crm/lead/%d/update' % lead.id, json={'owner_id': first.id})
    assert ('POST', 'conversation/ensure', {'phone': '919876543210', 'name': 'Ramesh Kumar', 'email': None,
                                            'create': True, 'assign_email': first.email}) in portal
    assert not [p for p in portal if p[1] == 'conversation/assign']
    _db.session.expire_all()
    person = _db.session.get(CrmLead, lead.id).person
    assert person.wacrm_conversation_id == 'conv-1' and not person.wacrm_assign_due
    # somebody else had the chat: it is moved to the new owner
    answer.update(assignment='kept', assignee_email='x@else.com')
    client.post('/admin/crm/lead/%d/update' % lead.id, json={'owner_id': second.id})
    assert ('POST', 'conversation/assign', {'conversation_id': 'conv-1', 'email': second.email}) in portal
    _db.session.expire_all()
    assert not _db.session.get(CrmLead, lead.id).person.wacrm_assign_due


def test_reassigning_in_the_inbox_changes_the_owner(app, client, sending, cs_user, monkeypatch):
    lead = ti_lead()
    other = make_user('o@test.com', 'other', role='cs')
    r = webhook(client, monkeypatch, 'conversation.assigned',
                {'contact_phone': '919876543210', 'assignee_email': 'o@test.com', 'origin': 'crm'})
    assert r.get_json().get('owner') == 'o@test.com'
    _db.session.expire_all()
    lead = _db.session.get(CrmLead, lead.id)
    assert lead.owner_id == other.id and lead.open_task.owner_id == other.id
    # our own change coming back is ignored
    r = webhook(client, monkeypatch, 'conversation.assigned',
                {'contact_phone': '919876543210', 'assignee_email': 'cs@test.com', 'origin': 'portal'})
    assert r.get_json().get('echo') and _db.session.get(CrmLead, lead.id).owner_id == other.id


def test_a_reply_from_the_inbox_counts_and_ticks_the_step(app, client, sending, cs_user, monkeypatch):
    lead = ti_lead()
    task = lead.open_task
    r = webhook(client, monkeypatch, 'message.sent',
                {'contact_phone': '919876543210', 'whatsapp_message_id': 'wamid.in1', 'content_type': 'text',
                 'text': 'Hi Ramesh, sending you two options now', 'sent_by_email': cs_user.email, 'source': 'inbox'})
    assert r.status_code == 200
    tp = CrmTouchpoint.query.filter_by(external_id='wamid.in1').one()
    assert tp.direction == 'out' and tp.agent_id == cs_user.id and tp.code == task.code
    _db.session.expire_all()
    assert _db.session.get(type(task), task.id).status == 'done'
    # the same message again (deliveries repeat) is not counted twice
    webhook(client, monkeypatch, 'message.sent', {'contact_phone': '919876543210', 'whatsapp_message_id': 'wamid.in1',
                                                  'text': 'x', 'source': 'inbox'})
    assert CrmTouchpoint.query.filter_by(external_id='wamid.in1').count() == 1
    # an automation's message is history, not somebody's work
    webhook(client, monkeypatch, 'message.sent', {'contact_phone': '919876543210', 'whatsapp_message_id': 'wamid.a1',
                                                  'text': 'Welcome!', 'source': 'automation'})
    tp = CrmTouchpoint.query.filter_by(external_id='wamid.a1').one()
    assert tp.agent_id is None and '(automation)' in tp.body


# ============================================================================== the lead beside the inbox

def test_the_inbox_panel_shows_the_conversations_lead(app, client, sending, cs_user):
    access.ensure_defaults()
    lead = ti_lead()
    login(client, cs_user.email)
    html = client.get('/admin/messaging/lead-panel?conversation=conv-7&phone=919876543210').get_data(as_text=True)
    assert 'data-lead-panel' not in html and 'data-lead-page' in html and 'Next follow-up' in html and 'Ramesh' in html
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).person.wacrm_conversation_id == 'conv-7'
    # the inbox page carries the panel for somebody who works leads
    page = client.get('/admin/messaging/inbox').get_data(as_text=True)
    assert 'data-lead-panel' in page and 'wacrm:conversation' in page


def test_a_page_opened_on_a_conversation_asks_the_crm_whose_it_is(app, client, sending, cs_user, monkeypatch):
    """A reload on ?p=/inbox?c=<id> only knows the conversation id: the phone comes from the CRM."""
    access.ensure_defaults()
    lead = ti_lead()
    asked = []

    def fake_api(method, path, payload=None, params=None):
        asked.append(path)
        return {'conversation_id': 'conv-3', 'contact': {'name': 'Ramesh Kumar', 'phone': '919876543210'}}
    monkeypatch.setattr(wacrm_team, '_api', fake_api)
    login(client, cs_user.email)
    html = client.get('/admin/messaging/lead-panel?conversation=conv-3').get_data(as_text=True)
    assert asked == ['conversation/conv-3'] and 'data-lead-page' in html and 'Ramesh' in html
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).person.wacrm_conversation_id == 'conv-3'
    # known now: no second question
    client.get('/admin/messaging/lead-panel?conversation=conv-3')
    assert asked == ['conversation/conv-3']


def test_somebody_new_on_whatsapp_becomes_a_lead_from_the_inbox(app, client, sending, cs_user):
    access.ensure_defaults()
    login(client, cs_user.email)
    html = client.get('/admin/messaging/lead-panel?conversation=conv-9&phone=919000000077&name=Asha').get_data(as_text=True)
    assert 'Not a sales lead yet' in html and 'Make Asha a lead' in html
    r = client.post('/admin/messaging/lead-panel/make',
                    data={'wa_phone': '919000000077', 'name': 'Asha', 'conversation': 'conv-9'}, follow_redirects=True)
    assert 'Next follow-up' in r.get_data(as_text=True) or 'Nothing planned' in r.get_data(as_text=True)
    lead = CrmLead.query.join(CrmLead.person).filter_by(phone='+919000000077').one()
    assert lead.person.wacrm_conversation_id == 'conv-9' and lead.created_by_id == cs_user.id


def test_a_role_without_the_sales_crm_sees_no_lead_there(app, client, sending, cs_user):
    ws = access.ensure_defaults()
    from app.models import WorkspaceMember, WorkspaceRole
    r = WorkspaceRole(workspace_id=ws.id, name='Chat only', pages=['wa_inbox'])
    _db.session.add(r)
    _db.session.commit()
    WorkspaceMember.query.filter_by(user_id=cs_user.id).one().role_id = r.id
    _db.session.commit()
    login(client, cs_user.email)
    assert 'does not include the Sales CRM' in client.get('/admin/messaging/lead-panel?conversation=c').get_data(as_text=True)
    assert 'data-lead-panel' not in client.get('/admin/messaging/inbox').get_data(as_text=True)


# ============================================================================== set-up

def test_templates_and_quick_replies_go_to_whatsapp_from_set_up(app, client, sending, admin_user):
    _, portal = sending
    crm.ensure_defaults()
    login(client, admin_user.email)
    page = client.get('/admin/crm/pipelines?show=templates').get_data(as_text=True)   # U2: its own page now
    assert 'nri_ti_1' in page and 'Waiting for WhatsApp' in page and 'Approved' in page
    r = client.get('/admin/crm/setup/templates/csv')
    assert r.headers['Content-Type'].startswith('text/csv') and b'nri_ti_1' in r.data
    client.post('/admin/crm/setup/templates/drafts')
    sent = [p for p in portal if p[1] == 'templates/drafts'][0][2]['items']
    assert all({'name', 'category', 'language', 'body', 'sample_values'} <= set(i) for i in sent)
    ti1 = next(s for s in stage('ti-standard', 'cold').steps if s.code == 'TI #1')
    assert ti1.wa_template == 'nri_ti_1'                          # the step now uses its template
    client.post('/admin/crm/quick-replies/push')          # U8: the copy card became Push all to WhatsApp
    pushes = [p for p in portal if p[1] == 'quick-replies']
    assert any(' · ' in i['title'] for i in pushes[0][2]['items'])   # first the old coded rows are adopted ...
    assert any(t.startswith('BW · ') for t in pushes[-1][2].get('remove_titles') or [])   # ... then removed
    items = pushes[-1][2]['items']
    assert not [i['title'] for i in items if ' · ' in i['title']]    # U8: titles go without the code
    assert any('{{contact.first_name}}' in i['text'] for i in items)
    assert all('{name}' not in i['text'] and '{agent}' not in i['text'] for i in items)


def test_links_in_messages_carry_the_prefix_once(app, monkeypatch):
    """SITE_URL ends in /travel-companions and so does the path: the link had it twice, and the
    insurance page (served beside the prefix) got it once too many."""
    # (the test app's server name is localhost, so the site is too)
    monkeypatch.setitem(app.config, 'SITE_URL', 'https://localhost/travel-companions')
    monkeypatch.setitem(app.config, 'APP_URL_PREFIX', '/travel-companions')
    lead = ti_lead()
    with app.test_request_context('/', base_url='https://localhost/travel-companions'):
        text = crm.fill('{companion_link} {insurance_link} {sahayak_link}', lead)
        assert text == ('https://localhost/travel-companions/trips https://localhost/travel-insurance '
                        'https://localhost/sahayak')
        body, _ = wa_templates.parts('See {insurance_link}')
        assert body == 'See https://localhost/travel-insurance'
