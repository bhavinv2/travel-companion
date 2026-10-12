"""Sales CRM: leads from every form, the follow-ups they get, the screens staff work from, and the
two public doors (/api/leads and the WhatsApp CRM webhook).

What these hold in place:
  * no enquiry is ever lost to the CRM -- an unknown form is kept as "unrouted", and a CRM fault
    never fails the form the visitor sent;
  * one person + one product is one lead, however many times they ask;
  * the next step is always on somebody's list, due when the sales playbook says;
  * a reply moves a cold lead on by itself;
  * the suggested answers for a question are the ones a person would pick.
"""
import hashlib
import hmac
import json
import time
from datetime import date, datetime, timedelta

import pytest

from conftest import TRIP_JSON, login, make_user
from app import db as _db
from app.models import (CrmAnswer, CrmLead, CrmPerson, CrmPipeline, CrmSource, CrmStage, CrmTask,
                        CrmTouchpoint)
from app.services import crm, crm_answers, wacrm


def stage(pipe_key, stage_key):
    return (CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == pipe_key, CrmStage.key == stage_key)
            .one())


def ti_lead(phone='+919876543210', **kw):
    return crm.capture('ti-quote', name=kw.pop('name', 'Ramesh Kumar'), phone=phone, utm={}, **kw)


# ============================================================================================ capture

def test_capture_makes_a_lead_with_its_first_step_planned(app, cs_user):
    lead = ti_lead(email='ramesh@example.com', details={'travellers_ages': '65, 62'})
    assert lead.pipeline.key == 'ti-standard' and lead.stage.key == 'cold'
    assert lead.person.phone == '+919876543210' and lead.person.country == 'IN'
    assert lead.owner_id == cs_user.id
    task = lead.open_task
    assert task.code == 'TI #1' and task.owner_id == cs_user.id
    assert task.due_at <= datetime.utcnow() + timedelta(minutes=1)
    tp = lead.touchpoints[0]
    assert tp.direction == 'in' and 'Travellers ages: 65, 62' in tp.body
    assert CrmSource.query.filter_by(key='ti-quote').one().lead_count == 1


def test_same_person_same_product_is_one_lead(app):
    a = ti_lead(phone='+91 98765 43210')
    b = ti_lead(phone='+919876543210', message='Asking again')
    assert a.id == b.id
    assert len(a.touchpoints) == 2
    other = crm.capture('sh-booking', phone='+919876543210', product='SH', utm={})
    assert other.id != a.id and other.person_id == a.person_id
    assert CrmPerson.query.count() == 1


def test_lead_without_any_way_to_reach_them_is_not_kept(app):
    assert crm.capture('ti-quote', name='Nobody', utm={}) is None
    assert CrmLead.query.count() == 0


def test_unknown_source_is_kept_unrouted_until_an_admin_routes_it(app, client, admin_user, cs_user):
    lead = crm.capture('diwali-landing', name='Sita', phone='+14155550123', product='TI', utm={})
    src = CrmSource.query.filter_by(key='diwali-landing').one()
    assert src.status == 'unrouted' and lead.pipeline is None and not lead.tasks
    login(client, admin_user.email)
    r = client.post('/cs/crm/setup/source', data={'id': src.id, 'name': 'Diwali page', 'kind': 'form',
                                                   'product': 'TI', 'pipeline': 'ti-standard',
                                                   'status': 'live', 'dedupe_days': '30'})
    assert r.status_code == 302
    _db.session.expire_all()
    lead = _db.session.get(CrmLead, lead.id)
    assert src.status == 'live' and lead.stage.key == 'cold'
    assert lead.open_task.code == 'TI #1' and lead.owner_id == cs_user.id


def test_paused_source_keeps_leads_but_plans_nothing(app):
    lead = crm.capture('newsletter', email='reader@example.com', utm={})
    assert lead is not None and lead.open_task is None


def test_leads_are_shared_evenly_between_agents(app):
    a = make_user('a@test.com', 'agenta', role='cs')
    b = make_user('b@test.com', 'agentb', role='cs')
    owners = [ti_lead(phone='+9198765432%02d' % i).owner_id for i in range(4)]
    assert sorted(owners) == sorted([a.id, a.id, b.id, b.id])


