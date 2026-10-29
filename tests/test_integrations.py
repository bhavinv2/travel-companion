"""Set-up > Integrations (2026-10-26): every integration as a card with its status, three tabs each, and the two
settings kept there -- tawk.to's webhook key and the other websites whose forms may send leads.

    cards     the twelve cards, their states from what the server has, the menu line that replaced "WhatsApp"
    secrets   a key's VALUE is never on any page, only whether it is set
    tawk      POST /api/crm/tawk-webhook: 404 with no key, 401 for a bad signature; a chat or ticket that leaves a phone
              or e-mail becomes a lead under "Tawk chat", once; an anonymous chat is not stored
    websites  the saved websites join the server's list for the lead forms' CORS
"""
import hashlib
import hmac
import json
import re

import pytest

from conftest import login
from app.models import CrmLead, CrmPerson, CrmSource, CrmTouchpoint
from app.services import access, crm, integrations, settings, tawk

KEY = 'tawk-secret-0123456789abcdef'
TABS = ('overview', 'install', 'settings')


def text(client, url):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', client.get(url).get_data(as_text=True)))


def tawk_post(client, body, key=KEY):
    raw = json.dumps(body).encode()
    sig = hmac.new(key.encode(), raw, hashlib.sha1).hexdigest()
    return client.post('/api/crm/tawk-webhook', data=raw, content_type='application/json',
                       headers={'X-Tawk-Signature': sig})


@pytest.fixture()
def tawk_on(app, monkeypatch):
    monkeypatch.setenv('TAWK_WEBHOOK_SECRET', KEY)
    crm.ensure_defaults()
    return KEY


def chat_start(cid='C1', email='asha@example.com', name='Asha', said='Hi, cover for my mother?'):
    return {'event': 'chat:start', 'chatId': cid, 'time': '2026-10-26T10:00:00Z',
            'message': {'text': said, 'type': 'msg', 'sender': {'type': 'visitor'}},
            'visitor': {'name': name, 'email': email, 'city': 'Austin', 'country': 'US'},
            'property': {'id': 'P1', 'name': 'Live chat'}}


def transcript(cid='C1', email=None, name='V1784410364168612', lines=(('v', 'my number is +1 415 555 0142'),)):
    return {'event': 'chat:transcript_created', 'time': '2026-10-26T10:20:00Z', 'property': {'id': 'P1'},
            'chat': {'id': cid, 'visitor': {'name': name, 'email': email},
                     'messages': [{'sender': {'t': t, 'n': 'Agent' if t == 'a' else ''}, 'type': 'msg', 'msg': m}
                                  for t, m in lines]}}


# ============================================================================================ the cards

def test_admin_sees_every_card_with_its_state(app, client, admin_user, monkeypatch):
    for name in ('META_APP_SECRET', 'META_PAGE_TOKEN', 'META_VERIFY_TOKEN', 'TAWK_WEBHOOK_SECRET',
                 'CRM_GOOGLE_LEADS_KEY', 'CRM_PAYMENT_WEBHOOK_SECRET'):
        monkeypatch.delenv(name, raising=False)
    login(client, admin_user.email)
    r = client.get('/admin/crm/integrations')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert html.count('data-ig-card') == len(integrations.KEYS) == 13
    for key in integrations.KEYS:
        assert '/admin/crm/integrations/%s' % key in html
    page = text(client, '/admin/crm/integrations')
    assert 'tawk.to chat' in page and 'Not connected' in page and 'Website lead forms' in page
    # Meta half set up needs a look
    monkeypatch.setenv('META_APP_SECRET', 'x' * 20)
    assert 'Half set up' in text(client, '/admin/crm/integrations')
    # the group filter keeps only that kind
    payments = client.get('/admin/crm/integrations?group=money').get_data(as_text=True)
    assert payments.count('data-ig-card') == 1 and 'Payment links' in payments


def test_every_tab_of_every_card_opens(app, client, admin_user):
    crm.ensure_defaults()
    login(client, admin_user.email)
    for key in integrations.KEYS:
        for tab in TABS:
            r = client.get('/admin/crm/integrations/%s?tab=%s' % (key, tab))
            assert r.status_code == 200, (key, tab)
    assert client.get('/admin/crm/integrations/nope').status_code == 404


def test_the_menu_line_is_integrations_and_whatsapp_opens_from_its_card(app, client, admin_user):
    login(client, admin_user.email)
    html = client.get('/admin/crm/integrations').get_data(as_text=True)
    assert 'Integrations' in html
    assert access.PAGES['crm_connection']['nav'] is False and access.PAGES['crm_integrations']['nav'] is True
    # whoever may open the WhatsApp page (or only its Number tab) has the Integrations line too
    assert 'crm_integrations' in access._implied(frozenset({'crm_connection'}))
    assert 'crm_integrations' in access._implied(frozenset({'wa_settings'}))
    wa = client.get('/admin/crm/connection').get_data(as_text=True)
    assert '/admin/crm/integrations' in wa          # the way back to the cards
    assert access._menu_place('crm_connection').endswith('Integrations › WhatsApp (a card)')


