"""WhatsApp chats: starting a chat with a lead, and the redesigned lead panel beside the inbox.

    start list   with no chat open (or after "New chat") the panel lists open leads with a phone and no WhatsApp chat
                 yet, newest first; whose: mine / not given to anyone / everyone; a search finds any lead, and one that
                 has a chat says "Open chat"
    message      makes the chat in the WhatsApp CRM (never sends), gives it to the lead's owner if nobody has it, links
                 the person, and answers the hand-off address that opens it in the frame; with WhatsApp on "Not yet"
                 it only opens chats that exist; a removed lead is not found
    panel        says what WhatsApp allows now (never wrote / 24 hours passed / free to write), and the quick
                 replies are one list, the one that fits what they asked first
"""
import json
import re
from datetime import datetime, timedelta

from conftest import login
from app import db as _db
from app.models import CrmPerson
from app.services import crm

from test_crm_wa_sending import DIGITS, World, ti_lead, wrote, world        # noqa: F401  (the fixture and its helpers)

START = '/admin/messaging/start-chat'


def words(html):
    return ' '.join(re.sub(r'<[^>]+>', ' ', html).split())


def lead(name, phone, owner=None, **kw):
    l = ti_lead(phone=phone, name=name)
    l.owner_id = owner.id if owner is not None else None
    for k, v in kw.items():
        setattr(l, k, v)
    _db.session.commit()
    return l


def test_the_start_list_is_new_leads_with_no_chat_newest_first(app, client, admin_user, world):
    old = lead('Older Olga', '+919811100011', admin_user, created_at=datetime.utcnow() - timedelta(days=3))
    new = lead('Newer Nina', '+919811100012', None)
    chatting = lead('Chatting Chandu', '+919811100013', admin_user)
    chatting.person.wacrm_conversation_id = 'conv-x'
    _db.session.commit()
    login(client, admin_user.email)
    html = client.get(START).get_data(as_text=True)
    t = words(html)
    assert 'Start a chat' in t and 'Newer Nina' in t and 'Older Olga' in t and 'Chatting Chandu' not in t
    assert t.index('Newer Nina') < t.index('Older Olga')                          # newest first
    assert '2 new leads with no WhatsApp chat yet' in t
    assert 'data-start-chat="%d"' % new.id in html and 'Message' in t
    mine = words(client.get(START + '?who=mine').get_data(as_text=True))
    assert 'Older Olga' in mine and 'Newer Nina' not in mine
    free = words(client.get(START + '?who=none').get_data(as_text=True))
    assert 'Newer Nina' in free and 'Older Olga' not in free
    # a search finds any lead; one with a chat is opened, not made
    found = client.get(START + '?q=Chandu').get_data(as_text=True)
    assert 'Chatting Chandu' in words(found) and 'Open chat' in words(found)
    assert 'data-start-chat="%d"' % chatting.id in found


def test_message_makes_the_chat_gives_it_to_the_owner_and_opens_it_in_the_frame(app, client, admin_user, world):
    l = lead('Message Meera', '+' + DIGITS, admin_user)
    login(client, admin_user.email)
    r = client.post(START, data={'lead': l.id})
    d = r.get_json()
    assert r.status_code == 200 and d['ok'] and d['name'] == 'Message Meera'
    calls = world.ensure_calls()
    assert calls and calls[-1][2]['create'] is True and calls[-1][2]['assign_email'] == admin_user.email
    assert world.messages == []                                                  # nothing was sent
    assert '/api/portal/sso?t=' in d['src'] and d['conversation']
    _db.session.expire_all()
    assert _db.session.get(CrmPerson, l.person_id).wacrm_conversation_id == d['conversation']
    # the hand-off lands on that chat, with the portal's lead panel beside it
    from app.services import wacrm_team
    token = d['src'].split('t=', 1)[1]
    from urllib.parse import unquote
    body = unquote(token).split('.')[0]
    import base64
    claims = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
    assert claims['next'] == '/inbox?mine=1&c=%s&panel=portal' % d['conversation']
    assert wacrm_team.enabled()


