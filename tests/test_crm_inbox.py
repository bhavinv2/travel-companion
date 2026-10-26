"""Inbox › All conversations (Staff Console 2.0, 2026-10-26): everybody who wrote to us, on any channel, one row each.

    rows      one per person who wrote on WhatsApp, e-mail, Instagram, Facebook, a website form or its chat, newest
              first, with what was said last either way, their lead, who looks after it, "Waiting on us"
    tabs      All / Mine / Not given to anyone / Waiting on us, each with its count; a channel chip; a search
    scope     a role that sees only its own leads sees only those conversations (and the ones nobody has)
    opening   the last word on WhatsApp with a chat opens WhatsApp chats on it; anything else, the lead page
    menu      the first line of the Inbox for whoever works leads
"""
import re
from datetime import datetime, timedelta

from conftest import login, logout, make_user
from app import db as _db
from app.models import WorkspaceRole
from app.services import access, crm

INBOX = '/cs/crm/inbox'


def words(html):
    return ' '.join(re.sub(r'<script.*?</script>|<[^>]+>', ' ', html, flags=re.S).split())


def rows(html):
    """The names in the list, in order."""
    return re.findall(r'class="ib-name" href="[^"]*">([^<]+)</a>', html)


def lead(name, phone=None, email=None, owner=None, source='ti-quote', message=None, ago=0):
    l = crm.capture(source, name=name, phone=phone, email=email, message=message, utm={},
                    when=datetime.utcnow() - timedelta(minutes=ago))
    l.owner_id = owner.id if owner is not None else None
    _db.session.commit()
    return l


def test_everybody_who_wrote_is_one_row_newest_first_with_what_was_said(app, client, admin_user):
    crm.ensure_defaults()
    form = lead('Form Farah', email='farah@example.com', source='contact-general', message='Do you cover parents?',
                ago=50)
    wa = lead('Chat Chitra', phone='+919811100201', ago=40)
    crm.log_touch(wa, 'whatsapp', 'in', body='How much is the cover?', external_id='wamid.c1',
                  at=datetime.utcnow() - timedelta(minutes=5))
    mail = lead('Mail Meena', email='meena@example.com', ago=30)
    crm.log_touch(mail, 'email', 'in', body='Please send the quote', at=datetime.utcnow() - timedelta(minutes=20))
    crm.log_touch(mail, 'email', 'out', body='Here it is', user=admin_user, at=datetime.utcnow() - timedelta(minutes=10))
    _db.session.commit()
    login(client, admin_user.email)
    html = client.get(INBOX).get_data(as_text=True)
    assert rows(html) == ['Chat Chitra', 'Mail Meena', 'Form Farah']             # newest message first
    t = words(html)
    assert 'How much is the cover?' in t and 'Do you cover parents?' in t
    assert 'Admin: Here it is' in t                                              # ours, with who sent it
    assert 'Waiting on us' in t
    # the tabs count: Chitra waits (she wrote last on WhatsApp); Meena was answered; a form is not a chat to answer
    assert re.search(r'Waiting on us\s*<b class="ib-n">1</b>', html) and re.search(r'All\s*<b class="ib-n">3</b>', html)
    waiting = rows(client.get(INBOX + '?who=waiting').get_data(as_text=True))
    assert waiting == ['Chat Chitra']


def test_the_tabs_channels_and_search_narrow_it(app, client, admin_user, cs_user):
    crm.ensure_defaults()
    mine = lead('Mine Mira', phone='+919811100211', owner=cs_user, ago=10)
    free = lead('Free Farida', email='farida@example.com', source='contact-general', message='Hello', ago=20)
    other = lead('Other Omar', email='omar@example.com', owner=admin_user, ago=30)
    crm.log_touch(other, 'email', 'in', body='About my quote')
    _db.session.commit()
    access.ensure_defaults()
    login(client, admin_user.email)
    assert rows(client.get(INBOX + '?who=none').get_data(as_text=True)) == ['Free Farida']
    assert rows(client.get(INBOX + '?ch=email').get_data(as_text=True)) == ['Other Omar']
    assert set(rows(client.get(INBOX + '?ch=forms').get_data(as_text=True))) == {'Mine Mira', 'Free Farida', 'Other Omar'}
    assert rows(client.get(INBOX + '?q=farida').get_data(as_text=True)) == ['Free Farida']
    assert 'Nothing here with these filters' in words(client.get(INBOX + '?q=nobody-at-all').get_data(as_text=True))
    logout(client)
    login(client, cs_user.email)
    assert rows(client.get(INBOX + '?who=mine').get_data(as_text=True)) == ['Mine Mira']
    assert mine.id


def test_a_role_that_sees_only_its_own_leads_sees_only_those_conversations(app, client):
    ws = access.ensure_defaults()
    crm.ensure_defaults()
    own = make_user('own@test.com', 'own', role='cs')
    role = WorkspaceRole(workspace_id=ws.id, name='Own only', pages=sorted(access.CS_ROLE_PAGES), crm_scope='own')
    _db.session.add(role)
    _db.session.flush()
    access.add_member(ws, own, role=role)
    other = make_user('oth@test.com', 'oth', role='cs')
    lead('Their Tara', phone='+919811100221', owner=other)
    lead('My Maya', phone='+919811100222', owner=own)
    lead('Nobody Nisha', phone='+919811100223')
    access._cache().clear()
    login(client, own.email)
    html = client.get(INBOX).get_data(as_text=True)
    assert set(rows(html)) == {'My Maya', 'Nobody Nisha'} and 'Their Tara' not in html


def test_a_row_opens_where_it_is_answered(app, client, admin_user, monkeypatch):
    crm.ensure_defaults()
    wa = lead('Wa Wanda', phone='+919811100231')
    crm.log_touch(wa, 'whatsapp', 'in', body='Hi', external_id='wamid.w1')
    wa.person.wacrm_conversation_id = 'conv-77'
    mail = lead('Mail Mona', email='mona@example.com')
    _db.session.commit()
    login(client, admin_user.email)
    html = client.get('/admin/crm/inbox').get_data(as_text=True)
    assert 'href="/admin/crm/lead/%d">Open lead' % mail.id in html
    # WhatsApp not connected here: the lead page, not the chat
    assert 'href="/admin/crm/lead/%d">Open lead' % wa.id in html
    from app.routes import messaging
    monkeypatch.setattr(messaging, 'can_start_chats', lambda user: True)
    html = client.get('/admin/crm/inbox').get_data(as_text=True)
    assert 'Open chat' in html and '/admin/messaging/inbox?p=/inbox?mine%3D1%26c%3Dconv-77' in html


def test_all_conversations_is_the_first_line_of_the_inbox(app, client, admin_user):
    access.ensure_defaults()
    with app.test_request_context('/cs/crm/today'):
        from flask_login import login_user
        login_user(admin_user)
        inbox = next(g for g in access.nav(admin_user) if g['key'] == 'inbox')
    assert [i['label'] for i in inbox['items']][:2] == ['All conversations', 'WhatsApp chats']
    assert 'crm_inbox' in access._implied(frozenset({'crm_today'}))             # whoever works leads has it
    assert access.PAGES['crm_inbox']['section'] == 'inbox'