def test_sales_and_service_cannot_open_integrations(app, client, cs_user):
    login(client, cs_user.email)
    r = client.get('/cs/crm/integrations')
    assert r.status_code in (302, 403)
    assert client.post('/cs/crm/integrations/tawk/save', data={'secret': KEY}).status_code in (302, 403)
    assert not (settings.get_setting(tawk.SETTING) or {}).get('secret')


def test_a_keys_value_is_never_shown(app, client, admin_user, monkeypatch):
    values = {'META_APP_SECRET': 'meta-secret-VALUE-1', 'META_PAGE_TOKEN': 'meta-token-VALUE-2',
              'META_VERIFY_TOKEN': 'meta-verify-VALUE-3', 'CRM_GOOGLE_LEADS_KEY': 'google-VALUE-4',
              'CRM_PAYMENT_WEBHOOK_SECRET': 'pay-VALUE-5', 'CRM_INBOUND_EMAIL_TOKEN': 'mail-VALUE-6',
              'TAWK_WEBHOOK_SECRET': 'tawk-VALUE-7-0123456789', 'ANTHROPIC_API_KEY': 'sk-ant-VALUE-8'}
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    login(client, admin_user.email)
    pages = [client.get('/admin/crm/integrations').get_data(as_text=True)]
    for key in integrations.KEYS:
        for tab in TABS:
            pages.append(client.get('/admin/crm/integrations/%s?tab=%s' % (key, tab)).get_data(as_text=True))
    for html in pages:
        for v in values.values():
            assert v not in html
    assert 'META_APP_SECRET' in text(client, '/admin/crm/integrations/meta?tab=install')        # the NAME is


# ============================================================================================ tawk.to

def test_tawk_answers_not_found_until_a_key_is_set(app, client, monkeypatch):
    monkeypatch.delenv('TAWK_WEBHOOK_SECRET', raising=False)
    assert client.post('/api/crm/tawk-webhook', json=chat_start()).status_code == 404


def test_a_bad_signature_is_refused(app, client, tawk_on):
    assert tawk_post(client, chat_start(), key='wrong-key-0123456789').status_code == 401
    assert CrmLead.query.count() == 0


def test_a_chat_with_an_email_becomes_one_tawk_lead(app, client, tawk_on):
    r = tawk_post(client, chat_start())
    assert r.status_code == 200 and r.get_json()['stored'] is True
    lead = CrmLead.query.one()
    assert lead.source.key == 'tawk' and lead.person.email == 'asha@example.com' and lead.person.name == 'Asha'
    tp = CrmTouchpoint.query.filter_by(external_id='tawk-chat:C1').one()
    assert tp.channel == 'chat' and tp.direction == 'in' and 'cover for my mother' in tp.body
    # the same chat again: nothing new; its transcript replaces the first message
    tawk_post(client, chat_start())
    tawk_post(client, transcript('C1', email='asha@example.com', name='Asha',
                                 lines=(('v', 'Hi, cover for my mother?'), ('a', 'Happy to help'), ('v', 'Thanks'))))
    assert CrmLead.query.count() == 1 and CrmTouchpoint.query.filter_by(external_id='tawk-chat:C1').count() == 1
    body = CrmTouchpoint.query.filter_by(external_id='tawk-chat:C1').one().body
    assert 'Visitor: Thanks' in body and 'Agent: Happy to help' in body


def test_a_phone_typed_in_the_chat_is_enough(app, client, tawk_on):
    r = tawk_post(client, transcript('C2'))
    assert r.get_json()['stored'] is True
    person = CrmPerson.query.one()
    assert person.phone == '+14155550142' and person.name in (None, '')     # tawk's V123... name is not a name


def test_an_anonymous_chat_is_not_stored(app, client, tawk_on):
    r = tawk_post(client, transcript('C3', lines=(('v', 'just looking'), ('a', 'Sure'))))
    assert r.status_code == 200 and r.get_json()['stored'] is False
    assert CrmLead.query.count() == 0
    assert tawk_post(client, {'event': 'chat:end', 'chatId': 'C3'}).get_json() == {'ok': True, 'stored': False}


