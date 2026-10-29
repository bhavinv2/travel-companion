"""Set-up › Channels (2026-10-29): a WhatsApp number the portal talks to Meta for itself, beside the WhatsApp CRM.

    the number      saved with its token and app secret sealed (never shown again), its own lead source; "Check with
                    Meta" reads it, "Connect" makes Meta send its account here (per-account callback) and lists its
                    templates
    Meta's webhook  checks the verify token; refuses anything unsigned; a message from somebody new is a lead under
                    the number's source; once only; a status moves the message on; a failure says why
    which number    the one they last wrote to; somebody who never wrote, by the number's prefixes; the WhatsApp CRM's
                    otherwise -- and the 24 hours are per number
    answering       the lead page's box sends through Meta on their number: free text inside its 24 hours, its own
                    approved templates otherwise; nothing while the number is paused
    copying         our follow-ups' templates go to the number's account for Meta to approve
"""
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmChannelLine, CrmLead, CrmPerson, CrmSource, CrmTouchpoint
from app.services import access, channels, crm, secretbox, wa_meta

PNID, WABA = '1416384351564275', '3450029945177107'
TOKEN = 'EAAG' + 'x' * 60
APP_SECRET = 'appsecret0123456789abcdef'
HOOK = '/api/whatsapp/lines-webhook'


class FakeMeta:
    """Meta's Graph API, in memory: what was asked, and what it answers."""

    def __init__(self):
        self.calls, self.sent, self.submitted = [], [], []
        self.templates = [{'name': 'hello_world', 'status': 'APPROVED', 'category': 'UTILITY', 'language': 'en_US',
                           'components': [{'type': 'BODY', 'text': 'Hello World'}]},
                          {'name': 'nri_ti_1', 'status': 'APPROVED', 'category': 'UTILITY', 'language': 'en',
                           'components': [{'type': 'BODY', 'text': 'Hi {{1}}, {{2}} here.'}]}]
        self.fail = None
        self.number_status = 'CONNECTED'

    def request(self, method, url, json=None, params=None, timeout=None, headers=None):
        path = url.split('/v21.0', 1)[1].split('?')[0]
        self.calls.append((method, path, json))
        assert headers['Authorization'] == 'Bearer ' + TOKEN
        if self.fail is not None:
            return Resp(400, {'error': self.fail})
        if method == 'GET' and path == '/' + PNID:
            return Resp(200, {'display_phone_number': '+1 917-900-5094', 'verified_name': 'NRI Parent Service',
                              'quality_rating': 'GREEN', 'status': self.number_status, 'id': PNID})
        if method == 'GET' and path == '/%s/phone_numbers' % WABA:
            return Resp(200, {'data': [{'id': PNID, 'display_phone_number': '+1 917-900-5094'}]})
        if path == '/%s/subscribed_apps' % WABA:
            return Resp(200, {'success': True})
        if method == 'GET' and path == '/%s/message_templates' % WABA:
            return Resp(200, {'data': self.templates})
        if method == 'POST' and path == '/%s/message_templates' % WABA:
            self.submitted.append(json)
            return Resp(200, {'id': 't%d' % len(self.submitted), 'status': 'PENDING'})
        if method == 'POST' and path == '/%s/messages' % PNID:
            self.sent.append(json)
            return Resp(200, {'messages': [{'id': 'wamid.us%d' % len(self.sent)}]})
        return Resp(404, {'error': {'message': 'unknown', 'code': 100}})


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


@pytest.fixture
def meta(app, monkeypatch):
    m = FakeMeta()
    monkeypatch.setattr(wa_meta.requests, 'request', m.request)
    crm.ensure_defaults()
    return m


def make_line(status='live', prefixes=('+1',), templates=True):
    line = CrmChannelLine(key='usa', label='USA', provider='meta', phone='+19179005094', phone_number_id=PNID,
                          waba_id=WABA, verify_token='nps-verify-123', prefixes=list(prefixes), status=status,
                          connected_at=datetime.utcnow() if status != 'new' else None)
    channels.set_secrets(line, token=TOKEN, app_secret=APP_SECRET)
    _db.session.add(line)
    _db.session.flush()
    channels.ensure_source(line)
    if templates:
        line.templates = [wa_meta._template_row(t) for t in FakeMeta().templates]
        line.templates_at = datetime.utcnow()
    _db.session.commit()
    return line


def signed(client, body, secret=APP_SECRET):
    raw = json.dumps(body).encode()
    sig = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(HOOK, data=raw, content_type='application/json', headers={'X-Hub-Signature-256': sig})