def test_a_source_team_owns_its_leads(app):
    make_user('a@test.com', 'agenta', role='cs')
    b = make_user('b@test.com', 'agentb', role='cs')
    crm.ensure_defaults()
    CrmSource.query.filter_by(key='ti-quote').one().team = [b.id]
    _db.session.commit()
    assert {ti_lead(phone='+9198765432%02d' % i).owner_id for i in range(3)} == {b.id}


def test_capture_safely_never_raises(app, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('db on fire')
    monkeypatch.setattr(crm, 'capture', boom)
    assert crm.capture_safely('ti-quote', phone='+919876543210') is None


# ============================================================================================ steps

def test_before_departure_steps_are_due_at_nine_in_india(app):
    crm.ensure_defaults()
    lead = crm.capture('tc-trip-post', phone='+919876543210', product='TC', utm={},
                       departure_date=date.today() + timedelta(days=30))
    first = lead.open_task
    assert first.code == 'TC #1'
    crm.complete_task(first)
    nxt = lead.open_task
    assert nxt.code == 'TC #4'
    want = datetime.combine(date.today() + timedelta(days=15), datetime.min.time()) + timedelta(hours=9) - crm.IST
    assert nxt.due_at == want


def test_moving_a_lead_closes_its_step_and_plans_the_new_stages(app):
    lead = ti_lead()
    old = lead.open_task
    crm.move_stage(lead, stage('ti-standard', 'quoted'))
    _db.session.commit()
    assert old.status == 'skipped'
    assert lead.open_task.code == 'TI #4'
    assert lead.stage_changes[0].to_stage.key == 'quoted'


def test_won_and_lost_close_the_lead(app):
    lead = ti_lead()
    crm.move_stage(lead, stage('ti-standard', 'prospect_fallout'), fallout_reason='Bought elsewhere')
    assert lead.status == 'lost' and lead.fallout_reason == 'Bought elsewhere' and lead.closed_at
    crm.move_stage(lead, stage('ti-standard', 'customer'))
    assert lead.status == 'won' and lead.fallout_reason is None
    assert lead.open_task.code == 'CE #1'


def test_a_reply_moves_a_cold_lead_to_prospect(app):
    lead = ti_lead()
    crm.record_reply(lead, 'Yes please, they are 65 and 62')
    _db.session.commit()
    assert lead.stage.key == 'prospect' and lead.temperature == 'R'
    assert lead.open_task.code == 'TI #2'
    # a later reply does not move it again
    crm.move_stage(lead, stage('ti-standard', 'quoted'))
    crm.record_reply(lead, 'Thanks')
    assert lead.stage.key == 'quoted'


def test_three_unanswered_calls_suggest_a_fallout(app):
    lead = ti_lead()
    for _ in range(2):
        assert crm.log_call(lead, 'no_answer') < crm.NO_ANSWER_LIMIT
    assert crm.log_call(lead, 'busy') == 3
    crm.log_call(lead, 'connected')
    assert crm.no_answer_streak(lead) == 0 and lead.stage.key == 'prospect'


def test_messages_are_filled_in_for_the_lead(app, cs_user):
    lead = ti_lead(name='Ramesh Kumar', departure_date=date.today() + timedelta(days=12))
    text = crm.fill('Hi {name}, this is {agent}. {days} days to go. {unknown}', lead)
    assert text == 'Hi Ramesh, this is Csagent. 12 days to go. {unknown}'
    assert crm.whatsapp_link(lead, 'Hi there').startswith('https://wa.me/919876543210?text=Hi%20there')


# ============================================================================================ answers

@pytest.mark.parametrize('question, expected', [
    ('my mother has diabetes and BP will it be covered', 'Are pre-existing conditions covered?'),
    ('why is your price higher than the other website', 'Why is your price different from another site?'),
    ('what is deductible', 'What is a deductible?'),
    ('can we buy the policy after they land in the US', 'Can I buy after my parents have arrived?'),
])
def test_suggested_answers_for_insurance_questions(app, question, expected):
    crm.ensure_defaults()
    top = crm_answers.suggest(question, 'TI')
    assert top and top[0]['title'] == expected


def test_suggestions_prefer_the_leads_product(app):
    crm.ensure_defaults()
    top = crm_answers.suggest('how does it work', 'TC')
    assert top[0]['product'] == 'TC'


def test_nothing_to_suggest_for_small_talk(app):
    crm.ensure_defaults()
    assert crm_answers.suggest('hi thanks ok', 'TI') == []


# ============================================================================================ screens

def test_cs_agent_works_the_crm_screens(app, client, cs_user):
    lead = ti_lead()
    crm.record_reply(lead, 'Is diabetes covered for my father?')
    _db.session.commit()
    login(client, cs_user.email)
    for url in ('/cs/crm/', '/cs/crm/today', '/cs/crm/add', '/cs/crm/insights',
                '/cs/crm/lead/%d' % lead.id, '/cs/crm/?p=tc-companion&owner=all&q=ramesh'):
        r = client.get(url)
        assert r.status_code == 200, url
    page = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'Are pre-existing conditions covered?' in page          # the suggestion for their question
    assert 'TI #2' in page                                           # their next step
    today = client.get('/cs/crm/today').get_data(as_text=True)
    assert 'Ramesh Kumar' in today


def test_send_logs_the_message_and_ticks_the_step(app, client, cs_user):
    lead = ti_lead()
    task = lead.open_task
    login(client, cs_user.email)
    r = client.post('/cs/crm/lead/%d/send' % lead.id, json={'text': 'Hello Ramesh', 'task_id': task.id})
    d = r.get_json()
    assert d['mode'] == 'link' and d['url'].startswith('https://wa.me/919876543210')
    _db.session.expire_all()
    assert _db.session.get(CrmTask, task.id).status == 'done'
    out = CrmTouchpoint.query.filter_by(direction='out').one()
    assert out.body == 'Hello Ramesh' and out.code == 'TI #1' and out.agent_id == cs_user.id
    assert _db.session.get(CrmLead, lead.id).open_task.code == 'CL #2'


def test_lost_needs_a_reason(app, client, cs_user):
    lead = ti_lead()
    login(client, cs_user.email)
    lost = stage('ti-standard', 'prospect_fallout')
    r = client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': lost.id})
    assert r.status_code == 400 and r.get_json()['need_reason']
    r = client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': lost.id, 'reason': 'No response'})
    assert r.get_json()['status'] == 'lost'


def test_call_task_and_note_endpoints(app, client, cs_user):
    lead = ti_lead()
    login(client, cs_user.email)
    for _ in range(3):
        d = client.post('/cs/crm/lead/%d/call' % lead.id, json={'outcome': 'no_answer'}).get_json()
    assert d['suggest_fallout'] is True
    assert client.post('/cs/crm/lead/%d/call' % lead.id, json={'outcome': 'shouting'}).status_code == 400
    r = client.post('/cs/crm/lead/%d/note' % lead.id,
                    json={'text': 'Is my dad covered for BP?', 'channel': 'instagram', 'from_them': True})
    assert r.get_json()['success']
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).stage.key == 'prospect'
    task = _db.session.get(CrmLead, lead.id).open_task
    assert client.post('/cs/crm/task/%d/snooze' % task.id, json={}).get_json()['success']
    assert client.post('/cs/crm/lead/%d/update' % lead.id, json={'temperature': 'U'}).get_json()['success']
    assert client.post('/cs/crm/lead/%d/update' % lead.id, json={'temperature': 'HOT'}).status_code == 400
    s = client.get('/cs/crm/suggest?q=deductible&lead=%d' % lead.id).get_json()['suggestions']
    assert s[0]['title'] == 'What is a deductible?'


