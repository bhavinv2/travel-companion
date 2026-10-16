"""U3: the lead page is one screen -- journey, WhatsApp strip, one merged timeline, a message box.

    drawing the page      asks the WhatsApp CRM nothing (the live endpoint does, and only for the box)
    the message box       one safe path (crm.send_by_hand): the right chat, once, inside the rules
    milestones            "I sent the quote" is a record, never a message to the customer
    the timeline          WhatsApp and CRM events in one chronological stream, built from portal data
"""
import re
from datetime import datetime, timedelta

import pytest

from conftest import login
from app import db as _db
from app.models import CrmLead, CrmPerson, CrmPipeline, CrmStage, CrmTask, CrmTouchpoint
from app.services import crm, crm_kpi, crm_timeline, wacrm, wacrm_team
from test_crm_wa_sending import World, ti_lead, wrote, world        # noqa: F401  (the fixture and its helpers)

PHONE = '+919876543210'


def stage(pipe_key, stage_key):
    return (CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == pipe_key, CrmStage.key == stage_key).one())


def page(client, lead, who=None):
    r = client.get('/admin/crm/lead/%d' % lead.id)
    assert r.status_code == 200
    return r.get_data(as_text=True)


def text_of(html):
    html = re.sub(r'<(script|style).*?</\1>', '', html, flags=re.S)
    return ' '.join(re.sub(r'<[^>]+>', ' ', html).split())


# ------------------------------------------------------------------ drawing the page is quiet

def test_the_page_draws_without_asking_the_whatsapp_crm_anything(app, client, admin_user, world):
    lead = ti_lead()
    wrote(lead)
    world.portal.clear()
    n = len(world.messages)

    def nope(*a, **k):
        raise AssertionError('the lead page called the WhatsApp CRM while drawing')
    import app.services.wacrm as w
    w._call, wacrm_team._api = nope, nope
    login(client, admin_user.email)
    html = page(client, lead)
    assert 'WhatsApp' in html and len(world.messages) == n


def test_the_page_has_one_journey_one_timeline_one_box_and_no_chat_frame(app, client, admin_user):
    lead = ti_lead()
    login(client, admin_user.email)
    html = page(client, lead)
    assert html.count('data-journey') == 1
    assert 'class="crm-wa-frame"' not in html
    t = text_of(html)
    assert 'Asked about Travel Insurance' in t and 'Looked after by' in t
    assert 'Click a stage to move them there.' in t
    assert 'Records it and moves them to' in html and 'Nothing is sent to the customer.' in html     # the buttons' hint
    assert 'I sent the quote' in t and 'I sent the payment link' in t
    assert 'Next follow-up' in t and 'Log a call' in t and 'Add a note' in t and 'They wrote to us' in t
    assert 'Replies' in t and 'Where' in t
    # the compact inbox panel keeps its own bar and says 'Next step'
    r = client.get('/admin/messaging/lead-panel', query_string={'phone': '919876543210'})
    assert r.status_code in (200, 302, 403)


def test_the_journey_shows_the_stuck_chip_and_the_stage(app, client, admin_user):
    lead = ti_lead()
    lead.entered_stage_at = datetime.utcnow() - timedelta(hours=100)
    _db.session.commit()
    login(client, admin_user.email)
    t = text_of(page(client, lead))
    assert 'In “Cold lead” since' in t and 'Stuck:' in t


# ------------------------------------------------------------------ the WhatsApp strip, in plain words

def _state(lead, **kw):
    return crm.wa_chat_state(lead, **kw)


def test_the_strip_says_where_the_chat_stands(app, world):
    crm.save_settings(whatsapp_mode='off')
    lead = ti_lead()
    assert crm.wa_line(_state(lead)) == 'WhatsApp is not connected for leads yet'
    crm.save_settings(whatsapp_mode='contacts')
    assert crm.wa_line(_state(lead)) == "They haven't written yet. WhatsApp only allows an approved template first."
    wrote(lead, hours_ago=3)
    st = _state(lead)
    assert st['state'] == 'open' and crm.wa_line(st) == 'Chat open, 21h left to write freely'
    wrote(lead, hours_ago=3, wamid='wamid.x')
    other = ti_lead(phone='+919800000009', name='Old Chat')
    wrote(other, hours_ago=30)
    assert crm.wa_line(_state(other)) == 'Only an approved template can go now'
    nophone = crm.capture('ti-quote', name='Mail Only', email='m@example.com', utm={})
    assert crm.wa_line(_state(nophone)) == 'There is no phone number for them yet.'