def test_each_delivery_is_remembered_by_its_field_names_only(app, client, admin_user, tawk_on):
    """What tawk sent lately (2026-10-29): with WhatsApp on tawk, one test message shows what a WhatsApp chat's
    delivery carries -- its fields and one-word labels, never a name, an e-mail, a number or what was written."""
    wa = chat_start('C9', email=None, name='Ravi Kumar', said='Call me on +1 917 555 0199 please')
    wa['channel'] = 'whatsapp'
    wa['visitor']['phone'] = '+19175550199'
    tawk_post(client, wa)
    tawk_post(client, {'event': 'chat:end', 'chatId': 'C9', 'visitor': {'name': 'Ravi Kumar'}})
    rows = tawk.seen()
    assert [r['event'] for r in rows] == ['chat:end', 'chat:start']
    first = rows[1]
    assert first['whatsapp'] and first['labels']['channel'] == 'whatsapp' and first['filed']
    assert {'chatId', 'visitor.name', 'visitor.phone', 'message.text', 'message.sender.type'} <= set(first['fields'])
    kept = json.dumps(rows)
    for secret in ('Ravi', '917 555', '19175550199', 'Call me', 'Austin'):
        assert secret not in kept, secret
    for i in range(20):
        tawk_post(client, {'event': 'chat:end', 'chatId': 'X%d' % i})
    assert len(tawk.seen()) == tawk.SEEN_MAX
    login(client, admin_user.email)
    page = text(client, '/admin/crm/integrations/tawk?tab=overview')
    assert 'What tawk sent lately' in page and 'chat:end' in page


def test_an_offline_ticket_becomes_a_lead(app, client, tawk_on):
    body = {'event': 'ticket:create', 'time': '2026-10-26T11:00:00Z', 'property': {'id': 'P1'},
            'requester': {'name': 'Ravi', 'email': 'ravi@example.com', 'type': 'visitor'},
            'ticket': {'id': 'T9', 'humanId': 12, 'subject': 'Sahayak visit', 'message': 'Can someone visit dad?'}}
    assert tawk_post(client, body).get_json()['stored'] is True
    tp = CrmTouchpoint.query.filter_by(external_id='tawk-ticket:12').one()
    assert 'Sahayak visit' in tp.body and tp.lead.source.key == 'tawk'


def test_an_admin_saves_and_removes_the_key_on_the_settings_tab(app, client, admin_user, monkeypatch):
    monkeypatch.delenv('TAWK_WEBHOOK_SECRET', raising=False)
    crm.ensure_defaults()
    login(client, admin_user.email)
    assert 'Not connected' in text(client, '/admin/crm/integrations/tawk')
    r = client.post('/admin/crm/integrations/tawk/save', data={'secret': 'short'})
    assert r.status_code == 302 and not tawk.enabled()
    client.post('/admin/crm/integrations/tawk/save', data={'secret': KEY})
    assert tawk.secret() == KEY
    page = client.get('/admin/crm/integrations/tawk?tab=settings').get_data(as_text=True)
    assert KEY not in page and 'A key is saved' in page
    assert tawk_post(client, chat_start('C7')).get_json()['stored'] is True
    client.post('/admin/crm/integrations/tawk/save', data={'action': 'remove'})
    assert not tawk.enabled()
    assert client.post('/api/crm/tawk-webhook', json=chat_start()).status_code == 404


# ============================================================================================ websites

@pytest.mark.parametrize('typed, kept', [
    ('preventia360.com', 'https://preventia360.com'),
    ('https://www.example.com/insurance?x=1', 'https://www.example.com'),
    ('https://example.com:8443/', 'https://example.com:8443'),
    ('http://localhost:5000', 'http://localhost:5000'),
    ('http://example.com', None),
    ('not a site', None),
    ('', None),
])
def test_a_website_is_kept_as_its_https_origin(app, typed, kept):
    assert integrations.clean_origin(typed) == kept


def test_saved_websites_may_send_leads_with_the_servers_own(app, client, admin_user):
    app.config['CRM_INTAKE_ORIGINS'] = 'https://partner.example'
    login(client, admin_user.email)
    client.post('/admin/crm/integrations/website/save',
                data={'sites': 'preventia360.com\nhttp://insecure.example\nhttps://nriparentservice.com/x'})
    assert integrations.saved_origins() == ['https://preventia360.com', 'https://nriparentservice.com']
    assert integrations.intake_origins() == ['https://partner.example', 'https://preventia360.com',
                                             'https://nriparentservice.com']
    for origin, allowed in (('https://preventia360.com', True), ('https://partner.example', True),
                            ('https://insecure.example', False)):
        r = client.open('/api/leads', method='OPTIONS', headers={'Origin': origin})
        assert (r.headers.get('Access-Control-Allow-Origin') == origin) is allowed, origin


def test_the_website_card_gives_the_snippet_for_the_chosen_form(app, client, admin_user):
    crm.ensure_defaults()
    login(client, admin_user.email)
    key = CrmSource.query.filter(CrmSource.status != 'paused').order_by(CrmSource.name).first().key
    html = client.get('/admin/crm/integrations/website?tab=install&form=%s' % key).get_data(as_text=True)
    assert 'lead-capture.js' in html and 'data-lead-source=&#34;%s&#34;' % key in html or \
        'data-lead-source="%s"' % key in html
    assert '/api/leads' in html