def inbound(text='Hi, cover for my mother?', sender='19175550199', wamid='wamid.in1', name='Ravi Kumar', ts=None):
    return {'object': 'whatsapp_business_account', 'entry': [{'id': WABA, 'changes': [{'field': 'messages', 'value': {
        'messaging_product': 'whatsapp', 'metadata': {'display_phone_number': '19179005094', 'phone_number_id': PNID},
        'contacts': [{'profile': {'name': name}, 'wa_id': sender}],
        'messages': [{'from': sender, 'id': wamid, 'timestamp': str(ts or int(time.time())),
                      'type': 'text', 'text': {'body': text}}]}}]}]}


def status(wamid, state, code=None, title=None):
    st = {'id': wamid, 'status': state, 'timestamp': str(int(time.time())), 'recipient_id': '1'}
    if code:
        st['errors'] = [{'code': code, 'title': title or 'Re-engagement message'}]
    return {'object': 'whatsapp_business_account', 'entry': [{'id': WABA, 'changes': [{'field': 'messages', 'value': {
        'messaging_product': 'whatsapp', 'metadata': {'phone_number_id': PNID}, 'statuses': [st]}}]}]}


# ============================================================================================== the number

def test_secrets_are_sealed_and_unreadable_under_another_key(app):
    sealed = secretbox.seal({'token': TOKEN})
    assert TOKEN not in sealed and secretbox.open(sealed) == {'token': TOKEN}
    app.config['SECRET_KEY'] = 'another-key'
    assert secretbox.open(sealed) is None


def test_an_admin_adds_checks_and_connects_a_number(app, client, admin_user, meta):
    login(client, admin_user.email)
    r = client.post('/admin/crm/channels/new', data={
        'label': 'USA', 'phone_number_id': PNID, 'waba_id': WABA, 'token': TOKEN, 'app_secret': APP_SECRET,
        'prefixes': '+1', 'also_tawk': 'on'})
    assert r.status_code == 302
    line = CrmChannelLine.query.one()
    assert line.status == 'new' and line.prefixes == ['+1'] and line.also_on == ['tawk']
    assert TOKEN not in (line.secrets or '') and channels.secrets_of(line) == {'token': TOKEN, 'app_secret': APP_SECRET}
    assert CrmSource.query.filter_by(key='wa-usa').one().name == 'USA number · chat'      # the built-in one, kept
    page = client.get('/admin/crm/channels/%d?tab=connect' % line.id).get_data(as_text=True)
    assert TOKEN not in page and APP_SECRET not in page and 'Saved. Paste a new one to replace it' in page

    client.post('/admin/crm/channels/%d/do' % line.id, data={'action': 'check', 'tab': 'connect'})
    assert CrmChannelLine.query.one().phone == '+19179005094'
    client.post('/admin/crm/channels/%d/do' % line.id, data={'action': 'connect', 'tab': 'connect'})
    line = CrmChannelLine.query.one()
    assert line.status == 'live' and line.connected_at is not None
    sub = [c for c in meta.calls if c[1] == '/%s/subscribed_apps' % WABA and c[0] == 'POST'][0][2]
    assert sub['override_callback_uri'].endswith(HOOK) and sub['verify_token'] == line.verify_token
    assert {t['name'] for t in line.templates} == {'hello_world', 'nri_ti_1'}
    listing = client.get('/admin/crm/channels').get_data(as_text=True)
    assert 'USA' in listing and 'Meta direct' in listing and 'tawk.to' in listing and 'Live' in listing


def test_the_ids_must_belong_together(app, client, admin_user, meta):
    line = make_line(status='new')
    line.phone_number_id = '999999999'
    _db.session.commit()
    login(client, admin_user.email)
    r = client.post('/admin/crm/channels/%d/do' % line.id, data={'action': 'connect'}, follow_redirects=True)
    assert 'Meta said' in r.get_data(as_text=True)
    meta.fail = None
    assert CrmChannelLine.query.one().status == 'error'


def test_an_unfinished_copy_of_the_number_is_not_connected(app, client, admin_user, meta):
    """Meta keeps pending copies of a number beside the live one (29 Oct: two under other accounts); Connect stops there,
    before asking Meta for anything else."""
    meta.number_status = 'PENDING'
    line = make_line(status='new')
    login(client, admin_user.email)
    page = client.post('/admin/crm/channels/%d/do' % line.id, data={'action': 'connect'},
                       follow_redirects=True).get_data(as_text=True)
    assert 'as pending' in page and 'shows Connected' in page
    assert CrmChannelLine.query.one().status == 'error'
    assert not [c for c in meta.calls if c[1].endswith('/subscribed_apps')]


def test_only_a_role_with_the_page_opens_it(app, client, meta):
    access.ensure_defaults()
    agent = make_user('agent@test.com', 'agent', role='cs')
    access.add_member(access.default_workspace(), agent, role=access.system_role(access.default_workspace(), 'cs'))
    login(client, agent.email)
    assert client.get('/cs/crm/channels').status_code == 302


