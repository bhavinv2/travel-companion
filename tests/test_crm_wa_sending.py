"""P2b: sending is safe -- the right customer, once, only when allowed.

    claim, then send    a step is taken before WhatsApp is called; a second click or run finds it taken
    switched off        nothing is ever written to WhatsApp
    opted out           nothing by template or by itself; a reply is still fine once they write
    US numbers          no marketing templates; utility templates and free text inside 24 h are fine
    the 24 hours        only their real WhatsApp messages count, and the WhatsApp CRM keeps the clock
"""
from datetime import datetime, timedelta

import pytest

from conftest import login
from app import db as _db
from app.models import CrmLead, CrmPerson, CrmPipeline, CrmStage, CrmTask, CrmTouchpoint
from app.services import crm, wa_templates, wacrm, wacrm_team

PHONE, DIGITS = '+919876543210', '919876543210'


def ti_lead(phone=PHONE, **kw):
    return crm.capture('ti-quote', name=kw.pop('name', 'Ramesh Kumar'), phone=phone, utm={}, **kw)


class World:
    """The WhatsApp CRM, in memory: what was sent, what it says about the chat, what it refuses."""

    def __init__(self):
        self.messages, self.portal = [], []
        self.templates = [{'name': 'nri_ti_1', 'status': 'APPROVED', 'language': 'en', 'category': 'MARKETING',
                           'variables': 2, 'body': 'Hi {{1}}, {{2}} here.'},
                          {'name': 'utility_one', 'status': 'APPROVED', 'language': 'en', 'category': 'UTILITY',
                           'variables': 1, 'body': 'Hello {{1}}'}]
        self.last_inbound_at = None       # what ensure says about the chat
        self.phone = None                 # the number ensure answers for (default: the one asked)
        self.send_error = None
        self.ensure_error = None

    def call(self, method, path, payload=None, params=None):
        if path == '/api/v1/messages':
            if self.send_error is not None:
                raise self.send_error
            self.messages.append(payload)
            return {'whatsapp_message_id': 'wamid.out%d' % len(self.messages)}
        if path == '/api/v1/contacts':
            return {'id': 'c-1', 'tags': []}
        return {}

    def api(self, method, path, payload=None, params=None):
        self.portal.append((method, path, payload))
        if path == 'templates':
            return self.templates
        if path == 'conversation/ensure':
            if self.ensure_error is not None:
                raise self.ensure_error
            cid = 'c-1' if payload['phone'] == DIGITS else 'c-' + payload['phone']       # one contact per number
            return {'contact_id': cid, 'conversation_id': 'conv-' + cid[2:], 'contact_phone': self.phone or payload['phone'],
                    'contact_name': 'Ramesh', 'created_contact': False, 'created_conversation': False,
                    'assignee_email': None, 'assignment': 'none',
                    'last_inbound_at': (self.last_inbound_at.replace(microsecond=0).isoformat() + 'Z')
                    if self.last_inbound_at else None, 'status': 'open'}
        return {}

    def ensure_calls(self):
        return [p for p in self.portal if p[1] == 'conversation/ensure']


@pytest.fixture
def world(app, monkeypatch):
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'wacrm_live_test')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    wa_templates.forget()
    crm._wa_inbound.clear()
    w = World()
    monkeypatch.setattr(wacrm, '_call', w.call)
    monkeypatch.setattr(wacrm_team, '_api', w.api)
    crm.save_settings(whatsapp_mode='send')
    return w


def wrote(lead, hours_ago=1, wamid=None):
    """They wrote to us on WhatsApp (a real message: it has WhatsApp's id)."""
    crm.log_touch(lead, 'whatsapp', 'in', body='Hello', external_id=wamid or 'wamid.in%d' % hours_ago,
                  at=datetime.utcnow() - timedelta(hours=hours_ago))
    _db.session.commit()


def tid(lead):
    return lead.open_task.id


def task_row(task_id):
    _db.session.expire_all()
    return _db.session.get(CrmTask, task_id)


# ------------------------------------------------------------------ switched off: nothing leaves

def test_while_off_nothing_is_ever_sent_or_asked(app, world):
    crm.save_settings(whatsapp_mode='off')
    lead = ti_lead(consent=True)
    wrote(lead)
    lead.open_task.auto = True
    lead.open_task.due_at = datetime.utcnow() - timedelta(minutes=5)
    _db.session.commit()
    assert crm.run_auto_steps() == {'crm_auto_sent': 0}
    assert crm.send_by_hand(lead, None, 'text', text='hello')['mode'] == 'off'
    assert crm.send_plan(lead, lead.open_task.step)['mode'] == 'link'
    assert world.messages == [] and world.ensure_calls() == []


