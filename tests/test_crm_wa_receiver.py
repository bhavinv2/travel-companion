"""P2a: the WhatsApp webhook receiver and the catch-up / health jobs.

    one bad event       answered 200 {"ok": false}, never a 500; the catch-up job finds it later
    no call back        the handler never calls the WhatsApp CRM (it waits 5 s and switches us off)
    right lead          the one we last wrote to; a closed lead is never reopened
    opt-out             STOP and Meta's 131050 mean nothing is sent to them any more
"""
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta

import pytest

from conftest import make_user
from app import db as _db
from app.models import CrmLead, CrmPerson, CrmPipeline, CrmStage, CrmTask, CrmTouchpoint, Notification, User
from app.services import crm, settings, wacrm, wacrm_team

SECRET = 'whsec_receiver'
PHONE, DIGITS = '+919876543210', '919876543210'


def ti_lead(phone=PHONE, **kw):
    return crm.capture('ti-quote', name=kw.pop('name', 'Ramesh Kumar'), phone=phone, utm={}, **kw)


def sh_lead(phone=PHONE, **kw):
    return crm.capture('sh-booking', name=kw.pop('name', 'Ramesh Kumar'), phone=phone, product='SH', utm={}, **kw)


def stage(pipe_key, stage_key):
    return (CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == pipe_key, CrmStage.key == stage_key).one())


@pytest.fixture
def hook(app, client, monkeypatch):
    """Post a signed event; the WhatsApp CRM is never called back (a call would fail the test)."""
    monkeypatch.setenv('WACRM_WEBHOOK_SECRET', SECRET)

    def no_call(*a, **k):
        raise AssertionError('the webhook handler called the WhatsApp CRM: %r' % (a,))
    monkeypatch.setattr(wacrm, '_call', no_call)
    monkeypatch.setattr(wacrm_team, '_api', no_call)

    def post(event, data, secret=SECRET, raw=None):
        raw = raw or json.dumps({'event': event, 'data': data}).encode()
        t = int(time.time())
        sig = hmac.new(secret.encode(), str(t).encode() + b'.' + raw, hashlib.sha256).hexdigest()
        return client.post('/api/crm/wacrm-webhook', data=raw,
                           headers={'X-Wacrm-Signature': 't=%d,v1=%s' % (t, sig), 'Content-Type': 'application/json'})
    return post


def fresh(model, pk):
    _db.session.expire_all()
    return _db.session.get(model, pk)


def received(**kw):
    d = {'contact_id': 'c-1', 'conversation_id': 'conv-1', 'contact_phone': DIGITS, 'contact_name': 'Ramesh',
         'content_type': 'text', 'text': 'Hello', 'whatsapp_message_id': 'wamid.%d' % time.time_ns()}
    d.update(kw)
    return d


# ------------------------------------------------------------------ never a 500, never a call back

def test_a_broken_event_answers_200_not_a_500_and_leaves_no_half_save(app, hook, monkeypatch):
    lead = ti_lead()

    def boom(*a, **k):
        _db.session.add(CrmTouchpoint(lead_id=lead.id, person_id=lead.person_id, channel='whatsapp', direction='in',
                                      body='half saved'))
        raise RuntimeError('database exploded')
    monkeypatch.setattr(crm, 'record_whatsapp_in', boom)
    r = hook('message.received', received())
    assert r.status_code == 200 and r.get_json() == {'ok': False}
    assert CrmTouchpoint.query.filter_by(body='half saved').count() == 0
    # the next event is handled normally
    monkeypatch.undo()


def test_each_event_type_is_caught_the_same_way(app, hook, monkeypatch):
    ti_lead()
    for name, event in (('_wacrm_sent', 'message.sent'), ('_wacrm_assigned', 'conversation.assigned'),
                        ('_wacrm_status', 'message.status_updated')):
        from app.routes import crm as routes
        monkeypatch.setitem(routes.WACRM_EVENTS, event, lambda d: (_ for _ in ()).throw(ValueError('x')))
        r = hook(event, {'contact_id': 'c-1'})
        assert r.status_code == 200 and r.get_json() == {'ok': False}, event


def test_an_unknown_event_and_odd_bodies_are_answered_politely(app, hook):
    assert hook('contact.created', {}).get_json() == {'ok': True}
    assert hook('x', None, raw=b'[1, 2]').get_json() == {'ok': True}
    assert hook('x', None, raw=b'not json').status_code == 400
    assert hook('message.received', received(), secret='wrong').status_code == 401