def test_with_whatsapp_on_not_yet_only_an_existing_chat_opens(app, client, admin_user, world, monkeypatch):
    from app.services import wacrm_team
    crm.save_settings(whatsapp_mode='off')
    l = lead('Notyet Neha', '+919811100031', admin_user)
    login(client, admin_user.email)
    html = client.get(START).get_data(as_text=True)
    assert 'WhatsApp is on “Not yet” in Set-up' in words(html)
    # the WhatsApp CRM has no chat for them: nothing is made
    real = world.api

    def no_chat(method, path, payload=None, params=None):
        if path == 'conversation/ensure' and not payload['create']:
            world.portal.append((method, path, payload))
            return {}
        return real(method, path, payload, params)
    monkeypatch.setattr(wacrm_team, '_api', no_chat)
    d = client.post(START, data={'lead': l.id}).get_json()
    assert d['ok'] is False and 'Not yet' in d['error']
    assert world.ensure_calls() and all(c[2]['create'] is False for c in world.ensure_calls())   # only looked up
    # it has one: that one opens
    monkeypatch.setattr(wacrm_team, '_api', real)
    assert client.post(START, data={'lead': l.id}).get_json()['ok'] is True
    assert all(c[2]['create'] is False for c in world.ensure_calls())


def test_a_removed_lead_or_one_without_a_phone_is_not_started(app, client, admin_user, world):
    gone = lead('Gone Gita', '+919811100041', admin_user, deleted_at=datetime.utcnow())
    nophone = lead('Nophone Nora', '+919811100042', admin_user)
    nophone.person.phone = None
    _db.session.commit()
    login(client, admin_user.email)
    assert client.post(START, data={'lead': gone.id}).status_code == 404
    d = client.post(START, data={'lead': nophone.id}).get_json()
    assert d['ok'] is False and 'no phone number' in d['error']
    assert 'Gone Gita' not in words(client.get(START).get_data(as_text=True))


def test_the_panel_says_what_whatsapp_allows_and_has_one_list_of_replies(app, client, admin_user, world):
    l = lead('Window Wanda', '+' + DIGITS, admin_user)
    l.person.wacrm_conversation_id = 'conv-w'
    _db.session.commit()
    login(client, admin_user.email)

    def panel():
        return words(client.get('/admin/messaging/lead-panel?conversation=conv-w').get_data(as_text=True))
    assert "Window hasn't written on WhatsApp yet" in panel()
    wrote(l, hours_ago=30)
    assert 'More than 24 hours since Window wrote' in panel()
    wrote(l, hours_ago=2, wamid='wamid.recent')
    t = panel()
    assert 'Free to write for 21 more hours' in t or 'Free to write for 22 more hours' in t
    assert 'Quick replies' in t and 'You press Send' in t and 'Open the lead to choose a template' not in t


def test_the_inbox_has_a_new_chat_button_beside_the_lead_panel(app, client, admin_user, world):
    from app.services import access
    ws = access.ensure_defaults()
    ws.wacrm = dict(ws.wacrm or {}, account_id='acc-1')
    _db.session.commit()
    login(client, admin_user.email)
    html = client.get('/admin/messaging/inbox').get_data(as_text=True)
    assert 'data-new-chat' in html and 'New chat' in html and 'data-lead-panel' in html


# ------------------------------------------------------------------ from a contact

def _next_of(src):
    import base64
    from urllib.parse import unquote
    body = unquote(src.split('t=', 1)[1]).split('.')[0]
    return json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))['next']