def test_keep_leads_in_step_is_enough_for_the_box_but_not_for_automatic_sends(app, world):
    crm.save_settings(whatsapp_mode='contacts')
    lead = ti_lead(consent=True)
    wrote(lead)
    world.last_inbound_at = datetime.utcnow() - timedelta(hours=1)
    lead.open_task.auto = True
    lead.open_task.due_at = datetime.utcnow() - timedelta(minutes=5)
    _db.session.commit()
    assert crm.run_auto_steps() == {'crm_auto_sent': 0} and world.messages == []
    assert crm.send_by_hand(lead, None, 'text', text='hello')['mode'] == 'sent'
    assert [m.get('text') or m.get('body') for m in world.messages] == ['hello']


# ------------------------------------------------------------------ claim, then send

def test_a_step_that_is_being_sent_is_never_sent_again(app, world):
    lead = ti_lead()
    task = lead.open_task
    task.status = 'sending'
    task.done_at = datetime.utcnow()
    _db.session.commit()
    wrote(lead)
    r = crm.send_step(lead, task, plan={'mode': 'text', 'template': None, 'reason': ''}, text='Hi')
    assert r['mode'] == 'taken' and world.messages == []
    assert crm.send_by_hand(lead, None, 'text', text='Hi', task=task)['mode'] == 'taken'


def test_two_presses_on_one_step_send_one_message(app, world):
    lead = ti_lead()
    wrote(lead)
    world.last_inbound_at = datetime.utcnow() - timedelta(hours=1)
    task = lead.open_task
    first = crm.send_step(lead, task, text='Hi', plan={'mode': 'text', 'template': None, 'reason': ''})
    assert first['mode'] == 'sent'
    again = crm.send_step(lead, task, text='Hi', plan={'mode': 'text', 'template': None, 'reason': ''})
    assert again['mode'] == 'taken' and len(world.messages) == 1


def test_a_refusal_opens_the_step_again_with_why_and_logs_nothing(app, world):
    lead = ti_lead()
    wrote(lead)
    world.send_error = wacrm.WacrmError('Meta said no', status=422, code='meta_error')
    n = CrmTouchpoint.query.count()
    task, task_id = lead.open_task, lead.open_task.id
    r = crm.send_step(lead, task, text='Hi', plan={'mode': 'text', 'template': None, 'reason': ''})
    assert r['mode'] == 'failed'
    t = task_row(task_id)
    assert t.status == 'open' and 'did not send it' in (t.note or '')
    assert CrmTouchpoint.query.count() == n


def test_no_answer_after_the_call_leaves_the_step_sending_and_it_is_never_resent(app, world):
    lead = ti_lead(consent=True)
    wrote(lead)
    task = lead.open_task
    task.auto = True
    task.due_at = datetime.utcnow() - timedelta(minutes=1)
    _db.session.commit()
    task_id = task.id
    world.last_inbound_at = datetime.utcnow() - timedelta(hours=1)
    world.send_error = wacrm.WacrmError('timed out', status=504)
    assert crm.run_auto_steps()['crm_auto_sent'] == 0
    t = task_row(task_id)
    assert t.status == 'sending' and 'check' in (t.note or '').lower()
    world.send_error = None
    n = len(world.messages)
    assert crm.run_auto_steps()['crm_auto_sent'] == 0
    assert len(world.messages) == n == 0
    # only after 15 minutes is it listed for a person to check
    assert crm.stuck_sends(now=datetime.utcnow()) == []
    assert [x.id for x in crm.stuck_sends(now=datetime.utcnow() + timedelta(minutes=20))] == [task_id]


def test_a_person_settling_a_stuck_send(app, world):
    lead = ti_lead()
    task = lead.open_task
    task.status = 'sending'
    task.done_at = datetime.utcnow() - timedelta(minutes=30)
    _db.session.commit()
    assert crm.settle_send(task, went=False) is True
    t = task_row(task.id)
    assert t.status == 'open' and t.auto is False
    assert crm.settle_send(t, went=True) is False          # not stuck any more


def test_the_run_stops_taking_steps_when_its_time_is_up(app, world):
    for i in range(3):
        l = ti_lead(phone='+91987654320%d' % i, consent=True, name='P%d' % i)
        wrote(l)
        l.open_task.auto = True
        l.open_task.due_at = datetime.utcnow() - timedelta(minutes=1)
    _db.session.commit()
    assert crm.run_auto_steps(budget=-1)['crm_auto_sent'] == 0 and world.messages == []


