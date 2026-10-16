"""The Sales CRM keeps the WhatsApp CRM in step by itself: the sync engine.

    a change here       only marks the person (crm.mark_wa_due): nothing is called during the request
    after the save      their contact, its tags, name and e-mail are brought into step (run_wa_sync);
                        the chat goes to the owner only when the owner changed here
    when it fails       the mark stays with a short reason, and the jobs runner tries again
    never               a message, a guessed contact, a mark or a write while WhatsApp is off
"""
import copy
import hashlib
import hmac
import importlib.util
import json
import os
import threading
import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
import requests

from conftest import login, make_user
from app import db as _db
from app.models import CrmLead, CrmPerson, CrmPipeline, CrmSource, CrmStage, CrmTouchpoint, InsuranceQuote
from app.services import access, crm, jobs, wacrm, wacrm_team

PHONE, DIGITS = '+919876543210', '919876543210'
FIVE = {'wacrm_sync_due_at', 'wacrm_assign_due', 'wa_sync_error', 'wa_synced_at', 'wa_opt_out_at'}


def stage(pipe_key, stage_key):
    return (CrmStage.query.join(CrmPipeline).filter(CrmPipeline.key == pipe_key, CrmStage.key == stage_key)
            .one())


def ti_lead(phone=PHONE, **kw):
    return crm.capture('ti-quote', name=kw.pop('name', 'Ramesh Kumar'), phone=phone, utm={}, **kw)


def sh_lead(phone=PHONE, **kw):
    return crm.capture('sh-booking', name=kw.pop('name', 'Ramesh Kumar'), phone=phone, product='SH', utm={}, **kw)


def fresh_person(pid):
    _db.session.expire_all()
    return _db.session.get(CrmPerson, pid)


def due_people():
    _db.session.expire_all()
    return CrmPerson.query.filter(CrmPerson.wacrm_sync_due_at.isnot(None)).all()


def someone_else(lead, *users):
    return next(u for u in users if u.id != lead.owner_id)


def signed(client, event, data, secret='whsec_test', t=None):
    raw = json.dumps({'event': event, 'data': data}).encode()
    t = int(time.time()) if t is None else t
    sig = hmac.new(secret.encode(), str(t).encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return client.post('/api/crm/wacrm-webhook', data=raw,
                       headers={'X-Wacrm-Signature': 't=%d,v1=%s' % (t, sig), 'Content-Type': 'application/json'})


class Busy:
    """Another sync holds this worker's lock."""
    def acquire(self, timeout=None):
        return False

    def release(self):
        raise AssertionError('released a lock it never had')


class FakeWhatsApp:
    """The WhatsApp CRM's public API and its /api/portal API, in memory: contacts by number, every
    call recorded, nothing leaves."""

    def __init__(self):
        self.contacts = {}            # digits -> {'id', 'phone', 'name', 'email', 'tags': [{'name'}]}
        self.calls, self.portal = [], []
        self.fail = None              # raised by every public API call
        self.fail_for = {}            # digits -> raised when that number is looked up
        self.answer_phone = None      # the number POST /contacts says it matched
        self.ensure = {}              # overrides for the conversation/ensure answer
        self.ensure_error = self.assign_error = None

    def seed(self, digits, tags=(), name=None, email=None, cid=None):
        c = {'id': cid or 'c-%d' % (len(self.contacts) + 1), 'phone': digits, 'name': name, 'email': email,
             'tags': [{'name': t} for t in tags]}
        self.contacts[digits] = c
        return c

    def by_id(self, cid):
        return next((c for c in self.contacts.values() if c['id'] == cid), None)

    def tags(self, digits=DIGITS):
        return sorted(t['name'] for t in self.contacts[digits]['tags'])

    def made(self, path):
        return [p for p in self.portal if p[1] == path]

    def patches(self):
        return [c for c in self.calls if c[0] == 'PATCH']

    def call(self, method, path, payload=None, params=None):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if self.fail is not None:
            raise self.fail
        if method == 'POST' and path == '/api/v1/contacts':
            d = ''.join(ch for ch in payload['phone'] if ch.isdigit())
            if d in self.fail_for:
                raise self.fail_for[d]
            c = self.contacts.get(d) or self.seed(d, name=payload.get('name'), email=payload.get('email'))
            out = copy.deepcopy(c)
            if self.answer_phone:
                out['phone'] = self.answer_phone
            return out
        if path.startswith('/api/v1/contacts/'):
            c = self.by_id(path.rsplit('/', 1)[-1])
            if c is None:
                raise wacrm.WacrmError('Not found', status=404)
            if method == 'PATCH':
                for k in ('name', 'email'):
                    if k in payload:
                        c[k] = payload[k]
                if 'tags' in payload:
                    c['tags'] = [{'name': t} for t in payload['tags']]
            return copy.deepcopy(c)
        return {}

    def api(self, method, path, payload=None, params=None):
        self.portal.append((method, path, copy.deepcopy(payload)))
        if path == 'conversation/ensure':
            if self.ensure_error is not None:
                raise self.ensure_error
            c = self.contacts.get(payload['phone'])
            if c is None:
                if not payload.get('create'):
                    return {'contact_id': None, 'conversation_id': None}
                c = self.seed(payload['phone'], name=payload.get('name'), email=payload.get('email'))
            email = payload.get('assign_email')
            return {'contact_id': self.ensure.get('contact_id', c['id']), 'conversation_id': 'conv-' + c['id'],
                    'contact_phone': c['phone'], 'contact_name': c['name'], 'created_contact': False,
                    'created_conversation': False,
                    'assignee_email': self.ensure.get('assignee_email', email),
                    'assignment': self.ensure.get('assignment', 'assigned' if email else 'none'),
                    'last_inbound_at': None, 'status': 'open'}
        if path == 'conversation/assign':
            if self.assign_error is not None:
                raise self.assign_error
            return {'conversation_id': payload.get('conversation_id'), 'assignee_email': payload['email'],
                    'changed': True}
        return {}


@pytest.fixture
def wa(app, monkeypatch):
    """The WhatsApp CRM connected (both APIs) and the switch on "Keep leads in step"."""
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'wacrm_live_test')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    fake = FakeWhatsApp()
    monkeypatch.setattr(wacrm, '_call', fake.call)
    monkeypatch.setattr(wacrm_team, '_api', fake.api)
    crm.save_settings(whatsapp_mode='contacts')
    yield fake
    # whatever the test did, nothing was ever sent to a customer (checked on the record: a raise
    # inside the fake would have been caught by the sync's own guard)
    assert not [c for c in fake.calls if c[1] == '/api/v1/messages']


# ============================================================================== marked now, told after the save

def test_marking_due_calls_nothing_until_the_save(app, wa):
    lead = ti_lead()
    pid, lid = lead.person_id, lead.id
    assert wa.tags() == ['TI: Cold lead', 'ti']
    del wa.calls[:]
    crm.move_stage(lead, stage('ti-standard', 'prospect'))
    assert wa.calls == [] and lead.person.wacrm_sync_due_at is not None
    # an undone save tells nobody anything
    _db.session.rollback()
    assert wa.calls == [] and fresh_person(pid).wacrm_sync_due_at is None
    lead = _db.session.get(CrmLead, lid)
    crm.move_stage(lead, stage('ti-standard', 'prospect'))
    _db.session.commit()
    assert wa.patches() == [('PATCH', '/api/v1/contacts/c-1', {'tags': ['TI: Prospect', 'ti']})]
    p = fresh_person(pid)
    assert p.wacrm_sync_due_at is None and p.wa_synced_at is not None and p.wa_sync_error is None
    assert p.wacrm_contact_id == 'c-1' and not p.wacrm_assign_due
    assert wa.portal == []


def test_a_savepoint_is_not_the_save(app, wa):
    lead = ti_lead()
    del wa.calls[:]
    with _db.session.begin_nested():
        crm.move_stage(lead, stage('ti-standard', 'prospect'))
    assert wa.calls == []                                        # the real commit is still to come
    _db.session.commit()
    assert wa.tags() == ['TI: Prospect', 'ti']


def test_a_savepoint_rolled_back_keeps_the_marks_of_the_save_around_it(app, wa):
    lead = ti_lead()
    crm.move_stage(lead, stage('ti-standard', 'prospect'))
    try:
        with _db.session.begin_nested():
            raise ValueError('a duplicate read mark, say')
    except ValueError:
        pass
    _db.session.commit()
    assert wa.tags() == ['TI: Prospect', 'ti']


def test_a_refused_edit_tells_whatsapp_nothing(app, client, wa, admin_user):
    lead = ti_lead()
    del wa.calls[:]
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/update' % lead.id, json={'name': 'Somebody Else', 'email': 'not-an-email'})
    assert r.status_code == 400
    _db.session.rollback()
    assert wa.calls == [] and wa.portal == [] and fresh_person(lead.person_id).wacrm_sync_due_at is None


def test_marks_add_up_and_never_cancel_an_owner_change(app, wa, monkeypatch):
    lead = ti_lead()
    monkeypatch.setattr(crm, '_wa_lock', Busy())                 # hold the sync so the marks can be read
    crm.mark_wa_due(lead.person, assign=True)
    crm.mark_wa_due(lead.person)
    _db.session.commit()
    p = fresh_person(lead.person_id)
    assert p.wacrm_assign_due is True and p.wacrm_sync_due_at is not None
    assert crm.mark_wa_due(None) is False