def test_a_new_number_becomes_a_lead_without_asking_the_crm_anything(app, hook):
    r = hook('message.received', received(contact_id='c-9', contact_phone='919000000009', contact_name='Gopal',
                                          text='Do you have insurance for my parents?'))
    assert r.get_json()['created'] is True
    lead = CrmLead.query.one()
    assert lead.source.key == 'wa-india' and lead.person.phone == '+919000000009' and lead.person.name == 'Gopal'
    assert lead.person.wacrm_contact_id == 'c-9'


def test_the_same_message_twice_is_one_message(app, hook):
    ti_lead()
    d = received(whatsapp_message_id='wamid.same')
    assert hook('message.received', d).get_json().get('duplicate') is None
    assert hook('message.received', d).get_json()['duplicate'] is True
    assert CrmTouchpoint.query.filter_by(external_id='wamid.same').count() == 1


def test_a_picture_is_kept_as_a_picture(app, hook):
    lead = ti_lead()
    hook('message.received', received(content_type='image', text='the policy page', whatsapp_message_id='wamid.img'))
    tp = CrmTouchpoint.query.filter_by(external_id='wamid.img').one()
    assert tp.body == '[image] the policy page'
    assert crm.wa_media(tp.body) == ('media', 'Photo', 'the policy page')
    hook('message.received', received(content_type='audio', text=None, whatsapp_message_id='wamid.aud'))
    assert CrmTouchpoint.query.filter_by(external_id='wamid.aud').one().body == '[audio]'


# ------------------------------------------------------------------ which lead

def test_with_two_open_leads_the_one_we_last_wrote_to_gets_the_reply(app, hook):
    ti, sh = ti_lead(), sh_lead()
    assert ti.person_id == sh.person_id
    crm.log_touch(ti, 'whatsapp', 'out', body='Hi', status='sent', at=datetime.utcnow() - timedelta(hours=3))
    crm.log_touch(sh, 'whatsapp', 'out', body='Hi', status='sent', at=datetime.utcnow() - timedelta(hours=1))
    _db.session.commit()
    hook('message.received', received(text='Yes please', whatsapp_message_id='wamid.which'))
    tp = CrmTouchpoint.query.filter_by(external_id='wamid.which').one()
    assert tp.lead_id == sh.id
    ti_id, sh_id = ti.id, sh.id
    # now we write to the other one: the reply follows
    crm.log_touch(fresh(CrmLead, ti_id), 'whatsapp', 'out', body='Hi again', status='sent')
    _db.session.commit()
    hook('message.received', received(text='Ok', whatsapp_message_id='wamid.which2'))
    assert CrmTouchpoint.query.filter_by(external_id='wamid.which2').one().lead_id == ti_id


def test_without_any_outbound_the_newest_open_lead_gets_it(app, hook):
    ti = ti_lead()
    sh = sh_lead()
    hook('message.received', received(whatsapp_message_id='wamid.new'))
    assert CrmTouchpoint.query.filter_by(external_id='wamid.new').one().lead_id == sh.id


def test_a_template_sent_from_whatsapp_ticks_the_step_that_uses_it(app, hook):
    lead = ti_lead()
    task = lead.open_task
    task.step.wa_template = 'nri_ti_1'                              # TI #1's approved template
    _db.session.commit()
    tid, lid = task.id, lead.id
    r = hook('message.sent', {'contact_id': 'c-1', 'contact_phone': DIGITS, 'whatsapp_message_id': 'wamid.t1',
                              'template_name': task.step.wa_template, 'source': 'automation'})
    assert r.get_json()['ok'] is True
    assert fresh(CrmTask, tid).status == 'done'
    tp = CrmTouchpoint.query.filter_by(external_id='wamid.t1').one()
    assert tp.direction == 'out' and tp.via == 'automation' and tp.lead_id == lid


def test_a_template_for_the_other_lead_ticks_that_leads_step(app, hook):
    ti, sh = ti_lead(), sh_lead()
    name = 'nri_ti_1'
    ti.open_task.step.wa_template = name
    _db.session.commit()
    assert sh.open_task is None or sh.open_task.step is None or sh.open_task.step.wa_template != name
    hook('message.sent', {'contact_id': 'c-1', 'contact_phone': DIGITS, 'whatsapp_message_id': 'wamid.t2',
                          'template_name': name, 'source': 'broadcast'})
    assert CrmTouchpoint.query.filter_by(external_id='wamid.t2').one().lead_id == ti.id