# ------------------------------------------------------------------ old backlogs are not sent when sending is switched on

def test_an_automatic_step_overdue_by_more_than_a_day_waits_for_a_click(app, world):
    lead = ti_lead(consent=True)
    wrote(lead)
    task = lead.open_task
    task.auto = True
    task.due_at = datetime.utcnow() - timedelta(days=3)
    _db.session.commit()
    task_id = task.id
    assert crm.run_auto_steps()['crm_auto_sent'] == 0
    t = task_row(task_id)
    assert t.auto is False and t.status == 'open' and t.note.startswith('Was due') and t.note.endswith('check before sending')
    assert world.messages == []


# ------------------------------------------------------------------ consent for automatic first messages

def _template_step(lead):
    step = lead.open_task.step
    step.wa_template = 'nri_ti_1'
    lead.open_task.auto = True
    lead.open_task.due_at = datetime.utcnow() - timedelta(minutes=1)
    _db.session.commit()
    return step


def test_an_automatic_first_template_needs_their_ok(app, world):
    lead = ti_lead()                                # no consent, never wrote
    _template_step(lead)
    task_id = lead.open_task.id
    assert crm.run_auto_steps()['crm_auto_sent'] == 0
    t = task_row(task_id)
    assert t.auto is False and t.note == 'Needs a click: they have not agreed to WhatsApp messages yet'
    assert world.messages == []


def test_with_consent_or_after_they_wrote_the_template_goes_by_itself(app, world):
    ok = ti_lead(consent=True)
    _template_step(ok)
    other = ti_lead(phone='+919876500000', name='Asha')
    _template_step(other)
    wrote(other)
    assert crm.run_auto_steps()['crm_auto_sent'] == 2
    assert {m['to'] if 'to' in m else m.get('phone') for m in world.messages} >= {
        m.get('to') or m.get('phone') for m in world.messages}
    assert len(world.messages) == 2


def test_the_consent_rule_can_be_switched_off_in_set_up(app, world):
    crm.save_settings(wa_first_needs_ok=False)
    lead = ti_lead()
    _template_step(lead)
    assert crm.run_auto_steps()['crm_auto_sent'] == 1


def test_one_click_sends_are_allowed_without_consent(app, world, client, cs_user):
    lead = ti_lead()
    _template_step(lead)
    world.last_inbound_at = None
    lead.owner_id = cs_user.id
    _db.session.commit()
    plan = crm.send_plan(lead, lead.open_task.step)
    assert plan['mode'] == 'template'
    assert crm.send_step(lead, lead.open_task, user=cs_user, plan=plan)['mode'] == 'sent'


# ------------------------------------------------------------------ opt-out

def test_an_opted_out_person_gets_no_template_and_nothing_by_itself(app, world):
    lead = ti_lead(consent=True)
    _template_step(lead)
    lead.person.wa_opt_out_at = datetime.utcnow() - timedelta(days=2)
    _db.session.commit()
    plan = crm.send_plan(lead, lead.open_task.step)
    assert plan['mode'] == 'blocked' and plan['reason'] == crm.WA_OPTED_OUT
    task_id = lead.open_task.id
    assert crm.run_auto_steps()['crm_auto_sent'] == 0
    assert task_row(task_id).auto is False and world.messages == []
    r = crm.send_by_hand(lead, None, 'template', template='nri_ti_1', params=['A', 'B'])
    assert r['mode'] == 'blocked' and world.messages == []


def test_opting_out_makes_the_old_messages_not_count_for_the_window(app, world):
    lead = ti_lead()
    wrote(lead, hours_ago=3)
    assert crm.whatsapp_window_open(lead) is True
    lead.person.wa_opt_out_at = datetime.utcnow() - timedelta(hours=1)
    assert crm.whatsapp_window_open(lead) is False
    wrote(lead, hours_ago=0, wamid='wamid.after')
    assert crm.whatsapp_window_open(lead) is True


def test_an_opted_out_person_who_writes_can_be_answered_inside_24_hours(app, world):
    lead = ti_lead()
    lead.person.wa_opt_out_at = datetime.utcnow() - timedelta(days=1)
    _db.session.commit()
    wrote(lead, hours_ago=0, wamid='wamid.back')
    world.last_inbound_at = datetime.utcnow()
    r = crm.send_by_hand(lead, None, 'text', text='Of course, here you go')
    assert r['mode'] == 'sent'