def test_somebody_without_a_number_is_never_sent(app, wa):
    lead = crm.capture('ti-quote', name='Mail Only', email='m@example.com', utm={})
    assert crm.mark_wa_due(lead.person) is False
    _db.session.commit()
    assert wa.calls == [] and wa.portal == [] and due_people() == []


def test_off_marks_and_writes_nothing(app, client, wa, cs_user, admin_user):
    crm.save_settings(whatsapp_mode='off')
    other = make_user('o@test.com', 'other', role='cs')
    lead = ti_lead()
    lead.person.wacrm_contact_id, lead.person.wacrm_conversation_id = 'c-9', 'conv-9'
    _db.session.commit()
    lid, pid = lead.id, lead.person_id
    sh = sh_lead()
    login(client, admin_user.email)
    client.post('/admin/crm/lead/%d/move' % lid, json={'stage_id': stage('ti-standard', 'prospect').id})
    d = client.post('/admin/crm/lead/%d/update' % lid,
                    json={'owner_id': someone_else(lead, cs_user, other).id, 'name': 'Ramesh K',
                          'email': 'r@example.com', 'phone': '+14155550123'}).get_json()
    assert d == {'success': True, 'whatsapp': False}
    p = fresh_person(pid)
    # the ids were the old number's: forgetting them is a local write, so it still happens
    assert p.phone == '+14155550123' and p.wacrm_contact_id is None and p.wacrm_conversation_id is None
    cold = stage('ti-standard', 'prospect')
    client.post('/admin/crm/setup/pipeline', data={'pipeline': 'ti-standard', 'action': 'stage', 'op': 'save',
                                                    'stage_id': cold.id, 'name': 'Warm lead', 'kind': cold.kind})
    client.post('/admin/crm/lead/%d/remove' % sh.id)
    client.post('/admin/crm/lead/%d/remove' % lid)
    assert wa.calls == [] and wa.portal == []
    assert due_people() == [] and not CrmPerson.query.filter(CrmPerson.wacrm_assign_due.is_(True)).count()
    ti_lead('+919000000077', name='Asha')
    assert crm.wa_backfill() == 0
    assert crm.run_wa_sync() == {'crm_wa_synced': 0, 'crm_wa_failed': 0}
    assert wa.calls == [] and wa.portal == [] and due_people() == []


def test_marks_made_before_switching_off_wait_until_it_is_on_again(app, wa):
    wa.fail = wacrm.WacrmError('The WhatsApp CRM could not be reached.')
    lead = ti_lead()
    wa.fail = None
    crm.save_settings(whatsapp_mode='off')
    del wa.calls[:]
    assert crm.run_wa_sync() == {'crm_wa_synced': 0, 'crm_wa_failed': 0}
    assert wa.calls == [] and fresh_person(lead.person_id).wacrm_sync_due_at is not None
    crm.save_settings(whatsapp_mode='contacts')
    assert crm.run_wa_sync()['crm_wa_synced'] == 1
    assert wa.tags() == ['TI: Cold lead', 'ti']


# ============================================================================== failures keep the work

def test_a_failed_sync_never_undoes_the_move(app, client, wa, cs_user):
    lead = ti_lead()
    wa.fail = wacrm.WacrmError('The WhatsApp CRM could not be reached.')
    login(client, cs_user.email)
    r = client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': stage('ti-standard', 'prospect').id})
    assert r.status_code == 200 and r.get_json()['success']
    _db.session.expire_all()
    lead = _db.session.get(CrmLead, lead.id)
    assert lead.stage.key == 'prospect'
    p = lead.person
    assert p.wacrm_sync_due_at is not None and p.wacrm_sync_due_at <= datetime.utcnow()   # due again now
    assert 'could not be reached' in p.wa_sync_error


def test_a_reply_is_kept_when_the_crm_is_down(app, client, wa, monkeypatch):
    monkeypatch.setenv('WACRM_WEBHOOK_SECRET', 'whsec_test')
    lead = ti_lead()                                              # their contact is c-1 now
    wa.fail = wacrm.WacrmError('The WhatsApp CRM could not be reached.')
    r = signed(client, 'message.received', {'contact_id': 'c-1', 'conversation_id': 'conv-1', 'text': 'Yes please',
                                            'whatsapp_message_id': 'wamid.r1', 'content_type': 'text'})
    assert r.status_code == 200 and r.get_json() == {'ok': True}
    assert CrmTouchpoint.query.filter_by(external_id='wamid.r1', direction='in').count() == 1
    _db.session.expire_all()
    lead = _db.session.get(CrmLead, lead.id)
    assert lead.stage.key == 'prospect' and lead.person.wacrm_sync_due_at is not None


def test_a_failure_backs_off_and_the_job_retries(app, wa):
    wa.fail = wacrm.WacrmError('Server error', status=500)
    lead = ti_lead()
    p = fresh_person(lead.person_id)
    assert p.wacrm_sync_due_at > datetime.utcnow() + timedelta(minutes=50) and p.wa_sync_error == 'Server error'
    del wa.calls[:]
    assert crm.run_wa_sync() == {'crm_wa_synced': 0, 'crm_wa_failed': 0, 'crm_wa_waiting': 1}
    assert wa.calls == []                                         # backing off: nobody is picked
    wa.fail = None
    out = crm.run_wa_sync(now=datetime.utcnow() + timedelta(hours=2))
    assert out == {'crm_wa_synced': 1, 'crm_wa_failed': 0, 'crm_wa_waiting': 0}
    p = fresh_person(lead.person_id)
    assert p.wa_sync_error is None and p.wacrm_sync_due_at is None and p.wacrm_contact_id == 'c-1'


def test_no_answer_stops_the_run_and_keeps_everyone_due(app, wa):
    now = datetime.utcnow()
    people = [CrmPerson(phone='+9190000001%02d' % i, wacrm_sync_due_at=now - timedelta(minutes=10 - i))
              for i in range(3)]
    _db.session.add_all(people)
    _db.session.commit()
    before = {p.id: p.wacrm_sync_due_at for p in people}
    wa.fail = wacrm.WacrmError('The WhatsApp CRM could not be reached.')
    out = crm.run_wa_sync()
    assert out == {'crm_wa_synced': 0, 'crm_wa_failed': 1, 'crm_wa_waiting': 3}
    assert len(wa.calls) == 1                                     # it is not answering: the rest wait
    first, *rest = sorted(before)
    assert fresh_person(first).wacrm_sync_due_at <= datetime.utcnow()
    assert [fresh_person(i).wacrm_sync_due_at for i in rest] == [before[i] for i in rest]


def test_a_bug_for_one_person_does_not_stop_the_rest(app, wa):
    now = datetime.utcnow()
    a = CrmPerson(phone='+919000000101', wacrm_sync_due_at=now - timedelta(minutes=2))
    b = CrmPerson(phone='+919000000102', wacrm_sync_due_at=now - timedelta(minutes=1))
    _db.session.add_all([a, b])
    _db.session.commit()
    wa.fail_for['919000000101'] = RuntimeError('a bug')
    out = crm.run_wa_sync()
    assert out['crm_wa_synced'] == 1 and out['crm_wa_failed'] == 1
    pa, pb = fresh_person(a.id), fresh_person(b.id)
    assert pa.wa_sync_error == 'Something went wrong -- see the server log'
    assert pa.wacrm_sync_due_at > datetime.utcnow() + timedelta(minutes=50) and pa.wacrm_contact_id is None
    assert pb.wacrm_sync_due_at is None and pb.wacrm_contact_id


def test_a_busy_worker_leaves_the_marks_for_later(app, wa, monkeypatch):
    monkeypatch.setattr(crm, '_wa_lock', Busy())
    lead = ti_lead()
    assert wa.calls == [] and fresh_person(lead.person_id).wacrm_sync_due_at is not None
    assert crm.run_wa_sync() == {'crm_wa_synced': 0, 'crm_wa_failed': 0}


def test_a_run_stops_taking_people_when_its_time_is_up(app, wa, monkeypatch):
    now = datetime.utcnow()
    _db.session.add_all([CrmPerson(phone='+9190000001%02d' % i, wacrm_sync_due_at=now - timedelta(minutes=5 - i))
                         for i in range(3)])
    _db.session.commit()
    ticks = [0, 0, 50]
    monkeypatch.setattr(crm, 'monotonic', lambda: ticks.pop(0) if len(ticks) > 1 else ticks[0])
    out = crm.run_wa_sync()
    assert out == {'crm_wa_synced': 1, 'crm_wa_failed': 0, 'crm_wa_waiting': 2}


def test_a_sync_that_died_is_picked_up_after_its_lease(app, wa):
    lead = ti_lead()
    p = _db.session.get(CrmPerson, lead.person_id)
    p.wacrm_sync_due_at = datetime.utcnow() + timedelta(minutes=4)          # another worker's lease
    _db.session.commit()
    del wa.calls[:]
    assert crm.run_wa_sync()['crm_wa_synced'] == 0 and wa.calls == []
    assert crm.run_wa_sync(now=datetime.utcnow() + timedelta(minutes=6))['crm_wa_synced'] == 1


def test_somebody_removed_meanwhile_is_skipped(app, wa):
    p = CrmPerson(phone='+919000000101', wacrm_sync_due_at=datetime.utcnow())
    _db.session.add(p)
    _db.session.commit()
    CrmPerson.query.filter_by(id=p.id).delete(synchronize_session=False)
    _db.session.commit()
    assert crm._wa_claim(p) is None