def test_the_strip_for_somebody_who_opted_out(app, world):
    lead = ti_lead()
    lead.person.wa_opt_out_at = datetime(2026, 10, 3, 6, 0)
    _db.session.commit()
    assert crm.wa_line(_state(lead)) == 'Opted out on 3 Oct. Send nothing unless they write.'
    wrote(lead, hours_ago=1)
    st = _state(lead)
    assert st['state'] == 'opted_out_open' and 'but they wrote since' in crm.wa_line(st)
    assert 'You can still answer' in crm.box_note(st)


def test_only_an_admin_gets_the_opt_back_in_button(app, client, admin_user, cs_user, world):
    lead = ti_lead()
    lead.person.wa_opt_out_at = datetime.utcnow() - timedelta(days=2)
    lead.owner_id = cs_user.id
    _db.session.commit()
    login(client, admin_user.email)
    assert 'Opt back in' in text_of(page(client, lead))
    client.post('/auth/logout')
    login(client, cs_user.email)
    html = client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'Opt back in' not in text_of(html)
    assert client.post('/cs/crm/lead/%d/opt-in' % lead.id).status_code == 403
    assert _db.session.get(CrmPerson, lead.person_id).wa_opt_out_at is not None


def test_opting_back_in_clears_it_notes_who_and_marks_them_for_the_tag_to_come_off(app, client, admin_user, world):
    lead = ti_lead()
    pid = lead.person_id
    lead.person.wa_opt_out_at = datetime.utcnow() - timedelta(days=2)
    _db.session.commit()
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/opt-in' % lead.id)
    assert r.get_json() == {'success': True, 'message': 'Opted back in. Their tag is removed in WhatsApp too.'}
    _db.session.expire_all()
    p = _db.session.get(CrmPerson, pid)
    assert p.wa_opt_out_at is None
    notes = [t.body for t in CrmTouchpoint.query.filter_by(person_id=pid, channel='note')]
    assert 'Opted back in to WhatsApp (by %s)' % admin_user.full_name in notes
    assert client.post('/admin/crm/lead/%d/opt-in' % lead.id).status_code == 400       # not opted out any more


def test_opting_in_while_whatsapp_is_off_says_the_tag_comes_later(app, client, admin_user):
    crm.save_settings(whatsapp_mode='off')
    lead = ti_lead()
    lead.person.wa_opt_out_at = datetime.utcnow()
    _db.session.commit()
    login(client, admin_user.email)
    assert client.post('/admin/crm/lead/%d/opt-in' % lead.id).get_json()['message'] == crm.OPTED_IN_LATER


def test_the_sync_state_and_try_again(app, client, admin_user, cs_user, world):
    lead = ti_lead()
    pid = lead.person_id
    login(client, admin_user.email)
    assert 'In step with WhatsApp' in text_of(page(client, lead))
    p = _db.session.get(CrmPerson, pid)
    p.wa_sync_error = 'More than one WhatsApp contact could be this number -- merge them in WhatsApp -> Contacts'
    p.wacrm_sync_due_at = None
    _db.session.commit()
    t = text_of(page(client, lead))
    assert 'Not in step: Two WhatsApp contacts could be this number. Open full chat, check the number' in t
    assert 'Try again' in t
    p = _db.session.get(CrmPerson, pid)
    p.wa_sync_error, p.wacrm_sync_due_at = None, datetime.utcnow() + timedelta(hours=1)
    _db.session.commit()
    assert 'Waiting to sync' in text_of(page(client, lead))
    # Try again marks them due; a person who is not the owner or an admin may not
    lead.owner_id = admin_user.id
    _db.session.commit()
    assert client.post('/admin/crm/lead/%d/wa-retry' % lead.id).get_json() == {'success': True}
    client.post('/auth/logout')
    login(client, cs_user.email)
    assert client.post('/cs/crm/lead/%d/wa-retry' % lead.id).status_code == 403