def test_a_message_we_sent_is_not_counted_twice(app, hook):
    ti_lead()
    d = {'contact_id': 'c-1', 'contact_phone': DIGITS, 'whatsapp_message_id': 'wamid.o', 'text': 'Hi', 'source': 'inbox'}
    hook('message.sent', d)
    assert hook('message.sent', d).get_json()['duplicate'] is True
    assert CrmTouchpoint.query.filter_by(external_id='wamid.o').count() == 1


# ------------------------------------------------------------------ closed leads are never reopened

def test_a_message_on_a_recently_closed_lead_is_logged_and_its_owner_told(app, hook, cs_user):
    lead = ti_lead()
    lead.owner_id = cs_user.id
    crm.move_stage(lead, stage('ti-standard', 'customer'))
    lead.closed_at = datetime.utcnow() - timedelta(days=3)
    _db.session.commit()
    lid = lead.id
    r = hook('message.received', received(text='One more question', whatsapp_message_id='wamid.c1'))
    assert r.get_json().get('closed') is True
    lead = fresh(CrmLead, lid)
    assert lead.status == 'won' and CrmLead.query.count() == 1
    assert CrmTouchpoint.query.filter_by(external_id='wamid.c1').one().lead_id == lid
    told = [n.title for n in Notification.query.filter_by(user_id=cs_user.id, type='crm_lead')]
    assert [t for t in told if 'wrote on WhatsApp' in t] == ['Ramesh Kumar wrote on WhatsApp']


def test_a_message_long_after_the_lead_closed_starts_a_new_lead_from_whatsapp(app, hook, cs_user):
    lead = ti_lead()
    crm.move_stage(lead, stage('ti-standard', 'customer'))
    lead.closed_at = datetime.utcnow() - timedelta(days=45)
    lead.last_activity_at = lead.closed_at
    _db.session.commit()
    lid = lead.id
    r = hook('message.received', received(text='Need cover again', whatsapp_message_id='wamid.c2'))
    assert r.get_json().get('created') is True
    assert fresh(CrmLead, lid).status == 'won'
    new = CrmLead.query.filter(CrmLead.id != lid).one()
    assert new.status == 'open' and new.source.key == 'wa-india' and new.person_id == fresh(CrmLead, lid).person_id


# ------------------------------------------------------------------ opt-out

@pytest.mark.parametrize('text', ['STOP', ' stop ', 'Stop.', 'UNSUBSCRIBE', 'Stop promotions', 'stop all',
                                  "Don't message", 'dont message', 'stop messages'])
def test_stop_words_opt_them_out(app, hook, text):
    lead = ti_lead()
    pid = lead.person_id
    r = hook('message.received', received(text=text, whatsapp_message_id='wamid.s'))
    assert r.get_json().get('opted_out') is True
    p = fresh(CrmPerson, pid)
    assert p.wa_opt_out_at is not None
    notes = [t.body for t in CrmTouchpoint.query.filter_by(person_id=pid, channel='note')]
    assert any('no more WhatsApp messages' in (n or '') for n in notes)


@pytest.mark.parametrize('text', ['stop by tomorrow please', 'Please do not stop', 'stopping', 'I want to stop and think',
                                  'yes', ''])
def test_ordinary_words_that_contain_stop_do_not_opt_out(app, hook, text):
    lead = ti_lead()
    hook('message.received', received(text=text, whatsapp_message_id='wamid.n'))
    assert fresh(CrmPerson, lead.person_id).wa_opt_out_at is None


def test_stop_from_somebody_we_do_not_know_makes_no_lead_but_keeps_the_no(app, hook):
    r = hook('message.received', received(contact_id='c-5', contact_phone='919111111111', text='STOP'))
    assert r.get_json().get('opted_out') is True
    assert CrmLead.query.count() == 0
    assert CrmPerson.query.filter_by(phone='+919111111111').one().wa_opt_out_at is not None


def test_a_second_stop_changes_nothing_new(app, hook):
    lead = ti_lead()
    pid = lead.person_id
    hook('message.received', received(text='STOP', whatsapp_message_id='wamid.1'))
    first = fresh(CrmPerson, pid).wa_opt_out_at
    hook('message.received', received(text='STOP', whatsapp_message_id='wamid.2'))
    assert fresh(CrmPerson, pid).wa_opt_out_at == first