def test_a_save_during_a_sync_wins(app, wa):
    lead = ti_lead()
    p = _db.session.get(CrmPerson, lead.person_id)
    p.wacrm_sync_due_at = datetime.utcnow() - timedelta(seconds=1)
    _db.session.commit()
    claimed = crm._wa_claim(p)
    assert claimed is not None and claimed > datetime.utcnow()
    assert crm._wa_claim(p) is None                               # taken: a second worker leaves them alone
    p.wacrm_sync_due_at = datetime.utcnow()                       # saved again while the sync was out
    _db.session.commit()
    assert crm._wa_finish(p.id, claimed, True, contact_id='c-9') is False
    p = fresh_person(p.id)
    assert p.wacrm_contact_id == 'c-1' and p.wacrm_sync_due_at is not None
    # another worker finished them meanwhile: once more, so the newest state has the last word
    p.wacrm_sync_due_at = None
    _db.session.commit()
    assert crm._wa_finish(p.id, claimed, True) is False
    assert fresh_person(p.id).wacrm_sync_due_at is not None


# ============================================================================== the background and the jobs runner

def test_after_a_save_a_background_thread_does_it(app, wa, monkeypatch):
    app.config['WA_SYNC_INLINE'] = False
    started = []

    class Recorder:
        def __init__(self, target=None, args=(), daemon=None, name=None):
            started.append((target, daemon, name, args))

        def start(self):
            pass
    monkeypatch.setattr(crm, 'threading', SimpleNamespace(Thread=Recorder))
    lead = ti_lead()
    assert [(t, d, n) for t, d, n, _ in started] == [(crm._wa_run_isolated, True, 'wacrm-sync')]
    assert started[0][3][0] is app and started[0][3][1] == [lead.person_id]
    assert wa.calls == []
    assert crm.run_wa_sync()['crm_wa_synced'] == 1 and wa.tags() == ['TI: Cold lead', 'ti']


def test_the_background_thread_really_brings_them_in(app, wa):
    app.config['WA_SYNC_INLINE'] = False
    crm.ensure_defaults()
    lead = ti_lead(notify=False)
    for t in threading.enumerate():
        if t.name == 'wacrm-sync':
            t.join(15)
    assert wa.tags() == ['TI: Cold lead', 'ti']
    p = fresh_person(lead.person_id)
    assert p.wacrm_contact_id == 'c-1' and p.wacrm_sync_due_at is None and p.wa_synced_at is not None


def test_the_sync_runs_in_the_background_unless_told_otherwise(tmp_path):
    from app import create_app
    other = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'SERVER_NAME': 'localhost',
                        'UPLOAD_FOLDER': str(tmp_path / 'u'), 'PRIVATE_UPLOAD_FOLDER': str(tmp_path / 'p')})
    assert other.config['WA_SYNC_INLINE'] is False


def test_after_a_save_only_the_people_it_marked_are_synced(app, wa):
    x = CrmPerson(phone='+919000000101', wacrm_sync_due_at=datetime.utcnow() - timedelta(minutes=5))
    _db.session.add(x)
    _db.session.commit()
    ti_lead()
    assert [c[2]['phone'] for c in wa.calls if c[:2] == ('POST', '/api/v1/contacts')] == [PHONE]
    assert fresh_person(x.id).wacrm_sync_due_at is not None         # left for the jobs runner


def test_one_save_syncs_ten_people_and_leaves_the_rest_to_the_jobs_runner(app, client, wa, admin_user):
    for i in range(12):
        ti_lead('+9190000002%02d' % i, name='Person %d' % i)
    login(client, admin_user.email)
    cold = stage('ti-standard', 'cold')
    client.post('/admin/crm/setup/pipeline', data={'pipeline': 'ti-standard', 'action': 'stage', 'op': 'save',
                                                    'stage_id': cold.id, 'name': 'Fresh lead', 'kind': cold.kind})
    assert len(due_people()) == 2
    assert crm.run_wa_sync() == {'crm_wa_synced': 2, 'crm_wa_failed': 0, 'crm_wa_waiting': 0}
    assert all(wa.tags('9190000002%02d' % i) == ['TI: Fresh lead', 'ti'] for i in range(12))


def test_the_job_drains_oldest_first_30_a_run(app, wa):
    now = datetime.utcnow()
    people = [CrmPerson(phone='+9190000003%02d' % i, wacrm_sync_due_at=now - timedelta(minutes=60 - i))
              for i in range(35)]
    _db.session.add_all(people)
    _db.session.commit()
    ids = [p.id for p in people]
    assert crm.run_wa_sync() == {'crm_wa_synced': 30, 'crm_wa_failed': 0, 'crm_wa_waiting': 5}
    assert sorted(p.id for p in due_people()) == sorted(ids[30:])   # the five marked last
    assert crm.run_wa_sync()['crm_wa_waiting'] == 0


def test_jobs_report_includes_the_sync(app, monkeypatch):
    monkeypatch.setattr(crm, 'run_wa_sync', lambda: {'crm_wa_synced': 7, 'crm_wa_failed': 0, 'crm_wa_waiting': 2})
    out = jobs.run_all()
    assert out['crm_wa_synced'] == 7 and out['crm_wa_waiting'] == 2

    def boom():
        raise RuntimeError('broken')
    monkeypatch.setattr(crm, 'run_wa_sync', boom)
    out = jobs.run_all()
    assert out['crm_wa_synced'] == 'failed' and 'escalated' in out


def test_the_backfill_command_marks_and_the_jobs_runner_brings_them_in(app, wa):
    crm.ensure_defaults()
    ti_lead(plan=False, notify=False, sync=False, imported=True)
    crm.save_settings(whatsapp_mode='off')
    r = app.test_cli_runner().invoke(args=['crm-wa-backfill'])
    assert 'nothing was marked' in r.output and due_people() == []
    crm.save_settings(whatsapp_mode='contacts')
    r = app.test_cli_runner().invoke(args=['crm-wa-backfill'])
    assert r.output.startswith('1 people marked') and 'nothing is sent' in r.output
    assert wa.calls == []
    out = jobs.run_all()
    assert out['crm_wa_synced'] == 1 and out['crm_wa_waiting'] == 0
    assert wa.tags() == ['TI: Cold lead', 'ti'] and wa.portal == []


# ============================================================================== no chat unless the owner changed here

def test_capture_moves_replies_and_backfill_never_make_a_chat(app, client, wa, monkeypatch):
    monkeypatch.setenv('WACRM_WEBHOOK_SECRET', 'whsec_test')
    lead = ti_lead()
    signed(client, 'message.received', {'contact_id': 'c-1', 'whatsapp_message_id': 'wamid.r2', 'text': 'Hi',
                                        'content_type': 'text'})
    lead = _db.session.get(CrmLead, lead.id)
    crm.move_stage(lead, stage('ti-standard', 'customer'))
    _db.session.commit()
    ti_lead('+919000000077', name='Asha', plan=False, notify=False, sync=False, imported=True)
    assert crm.wa_backfill() == 1
    assert crm.run_wa_sync()['crm_wa_synced'] == 1
    assert not [p for p in wa.portal if p[1].startswith('conversation')]
    assert not CrmPerson.query.filter(CrmPerson.wacrm_assign_due.is_(True)).count()


def test_a_whatsapp_reassignment_is_not_pushed_back(app, client, wa, cs_user, monkeypatch):
    monkeypatch.setenv('WACRM_WEBHOOK_SECRET', 'whsec_test')
    other = make_user('o@test.com', 'other', role='cs')
    lead = ti_lead()
    new = someone_else(lead, other, cs_user)
    del wa.calls[:]
    del wa.portal[:]
    r = signed(client, 'conversation.assigned', {'contact_phone': DIGITS, 'conversation_id': 'conv-5',
                                                 'assignee_email': new.email, 'origin': 'crm'})
    assert r.get_json().get('owner') == new.email
    _db.session.expire_all()
    lead = _db.session.get(CrmLead, lead.id)
    assert lead.owner_id == new.id
    assert not lead.person.wacrm_assign_due and lead.person.wacrm_sync_due_at is None
    assert wa.calls == [] and wa.portal == []


def test_a_new_number_writing_in_becomes_a_tagged_contact_and_its_chat_is_left_alone(app, client, wa, monkeypatch):
    monkeypatch.setenv('WACRM_WEBHOOK_SECRET', 'whsec_test')
    wa.seed('919000000077', name='Asha', cid='c-77')
    r = signed(client, 'message.received', {'contact_id': 'c-77', 'conversation_id': 'conv-77', 'text': 'Hi',
                                            'whatsapp_message_id': 'wamid.n1', 'content_type': 'text'})
    assert r.get_json() == {'ok': True, 'created': True}
    _db.session.expire_all()
    person = CrmPerson.query.filter_by(phone='+919000000077').one()
    assert person.wacrm_contact_id == 'c-77' and person.wacrm_conversation_id == 'conv-77'
    assert 'gen' in wa.tags('919000000077') and wa.portal == []