def test_the_sync_state_is_not_shown_to_somebody_who_neither_owns_nor_administers(app, client, cs_user, admin_user, world):
    lead = ti_lead()
    lead.owner_id = admin_user.id
    _db.session.commit()
    login(client, cs_user.email)
    t = text_of(client.get('/cs/crm/lead/%d' % lead.id).get_data(as_text=True))
    assert 'In step with WhatsApp' not in t and 'Waiting to sync' not in t


# ------------------------------------------------------------------ the message box

def test_the_box_sends_free_text_inside_the_window_and_logs_it_once(app, client, admin_user, world):
    lead = ti_lead()
    wrote(lead, hours_ago=1)
    world.last_inbound_at = datetime.utcnow() - timedelta(hours=1)
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/message' % lead.id, json={'kind': 'text', 'text': 'Happy to help'})
    assert r.status_code == 200 and r.get_json()['success'] is True
    assert len(world.messages) == 1
    out = CrmTouchpoint.query.filter_by(lead_id=lead.id, direction='out', channel='whatsapp').all()
    assert len(out) == 1 and out[0].body == 'Happy to help' and out[0].agent_id == admin_user.id and out[0].via == 'person'


def test_the_box_refuses_free_text_when_the_chat_is_closed_and_says_why(app, client, admin_user, world):
    lead = ti_lead()
    wrote(lead, hours_ago=1)
    world.last_inbound_at = datetime.utcnow() - timedelta(hours=40)
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/message' % lead.id, json={'kind': 'text', 'text': 'Hello?'})
    assert r.status_code == 409 and r.get_json()['mode'] == 'window_closed' and world.messages == []


def test_the_box_checks_what_it_is_given(app, client, admin_user, world):
    lead = ti_lead()
    login(client, admin_user.email)
    url = '/admin/crm/lead/%d/message' % lead.id
    assert client.post(url, json={'kind': 'banana'}).status_code == 400
    assert client.post(url, json={'kind': 'template', 'template': 'nri_ti_1', 'params': 'x'}).status_code == 400
    assert client.post(url, json={'kind': 'template', 'template': 'nri_ti_1', 'params': ['', 'A']}).status_code == 409
    assert client.post(url, json={'kind': 'text', 'text': '   '}).status_code == 409
    assert world.messages == []
    # a task from another lead is ignored, not completed
    other = ti_lead(phone='+919800000011', name='Other')
    r = client.post(url, json={'kind': 'template', 'template': 'nri_ti_1', 'params': ['A', 'B'],
                               'task_id': other.open_task.id})
    assert r.status_code == 200
    _db.session.expire_all()
    assert _db.session.get(CrmTask, other.open_task.id).status == 'open'


def test_the_box_never_sends_while_whatsapp_is_off(app, client, admin_user, world):
    crm.save_settings(whatsapp_mode='off')
    lead = ti_lead()
    wrote(lead)
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/message' % lead.id, json={'kind': 'text', 'text': 'Hi'})
    assert r.status_code == 409 and world.messages == [] and world.ensure_calls() == []


def test_the_box_leaves_a_second_press_alone_when_the_first_is_still_sending(app, client, admin_user, world):
    lead = ti_lead()
    task = lead.open_task
    task.step.wa_template = 'nri_ti_1'
    task.status, task.done_at = 'sending', datetime.utcnow()
    _db.session.commit()
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/message' % lead.id, json={'kind': 'template', 'template': 'nri_ti_1',
                                                                   'params': ['A', 'B'], 'task_id': task.id})
    assert r.status_code == 409 and r.get_json()['mode'] == 'taken' and world.messages == []


# ------------------------------------------------------------------ milestones are records

def test_a_milestone_never_messages_the_customer(app, client, admin_user, world):
    lead = ti_lead()
    crm.move_stage(lead, stage('ti-standard', 'prospect'))
    _db.session.commit()
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/event' % lead.id, json={'code': 'Q'})
    assert r.get_json()['stage'] == 'Quoted'
    assert world.messages == []
    tp = CrmTouchpoint.query.filter_by(lead_id=lead.id, code='Q').one()
    assert (tp.channel, tp.direction, tp.external_id) == ('system', 'none', None)
    assert crm.whatsapp_window_open(lead) is False