def test_meta_131050_opts_them_out_and_131049_is_explained(app, hook, cs_user):
    lead = ti_lead()
    lead.owner_id = cs_user.id
    crm.log_touch(lead, 'whatsapp', 'out', body='Offer', user=cs_user, status='sent', external_id='wamid.o1')
    crm.log_touch(lead, 'whatsapp', 'out', body='Offer 2', user=cs_user, status='sent', external_id='wamid.o2')
    _db.session.commit()
    pid = lead.person_id
    hook('message.status_updated', {'whatsapp_message_id': 'wamid.o1', 'status': 'failed', 'error_code': 131050,
                                    'error_title': 'User stopped marketing messages'})
    assert fresh(CrmPerson, pid).wa_opt_out_at is not None
    tp = CrmTouchpoint.query.filter_by(external_id='wamid.o1').one()
    assert tp.status == 'failed' and 'stopped marketing' in tp.fail_reason
    hook('message.status_updated', {'whatsapp_message_id': 'wamid.o2', 'status': 'failed', 'error_code': 131049,
                                    'error_title': 'Healthy ecosystem engagement'})
    assert 'marketing' in CrmTouchpoint.query.filter_by(external_id='wamid.o2').one().fail_reason
    bells = [n.body for n in Notification.query.filter_by(user_id=cs_user.id, type='crm_failed')]
    assert len(bells) == 2


def test_a_failed_delivery_shows_metas_own_reason_not_the_24_hour_guess(app, hook, cs_user):
    lead = ti_lead()
    crm.log_touch(lead, 'whatsapp', 'out', body='Hi', user=cs_user, status='sent', external_id='wamid.f')
    _db.session.commit()
    hook('message.status_updated', {'whatsapp_message_id': 'wamid.f', 'status': 'failed', 'error_code': 131026,
                                    'error_title': 'Message undeliverable'})
    why = CrmTouchpoint.query.filter_by(external_id='wamid.f').one().fail_reason
    assert 'Message undeliverable' in why and 'over 24 hours' not in why
    assert 'Message undeliverable' in Notification.query.filter_by(user_id=cs_user.id, type='crm_failed').one().body


def test_a_delivery_tick_never_steps_back(app, hook, cs_user):
    lead = ti_lead()
    crm.log_touch(lead, 'whatsapp', 'out', body='Hi', user=cs_user, status='sent', external_id='wamid.d')
    _db.session.commit()
    for st in ('read', 'delivered', 'sent'):
        hook('message.status_updated', {'whatsapp_message_id': 'wamid.d', 'status': st})
    assert CrmTouchpoint.query.filter_by(external_id='wamid.d').one().status == 'read'
    hook('message.status_updated', {'whatsapp_message_id': 'wamid.unknown', 'status': 'read'})   # nothing to find: fine


def test_error_code_text_is_a_number_or_nothing():
    from app.services.crm import _error_code          # moved with the status handling (crm.wa_status_update)
    assert _error_code('131050') == 131050 and _error_code(None) is None and _error_code('x') is None


def test_us_numbers_get_the_paused_by_meta_text():
    p = CrmPerson(phone='+14155550123')
    assert 'US numbers are paused by Meta' in crm.wa_failure_text(131049, None, p)
    assert 'US numbers' not in crm.wa_failure_text(131049, None, CrmPerson(phone=PHONE))


# ------------------------------------------------------------------ the owner follows WhatsApp (contract 26)

def test_an_inbox_hand_over_changes_the_owner_but_our_own_echo_does_not(app, hook, cs_user, admin_user):
    lead = ti_lead()
    lead.owner_id = admin_user.id
    _db.session.commit()
    lid = lead.id
    r = hook('conversation.assigned', {'contact_id': 'c-1', 'contact_phone': DIGITS, 'conversation_id': 'conv-1',
                                       'assignee_email': cs_user.email, 'origin': 'portal'})
    assert r.get_json().get('echo') is True and fresh(CrmLead, lid).owner_id == admin_user.id
    r = hook('conversation.assigned', {'contact_id': 'c-1', 'contact_phone': DIGITS, 'conversation_id': 'conv-1',
                                       'assignee_email': cs_user.email, 'origin': 'inbox'})
    assert fresh(CrmLead, lid).owner_id == cs_user.id
    assert Notification.query.filter_by(user_id=cs_user.id, type='crm_assigned').count() == 1


def test_a_reply_rule_or_the_bot_never_changes_the_owner(app, hook, cs_user, admin_user):
    lead = ti_lead()
    lead.owner_id = admin_user.id
    _db.session.commit()
    lid = lead.id
    for origin in ('automation', 'flow', 'ai', 'something-new'):
        hook('conversation.assigned', {'contact_id': 'c-1', 'contact_phone': DIGITS, 'assignee_email': cs_user.email,
                                       'origin': origin})
        assert fresh(CrmLead, lid).owner_id == admin_user.id, origin