@pytest.mark.parametrize('answer', ['assigned', 'kept', 'not_member'])
def test_an_owner_change_gives_the_chat_to_the_owner(app, client, wa, cs_user, admin_user, answer):
    other = make_user('o@test.com', 'other', role='cs')
    lead = ti_lead()
    new = someone_else(lead, other, cs_user)
    if answer == 'kept':
        wa.ensure = {'assignment': 'kept', 'assignee_email': 'x@else.com'}
    elif answer == 'not_member':
        wa.ensure = {'assignment': 'not_member', 'assignee_email': None}
    del wa.portal[:]
    login(client, admin_user.email)
    d = client.post('/admin/crm/lead/%d/update' % lead.id, json={'owner_id': new.id}).get_json()
    assert d == {'success': True, 'whatsapp': True}
    assert wa.made('conversation/ensure') == [('POST', 'conversation/ensure', {
        'phone': DIGITS, 'name': 'Ramesh Kumar', 'email': None, 'create': True, 'assign_email': new.email})]
    assigns = wa.made('conversation/assign')
    p = fresh_person(lead.person_id)
    assert wa.tags() == ['TI: Cold lead', 'ti'] and p.wacrm_conversation_id == 'conv-c-1'
    if answer == 'not_member':
        assert assigns == []
        assert p.wa_sync_error.startswith('%s is not in the WhatsApp team yet' % new.email)
        # U1 d: a refusal a person must fix is parked (no hourly retry); the hand-over stays owed
        assert p.wacrm_assign_due and p.wacrm_sync_due_at is None
        assert crm.run_wa_sync(now=datetime.utcnow() + timedelta(hours=2))['crm_wa_synced'] == 0
        # they join the team: the next mark gives them the chat
        wa.ensure = {}
        crm.mark_wa_due(p)
        _db.session.commit()
        # the commit syncs inline in tests, so the hand-over is already done
        p = fresh_person(lead.person_id)
        assert len(wa.made('conversation/ensure')) == 2
    else:
        assert assigns == ([] if answer == 'assigned' else
                           [('POST', 'conversation/assign', {'conversation_id': 'conv-c-1', 'email': new.email})])
    assert not p.wacrm_assign_due and p.wacrm_sync_due_at is None and p.wa_sync_error is None


def test_a_member_the_chat_cannot_go_to_is_retried_and_other_errors_too(app, client, wa, cs_user, admin_user):
    other = make_user('o@test.com', 'other', role='cs')
    lead = ti_lead()
    new = someone_else(lead, other, cs_user)
    wa.ensure = {'assignment': 'kept', 'assignee_email': 'x@else.com'}
    wa.assign_error = wacrm_team.TeamError('Not a member', status=422)
    login(client, admin_user.email)
    client.post('/admin/crm/lead/%d/update' % lead.id, json={'owner_id': new.id})
    p = fresh_person(lead.person_id)
    assert p.wa_sync_error.startswith('%s is not in the WhatsApp team yet' % new.email) and p.wacrm_assign_due
    assert p.wacrm_sync_due_at is None          # U1 d: parked until the next mark
    wa.assign_error = wacrm_team.TeamError('Boom', status=500)
    crm.mark_wa_due(p)                          # the next mark retries; a 500 keeps today's backoff
    _db.session.commit()
    assert crm.run_wa_sync(now=datetime.utcnow() + timedelta(hours=2))['crm_wa_failed'] == 1
    p = fresh_person(lead.person_id)
    assert p.wa_sync_error == 'Boom' and p.wacrm_assign_due
    assert p.wacrm_sync_due_at > datetime.utcnow() + timedelta(minutes=50)


def test_ensure_answering_for_another_contact_is_refused(app, client, wa, cs_user, admin_user):
    other = make_user('o@test.com', 'other', role='cs')
    lead = ti_lead()
    wa.ensure = {'contact_id': 'c-99'}
    login(client, admin_user.email)
    client.post('/admin/crm/lead/%d/update' % lead.id, json={'owner_id': someone_else(lead, other, cs_user).id})
    p = fresh_person(lead.person_id)
    assert p.wa_sync_error == 'WhatsApp gave two different contacts for this number'
    assert p.wacrm_conversation_id is None and p.wacrm_contact_id == 'c-1' and p.wacrm_assign_due
    assert wa.made('conversation/assign') == []


def test_an_ambiguous_number_is_an_error_not_a_guess(app, client, wa, cs_user, admin_user):
    other = make_user('o@test.com', 'other', role='cs')
    lead = ti_lead()
    wa.ensure_error = wacrm_team.TeamError('Two contacts', status=409, code='ambiguous_contact')
    login(client, admin_user.email)
    client.post('/admin/crm/lead/%d/update' % lead.id, json={'owner_id': someone_else(lead, other, cs_user).id})
    assert wa.made('conversation/assign') == []
    p = fresh_person(lead.person_id)
    assert p.wa_sync_error == crm.WA_ERRORS['ambiguous_contact']
    assert p.wacrm_assign_due and p.wacrm_sync_due_at is None      # U1 d: 4xx is parked, not retried hourly
    assert wa.tags() == ['TI: Cold lead', 'ti'] and p.wacrm_contact_id == 'c-1'


def test_taking_the_owner_off_moves_no_chat(app, client, wa, cs_user, admin_user):
    lead = ti_lead()
    lead.owner_id = cs_user.id
    _db.session.commit()
    login(client, admin_user.email)
    d = client.post('/admin/crm/lead/%d/update' % lead.id, json={'owner_id': 0}).get_json()
    assert d == {'success': True, 'whatsapp': False}
    assert wa.portal == []
    p = fresh_person(lead.person_id)
    assert not p.wacrm_assign_due and p.wacrm_sync_due_at is None


def test_saving_the_same_owner_again_tells_whatsapp_nothing(app, client, wa, cs_user, admin_user):
    lead = ti_lead()
    lead.owner_id = cs_user.id
    _db.session.commit()
    del wa.calls[:]
    login(client, admin_user.email)
    d = client.post('/admin/crm/lead/%d/update' % lead.id, json={'owner_id': cs_user.id}).get_json()
    assert d == {'success': True, 'whatsapp': False}
    assert wa.calls == [] and wa.portal == []


def test_without_the_team_link_tags_go_but_no_chat_is_promised(app, client, wa, cs_user, admin_user, monkeypatch):
    monkeypatch.delenv('WACRM_PORTAL_SECRET')
    other = make_user('o@test.com', 'other', role='cs')
    lead = ti_lead()
    login(client, admin_user.email)
    d = client.post('/admin/crm/lead/%d/update' % lead.id,
                    json={'owner_id': someone_else(lead, other, cs_user).id, 'name': 'Ramesh K'}).get_json()
    assert d == {'success': True, 'whatsapp': False}
    assert wa.portal == [] and wa.contacts[DIGITS]['name'] == 'Ramesh K'
    assert fresh_person(lead.person_id).wacrm_sync_due_at is None


def test_the_owner_toast_only_when_whatsapp_follows(app, client, wa, cs_user, admin_user):
    other = make_user('o@test.com', 'other', role='cs')
    lead = ti_lead()
    first = someone_else(lead, other, cs_user)
    login(client, admin_user.email)
    d = client.post('/admin/crm/lead/%d/update' % lead.id, json={'owner_id': first.id}).get_json()
    assert d == {'success': True, 'whatsapp': True}
    crm.save_settings(whatsapp_mode='off')
    second = other if first is cs_user else cs_user
    d = client.post('/admin/crm/lead/%d/update' % lead.id, json={'owner_id': second.id}).get_json()
    assert d == {'success': True, 'whatsapp': False}


def test_the_toast_does_not_promise_a_chat_that_goes_to_another_leads_owner(app, client, wa, cs_user, admin_user):
    """One chat per person: it follows their most recently active open lead. Changing the owner of
    another of their leads must not say "their WhatsApp chat goes to them too"."""
    b = make_user('b@test.com', 'bee', role='cs')
    c = make_user('c@test.com', 'cee', role='cs')
    ti, sh = ti_lead(), sh_lead()
    ti.owner_id, sh.owner_id = cs_user.id, b.id
    sh.last_activity_at = datetime.utcnow() + timedelta(minutes=1)      # the Sahayak lead is the live one
    _db.session.commit()
    login(client, admin_user.email)
    d = client.post('/admin/crm/lead/%d/update' % ti.id, json={'owner_id': c.id}).get_json()
    assert [e[2]['assign_email'] for e in wa.made('conversation/ensure')] == ['b@test.com']
    assert d == {'success': True, 'whatsapp': False}


# ------------------------------------------------------------------ every owner change made here

def test_adding_a_lead_as_mine_gives_me_the_chat(app, client, wa, cs_user):
    login(client, cs_user.email)
    r = client.post('/cs/crm/add', data={'source': 'call', 'name': 'Asha Rao', 'phone': '9000000077',
                                         'phone_cc': 'IN', 'product': 'TI', 'owner': 'me'})
    assert r.status_code == 302
    ensures = wa.made('conversation/ensure')
    assert [(e[2]['phone'], e[2]['assign_email']) for e in ensures] == [('919000000077', 'cs@test.com')]
    # shared out instead: their contact, but no chat
    client.post('/cs/crm/add', data={'source': 'call', 'name': 'Kiran Rao', 'phone': '9000000078',
                                     'phone_cc': 'IN', 'product': 'TI'})
    assert len(wa.made('conversation/ensure')) == 1 and '919000000078' in wa.contacts


def test_making_a_lead_from_a_record_gives_me_the_chat(app, client, wa, cs_user):
    q = InsuranceQuote(email='kiran@example.com', phone='+919000000001', insurance_type='visitors', citizenship='IND',
                       start_date=date.today() + timedelta(days=20), end_date=date.today() + timedelta(days=80),
                       travellers=[{'age': '66'}])
    _db.session.add(q)
    _db.session.commit()
    login(client, cs_user.email)
    client.post('/cs/crm/add/record', data={'kind': 'insurance_quote', 'id': q.id})
    assert [e[2]['assign_email'] for e in wa.made('conversation/ensure')] == ['cs@test.com']