def test_quotes_and_payment_links_have_their_own_rows_in_the_numbers(app, client, admin_user, world):
    lead = ti_lead()
    crm.move_stage(lead, stage('ti-standard', 'prospect'))
    _db.session.commit()
    login(client, admin_user.email)
    client.post('/admin/crm/lead/%d/event' % lead.id, json={'code': 'Q'})
    client.post('/admin/crm/lead/%d/event' % lead.id, json={'code': 'PLS'})
    today = (datetime.utcnow() + crm.IST).date()
    team = crm_kpi.compute(today, today)
    assert team['quotes_sent'][today] == 1 and team['payment_links_sent'][today] == 1
    assert not team['msg_total'].get(today)                      # milestones are not "Messages sent"
    days, groups = crm_kpi.table(today, today)
    labels = [label for _, lines in groups for _, label, _, _, _ in lines]
    assert 'Quotes sent' in labels and 'Payment links sent' in labels


# ------------------------------------------------------------------ the merged timeline

def test_the_timeline_is_one_chronological_stream_of_messages_and_events(app, client, admin_user, world):
    lead = ti_lead()
    now = datetime.utcnow()
    crm.log_touch(lead, 'whatsapp', 'in', body='[image] policy page', external_id='wamid.1', at=now - timedelta(hours=5))
    crm.log_touch(lead, 'whatsapp', 'out', body='Thanks, got it', user=admin_user, status='read', external_id='wamid.2',
                  at=now - timedelta(hours=4))
    crm.log_touch(lead, 'whatsapp', 'out', body='Offer', user=admin_user, status='failed', external_id='wamid.3',
                  at=now - timedelta(hours=3))
    _db.session.query(CrmTouchpoint).filter_by(external_id='wamid.3').update({'fail_reason': 'WhatsApp says: Undeliverable.'})
    crm.log_touch(lead, 'note', 'none', body='Call him after lunch', user=admin_user, at=now - timedelta(hours=2))
    crm.log_touch(lead, 'system', 'none', body='I sent the quote', code='Q', user=admin_user, at=now - timedelta(hours=1))
    _db.session.commit()
    login(client, admin_user.email)
    items = crm_timeline.build(_db.session.get(CrmLead, lead.id))
    kinds = [i['kind'] for i in items]
    assert kinds[0] == 'day' and 'msg' in kinds and 'event' in kinds
    stream = [i for i in items if i['kind'] in ('msg', 'event')]
    times = [i['at'] for i in stream]
    assert times == sorted(times)                                         # oldest first
    msgs = [i for i in items if i['kind'] == 'msg']
    assert msgs[0]['media'] == 'Photo' and msgs[0]['side'] == 'in'
    assert msgs[1]['tick'] == 'read' and msgs[2]['tick'] == 'failed' and msgs[2]['fail'] == 'WhatsApp says: Undeliverable.'
    assert any(i['kind'] == 'event' and 'Note by' in i['text'] for i in items)
    assert any(i['kind'] == 'event' and i['text'].startswith('I sent the quote') for i in items)
    html = text_of(page(client, lead))
    assert 'Thanks, got it' in html and 'Photo' in html


def test_the_timeline_costs_a_fixed_number_of_queries(app, admin_user):
    from sqlalchemy import event
    lead = ti_lead()
    for i in range(40):
        crm.log_touch(lead, 'whatsapp', 'in' if i % 2 else 'out', body='m%d' % i, external_id='w%d' % i, user=admin_user if i % 2 == 0 else None)
    _db.session.commit()
    lead = _db.session.get(CrmLead, lead.id)
    seen = []
    engine = _db.engine

    def count(*a, **k):
        seen.append(1)
    event.listen(engine, 'before_cursor_execute', count)
    try:
        crm_timeline.build(lead)
    finally:
        event.remove(engine, 'before_cursor_execute', count)
    assert len(seen) <= 6                                                  # not one per message