def test_an_assignment_to_somebody_who_is_not_staff_is_ignored(app, hook, admin_user):
    lead = ti_lead()
    lead.owner_id = admin_user.id
    _db.session.commit()
    outsider = make_user('plain@test.com', 'plainuser', role='user')
    hook('conversation.assigned', {'contact_id': 'c-1', 'contact_phone': DIGITS, 'assignee_email': outsider.email,
                                   'origin': 'inbox'})
    assert fresh(CrmLead, lead.id).owner_id == admin_user.id


# ------------------------------------------------------------------ the catch-up job

def _connected(monkeypatch, items, next_since=None, calls=None):
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'wacrm_live_test')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    crm.save_settings(wacrm_webhook={'id': 'wh-1', 'secret': SECRET, 'url': 'https://example.org/hook'})

    def activity(since, limit=100):
        if calls is not None:
            calls.append((since, limit))
        return {'items': items, 'next_since': next_since}
    monkeypatch.setattr(wacrm_team, 'activity', activity)


def _item(wamid, at, text='Hello', phone=DIGITS, cid='c-1', last=None, assignee=None):
    return {'conversation_id': 'conv-' + cid, 'contact_id': cid, 'contact_phone': phone, 'contact_name': 'R',
            'assignee_email': assignee, 'status': 'open', 'unread_count': 1,
            'last_message_at': last or at,
            'last_inbound': {'whatsapp_message_id': wamid, 'text': text, 'content_type': 'text', 'at': at}}


def test_a_reply_the_webhook_missed_is_caught_up_at_its_real_time(app, monkeypatch):
    lead = ti_lead()
    wrote = datetime.utcnow() - timedelta(hours=2)
    iso = wrote.replace(microsecond=0).isoformat() + 'Z'
    _connected(monkeypatch, [_item('wamid.missed', iso, text='Ages are 65 and 62')])
    out = crm.wa_catch_up()
    assert out == {'crm_wa_caught_up': 1}
    tp = CrmTouchpoint.query.filter_by(external_id='wamid.missed').one()
    assert tp.lead_id == lead.id and abs((tp.created_at - wrote).total_seconds()) < 2
    # running it again finds nothing new (idempotent) and asks from where it stopped
    calls = []
    _connected(monkeypatch, [_item('wamid.missed', iso)], calls=calls)
    assert crm.wa_catch_up() == {'crm_wa_caught_up': 0}
    assert calls[0][0] == iso
    assert CrmTouchpoint.query.filter_by(external_id='wamid.missed').count() == 1


def test_the_newest_two_minutes_are_left_for_the_webhook(app, monkeypatch):
    ti_lead()
    now = datetime.utcnow()
    fresh_iso = (now - timedelta(seconds=30)).replace(microsecond=0).isoformat() + 'Z'
    _connected(monkeypatch, [_item('wamid.justnow', fresh_iso)])
    assert crm.wa_catch_up(now=now) == {'crm_wa_caught_up': 0}
    assert CrmTouchpoint.query.filter_by(external_id='wamid.justnow').count() == 0


def test_catch_up_creates_a_lead_for_a_number_we_never_heard_of(app, monkeypatch):
    iso = (datetime.utcnow() - timedelta(hours=1)).replace(microsecond=0).isoformat() + 'Z'
    _connected(monkeypatch, [_item('wamid.stranger', iso, phone='919222222222', cid='c-77', text='Hi')])
    assert crm.wa_catch_up() == {'crm_wa_caught_up': 1}
    lead = CrmLead.query.one()
    assert lead.person.phone == '+919222222222' and lead.source.key == 'wa-india'


def test_catch_up_does_nothing_until_replies_are_connected_here(app, monkeypatch):
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'k')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    monkeypatch.setattr(wacrm_team, 'activity', lambda *a, **k: (_ for _ in ()).throw(AssertionError('called')))
    assert crm.wa_catch_up() == {}


def test_a_catch_up_that_cannot_reach_the_crm_reports_and_moves_on(app, monkeypatch):
    _connected(monkeypatch, [])
    def down(since, limit=100):
        raise wacrm_team.TeamError('down', status=502)
    monkeypatch.setattr(wacrm_team, 'activity', down)
    assert crm.wa_catch_up() == {'crm_wa_caught_up': 'failed'}