def test_routing_a_waiting_lead_to_myself_gives_me_the_chat(app, client, wa, cs_user):
    lead = crm.capture('mystery-form', name='Asha Rao', phone='+919000000077', utm={})
    assert lead.pipeline_id is None
    lead.owner_id = None
    _db.session.commit()
    del wa.portal[:]
    login(client, cs_user.email)
    client.post('/cs/crm/lead/%d/route' % lead.id, data={'pipeline': 'ti-standard'})
    assert [e[2]['assign_email'] for e in wa.made('conversation/ensure')] == ['cs@test.com']
    # an unknown page's lead stays General; the pipeline it was routed to gives it a stage tag now
    assert wa.tags('919000000077') == ['GEN: Cold lead', 'gen']


def test_routing_a_source_gives_its_waiting_leads_chats_to_their_owners(app, client, wa, cs_user, admin_user):
    lead = crm.capture('mystery-form', name='Asha Rao', phone='+919000000077', utm={})
    lead.owner_id = None
    _db.session.commit()
    src_id = lead.source_id
    del wa.portal[:]
    login(client, admin_user.email)
    client.post('/admin/crm/setup/source', data={'id': str(src_id), 'name': 'Mystery form', 'kind': 'form',
                                                 'product': 'TI', 'pipeline': 'ti-standard', 'status': 'live',
                                                 'team': str(cs_user.id)})
    _db.session.expire_all()
    lead = _db.session.get(CrmLead, lead.id)
    assert lead.owner_id == cs_user.id and lead.pipeline.key == 'ti-standard'
    assert [e[2]['assign_email'] for e in wa.made('conversation/ensure')] == ['cs@test.com']


def test_making_a_lead_from_the_inbox_gives_the_chat_to_its_owner(app, client, wa, cs_user):
    access.ensure_defaults()
    login(client, cs_user.email)
    client.post('/admin/messaging/lead-panel/make',
                data={'wa_phone': '919000000077', 'name': 'Asha', 'conversation': 'conv-9'})
    lead = CrmLead.query.join(CrmLead.person).filter_by(phone='+919000000077').one()
    assert lead.owner is not None
    assert [e[2]['assign_email'] for e in wa.made('conversation/ensure')] == [lead.owner.email.lower()]


# ============================================================================== tags, name, e-mail, number

def test_tags_cover_every_lead_and_drop_stale_ones(app, wa):
    wa.seed(DIGITS, tags=['vip', 'TC: Posted', 'opted-out'])
    lead = ti_lead()
    crm.move_stage(lead, stage('ti-standard', 'prospect'))
    _db.session.commit()
    sh_lead()
    first_sh = stage('sahayak-visit', 'new').name
    assert wa.tags() == sorted(['vip', 'opted-out', 'ti', 'TI: Prospect', 'sh', 'SH: ' + first_sh])
    # they opt out: the tag goes on, and nothing the portal does takes it off again
    other = ti_lead('+919000000077', name='Asha')
    assert 'opted-out' not in wa.tags('919000000077')
    other.person.wa_opt_out_at = datetime.utcnow()
    crm.mark_wa_due(other.person)
    _db.session.commit()
    assert wa.tags('919000000077') == ['TI: Cold lead', 'opted-out', 'ti']


def test_a_won_lead_keeps_its_stage_tag_until_a_new_enquiry(app, wa):
    lead = ti_lead()
    won = stage('ti-standard', 'customer')
    crm.move_stage(lead, won)
    _db.session.commit()
    assert wa.tags() == sorted(['ti', 'TI: ' + won.name])
    # they ask again: the open lead is where they are now
    again = ti_lead()
    assert again.id != lead.id and wa.tags() == ['TI: Cold lead', 'ti']


def test_undo_and_reopen_put_the_stage_tag_back(app, client, wa, cs_user):
    lead = ti_lead()
    login(client, cs_user.email)
    client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': stage('ti-standard', 'prospect').id})
    assert wa.tags() == ['TI: Prospect', 'ti']
    assert client.post('/cs/crm/lead/%d/undo' % lead.id).get_json()['success']
    assert wa.tags() == ['TI: Cold lead', 'ti']
    lost = stage('ti-standard', 'prospect_fallout')
    client.post('/cs/crm/lead/%d/move' % lead.id, json={'stage_id': lost.id, 'reason': 'No response'})
    assert wa.tags() == sorted(['TI: ' + lost.name, 'ti'])
    assert client.post('/cs/crm/lead/%d/reopen' % lead.id).get_json()['success']
    assert wa.tags() == ['TI: Cold lead', 'ti'] and wa.portal == []


def test_a_repeat_enquiry_brings_the_contact_into_step_again(app, wa):
    lead = ti_lead()
    wa.contacts[DIGITS]['tags'] = []                              # somebody cleared them by hand
    again = ti_lead()
    assert again.id == lead.id and wa.tags() == ['TI: Cold lead', 'ti']


def test_a_sources_tags_go_on_the_contact(app, wa):
    crm.ensure_defaults()
    CrmSource.query.filter_by(key='ti-quote').one().crm_tags = ['diwali']
    _db.session.commit()
    ti_lead()
    assert wa.tags() == sorted(['TI: Cold lead', 'diwali', 'ti'])


def test_tags_compare_ignoring_case_and_keep_hand_made_ones():
    assert crm._wa_tag_list(['TI', 'ti: prospect', 'vip'], {'ti', 'TI: Prospect'}, set()) is None
    assert crm._wa_tag_list(['ti', 'TI: Prospect', 'vip', 'diwali', 'Opted-Out'], {'sh', 'SH: New'}, {'diwali'}) == \
        sorted(['vip', 'Opted-Out', 'sh', 'SH: New'])
    assert crm._wa_tag_list([], set(), set()) is None


def test_removing_a_lead_drops_only_its_product_tags(app, client, wa, admin_user):
    wa.seed(DIGITS, tags=['vip', 'opted-out'])
    ti, sh = ti_lead(), sh_lead()
    ti_id, sh_id, pid = ti.id, sh.id, ti.person_id
    login(client, admin_user.email)
    assert client.post('/admin/crm/lead/%d/remove' % sh_id).get_json()['success']
    assert wa.tags() == sorted(['TI: Cold lead', 'opted-out', 'ti', 'vip'])
    del wa.calls[:]
    client.post('/admin/crm/lead/%d/remove' % ti_id)
    assert wa.calls == [('GET', '/api/v1/contacts/c-1', None),
                        ('PATCH', '/api/v1/contacts/c-1', {'tags': ['opted-out', 'vip']})]
    assert fresh_person(pid) is None and wa.by_id('c-1') is not None          # the contact itself stays


def test_removing_the_last_lead_can_leave_a_contact_with_no_tags(app, client, wa, admin_user):
    lead = ti_lead()
    login(client, admin_user.email)
    client.post('/admin/crm/lead/%d/remove' % lead.id)
    assert wa.patches()[-1] == ('PATCH', '/api/v1/contacts/c-1', {'tags': []})


def test_name_and_email_edits_reach_the_contact(app, client, wa, admin_user):
    wa.seed(DIGITS, name='Ramu')
    lead = ti_lead()
    assert wa.contacts[DIGITS]['name'] == 'Ramesh Kumar'             # the portal is master
    del wa.calls[:]
    login(client, admin_user.email)
    client.post('/admin/crm/lead/%d/update' % lead.id, json={'name': 'Ramesh K', 'email': 'r@example.com'})
    assert wa.patches() == [('PATCH', '/api/v1/contacts/c-1', {'name': 'Ramesh K', 'email': 'r@example.com'})]
    del wa.calls[:]
    crm.mark_wa_due(fresh_person(lead.person_id))
    _db.session.commit()
    assert [c[0] for c in wa.calls] == ['POST']                       # in step already: nothing to change


def test_placeholder_names_never_reach_whatsapp(app, wa):
    wa.seed(DIGITS, name='Ramesh Kumar')
    crm.capture('ti-quote', name='Newsletter subscriber', phone=PHONE, utm={})
    post = [c for c in wa.calls if c[:2] == ('POST', '/api/v1/contacts')][0][2]
    assert 'name' not in post and not [p for p in wa.patches() if 'name' in p[2]]
    assert wa.contacts[DIGITS]['name'] == 'Ramesh Kumar'


def test_a_new_number_relinks_the_contact(app, client, wa, admin_user):
    wa.seed(DIGITS, tags=['vip'])
    lead = ti_lead()
    lead.person.wacrm_conversation_id = 'conv-1'
    _db.session.commit()
    del wa.calls[:]
    login(client, admin_user.email)
    assert client.post('/admin/crm/lead/%d/update' % lead.id, json={'phone': '+14155550123'}).get_json()['success']
    assert wa.calls[:3] == [('GET', '/api/v1/contacts/c-1', None),
                            ('PATCH', '/api/v1/contacts/c-1', {'tags': ['vip']}),
                            ('POST', '/api/v1/contacts', {'phone': '+14155550123', 'name': 'Ramesh Kumar'})]
    assert wa.tags() == ['vip'] and wa.tags('14155550123') == ['TI: Cold lead', 'ti']
    p = fresh_person(lead.person_id)
    assert p.phone == '+14155550123' and p.wacrm_contact_id == 'c-2' and p.wacrm_conversation_id is None