# ============================================================================================ Meta's webhook

def test_meta_checks_the_address_with_a_verify_token(app, client, meta):
    make_line()
    ok = client.get(HOOK + '?hub.mode=subscribe&hub.verify_token=nps-verify-123&hub.challenge=42')
    assert ok.status_code == 200 and ok.get_data(as_text=True) == '42'
    assert client.get(HOOK + '?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=42').status_code == 403


def test_an_unsigned_delivery_is_refused(app, client, meta):
    make_line()
    assert client.post(HOOK, json=inbound()).status_code == 401
    assert signed(client, inbound(), secret='not-the-secret-000000').status_code == 401
    assert CrmTouchpoint.query.count() == 0


def test_somebody_new_becomes_a_lead_on_the_number_once(app, client, meta):
    line = make_line()
    r = signed(client, inbound())
    assert r.status_code == 200 and r.get_json()['messages'] == 1
    lead = CrmLead.query.one()
    assert lead.source.key == 'wa-usa' and lead.person.phone == '+19175550199' and lead.person.name == 'Ravi Kumar'
    tp = CrmTouchpoint.query.filter_by(external_id='wamid.in1').one()
    assert tp.line_id == line.id and tp.channel == 'whatsapp' and tp.direction == 'in'
    assert lead.person.wa_line_id == line.id and lead.person.wacrm_sync_due_at is None   # nothing for the WhatsApp CRM
    signed(client, inbound())
    assert CrmTouchpoint.query.filter_by(external_id='wamid.in1').count() == 1
    assert CrmChannelLine.query.one().last_in_at is not None


def test_a_status_moves_the_message_on_and_a_failure_says_why(app, client, meta):
    make_line()
    signed(client, inbound())
    lead = CrmLead.query.one()
    crm.log_touch(lead, 'whatsapp', 'out', body='Hello', status='sent', external_id='wamid.out1')
    _db.session.commit()
    signed(client, status('wamid.out1', 'delivered'))
    assert CrmTouchpoint.query.filter_by(external_id='wamid.out1').one().status == 'delivered'
    signed(client, status('wamid.out1', 'failed', code=131047))
    tp = CrmTouchpoint.query.filter_by(external_id='wamid.out1').one()
    assert tp.status == 'failed' and '24 hours' in (tp.fail_reason or '')


def test_a_message_sent_from_the_business_app_shows_on_the_lead(app, client, meta):
    line = make_line()
    signed(client, inbound())
    echo = {'object': 'whatsapp_business_account', 'entry': [{'id': WABA, 'changes': [{'field': 'smb_message_echoes',
            'value': {'metadata': {'phone_number_id': PNID}, 'message_echoes': [
                {'from': '19179005094', 'to': '19175550199', 'id': 'wamid.echo1', 'timestamp': '1761700000',
                 'type': 'text', 'text': {'body': 'Sure, calling you now'}}]}}]}]}
    assert signed(client, echo).get_json()['echoes'] == 1
    tp = CrmTouchpoint.query.filter_by(external_id='wamid.echo1').one()
    assert tp.direction == 'out' and tp.line_id == line.id and 'WhatsApp Business app' in tp.body


# ============================================================================================ which number

def test_the_number_they_last_wrote_to_else_the_prefix(app, client, meta):
    line = make_line()
    us = crm.capture('ti-quote', name='Anna', phone='+14155550142', utm={})
    india = crm.capture('ti-quote', name='Ramesh', phone='+919876543210', utm={})
    _db.session.commit()
    assert channels.line_for(us.person) == line                 # never wrote: +1 goes out on the US number
    assert channels.line_for(india.person) is None              # the WhatsApp CRM's
    crm.record_whatsapp_in(phone='14155550142', wamid='wamid.crm1', text='hello')     # they wrote on the CRM's number
    assert channels.line_for(_db.session.get(CrmPerson, us.person_id)) is None
    line.status = 'paused'
    _db.session.commit()
    signed(client, inbound(sender='919876543210', wamid='wamid.in9'))                 # wrote to the US number
    assert channels.line_for(_db.session.get(CrmPerson, india.person_id)) == line


def test_the_24_hours_are_per_number(app, client, meta):
    line = make_line()
    signed(client, inbound())
    lead = CrmLead.query.one()
    assert crm.whatsapp_window_open(lead, line=line) is True
    assert crm.whatsapp_window_open(lead, line=None) is False          # nothing on the WhatsApp CRM's number


# =============================================================================================== answering