def test_quick_add(app, client, cs_user):
    login(client, cs_user.email)
    crm.ensure_defaults()
    r = client.post('/cs/crm/add', data={'product': 'TI', 'name': 'Meena', 'phone': '98480 00001',
                                         'phone_cc': 'IN', 'source': 'instagram', 'owner': 'me',
                                         'note': 'Parents flying to Dallas'})
    assert r.status_code == 302
    lead = CrmLead.query.one()
    assert lead.person.phone == '+919848000001' and lead.pipeline.key == 'ti-standard'
    assert lead.owner_id == cs_user.id and lead.open_task.owner_id == cs_user.id
    r = client.post('/cs/crm/add', data={'product': 'TI', 'name': 'X', 'source': 'instagram'})
    assert b'A phone number, an e-mail or an Instagram' in r.data


def test_setup_is_for_admins(app, client, cs_user, admin_user):
    login(client, cs_user.email)
    assert client.get('/cs/crm/setup').status_code == 302
    client.post('/auth/logout')
    login(client, admin_user.email)
    for tab in ('sources', 'pipelines', 'messages', 'answers', 'connect'):
        assert client.get('/cs/crm/setup?tab=%s' % tab).status_code == 200, tab
    assert client.get('/cs/crm/setup?tab=sources&edit=new').status_code == 200
    assert client.get('/cs/crm/setup?tab=answers&edit=new').status_code == 200


