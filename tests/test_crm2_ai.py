"""Sales CRM 2.0, run 5b -- AI help on the lead page ("Summarise").

    switch     off by default; it needs BOTH the setting (Automation > Overview, "AI on the lead page", with its note)
               and the server's ANTHROPIC_API_KEY
    summarise  3-5 lines and a suggested next message, only for the message box; nothing is sent
    privacy    phone numbers and e-mail addresses never leave: they are taken out of what is sent
    cache      kept on the lead until a newer message or note arrives
    errors     any failure says "AI is not available right now"
    the call   one POST to the Messages API (model, headers, a 20 s timeout) -- replaced in every test: no network
"""
import re

import pytest

from conftest import login, make_user
from app import db as _db
from app.models import CrmLead, CrmTouchpoint
from app.services import crm, crm_ai

from test_crm_wa_sync_engine import ti_lead

ANSWER = ('{"summary": ["Wants cover for her parents in Dallas.", "Asked about the price twice.", '
          '"Travels on 3 Nov."], "next_message": "Hi Meera, the quote for your parents is ready. Shall I send it?"}')


def words(html):
    import html as _html
    return _html.unescape(re.sub(r'\s+', ' ', re.sub(r'<script.*?</script>|<[^>]+>', ' ', html, flags=re.S)))