def test_one_bad_message_does_not_stop_the_rest(app, monkeypatch):
    ti_lead()
    old = (datetime.utcnow() - timedelta(hours=3)).replace(microsecond=0).isoformat() + 'Z'
    old2 = (datetime.utcnow() - timedelta(hours=2)).replace(microsecond=0).isoformat() + 'Z'
    _connected(monkeypatch, [_item('wamid.bad', old), _item('wamid.good', old2)])
    real = crm.record_whatsapp_in

    def picky(*a, **k):
        if k.get('wamid') == 'wamid.bad':
            raise RuntimeError('boom')
        return real(*a, **k)
    monkeypatch.setattr(crm, 'record_whatsapp_in', picky)
    assert crm.wa_catch_up() == {'crm_wa_caught_up': 1}
    assert CrmTouchpoint.query.filter_by(external_id='wamid.good').count() == 1


def test_the_jobs_runner_runs_the_catch_up_and_survives_its_failure(app, monkeypatch):
    from app.services import jobs
    monkeypatch.setattr(crm, 'wa_catch_up', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('x')))
    try:
        out = jobs.run_all()
    except Exception as exc:          # noqa: BLE001
        pytest.fail('the jobs runner died with the catch-up: %r' % exc)
    assert isinstance(out, dict)


# ------------------------------------------------------------------ the webhook health job

def _hook_calls(monkeypatch, rows, mode='contacts'):
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'wacrm_live_test')
    crm.save_settings(whatsapp_mode=mode, wacrm_webhook={'id': 'wh-1', 'secret': SECRET, 'url': 'https://example.org/hook'})
    calls = []

    def call(method, path, payload=None, params=None):
        calls.append((method, path, payload))
        return rows if method == 'GET' else {}
    monkeypatch.setattr(wacrm, '_call', call)
    return calls


def test_a_switched_off_webhook_is_switched_back_on_and_the_admins_told_once(app, monkeypatch, admin_user):
    calls = _hook_calls(monkeypatch, [{'id': 'wh-1', 'url': 'https://example.org/hook', 'is_active': False}])
    now = datetime(2026, 10, 16, 10, 0)
    assert crm.wa_webhook_health(now=now) == {'crm_wa_webhook': 'switched_on'}
    assert ('PATCH', '/api/v1/webhooks/wh-1', {'is_active': True}) in calls
    assert Notification.query.filter_by(user_id=admin_user.id, type='crm_failed').count() == 1
    # within the hour: not even looked at
    n = len(calls)
    assert crm.wa_webhook_health(now=now + timedelta(minutes=20)) == {}
    assert len(calls) == n
    # still off next hour (it keeps getting switched off): switched on again, the admins not nagged again
    out = crm.wa_webhook_health(now=now + timedelta(hours=1, minutes=5))
    assert out == {'crm_wa_webhook': 'switched_on'}
    assert Notification.query.filter_by(user_id=admin_user.id, type='crm_failed').count() == 1


def test_a_healthy_webhook_is_left_alone(app, monkeypatch, admin_user):
    calls = _hook_calls(monkeypatch, [{'id': 'wh-1', 'url': 'https://example.org/hook', 'is_active': True}])
    assert crm.wa_webhook_health(now=datetime(2026, 10, 16, 10, 0)) == {'crm_wa_webhook': 'ok'}
    assert [c for c in calls if c[0] != 'GET'] == []
    assert Notification.query.filter_by(type='crm_failed').count() == 0


def test_with_whatsapp_off_a_dead_webhook_is_reported_not_switched_on(app, monkeypatch, admin_user):
    calls = _hook_calls(monkeypatch, [{'id': 'wh-1', 'url': 'https://example.org/hook', 'is_active': False}], mode='off')
    assert crm.wa_webhook_health(now=datetime(2026, 10, 16, 10, 0)) == {'crm_wa_webhook': 'off'}
    assert [c for c in calls if c[0] != 'GET'] == []


def test_a_webhook_that_vanished_is_reported(app, monkeypatch, admin_user):
    _hook_calls(monkeypatch, [])
    assert crm.wa_webhook_health(now=datetime(2026, 10, 16, 10, 0)) == {'crm_wa_webhook': 'missing'}


def test_nothing_is_checked_where_replies_were_never_connected(app, monkeypatch):
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'k')
    monkeypatch.setattr(wacrm, '_call', lambda *a, **k: (_ for _ in ()).throw(AssertionError('called')))
    assert crm.wa_webhook_health() == {}