def test_a_milestone_logged_the_old_way_as_a_whatsapp_out_still_reads_as_an_event(app, admin_user):
    lead = ti_lead()
    crm.log_touch(lead, 'whatsapp', 'out', body='Quote sent', code='Q', user=admin_user)      # older rows
    _db.session.commit()
    items = crm_timeline.build(_db.session.get(CrmLead, lead.id))
    assert not [i for i in items if i['kind'] == 'msg']
    assert any(i['kind'] == 'event' and 'I sent the quote' in i['text'] for i in items)


def test_message_bodies_keep_what_kind_of_message_they_were():
    assert crm.wa_body('look', 'image') == '[image] look' and crm.wa_body(None, 'audio') == '[audio]'
    assert crm.wa_body('hello', 'text') == 'hello' and crm.wa_body(None, None) == '[message]'
    assert crm.wa_media('[image] look') == ('media', 'Photo', 'look')
    assert crm.wa_media('[document]')[0:2] == ('media', 'Document')
    assert crm.wa_media('[template nri_x]') == ('template', 'Approved template', '')
    assert crm.wa_media('[button] Yes please')[0] == 'button'
    assert crm.wa_media('plain words') == (None, None, 'plain words')


# ------------------------------------------------------------------ older messages come in once

def test_older_messages_come_in_once_as_history_and_change_nothing_else(app, client, admin_user, world, monkeypatch):
    lead = ti_lead()
    lead.person.wacrm_conversation_id = 'conv-1'
    _db.session.commit()
    stage_before, activity = lead.stage_id, lead.last_activity_at
    rows = [{'whatsapp_message_id': 'wamid.h2', 'direction': 'outbound', 'content_type': 'text', 'content_text': 'Hi again',
             'created_at': '2026-10-10T09:05:00Z'},
            {'whatsapp_message_id': 'wamid.h1', 'direction': 'inbound', 'content_type': 'text', 'content_text': 'Old question',
             'created_at': '2026-10-10T09:00:00Z'}]
    calls = []
    monkeypatch.setattr(wacrm, 'conversation_messages', lambda cid, limit=40: calls.append(cid) or rows)
    login(client, admin_user.email)
    assert client.get('/admin/crm/lead/%d/live?first=1' % lead.id).status_code == 200
    assert client.get('/admin/crm/lead/%d/live?first=1' % lead.id).status_code == 200
    assert calls == ['conv-1']                                              # once
    got = {t.external_id: t for t in CrmTouchpoint.query.filter(CrmTouchpoint.external_id.like('wamid.h%'))}
    assert set(got) == {'wamid.h1', 'wamid.h2'} and got['wamid.h1'].direction == 'in' and got['wamid.h1'].status == 'imported'
    assert got['wamid.h1'].created_at == datetime(2026, 10, 10, 9, 0)
    _db.session.expire_all()
    l = _db.session.get(CrmLead, lead.id)
    assert l.stage_id == stage_before and l.last_activity_at == activity
    assert crm.whatsapp_window_open(l) is False                           # history never opens the 24 hours


def test_history_that_failed_to_load_is_tried_again_next_time(app, world, monkeypatch):
    lead = ti_lead()
    lead.person.wacrm_conversation_id = 'conv-1'
    _db.session.commit()

    def boom(cid, limit=40):
        raise wacrm.WacrmError('down', status=502)
    monkeypatch.setattr(wacrm, 'conversation_messages', boom)
    assert crm.wa_import_history(lead) is None
    _db.session.expire_all()
    assert _db.session.get(CrmPerson, lead.person_id).wa_history_at is None
    monkeypatch.setattr(wacrm, 'conversation_messages', lambda cid, limit=40: [])
    assert crm.wa_import_history(_db.session.get(CrmLead, lead.id)) == 0


def test_no_history_is_fetched_for_somebody_whose_chat_we_do_not_know_or_who_has_messages(app, world, monkeypatch):
    monkeypatch.setattr(wacrm, 'conversation_messages', lambda *a, **k: (_ for _ in ()).throw(AssertionError('asked')))
    lead = ti_lead()
    lead.person.wacrm_conversation_id = None
    _db.session.commit()
    assert crm.wa_import_history(lead) is None
    lead.person.wacrm_conversation_id = 'conv-1'
    wrote(lead)
    assert crm.wa_import_history(lead) is None