def test_the_lead_page_answers_through_meta_on_their_number(app, client, admin_user, meta):
    line = make_line()
    signed(client, inbound())
    lead = CrmLead.query.one()
    login(client, admin_user.email)
    page = client.get('/admin/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'USA · +1' in page and 'WhatsApp · USA' in page
    r = client.post('/admin/crm/lead/%d/message' % lead.id, json={'kind': 'text', 'text': 'Happy to help'})
    assert r.get_json().get('success') or r.get_json().get('mode') == 'sent', r.get_json()
    assert meta.sent[-1]['to'] == '19175550199' and meta.sent[-1]['text']['body'] == 'Happy to help'
    out = CrmTouchpoint.query.filter_by(external_id='wamid.us1').one()
    assert out.direction == 'out' and out.line_id == line.id and out.agent_id == admin_user.id
    r = client.post('/admin/crm/lead/%d/message' % lead.id,
                    json={'kind': 'template', 'template': 'nri_ti_1', 'params': ['Ravi', 'Asha']})
    assert meta.sent[-1]['template'] == {'name': 'nri_ti_1', 'language': {'code': 'en'}, 'components': [
        {'type': 'body', 'parameters': [{'type': 'text', 'text': 'Ravi'}, {'type': 'text', 'text': 'Asha'}]}]}
    assert CrmTouchpoint.query.filter_by(external_id='wamid.us2').one().body == 'Hi Ravi, Asha here.'


def test_free_text_waits_for_their_24_hours_on_that_number(app, client, admin_user, meta):
    make_line()
    signed(client, inbound(ts=int(time.time() - 30 * 3600)))
    lead = CrmLead.query.one()
    for tp in CrmTouchpoint.query.all():
        tp.created_at = datetime.utcnow() - timedelta(hours=30)
    _db.session.commit()
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/message' % lead.id, json={'kind': 'text', 'text': 'Hello?'})
    assert r.get_json().get('mode') == 'window_closed' or 'template' in json.dumps(r.get_json()).lower()
    assert meta.sent == []


def test_nothing_goes_out_while_the_number_is_paused(app, client, admin_user, meta):
    make_line(status='paused')
    signed(client, inbound())
    lead = CrmLead.query.one()
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/message' % lead.id, json={'kind': 'text', 'text': 'Hi'})
    assert 'not sending right now' in json.dumps(r.get_json()) and meta.sent == []


def test_a_follow_up_runs_on_the_number_with_its_own_template(app, client, meta):
    line = make_line()
    signed(client, inbound())
    lead = CrmLead.query.one()
    plan = crm.send_plan(lead)
    assert plan['mode'] in ('text', 'link', 'template')
    assert crm.box_templates(lead)['line'].startswith('USA')
    assert [i['name'] for i in crm.box_templates(lead)['items']] and line.status == 'live'


# ================================================================================================ copying

def test_our_follow_up_templates_go_to_the_number_for_approval(app, client, admin_user, meta):
    from app.models import CrmPlaybookStep
    line = make_line(templates=False)
    meta.templates = [meta.templates[0]]
    steps = CrmPlaybookStep.query.filter(CrmPlaybookStep.channel == 'whatsapp', CrmPlaybookStep.body.isnot(None)).all()
    assert steps
    login(client, admin_user.email)
    client.post('/admin/crm/channels/%d/do' % line.id, data={'action': 'copy', 'tab': 'templates'})
    assert meta.submitted, 'nothing was sent to Meta'
    first = meta.submitted[0]
    assert first['language'] == 'en' and first['components'][0]['type'] == 'BODY'
    names = {s['name'] for s in meta.submitted}
    assert len(names) == len(meta.submitted)                              # each once
    client.post('/admin/crm/channels/%d/do' % line.id, data={'action': 'copy', 'tab': 'templates'})


def test_numbers_and_who_answers_lists_every_system(app, client, admin_user, meta):
    make_line()
    login(client, admin_user.email)
    page = client.get('/admin/crm/channels').get_data(as_text=True)
    for words in ('Numbers &amp; who answers', 'WhatsApp CRM number', 'Website chat bubble', 'What each provider can do',
                  'Replies from the portal'):
        assert words in page, words


def test_the_jobs_runner_keeps_templates_fresh_and_sends_follow_ups_on_the_number(app, client, meta):
    """Approvals show up by themselves (once an hour), and a live number sends its people's automatic steps even
    while the WhatsApp CRM's switch is off -- whose steps keep waiting, untouched."""
    line = make_line()
    line.templates_at = datetime.utcnow() - timedelta(hours=2)
    _db.session.commit()
    assert channels.refresh_due()['wa_lines_templates'] == 1
    assert channels.refresh_due()['wa_lines_templates'] == 0                    # within the hour: not asked again
    crm.save_settings(whatsapp_mode='off')
    india = crm.capture('ti-quote', name='Ramesh', phone='+919876543210', utm={})
    _db.session.commit()
    before = [(t.id, t.status, t.note) for t in india.tasks]
    crm.run_auto_steps()
    assert [(t.id, t.status, t.note) for t in _db.session.get(CrmLead, india.id).tasks] == before