def test_an_opted_out_person_who_has_not_written_since_is_blocked_for_text_too(app, world):
    lead = ti_lead()
    wrote(lead, hours_ago=5)
    lead.person.wa_opt_out_at = datetime.utcnow() - timedelta(hours=1)
    _db.session.commit()
    world.last_inbound_at = datetime.utcnow() - timedelta(hours=5)         # WhatsApp's clock is open, ours says stop
    r = crm.send_by_hand(lead, None, 'text', text='Hello again')
    assert r['mode'] == 'blocked' and world.messages == []


# ------------------------------------------------------------------ US numbers

@pytest.mark.parametrize('phone,us', [('+14155550123', True), ('+12125550123', True), ('+16135550123', False),
                                      ('+14165550123', False), ('+919876543210', False), ('+1415555012', False),
                                      ('', False), (None, False)])
def test_which_numbers_are_us(phone, us):
    assert crm.us_number(phone) is us


def test_a_marketing_template_to_a_us_number_is_blocked_but_utility_and_text_are_not(app, world):
    lead = ti_lead(phone='+14155550123')
    step = _template_step(lead)
    plan = crm.send_plan(lead, step)
    assert plan['mode'] == 'blocked' and 'US numbers' in plan['reason']
    assert crm.send_by_hand(lead, None, 'template', template='nri_ti_1', params=['A', 'B'])['mode'] == 'blocked'
    # a utility template is fine
    step.wa_template = 'utility_one'
    step.body = 'Hello {name}'
    _db.session.commit()
    assert crm.send_plan(lead, step)['mode'] == 'template'
    # free text inside the 24 hours is fine
    wrote(lead)
    step.wa_template = 'nri_ti_1'
    _db.session.commit()
    assert crm.send_plan(lead, step)['mode'] == 'text'
    assert world.messages == []


def test_a_canadian_number_is_not_treated_as_us(app, world):
    lead = ti_lead(phone='+14165550123')
    assert crm.send_plan(lead, _template_step(lead))['mode'] == 'template'


# ------------------------------------------------------------------ the 24-hour window

def test_a_typed_in_reply_or_a_form_does_not_open_the_window(app, world):
    lead = ti_lead()
    crm.record_reply(lead, 'They said yes on the phone')            # no WhatsApp id: not a WhatsApp message
    crm.log_touch(lead, 'whatsapp', 'in', body='typed by hand')
    _db.session.commit()
    assert crm.whatsapp_window_open(lead) is False
    assert crm.send_plan(lead, None)['mode'] == 'link'


def test_a_real_message_older_than_24_hours_does_not_count(app, world):
    lead = ti_lead()
    wrote(lead, hours_ago=25)
    assert crm.whatsapp_window_open(lead) is False
    wrote(lead, hours_ago=23, wamid='wamid.recent')
    assert crm.whatsapp_window_open(lead) is True


def test_before_free_text_goes_the_whatsapp_crm_is_asked_and_its_clock_wins(app, world):
    lead = ti_lead()
    wrote(lead, hours_ago=2)                                       # our record says open...
    world.last_inbound_at = datetime.utcnow() - timedelta(hours=30)   # ...Meta's clock says closed
    assert crm.whatsapp_window_open(lead, confirm=True) is False
    calls = world.ensure_calls()
    assert calls and calls[0][2]['create'] is False and not calls[0][2].get('assign_email')
    # asked once a minute, not on every press
    crm.whatsapp_window_open(lead, confirm=True)
    assert len(world.ensure_calls()) == 1


def test_when_the_whatsapp_crm_cannot_say_our_own_record_decides(app, world):
    lead = ti_lead()
    wrote(lead, hours_ago=2)
    world.ensure_error = wacrm_team.TeamError('down', status=502)
    assert crm.whatsapp_window_open(lead, confirm=True) is True
    other = ti_lead(phone='+919800000001', name='B')
    assert crm.whatsapp_window_open(other, confirm=True) is False


def test_a_closed_window_gives_the_link_plan_not_free_text(app, world):
    lead = ti_lead()
    wrote(lead, hours_ago=2)
    world.last_inbound_at = datetime.utcnow() - timedelta(hours=30)
    r = crm.send_whatsapp(lead, 'Hello', user=None)
    assert r['mode'] == 'link' and world.messages == []


# ------------------------------------------------------------------ template blanks