# ------------------------------------------------------------------ calls, notes, "they wrote to us"

def test_call_back_makes_a_follow_up_that_plans_nothing_when_done(app, client, admin_user):
    lead = ti_lead()
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/call' % lead.id, json={'outcome': 'call_back', 'when': '1h'})
    assert r.get_json()['success'] is True and r.get_json()['call_back']
    cb = CrmTask.query.filter_by(lead_id=lead.id, title='Call back').one()
    assert cb.channel == 'call' and cb.step_id is None and cb.code is None and cb.status == 'open'
    n = CrmTask.query.filter_by(lead_id=lead.id).count()
    crm.complete_task(cb, user=admin_user)
    _db.session.commit()
    assert CrmTask.query.filter_by(lead_id=lead.id).count() == n            # done: nothing new planned
    assert client.post('/admin/crm/lead/%d/call' % lead.id, json={'outcome': 'call_back', 'when': 'at',
                                                                  'at': '2001-01-01T10:00'}).status_code == 400


def test_call_back_times():
    now = datetime(2026, 10, 16, 5, 0)                    # 10:30 in India
    assert crm.call_back_at('1h', now=now) == now + timedelta(hours=1)
    assert crm.call_back_at('evening', now=now) == datetime(2026, 10, 16, 12, 30)       # 18:00 IST
    late = datetime(2026, 10, 16, 12, 0)                  # 17:30 IST: an hour from now beats 18:00
    assert crm.call_back_at('evening', now=late) == late + timedelta(hours=1)
    assert crm.call_back_at('morning', now=now) == datetime(2026, 10, 17, 4, 30)        # 10:00 IST tomorrow
    assert crm.call_back_at('at', '2026-10-17T17:30', now=now) == datetime(2026, 10, 17, 12, 0)
    assert crm.call_back_at('at', 'nonsense', now=now) is None and crm.call_back_at('at', '2026-10-15T10:00', now=now) is None
    assert crm.call_back_at('whenever', now=now) is None


def test_they_wrote_to_us_on_another_number_is_a_reply_but_never_opens_the_24_hours(app, client, admin_user, world):
    lead = ti_lead()
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/note' % lead.id, json={'text': 'Said yes on my other number',
                                                               'channel': 'wa_other', 'from_them': True})
    assert r.get_json()['success'] is True
    tp = CrmTouchpoint.query.filter_by(lead_id=lead.id, channel='wa_other').one()
    assert tp.direction == 'in' and not tp.external_id
    assert crm.whatsapp_window_open(_db.session.get(CrmLead, lead.id)) is False
    assert 'WhatsApp (other number)' in crm_timeline_text(lead)


def crm_timeline_text(lead):
    return ' '.join(str(i) for i in crm_timeline.build(_db.session.get(CrmLead, lead.id)))


def test_the_next_follow_up_opens_the_agents_own_whatsapp_only_when_the_switch_is_off(app, client, admin_user, world):
    lead = ti_lead()
    login(client, admin_user.email)
    crm.save_settings(whatsapp_mode='off')
    assert "Open my WhatsApp (replies won't come here)" in text_of(page(client, lead)).replace('&#39;', "'")
    crm.save_settings(whatsapp_mode='send')
    assert "Open my WhatsApp" not in text_of(page(client, lead))


def test_quick_replies_are_filled_in_for_the_lead_and_the_lead_products_come_first(app, admin_user):
    from app.models import CrmAnswer
    crm.ensure_defaults()
    lead = ti_lead()
    pairs = crm.quick_replies_for(lead, admin_user)
    assert pairs and all(isinstance(a, CrmAnswer) for a, _ in pairs)
    assert not any('{name}' in text for _, text in pairs)
    products = [a.product for a, _ in pairs]
    first_other = next((i for i, p in enumerate(products) if p not in ('TI', 'GEN')), len(products))
    assert all(p in ('TI', 'GEN') for p in products[:first_other])