def test_a_contact_changed_in_whatsapp_relinks_and_forgets_the_old_chat(app, wa):
    lead = ti_lead()
    p = lead.person
    p.wacrm_contact_id, p.wacrm_conversation_id = 'c-old', 'conv-old'
    _db.session.commit()
    crm.mark_wa_due(p)
    _db.session.commit()
    p = fresh_person(lead.person_id)
    assert p.wacrm_contact_id == 'c-1' and p.wacrm_conversation_id is None


# ------------------------------------------------------------------ never somebody else's contact

def test_never_take_a_contact_another_person_holds(app, wa):
    b = CrmPerson(phone='+15550001111', wacrm_contact_id='c-1')
    _db.session.add(b)
    _db.session.commit()
    lead = ti_lead()
    p = fresh_person(lead.person_id)
    assert p.wacrm_contact_id is None and p.wa_sync_error == 'Same WhatsApp contact as person %d' % b.id
    assert wa.patches() == [] and wa.portal == [] and p.wacrm_sync_due_at is None   # U1 d: parked


def test_a_contact_with_another_number_is_refused(app, wa):
    wa.answer_phone = '19876543210'
    lead = ti_lead()
    p = fresh_person(lead.person_id)
    assert p.wacrm_contact_id is None and p.wa_sync_error == 'WhatsApp matched a different number, ending 3210'
    assert wa.patches() == []


def test_the_same_number_saved_without_its_country_code_is_theirs(app, wa):
    wa.answer_phone = '9876543210'
    lead = ti_lead()
    p = fresh_person(lead.person_id)
    assert p.wacrm_contact_id == 'c-1' and p.wa_sync_error is None


def test_same_whatsapp_number_rules():
    yes = [('919876543210', '919876543210'), ('370063949836', '37063949836'), ('37063949836', '370063949836'),
           ('919876543210', '9876543210'), ('+91 98765 43210', '919876543210')]
    no = [('919171234567', '19171234567'), ('919876543210', '91987654321'), ('919876543210', '43210'),
          ('919876543210', ''), ('', '919876543210'), ('919876543210', '19876543210'),
          ('919876543210', '0919876543210x1')]
    assert all(crm.same_whatsapp_number(a, b) for a, b in yes)
    assert not any(crm.same_whatsapp_number(a, b) for a, b in no)


# ------------------------------------------------------------------ stage renames, imports

def test_a_renamed_stage_retags_its_people(app, client, wa, admin_user):
    ti_lead()
    won_lead = ti_lead('+919000000077', name='Asha')
    crm.move_stage(won_lead, stage('ti-standard', 'customer'))
    _db.session.commit()
    login(client, admin_user.email)
    cold = stage('ti-standard', 'cold')
    del wa.calls[:]
    client.post('/admin/crm/setup/pipeline', data={'pipeline': 'ti-standard', 'action': 'stage', 'op': 'save',
                                                    'stage_id': cold.id, 'name': 'Fresh lead', 'kind': 'open'})
    assert ('PATCH', '/api/v1/contacts/c-1', {'tags': ['TI: Fresh lead', 'ti']}) in wa.calls
    assert not [c for c in wa.calls if c[1] == '/api/v1/contacts/c-2']       # not in that stage
    # where a finished lead stays: its people follow too
    won = stage('ti-standard', 'customer')
    client.post('/admin/crm/setup/pipeline', data={'pipeline': 'ti-standard', 'action': 'stage', 'op': 'save',
                                                    'stage_id': won.id, 'name': 'Policy sold', 'kind': 'won'})
    assert wa.tags('919000000077') == ['TI: Policy sold', 'ti']
    # saved without a new name: nothing for WhatsApp
    del wa.calls[:]
    client.post('/admin/crm/setup/pipeline', data={'pipeline': 'ti-standard', 'action': 'stage', 'op': 'save',
                                                    'stage_id': cold.id, 'name': 'Fresh lead', 'kind': 'open'})
    assert wa.calls == []


def test_imports_stay_quiet_until_the_backfill(app, wa):
    crm.ensure_defaults()
    quiet = dict(utm={}, plan=False, notify=False, sync=False, imported=True)
    lead = crm.capture('ti-quote', name='Imported One', phone=PHONE, **quiet)
    crm.move_stage(lead, stage('ti-standard', 'prospect'), plan=False, sync=False)
    _db.session.commit()
    crm.capture('ti-quote', name='Closed One', phone='+919000000077', fallout_reason='No response',
                start_stage=stage('ti-standard', 'prospect_fallout'), **quiet)
    crm.capture('ti-quote', name='Mail Only', email='m@example.com', **quiet)
    assert wa.calls == [] and wa.portal == [] and due_people() == []
    assert crm.wa_backfill() == 1                                  # open, with a phone
    assert wa.calls == []                                          # marking is all it does: no burst
    assert crm.run_wa_sync() == {'crm_wa_synced': 1, 'crm_wa_failed': 0, 'crm_wa_waiting': 0}
    assert [c[:2] for c in wa.calls] == [('POST', '/api/v1/contacts'), ('PATCH', '/api/v1/contacts/c-1')]
    assert wa.portal == [] and wa.tags() == ['TI: Prospect', 'ti']
    assert not CrmPerson.query.filter_by(phone=PHONE).one().wacrm_assign_due


def test_the_sales_sheet_import_stays_quiet_until_the_backfill(app, wa, cs_user):
    from app.services import crm_import
    from test_crm_more import workbook
    rows, _, _ = crm_import.read_sheet(workbook())
    crm_import.import_sheet(rows, owner_id=cs_user.id)              # owners too: still nothing for WhatsApp
    assert CrmLead.query.count() == 6
    assert wa.calls == [] and wa.portal == [] and due_people() == []
    open_with_phone = {l.person_id for l in CrmLead.query.filter_by(status='open').all() if l.person.phone}
    assert crm.wa_backfill() == len(open_with_phone) > 0
    out = crm.run_wa_sync()
    assert out['crm_wa_synced'] == len(open_with_phone) and out['crm_wa_waiting'] == 0
    assert wa.portal == []


# ============================================================================== short timeouts, the webhook, the clients

def test_the_sync_uses_short_timeouts(app, client, cs_user, admin_user, monkeypatch):
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'k')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    crm.save_settings(whatsapp_mode='contacts')
    seen = []

    class R:
        status_code = 200

        def __init__(self, url, kw):
            self.url, self.kw = url, kw

        def json(self):
            if self.url.endswith('/api/portal/conversation/ensure'):
                return {'data': {'contact_id': 'c-1', 'conversation_id': 'conv-1', 'assignment': 'assigned',
                                 'assignee_email': self.kw['json']['assign_email']}}
            return {'data': {'id': 'c-1', 'phone': DIGITS, 'tags': []}}

    def fake_request(method, url, **kw):
        seen.append((url.replace('https://crm.example/crm', ''), kw['timeout']))
        return R(url, kw)
    monkeypatch.setattr(requests, 'request', fake_request)
    other = make_user('o@test.com', 'other', role='cs')
    lead = ti_lead()
    login(client, admin_user.email)
    client.post('/admin/crm/lead/%d/update' % lead.id, json={'owner_id': someone_else(lead, other, cs_user).id})
    assert '/api/portal/conversation/ensure' in [u for u, _ in seen]
    assert {t for _, t in seen} == {(3, 6)}
    del seen[:]
    wacrm.me()
    wacrm_team.workspace_info()
    assert [t for _, t in seen] == [(3.05, 10), (3.05, 10)]       # outside the sync: as before


def test_webhook_accepts_the_saved_or_the_env_secret(app, client, monkeypatch):
    crm.save_settings(wacrm_webhook={'secret': 'whsec_saved'})
    monkeypatch.setenv('WACRM_WEBHOOK_SECRET', 'whsec_env')
    for secret, code in (('whsec_saved', 200), ('whsec_env', 200), ('other', 401)):
        assert signed(client, 'ping', {}, secret=secret).status_code == code
    assert wacrm.webhook_secret() == 'whsec_saved' and wacrm.webhook_secrets() == ['whsec_saved', 'whsec_env']
    # five minutes either way, whichever secret signed it
    assert signed(client, 'ping', {}, secret='whsec_env', t=int(time.time()) - 600).status_code == 401
    assert client.post('/api/crm/wacrm-webhook', data=b'{}').status_code == 401
    # only the variable
    crm.save_settings(wacrm_webhook={})
    assert signed(client, 'ping', {}, secret='whsec_env').status_code == 200
    assert wacrm.webhook_secrets() == ['whsec_env']
    # the same one in both places is one secret
    crm.save_settings(wacrm_webhook={'secret': 'whsec_env'})
    assert wacrm.webhook_secrets() == ['whsec_env']
    # neither
    crm.save_settings(wacrm_webhook={})
    monkeypatch.delenv('WACRM_WEBHOOK_SECRET')
    assert signed(client, 'ping', {}, secret='whsec_env').status_code == 401 and wacrm.webhook_secret() == ''