def test_admin_edits_pipelines_steps_and_answers(app, client, admin_user):
    login(client, admin_user.email)
    crm.ensure_defaults()
    r = client.post('/cs/crm/setup/pipeline', data={'action': 'new', 'name': 'Gift Health', 'product': 'GH'})
    assert r.status_code == 302
    pipe = CrmPipeline.query.filter_by(key='gift-health').one()
    assert [s.kind for s in pipe.stages] == ['open', 'open', 'won', 'lost']
    st = pipe.stages[0]
    client.post('/cs/crm/setup/step', data={'stage_id': st.id, 'code': 'GH #1', 'title': 'Say hello',
                                            'channel': 'whatsapp', 'value': '2', 'unit': 'days',
                                            'trigger': 'after_hours', 'body': 'Hi {name}'})
    step = st.steps[0]
    assert step.trigger_value == 48 and step.body == 'Hi {name}'
    client.post('/cs/crm/setup/answer', data={'title': 'Do you ship gifts abroad?', 'body': 'Yes, we do.',
                                              'keywords': 'gift ship courier', 'product': 'GH'})
    assert crm_answers.suggest('can you courier a gift', 'GH')[0]['title'] == 'Do you ship gifts abroad?'


def test_restricted_agent_without_the_crm_cannot_open_it(app, client):
    agent = make_user('r@test.com', 'restricted', role='cs')
    agent.cs_access = ['home']
    _db.session.commit()
    login(client, agent.email)
    r = client.get('/cs/crm/')
    assert r.status_code == 302 and '/cs/crm' not in r.headers['Location']


def test_signed_out_and_regular_users_are_kept_out(app, client, user):
    assert client.get('/cs/crm/').status_code == 302
    login(client, user.email)
    assert client.get('/cs/crm/today').status_code == 302


def test_due_follow_ups_show_on_the_menu_badge(app, cs_user):
    from app.services import nav_badges
    ti_lead()
    nav_badges.forget()
    assert nav_badges.unread(cs_user)['crm_board'] == 1


# ============================================================================================ intake

def test_any_landing_page_can_send_leads(app, client):
    r = client.post('/api/leads', json={'source': 'diwali-insurance', 'name': 'Anita', 'phone': '+1 415 555 0123',
                                        'product': 'TI', 'fields': {'ages': '70, 68'},
                                        'utm_campaign': 'diwali'})
    assert r.status_code == 201
    lead = CrmLead.query.one()
    assert lead.source.status == 'unrouted' and lead.details == {'ages': '70, 68'}
    assert lead.utm['utm_campaign'] == 'diwali'


@pytest.mark.parametrize('body, status', [
    ({'source': 'x y', 'phone': '+14155550123'}, 400),
    ({'source': 'page', 'name': 'No contact'}, 400),
    ({'source': 'page', 'phone': '12'}, 400),
    ({'source': 'page', 'email': 'not-an-email'}, 400),
])
def test_intake_refuses_what_cannot_be_followed_up(app, client, body, status):
    assert client.post('/api/leads', json=body).status_code == status
    assert CrmLead.query.count() == 0


def test_intake_quietly_drops_bots(app, client):
    r = client.post('/api/leads', json={'source': 'page', 'phone': '+14155550123', 'website': 'spam.biz'})
    assert r.status_code == 201 and CrmLead.query.count() == 0