@pytest.fixture
def ai_on(app, monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-key')
    crm_ai.switch(True)
    sent = []

    def fake(system, text):
        sent.append(text)
        return ANSWER
    monkeypatch.setattr(crm_ai, 'call_claude', fake)
    return sent


@pytest.fixture
def lead(app):
    crm.ensure_defaults()
    l = ti_lead(phone='+919812345678', name='Meera Rao', email='meera.rao@example.com')
    crm.record_reply(l, 'My number is +91 98123 45678, or mail meera.rao@example.com. Also call 001-214-555-0100.')
    crm.log_touch(l, 'note', 'none', body='Her son Ravi (ravi@example.org) pays.')
    _db.session.commit()
    return l


def test_it_is_off_by_default(app, client, admin_user, lead, monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    login(client, admin_user.email)
    page = client.get('/admin/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'data-ai' not in page and 'crm-ai.js' not in page
    r = client.post('/admin/crm/lead/%d/ai' % lead.id, json={})
    assert r.status_code == 503 and r.get_json()['error'] == 'AI is not available right now'
    # the setting alone is not enough, nor the key alone
    crm_ai.switch(True)
    assert crm_ai.enabled() is False
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'k')
    crm_ai.switch(False)
    assert crm_ai.enabled() is False


def test_the_switch_and_its_note_on_automation(app, client, admin_user, monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    login(client, admin_user.email)
    page = words(client.get('/admin/crm/automatic').get_data(as_text=True))
    assert 'AI on the lead page' in page and crm_ai.NOTE in page and 'Switch on' in page
    r = client.post('/admin/crm/automatic/ai', data={'on': '1'}, follow_redirects=True)
    assert crm_ai.switched_on() is True and 'no Anthropic key' in words(r.get_data(as_text=True))
    agent = make_user('ag@test.com', 'ag', role='cs')
    client.post('/auth/logout')
    from flask import g
    g.pop('_login_user', None)
    login(client, agent.email)
    client.post('/cs/crm/automatic/ai', data={'on': '0'})
    assert crm_ai.switched_on() is True                               # set-up only


def test_summarise_fills_nothing_but_the_page_and_sends_nothing(app, client, admin_user, lead, ai_on):
    login(client, admin_user.email)
    page = client.get('/admin/crm/lead/%d' % lead.id).get_data(as_text=True)
    assert 'data-ai' in page and 'Summarise' in page and 'crm-ai.js' in page
    before = CrmTouchpoint.query.count()
    r = client.post('/admin/crm/lead/%d/ai' % lead.id, json={})
    d = r.get_json()
    assert r.status_code == 200 and d['summary'][0] == 'Wants cover for her parents in Dallas.' and len(d['summary']) == 3
    assert d['next'].startswith('Hi Meera') and d['cached'] is False
    assert CrmTouchpoint.query.count() == before                    # nothing was sent or logged on the lead
    # the suggestion goes into the message box through the quotes card's own button (crm-quotes.js)
    js = open('app/static/js/crm-ai.js', encoding='utf-8').read()
    assert 'data-qp-box' in js and 'fetch(' not in js.replace('window.CRM.post', '')


def test_phone_numbers_and_e_mails_are_never_sent(app, client, admin_user, lead, ai_on):
    login(client, admin_user.email)
    client.post('/admin/crm/lead/%d/ai' % lead.id, json={})
    text = ai_on[0]
    for secret in ('98123', '45678', 'meera.rao@example.com', 'ravi@example.org', '555-0100', '+91'):
        assert secret not in text, secret
    assert '[phone]' in text and '[e-mail]' in text and 'Her son Ravi' in text and 'Travel Insurance' in text
    assert crm_ai.scrub('Call +1 (214) 555-0100 or 9812345678; write a.b@c.co.in') == \
        'Call [phone] or [phone]; write [e-mail]'
    assert crm_ai.scrub('Travels on 3 Nov, 2 people, ₹18,500') == 'Travels on 3 Nov, 2 people, ₹18,500'


def test_it_is_kept_until_a_newer_message(app, client, admin_user, lead, ai_on):
    login(client, admin_user.email)
    client.post('/admin/crm/lead/%d/ai' % lead.id, json={})
    again = client.post('/admin/crm/lead/%d/ai' % lead.id, json={}).get_json()
    assert again['cached'] is True and len(ai_on) == 1
    l = _db.session.get(CrmLead, lead.id)
    crm.record_reply(l, 'Any update?')
    _db.session.commit()
    third = client.post('/admin/crm/lead/%d/ai' % lead.id, json={}).get_json()
    assert third['cached'] is False and len(ai_on) == 2


def test_any_failure_says_ai_is_not_available(app, client, admin_user, lead, ai_on, monkeypatch):
    def broken(system, text):
        raise TimeoutError('slow')
    monkeypatch.setattr(crm_ai, 'call_claude', broken)
    login(client, admin_user.email)
    r = client.post('/admin/crm/lead/%d/ai' % lead.id, json={})
    assert r.status_code == 503 and r.get_json() == {'error': 'AI is not available right now'}
    _db.session.expire_all()
    assert _db.session.get(CrmLead, lead.id).ai_cache is None
    monkeypatch.setattr(crm_ai, 'call_claude', lambda s, t: 'not json, and not useful')
    d = client.post('/admin/crm/lead/%d/ai' % lead.id, json={}).get_json()
    assert d['summary'] == ['not json, and not useful'] and d['next'] == ''


def test_the_call_is_one_post_to_the_messages_api(app, monkeypatch):
    import requests
    seen = {}

    class Resp:
        status_code = 200

        def json(self):
            return {'content': [{'type': 'thinking', 'thinking': ''}, {'type': 'text', 'text': ANSWER}],
                    'stop_reason': 'end_turn'}

    def post(url, **kw):
        seen.update(url=url, **kw)
        return Resp()
    monkeypatch.setattr(requests, 'post', post)
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-test')
    assert crm_ai.call_claude('sys', 'hello') == ANSWER
    assert seen['url'] == 'https://api.anthropic.com/v1/messages' and seen['timeout'] == 20
    assert seen['headers'] == {'x-api-key': 'sk-test', 'anthropic-version': '2023-06-01',
                               'content-type': 'application/json'}
    body = seen['json']
    assert body['model'] == 'claude-sonnet-5-5' and 500 <= body['max_tokens'] <= 2000  # room for the model's own thinking
    assert body['messages'] == [{'role': 'user', 'content': 'hello'}] and body['system'] == 'sys'

    class Refused(Resp):
        def json(self):
            return {'content': [], 'stop_reason': 'refusal'}
    monkeypatch.setattr(requests, 'post', lambda url, **kw: Refused())
    with pytest.raises(crm_ai.AIError):
        crm_ai.call_claude('sys', 'hello')
    monkeypatch.delenv('ANTHROPIC_API_KEY')
    with pytest.raises(crm_ai.AIError):
        crm_ai.call_claude('sys', 'hello')