def test_team_client_speaks_contract_v2(app, monkeypatch):
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    got = []

    def fake(method, path, payload=None, params=None):
        got.append((method, path, copy.deepcopy(payload), params))
        if path == 'automations':
            return {'items': [{'id': 'a1', 'name': 'Welcome', 'active': True, 'trigger_type': 'tag_added',
                               'trigger_tags': ['ti'], 'sends': True}]}
        if path == 'quick-replies':
            return {'created': 1, 'updated': 2, 'removed': 3 if 'remove_titles' in payload else 0}
        if path == 'conversations/activity':
            return {'items': [{'conversation_id': 'conv-1'}], 'next_since': '2026-10-15T02:00:00Z'}
        return {'contact_id': 'c-1'}
    monkeypatch.setattr(wacrm_team, '_api', fake)
    assert wacrm_team.ensure_conversation('+91 98765 43210', name='R', create=False, assign_email=' A@X.COM ') == \
        {'contact_id': 'c-1'}
    assert got[-1] == ('POST', 'conversation/ensure', {'phone': DIGITS, 'name': 'R', 'email': None, 'create': False,
                                                       'assign_email': 'a@x.com'}, None)
    wacrm_team.ensure_conversation(DIGITS)
    assert got[-1][2] == {'phone': DIGITS, 'name': None, 'email': None, 'create': True, 'assign_email': None}
    wacrm_team.assign_conversation(None, 'a@x.com', conversation_id='conv-1', only_if_unassigned=True)
    assert got[-1][1:3] == ('conversation/assign', {'conversation_id': 'conv-1', 'email': 'a@x.com',
                                                    'only_if_unassigned': True})
    wacrm_team.assign_conversation(DIGITS, 'a@x.com')               # as before: nothing extra in the body
    assert got[-1][2] == {'phone': DIGITS, 'email': 'a@x.com'}
    out = wacrm_team.activity(datetime(2026, 10, 15, 1, 2, 3, 456), limit=500)
    assert got[-1] == ('GET', 'conversations/activity', None, {'since': '2026-10-15T01:02:03Z', 'limit': 200})
    assert out == {'items': [{'conversation_id': 'conv-1'}], 'next_since': '2026-10-15T02:00:00Z'}
    wacrm_team.activity('2026-10-15T01:02:03Z', limit=0)
    assert got[-1][3] == {'since': '2026-10-15T01:02:03Z', 'limit': 1}
    assert wacrm_team.automations()[0]['sends'] is True and got[-1][:2] == ('GET', 'automations')
    del got[:]
    assert wacrm_team.push_quick_replies([], remove_titles=['Old']) == {'created': 1, 'updated': 2, 'removed': 3, 'conflicts': []}
    assert [g[2] for g in got] == [{'items': [], 'remove_titles': ['Old']}]
    del got[:]
    assert wacrm_team.push_quick_replies([]) == {'created': 0, 'updated': 0, 'removed': 0, 'conflicts': []} and got == []
    items = [{'title': 'T%d' % i, 'text': 'x'} for i in range(250)]
    wacrm_team.push_quick_replies(items, remove_titles=['Old', ''])
    assert [(len(g[2]['items']), g[2].get('remove_titles')) for g in got] == [(200, ['Old']), (50, None)]
    del got[:]
    wacrm_team.push_quick_replies(items)
    assert all('remove_titles' not in g[2] for g in got)


def test_errors_carry_the_http_status(app, monkeypatch):
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'k')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)

    class R:
        def __init__(self, code, body):
            self.status_code, self.body = code, body

        def json(self):
            if self.body is None:
                raise ValueError('html')
            return self.body

    def answer(resp):
        def request(*a, **k):
            if isinstance(resp, Exception):
                raise resp
            return resp
        monkeypatch.setattr(requests, 'request', request)
    for resp, status, code in ((R(409, {'error': {'code': 'ambiguous_contact', 'message': 'm'}}), 409, 'ambiguous_contact'),
                               (R(422, {'error': 'invalid_phone'}), 422, 'invalid_phone'),
                               (R(404, None), 404, None),
                               (requests.ConnectionError('down'), None, None)):
        answer(resp)
        with pytest.raises(wacrm_team.TeamError) as e:
            wacrm_team.ensure_conversation(DIGITS)
        assert (e.value.status, e.value.code) == (status, code)
    for resp, status in ((R(500, {'error': {'message': 'Boom'}}), 500), (R(502, None), 502),
                         (requests.Timeout('slow'), None)):
        answer(resp)
        with pytest.raises(wacrm.WacrmError) as e:
            wacrm.me()
        assert e.value.status == status
    assert wacrm.WacrmError('x').status is None and wacrm_team.TeamError('x').code is None


def test_contact_calls_send_only_what_is_given(app, monkeypatch):
    sent = []
    monkeypatch.setattr(wacrm, '_call', lambda m, p, payload=None, params=None: sent.append((m, p, payload)) or {})
    wacrm.find_or_create_contact(PHONE)
    wacrm.find_or_create_contact(PHONE, name='R', email='r@example.com')
    assert wacrm.update_contact('c-1') is None
    wacrm.update_contact('c-1', tags=[])
    wacrm.update_contact('c-1', name='R')
    assert sent == [('POST', '/api/v1/contacts', {'phone': PHONE}),
                    ('POST', '/api/v1/contacts', {'phone': PHONE, 'name': 'R', 'email': 'r@example.com'}),
                    ('PATCH', '/api/v1/contacts/c-1', {'tags': []}),
                    ('PATCH', '/api/v1/contacts/c-1', {'name': 'R'})]


# ============================================================================== set-up wording

def test_mode_labels_say_what_happens(app, client, wa, admin_user):
    login(client, admin_user.email)
    page = client.post('/admin/crm/setup/whatsapp', data={'action': 'mode', 'mode': 'contacts'},
                       follow_redirects=True).get_data(as_text=True)
    assert 'WhatsApp CRM: Keep leads in step.' in page
    page = client.get('/admin/crm/connection').get_data(as_text=True)
    assert 'Off — nothing goes to WhatsApp' in page
    assert 'Keep leads in step — agents send from the chat' in page
    assert 'Keep leads in step and send — follow-ups also go from here' in page
    assert 'automations that start on a tag will start too' in page
    assert crm.wa_mode() == 'contacts' and not crm.wa_can_send()
    client.post('/admin/crm/setup/whatsapp', data={'action': 'mode', 'mode': 'send'})
    assert crm.wa_can_send()
    client.post('/admin/crm/setup/whatsapp', data={'action': 'mode', 'mode': 'off'})
    assert crm.wa_mode() == 'off' and set(crm.WA_MODES) == {'off', 'contacts', 'send'}


# ============================================================================== the migration