def test_a_contact_starts_their_chat_in_whatsapp_chats_with_the_lead_beside_it(app, client, admin_user, world):
    from urllib.parse import unquote
    l = lead('Contact Kavya', '+' + DIGITS, admin_user)
    login(client, admin_user.email)
    page = '/cs/crm/contact/%d' % l.person_id
    chat = '/admin/messaging/contact/%d/chat' % l.person_id
    html = client.get(page).get_data(as_text=True)
    assert 'action="%s"' % chat in html and 'Start WhatsApp chat' in words(html)
    r = client.post(chat, data={'next': page})
    _db.session.expire_all()
    conv = _db.session.get(CrmPerson, l.person_id).wacrm_conversation_id
    assert r.status_code == 302 and conv
    assert unquote(r.headers['Location']).endswith('/admin/messaging/inbox?p=/inbox?mine=1&c=%s' % conv)
    calls = world.ensure_calls()
    assert calls[-1][2]['create'] is True and calls[-1][2]['assign_email'] == admin_user.email   # the lead's owner
    assert world.messages == []                                                                   # nothing was sent
    # WhatsApp chats opens on that chat, with the portal's lead panel beside it
    inbox = client.get(r.headers['Location']).get_data(as_text=True)
    src = re.search(r'<iframe class="wa-frame" src="([^"]+)"', inbox).group(1).replace('&amp;', '&')
    assert _next_of(src) == '/inbox?mine=1&c=%s&panel=portal' % conv
    # and the contact now opens it
    assert 'Open WhatsApp chat' in words(client.get(page).get_data(as_text=True))


def test_contacts_offer_chat_on_every_row_with_a_number(app, client, admin_user, world):
    has = lead('Rowphone Ravi', '+919811100051', admin_user)
    none = lead('Rownone Rekha', '+919811100052', admin_user)
    none.person.phone = None
    _db.session.commit()
    login(client, admin_user.email)
    html = client.get('/cs/crm/contacts').get_data(as_text=True)
    assert 'action="/admin/messaging/contact/%d/chat"' % has.person_id in html
    assert 'action="/admin/messaging/contact/%d/chat"' % none.person_id not in html
    assert 'Start a WhatsApp chat with Rowphone Ravi' in html
    # a contact without a number says so, and is not started
    page = '/cs/crm/contact/%d' % none.person_id
    assert 'No phone number to chat on' in words(client.get(page).get_data(as_text=True))
    r = client.post('/admin/messaging/contact/%d/chat' % none.person_id, data={'next': page})
    assert r.status_code == 302 and r.headers['Location'].endswith(page)
    assert 'has no phone number' in words(client.get(page).get_data(as_text=True))
    assert not world.ensure_calls()


def test_a_contact_chat_on_not_yet_only_opens_one_that_exists(app, client, admin_user, world, monkeypatch):
    from app.services import wacrm_team
    crm.save_settings(whatsapp_mode='off')
    l = lead('Notyet Nalini', '+919811100061', admin_user)
    real = world.api

    def no_chat(method, path, payload=None, params=None):
        if path == 'conversation/ensure' and not payload['create']:
            world.portal.append((method, path, payload))
            return {}
        return real(method, path, payload, params)
    monkeypatch.setattr(wacrm_team, '_api', no_chat)
    login(client, admin_user.email)
    page = '/cs/crm/contact/%d' % l.person_id
    r = client.post('/admin/messaging/contact/%d/chat' % l.person_id, data={'next': page})
    assert r.status_code == 302 and r.headers['Location'].endswith(page)
    assert '“Not yet”' in words(client.get(page).get_data(as_text=True))
    assert world.ensure_calls() and all(c[2]['create'] is False for c in world.ensure_calls())   # only looked up
    # an unsafe `next` goes to Contacts instead
    r = client.post('/admin/messaging/contact/%d/chat' % l.person_id, data={'next': '//evil.example/x'})
    assert 'evil' not in r.headers['Location']


def test_no_chat_button_while_whatsapp_is_not_connected(app, client, admin_user):
    l = ti_lead(phone='+919811100071', name='Offline Omkar')
    login(client, admin_user.email)
    page = '/cs/crm/contact/%d' % l.person_id
    html = client.get(page).get_data(as_text=True)
    assert '/admin/messaging/contact/' not in html and 'Start WhatsApp chat' not in words(html)
    assert '/admin/messaging/contact/' not in client.get('/cs/crm/contacts').get_data(as_text=True)
    r = client.post('/admin/messaging/contact/%d/chat' % l.person_id, data={'next': page})
    assert r.status_code == 302 and 'not connected for you' in words(client.get(page).get_data(as_text=True))
    assert client.post('/admin/messaging/contact/999999/chat').status_code == 404