def test_a_template_whose_blanks_differ_from_the_step_uses_the_link_plan(app, world):
    lead = ti_lead()
    step = lead.open_task.step
    step.wa_template = 'nri_ti_1'
    step.body = 'Hi {name}, {agent} here, about {product}'         # 3 blanks, the template has 2
    _db.session.commit()
    plan = crm.send_plan(lead, step)
    assert plan['mode'] == 'link' and plan['reason'].startswith('The approved template has 2 fill-ins, the follow-up has 3')
    step.body = 'Hi {name}, {agent} here'
    _db.session.commit()
    assert crm.send_plan(lead, step)['mode'] == 'template'


# ------------------------------------------------------------------ the box: the right chat, the right number

def test_a_chat_for_another_number_is_refused_and_nothing_is_sent(app, world):
    lead = ti_lead()
    world.phone = '19998887777'
    r = crm.send_by_hand(lead, None, 'text', text='Hi')
    assert r['mode'] == 'wrong_number' and world.messages == []
    _db.session.rollback()
    assert fresh_person(lead.person_id).wacrm_conversation_id is None


def fresh_person(pid):
    _db.session.expire_all()
    return _db.session.get(CrmPerson, pid)


def test_a_chat_held_by_another_person_is_refused(app, world):
    lead = ti_lead()
    other = CrmPerson(phone='+15550001111', wacrm_contact_id='c-1')
    _db.session.add(other)
    _db.session.commit()
    r = crm.send_by_hand(lead, None, 'text', text='Hi')
    assert r['mode'] == 'wrong_number' and world.messages == []


def test_two_contacts_for_one_number_is_never_guessed(app, world):
    lead = ti_lead()
    world.ensure_error = wacrm_team.TeamError('Two', status=409, code='ambiguous_contact')
    r = crm.send_by_hand(lead, None, 'text', text='Hi')
    assert r['mode'] == 'ambiguous' and r['reason'] == crm.WA_ERRORS['ambiguous_contact'] and world.messages == []


def test_a_person_who_has_never_written_gets_only_a_template(app, world):
    lead = ti_lead()
    world.last_inbound_at = None
    r = crm.send_by_hand(lead, None, 'text', text='Hi')
    assert r['mode'] == 'window_closed' and r['reason'] == crm.WA_LINE_NEVER and world.messages == []
    assert crm.send_by_hand(lead, None, 'text', text='   ')['mode'] in ('blocked', 'window_closed')


def test_the_whatsapp_crm_refusing_the_24_hour_rule_is_told_plainly(app, world):
    lead = ti_lead()
    wrote(lead)
    world.last_inbound_at = datetime.utcnow() - timedelta(hours=1)
    world.send_error = wacrm.WacrmError('closed', status=422, code='window_closed')
    r = crm.send_by_hand(lead, None, 'text', text='Hi')
    assert r['mode'] == 'window_closed' and r['reason'] == crm.WA_CHAT_CLOSED


def test_a_template_that_is_not_approved_or_has_empty_fill_ins_does_not_go(app, world):
    lead = ti_lead()
    assert crm.send_by_hand(lead, None, 'template', template='made_up', params=['A'])['mode'] == 'blocked'
    r = crm.send_by_hand(lead, None, 'template', template='nri_ti_1', params=['A', ''])
    assert r['mode'] == 'blocked' and r['reason'] == crm.WA_FILL_INS
    assert world.messages == []


def test_sending_a_template_by_hand_logs_it_and_ticks_the_matching_step_once(app, world):
    lead = ti_lead()
    step = _template_step(lead)
    task_id = lead.open_task.id
    r = crm.send_by_hand(lead, None, 'template', template='nri_ti_1')
    assert r == {'mode': 'sent', 'via': 'template'} or r['mode'] == 'sent'
    assert task_row(task_id).status == 'done'
    assert crm.send_by_hand(lead, None, 'template', template='nri_ti_1', params=['A', 'B'])['mode'] == 'sent'
    assert len(world.messages) == 2                                  # the second is a new message, not the step again
    assert CrmTouchpoint.query.filter_by(lead_id=lead.id, direction='out', channel='whatsapp').count() == 2


# ------------------------------------------------------------------ making someone a lead is not them writing

def test_making_a_lead_from_the_chat_logs_a_note_not_an_inbound_message(app, world, client, admin_user):
    login(client, admin_user.email)
    r = client.post('/admin/messaging/lead-panel/make', data={'wa_phone': '919123456789', 'name': 'New Person',
                                                               'conversation': 'conv-9'})
    assert r.status_code in (302, 303)
    lead = CrmLead.query.one()
    kinds = {(t.channel, t.direction) for t in CrmTouchpoint.query.filter_by(lead_id=lead.id)}
    assert ('whatsapp', 'in') not in kinds
    assert crm.whatsapp_window_open(lead) is False