def test_the_new_revision_is_the_only_head_and_adds_the_columns(tmp_path):
    import sqlalchemy as sa
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.script import ScriptDirectory
    mig = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations')
    cfg = Config()
    cfg.set_main_option('script_location', mig)
    script = ScriptDirectory.from_config(cfg)
    assert len(script.get_heads()) == 1          # exactly one head, whatever its name
    assert script.get_revision('r1crm003').down_revision == 'q1ws001'
    spec = importlib.util.spec_from_file_location('r1crm003', os.path.join(mig, 'versions', 'r1crm003_whatsapp_sync.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    engine = sa.create_engine('sqlite:///' + str(tmp_path / 'm.db').replace(os.sep, '/'))
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE crm_people (id INTEGER PRIMARY KEY, phone VARCHAR(32))')
        conn.exec_driver_sql("INSERT INTO crm_people (phone) VALUES ('+919876543210')")
        with Operations.context(MigrationContext.configure(conn)):
            mod.upgrade()
        assert FIVE <= {c['name'] for c in sa.inspect(conn).get_columns('crm_people')}
        assert 'ix_crm_people_wacrm_sync_due_at' in {i['name'] for i in sa.inspect(conn).get_indexes('crm_people')}
        conn.exec_driver_sql("INSERT INTO crm_people (phone) VALUES ('+919000000077')")
        assert [r[0] for r in conn.exec_driver_sql('SELECT wacrm_assign_due FROM crm_people ORDER BY id')] == [0, 0]
        with Operations.context(MigrationContext.configure(conn)):
            mod.downgrade()
        cols = {c['name'] for c in sa.inspect(conn).get_columns('crm_people')}
        assert not FIVE & cols and {'id', 'phone'} <= cols
        assert conn.exec_driver_sql('SELECT count(*) FROM crm_people').scalar() == 2      # the rows survive
    assert FIVE <= set(CrmPerson.__table__.columns.keys())
    assert 'ix_crm_people_wacrm_sync_due_at' in {i.name for i in CrmPerson.__table__.indexes}


# ============================================================================== U1: the P1 review issues, closed

def test_an_imported_lead_that_ages_out_makes_no_whatsapp_call_until_the_backfill(app, wa):
    """Review issue 2: the automatic no-reply move must not drag imported people into WhatsApp."""
    crm.ensure_defaults()
    lead = crm.capture('ti-quote', name='Imported Old', phone=PHONE, utm={}, plan=False, notify=False, sync=False,
                       imported=True, when=datetime.utcnow() - timedelta(days=40))
    crm.move_stage(lead, stage('ti-standard', 'prospect'), plan=False, sync=False)
    lead.entered_stage_at = datetime.utcnow() - timedelta(days=40)
    _db.session.commit()
    assert crm.run_stage_automations()['crm_auto_moved'] == 1
    assert _db.session.get(CrmLead, lead.id).stage.key == 'prospect_fallout'
    assert wa.calls == [] and wa.portal == [] and due_people() == []
    # a person already in the WhatsApp CRM is kept in step as before
    other = crm.capture('ti-quote', name='Known', phone='+919000000042', utm={}, plan=False, notify=False, sync=False,
                        imported=True)
    other.person.wacrm_contact_id = 'c-known'
    crm.move_stage(other, stage('ti-standard', 'prospect'), plan=False, sync=False)
    other.entered_stage_at = datetime.utcnow() - timedelta(days=40)
    _db.session.commit()
    assert crm.run_stage_automations()['crm_auto_moved'] == 1
    assert wa.calls != []                       # it is in WhatsApp already: kept in step, no hold-back


def test_a_conversation_id_the_portal_already_knew_survives_the_first_sync(app, wa):
    """Review issue 3: someone with no contact id but a known chat keeps that chat."""
    crm.ensure_defaults()
    lead = crm.capture('ti-quote', name='Ramesh Kumar', phone=PHONE, utm={}, sync=False)
    lead.person.wacrm_conversation_id = 'conv-known'
    _db.session.commit()
    crm.mark_wa_due(lead.person)
    _db.session.commit()
    p = fresh_person(lead.person_id)
    assert p.wacrm_contact_id == 'c-1' and p.wacrm_conversation_id == 'conv-known'


def test_making_a_lead_from_the_inbox_hands_the_chat_over_only_when_the_owner_was_set_there(app, client, wa, cs_user, admin_user):
    """Review issue 4: a source that routed the lead to somebody keeps the chat with the agent chatting."""
    from app.models import CrmSource
    crm.ensure_defaults()
    src = CrmSource.query.filter_by(key='wa-india').first()
    routed = make_user('routed@test.com', 'routed', role='cs')
    if src is not None:
        src.team = [routed.id]
        _db.session.commit()
    login(client, cs_user.email)
    access.ensure_defaults()
    client.post('/admin/messaging/lead-panel/make', data={'wa_phone': '919333333333', 'name': 'New One',
                                                           'conversation': 'conv-33'})
    lead = CrmLead.query.filter_by(source_id=src.id).first() if src is not None else CrmLead.query.first()
    assert lead is not None
    ensures = wa.made('conversation/ensure')
    if lead.owner_id == cs_user.id:
        assert ensures and ensures[-1][2]['assign_email'] == cs_user.email         # took it: the chat comes along
    else:
        assert all(e[2].get('assign_email') != cs_user.email for e in ensures)       # routed elsewhere: not forced


def test_a_whatsapp_reassignment_changes_the_lead_that_holds_the_chat(app, client, wa, cs_user, admin_user, monkeypatch):
    monkeypatch.setenv('WACRM_WEBHOOK_SECRET', 'whsec_test')
    """Review issue 9: one owner per person -- the same lead the portal pushes is the one WhatsApp changes."""
    ti, sh = ti_lead(), sh_lead()
    ti.owner_id = admin_user.id
    sh.owner_id = admin_user.id
    sh.last_activity_at = datetime.utcnow() + timedelta(minutes=5)
    _db.session.commit()
    main = crm._wa_main_lead(fresh_person(ti.person_id))
    assert main.id == sh.id
    signed(client, 'conversation.assigned', {'contact_id': 'c-1', 'contact_phone': DIGITS, 'conversation_id': 'conv-c-1',
                                             'assignee_email': cs_user.email, 'origin': 'inbox'})
    _db.session.expire_all()
    assert _db.session.get(CrmLead, sh.id).owner_id == cs_user.id
    assert _db.session.get(CrmLead, ti.id).owner_id == admin_user.id


def test_same_whatsapp_number_follows_w1s_table():
    yes = [('919876543210', '00919876543210'), ('919876543210', '0919876543210'),
           ('37063949836', '370063949836'),                  # trunk 0 after a 3 digit country code
           ('5215512345678', '525512345678'), ('525512345678', '5215512345678'),         # Mexico 52 1
           ('5491155551234', '541155551234'),                                             # Argentina 54 9
           ('5511987654321', '551187654321'),                                             # Brazil 55 + area + 9
           ('919876543210', '9876543210'), ('14155550123', '4155550123')]
    no = [('919876543210', '918876543210'),                 # a different number
          ('442071234567', '912071234567'),                 # same last digits, two countries
          ('5511587654321', '551187654321'),                # Brazil: the extra digit must be 6-9
          ('9876543210', '919876543210'),                   # only THEIR side may lack the country code
          ('919876543210', '987654321'),                    # 9 digits of theirs that are not a local form
          ('12345', '12345678')]
    assert all(crm.same_whatsapp_number(a, b) for a, b in yes), [p for p in yes if not crm.same_whatsapp_number(*p)]
    assert not any(crm.same_whatsapp_number(a, b) for a, b in no), [p for p in no if crm.same_whatsapp_number(*p)]


def test_a_thread_that_cannot_start_leaves_the_save_done_and_the_mark_for_the_jobs_runner(app, wa, monkeypatch):
    """Review issue 7: 'can't start new thread' must never turn a saved enquiry into a 500."""
    app.config['WA_SYNC_INLINE'] = False

    class NoThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")
    monkeypatch.setattr(crm, 'threading', SimpleNamespace(Thread=NoThread))
    lead = ti_lead()                                               # the commit inside must not raise
    assert lead is not None and CrmLead.query.count() == 1
    assert fresh_person(lead.person_id).wacrm_sync_due_at is not None and wa.calls == []
    assert crm.run_wa_sync()['crm_wa_synced'] == 1




def test_tags_a_source_stops_adding_are_taken_off_and_remembered(app, client, wa, admin_user):
    """Review issue 8: removed source tags are retired, not left on contacts for good."""
    crm.ensure_defaults()
    src = CrmSource.query.filter_by(key='ti-quote').one()
    src.crm_tags = ['diwali', 'vip-deal']
    _db.session.commit()
    ti_lead()
    assert wa.tags() == sorted(['TI: Cold lead', 'diwali', 'vip-deal', 'ti'])
    wa.contacts[DIGITS]['tags'].append({'name': 'hand-made'})
    login(client, admin_user.email)
    form = {'id': src.id, 'name': src.name, 'kind': src.kind, 'product': src.product,
            'pipeline': src.pipeline.key if src.pipeline else "", 'status': 'live', 'crm_tags': 'diwali'}
    assert client.post('/admin/crm/setup/source', data=form).status_code == 302
    raw = crm.crm_settings_raw()
    assert raw[crm.WA_RETIRED_TAGS_KEY] == ['vip-deal']
    assert due_people() != []                                      # marked (quietly) for the jobs runner
    crm.run_wa_sync()
    assert wa.tags() == sorted(['TI: Cold lead', 'diwali', 'ti', 'hand-made'])     # hand-made stays, retired goes


def test_retired_tags_are_capped_ordered_and_never_the_opt_out_or_a_live_tag(app):
    crm.ensure_defaults()
    CrmSource.query.filter_by(key='ti-quote').one().crm_tags = ['live-one']
    _db.session.commit()
    out = crm.wa_retire_tags(['Opted-Out', 'live-one', 'gone-a'])
    assert out == ['gone-a']
    out = crm.wa_retire_tags(['gone-b'])
    assert out[0] == 'gone-b' and 'gone-a' in out
    crm.wa_retire_tags(['n%03d' % i for i in range(300)])
    assert len(crm.crm_settings_raw()[crm.WA_RETIRED_TAGS_KEY]) == crm.WA_RETIRED_MAX == 200
    # a tag put back leaves the list
    CrmSource.query.filter_by(key='ti-quote').one().crm_tags = ['n001']
    _db.session.commit()
    assert 'n001' not in crm.wa_retire_tags([])
    assert crm._wa_is_portal_tag('gone-b', crm._wa_source_tags()) in (True, False)
    assert crm._wa_is_portal_tag('opted-out', crm._wa_source_tags()) is False


def test_the_opted_out_tag_is_never_taken_off_by_the_sync_but_an_admin_opt_in_removes_it_once(app, client, wa, admin_user):
    lead = ti_lead()
    pid = lead.person_id
    crm.wa_opt_out(fresh_person(pid), lead)
    _db.session.commit()
    assert 'opted-out' in wa.tags()
    # the sync alone never removes it (somebody may have put it there by hand)
    p = fresh_person(pid)
    p.wa_opt_out_at = None
    p.wa_opt_in_due = False
    crm.mark_wa_due(p)
    _db.session.commit()
    assert 'opted-out' in wa.tags()
    # an admin opts them back in: the tag goes, once
    p = fresh_person(pid)
    p.wa_opt_out_at = datetime.utcnow()
    _db.session.commit()
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/opt-in' % lead.id)
    assert r.status_code in (200, 302)
    assert 'opted-out' not in wa.tags() and fresh_person(pid).wa_opt_in_due in (False, None)
    assert fresh_person(pid).wa_opt_out_at is None
    notes = [t.body for t in CrmTouchpoint.query.filter_by(person_id=pid, channel='note')]
    assert any('Opted back in to WhatsApp' in (n or '') for n in notes)


def test_a_refusal_parks_until_the_next_mark_but_a_500_keeps_its_backoff(app, wa):
    """Review issue 5."""
    wa.fail_for[DIGITS] = wacrm.WacrmError('Bad number', status=422, code='invalid_phone')
    lead = ti_lead()
    p = fresh_person(lead.person_id)
    assert p.wa_sync_error and p.wacrm_sync_due_at is None
    assert crm.run_wa_sync(now=datetime.utcnow() + timedelta(days=2))['crm_wa_synced'] == 0       # no hourly retry
    wa.fail_for[DIGITS] = wacrm.WacrmError('Boom', status=500)
    crm.mark_wa_due(p)
    _db.session.commit()
    p = fresh_person(lead.person_id)
    assert p.wa_sync_error == 'Boom' and p.wacrm_sync_due_at > datetime.utcnow() + timedelta(minutes=50)
    wa.fail_for.clear()
    assert crm.run_wa_sync(now=datetime.utcnow() + timedelta(hours=2))['crm_wa_synced'] == 1