def test_intake_allows_only_listed_other_sites(app, client):
    app.config['CRM_INTAKE_ORIGINS'] = 'https://partner.example'
    r = client.post('/api/leads', json={'source': 'page', 'phone': '+14155550123'},
                    headers={'Origin': 'https://partner.example'})
    assert r.headers.get('Access-Control-Allow-Origin') == 'https://partner.example'
    r = client.post('/api/leads', json={'source': 'page', 'phone': '+14155550124'},
                    headers={'Origin': 'https://evil.example'})
    assert 'Access-Control-Allow-Origin' not in r.headers


# ============================================================================================ webhook

SECRET = 'whsec_test'


def signed(body, secret=SECRET, t=None):
    raw = json.dumps(body).encode()
    t = int(t or time.time())
    sig = hmac.new(secret.encode(), str(t).encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return raw, {'X-Wacrm-Signature': 't=%d,v1=%s' % (t, sig), 'Content-Type': 'application/json'}


def test_signature_check():
    raw, h = signed({'a': 1})
    assert wacrm.verify_signature(h['X-Wacrm-Signature'], raw, SECRET)
    assert not wacrm.verify_signature(h['X-Wacrm-Signature'], raw + b' ', SECRET)
    assert not wacrm.verify_signature(h['X-Wacrm-Signature'], raw, 'other')
    old_raw, old = signed({'a': 1}, t=time.time() - 3600)
    assert not wacrm.verify_signature(old['X-Wacrm-Signature'], old_raw, SECRET)
    assert not wacrm.verify_signature('', raw, SECRET)


def test_webhook_reply_moves_the_lead(app, client, monkeypatch):
    monkeypatch.setenv('WACRM_WEBHOOK_SECRET', SECRET)
    lead = ti_lead()
    lead.person.wacrm_contact_id = 'c-1'
    _db.session.commit()
    body = {'id': 'e1', 'event': 'message.received', 'data': {
        'contact_id': 'c-1', 'whatsapp_message_id': 'wamid.1', 'content_type': 'text', 'text': 'Ages 65 and 62'}}
    raw, h = signed(body)
    assert client.post('/api/crm/wacrm-webhook', data=raw, headers=h).status_code == 200
    _db.session.expire_all()
    lead = _db.session.get(CrmLead, lead.id)
    assert lead.stage.key == 'prospect' and lead.touchpoints[0].body == 'Ages 65 and 62'
    # the same delivery again is not a second reply
    raw, h = signed(body)
    assert client.post('/api/crm/wacrm-webhook', data=raw, headers=h).get_json()['duplicate']


def test_webhook_from_a_new_number_creates_a_lead(app, client, monkeypatch):
    monkeypatch.setenv('WACRM_WEBHOOK_SECRET', SECRET)
    monkeypatch.setattr(wacrm, 'get_contact', lambda cid: {'phone': '919000000009', 'name': 'Gopal'})
    body = {'event': 'message.received', 'data': {'contact_id': 'c-9', 'whatsapp_message_id': 'wamid.9',
                                                  'text': 'Do you have insurance for my parents?'}}
    raw, h = signed(body)
    assert client.post('/api/crm/wacrm-webhook', data=raw, headers=h).get_json()['created']
    lead = CrmLead.query.one()
    assert lead.source.key == 'wa-india' and lead.person.phone == '+919000000009'
    assert lead.person.wacrm_contact_id == 'c-9'


def test_webhook_refuses_unsigned_calls(app, client, monkeypatch):
    monkeypatch.setenv('WACRM_WEBHOOK_SECRET', SECRET)
    r = client.post('/api/crm/wacrm-webhook', json={'event': 'message.received', 'data': {}})
    assert r.status_code == 401


def test_automatic_steps_go_out_once_connected(app, monkeypatch):
    lead = ti_lead()
    assert crm.run_auto_steps() == {'crm_auto_sent': 0}          # not connected: nothing sent
    monkeypatch.setenv('WACRM_URL', 'https://crm.example')
    monkeypatch.setenv('WACRM_API_KEY', 'wacrm_live_test')
    sent = []
    monkeypatch.setattr(wacrm, 'send_text', lambda phone, text: sent.append((phone, text)) or 'wamid.x')
    monkeypatch.setattr(wacrm, 'upsert_contact', lambda *a, **k: 'c-1')
    assert crm.run_auto_steps()['crm_auto_sent'] == 0           # keys alone are not enough...
    crm.save_settings(whatsapp_mode='send')                      # ...an admin has to switch it on
    assert crm.run_auto_steps()['crm_auto_sent'] == 1
    assert sent[0][0] == '+919876543210' and 'Ramesh' in sent[0][1]
    assert lead.open_task.code == 'CL #2'


# ============================================================================================ hooks

def test_site_forms_become_leads(app, client, user, monkeypatch):
    # Sahayak booking
    r = client.post('/api/sahayak-booking', json={
        'service': 'phlebotomy', 'patient_name': 'Lakshmi Rao', 'patient_age': '68',
        'phone': '+91 90000 00000', 'address': '12 Green Park, New Delhi', 'pincode': '110016'})
    assert r.status_code == 201
    booking = CrmLead.query.filter_by(product='SH').one()
    assert booking.pipeline.key == 'sahayak-visit' and booking.ref_type == 'sahayak_bookings'
    # Contact us, insurance topic
    r = client.post('/api/contact', json={'name': 'Kiran', 'email': 'kiran@example.com',
                                          'phone': '+91 98480 00002', 'message': 'Need cover for my parents',
                                          'topic': 'Travel insurance'})
    assert r.status_code == 200
    assert CrmLead.query.filter(CrmLead.ref_type == 'contact_messages').count() == 1
    # Trip posted on the site
    login(client, user.email)
    r = client.post('/api/post-trip', json=TRIP_JSON)
    assert r.status_code == 201
    trip_lead = CrmLead.query.filter_by(product='TC').one()
    assert trip_lead.person.phone == '+12145550100' and trip_lead.departure_date == date(2099, 12, 1)
    assert 'Hyderabad' in trip_lead.details['route']


def test_insurance_quote_becomes_a_lead(app, client, monkeypatch):
    import urllib.request

    class Resp:
        def read(self):
            return json.dumps({'status': 'success', 'data': {'redirectToBN': '/q?id=1'}}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(urllib.request, 'urlopen', lambda req, timeout=None: Resp())
    start = date.today() + timedelta(days=10)
    r = client.post('/api/insurance-quote', json={
        'start_date': start.isoformat(), 'end_date': (start + timedelta(days=30)).isoformat(),
        'citizenship': 'IND', 'travellers': [{'age': '65'}], 'insurance_type': 'visitors',
        'email': 'ramesh@example.com', 'phone': '+91 98765 43210'})
    assert r.status_code == 200
    lead = CrmLead.query.one()
    assert lead.source.key == 'ti-quote' and lead.departure_date == start
    assert lead.details['travellers_ages'] == '65' and lead.ref_type == 'insurance_quotes'


def test_a_crm_fault_never_fails_the_form(app, client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('crm down')
    monkeypatch.setattr(crm, 'capture', boom)
    r = client.post('/api/contact', json={'name': 'Kiran', 'email': 'kiran@example.com',
                                          'phone': '+91 98480 00002', 'message': 'Need cover for my parents'})
    assert r.status_code == 200 and r.get_json()['success']


def test_question_box_holds_what_they_wrote_not_the_form_fields(app, client, cs_user):
    lead = crm.capture('tc-trip-post', phone='+919848000001', product='TC', utm={},
                       details={'route': 'Hyderabad (HYD) → Dallas (DFW)'})
    login(client, cs_user.email)
    page = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    box = page.split('id="crm-q"', 1)[1].split('</textarea>', 1)[0]
    assert 'Route:' not in box
    lead2 = crm.capture('contact-insurance', phone='+919848000002', utm={},
                        message='Is diabetes covered?', details={'preferred_contact': 'WhatsApp'})
    page = client.get('/cs/crm/lead/%d' % lead2.id).get_data(as_text=True)
    box = page.split('id="crm-q"', 1)[1].split('</textarea>', 1)[0]
    assert 'Is diabetes covered?' in box and 'Preferred' not in box
