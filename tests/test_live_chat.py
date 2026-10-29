"""Live chat (2026-10-30): our own chat bubble on our websites, answered in the portal -- no tawk.to frame.

    the visitor   starts a chat (a lead under "Website live chat", the first message on it), writes, asks for news;
                  sees only their own chat, and of us a first name; what they need to give, and why not
    our side      the box's "Live chat" answers them; one of us typing shows; they wait on us until answered;
                  Live chat's page, its chats (who is on the site now) and one chat; Live chat on the rail
    the bubble    /live-chat.js with its words, on our public pages instead of tawk.to's, switched off from
                  Set-up › Integrations › Live chat; other websites only when listed
"""
import json
from datetime import datetime, timedelta
from html import unescape

from conftest import login, make_user
from app import db as _db
from app.models import CrmLead, CrmLiveChat, CrmTouchpoint
from app.services import crm, crm_inbox, integrations, livechat

from test_wa_numbers_shown import two_numbers          # noqa: F401  (the fixture: the WhatsApp CRM and a second number)

START = '/api/live-chat/start'
PAGE = '/admin/messaging/live-chat'
INBOX = '/admin/messaging/inbox'


def begin(client, **kw):
    body = {'name': 'Meera Iyer', 'contact': 'meera@example.com', 'message': 'Is my mother covered for diabetes?',
            'topic': 'TI', 'page': 'https://nriparentservice.com/travel-insurance#quote', 'title': 'Travel insurance'}
    body.update(kw)
    r = client.post(START, data=json.dumps(body), content_type='text/plain;charset=UTF-8', headers=kw.pop('headers', {}))
    return r, r.get_json()


def news(client, token, after=0, **args):
    q = '&'.join('%s=%s' % kv for kv in args.items())
    return client.get('/api/live-chat/%s?after=%d%s' % (token, after, '&' + q if q else '')).get_json()


def page(client, url):
    r = client.get(url)
    assert r.status_code == 200, (url, r.status_code)
    return unescape(r.get_data(as_text=True))


def fresh_online():
    livechat._online['at'] = 0.0


# ------------------------------------------------------------------------------------------------ the visitor

def test_a_visitor_starts_a_chat_and_it_becomes_a_lead(app, client):
    r, d = begin(client)
    assert r.status_code == 201 and d['ok'] and len(d['token']) >= 40
    assert [m['text'] for m in d['messages']] == ['Is my mother covered for diabetes?'] and d['messages'][0]['me']
    chat = CrmLiveChat.query.one()
    lead = _db.session.get(CrmLead, chat.lead_id)
    assert lead.person.email == 'meera@example.com' and lead.person.display_name == 'Meera Iyer'
    assert lead.source.key == 'live-chat' and lead.product == 'TI'          # the topic picked the pipeline
    assert chat.site == 'nriparentservice.com' and chat.page_title == 'Travel insurance'
    first = CrmTouchpoint.query.filter_by(live_chat_id=chat.id).one()
    assert (first.channel, first.direction, first.body) == ('webchat', 'in', 'Is my mother covered for diabetes?')
    assert 'travel-insurance' not in first.body                            # the page is the chat's, not their words


def test_the_bubble_asks_for_what_it_needs(app, client):
    for kw, said in (({'name': ''}, 'your name'), ({'contact': ''}, 'e-mail or a WhatsApp number'),
                     ({'contact': 'meera@'}, 'e-mail address does not look right'),
                     ({'contact': '12'}, 'number does not look right'), ({'message': '  '}, 'question first')):
        r, d = begin(client, **kw)
        assert r.status_code == 400 and said in d['error'], kw
    r, d = begin(client, website='http://spam.example')                  # the field only a bot fills in
    assert r.status_code == 400
    r, d = begin(client, contact='+1 (917) 555-0123')
    assert r.status_code == 201 and CrmLiveChat.query.one().person.phone == '+19175550123'
    assert CrmLiveChat.query.count() == 1


def test_a_visitor_sees_only_their_own_chat(app, client, admin_user):
    _r, a = begin(client)
    _r, b = begin(client, message='A second question, from another browser')
    assert CrmLiveChat.query.count() == 2
    chat_a, chat_b = CrmLiveChat.query.order_by(CrmLiveChat.id).all()
    assert chat_a.person_id == chat_b.person_id                          # the same e-mail: the same person
    lead = chat_b.lead
    crm.log_touch(lead, 'whatsapp', 'in', body='Something said on WhatsApp')        # never shown in a live chat
    _db.session.commit()
    assert [m['text'] for m in news(client, a['token'])['messages']] == ['Is my mother covered for diabetes?']
    assert [m['text'] for m in news(client, b['token'])['messages']] == ['A second question, from another browser']
    # a reply goes to their newest chat
    livechat.reply(lead, 'Yes, it is covered.', admin_user)
    assert 'Yes, it is covered.' not in [m['text'] for m in news(client, a['token'])['messages']]
    assert 'Yes, it is covered.' in [m['text'] for m in news(client, b['token'])['messages']]
    assert client.get('/api/live-chat/not-a-real-token-at-all-0000000000000').status_code == 404


def test_an_agent_answers_and_the_visitor_sees_a_first_name(app, client, admin_user):
    admin_user.last_name = 'Sharma'
    _db.session.commit()
    _r, d = begin(client)
    first_id = d['messages'][0]['id']
    chat = CrmLiveChat.query.one()
    agent = app.test_client()
    login(agent, admin_user.email)
    r = agent.post('/admin/crm/lead/%d/send' % chat.lead_id, json={'via': 'webchat', 'text': 'Hello Meera, yes it is.'})
    assert r.status_code == 200 and r.get_json()['success'] and r.get_json()['here'] is True
    got = news(client, d['token'], first_id, open='1')
    assert [(m['text'], m['who'], m['me']) for m in got['messages']] == [('Hello Meera, yes it is.', 'Admin', False)]
    assert 'Sharma' not in json.dumps(got)
    fresh_online()
    assert got['online'] == ['Admin']                     # whoever answered is here, whatever the shared list says
    assert _db.session.get(CrmLiveChat, chat.id).read_upto == got['messages'][0]['id']    # open on their screen
    # typing
    assert news(client, d['token'], 10 ** 6)['typing'] is None
    assert agent.post('/admin/messaging/live-chat/%d/typing' % chat.person_id).get_json()['ok']
    assert news(client, d['token'], 10 ** 6)['typing'] == 'Admin'
    # somebody without a chat cannot be answered here
    other = crm.capture('contact-general', name='No Chat', email='nochat@example.com', message='Hi')
    _db.session.commit()
    r = agent.post('/admin/crm/lead/%d/send' % other.id, json={'via': 'webchat', 'text': 'Hello'})
    assert r.status_code == 400 and 'no live chat' in r.get_json()['error']


def test_what_the_visitor_writes_waits_on_us_until_answered(app, client, admin_user):
    _r, d = begin(client)
    r = client.post('/api/live-chat/%s/send' % d['token'], data=json.dumps({'text': 'Also, my father?'}),
                    content_type='text/plain')
    assert r.status_code == 200 and r.get_json()['ok']
    chat = CrmLiveChat.query.one()
    assert [t.body for t in CrmTouchpoint.query.filter_by(live_chat_id=chat.id).order_by(CrmTouchpoint.id)] == \
        ['Is my mother covered for diabetes?', 'Also, my father?']
    assert crm_inbox.live_waiting(admin_user) == 1
    livechat.reply(chat.lead, 'Him too.', admin_user)
    assert crm_inbox.live_waiting(admin_user) == 0
    r = client.post('/api/live-chat/%s/send' % d['token'], data=json.dumps({'text': ''}), content_type='text/plain')
    assert r.status_code == 400


def test_they_can_end_the_chat(app, client, admin_user):
    _r, d = begin(client)
    assert client.post('/api/live-chat/%s/end' % d['token']).get_json()['ok']
    chat = CrmLiveChat.query.one()
    assert chat.closed_at is not None and news(client, d['token'])['closed'] is True
    assert livechat.status_line(chat) == 'Ended the chat'


# ------------------------------------------------------------------------------------------------ our side

def test_live_chat_page_lists_chats_and_who_is_on_the_site(app, client, admin_user):
    _r, d = begin(client)
    _r, d2 = begin(client, name='Arjun Mehta', contact='arjun@example.com', message='Do you cover Canada?',
                   topic='', title='Contact us')
    gone = CrmLiveChat.query.filter_by(token=d2['token']).one()
    gone.seen_at = datetime.utcnow() - timedelta(minutes=12)
    _db.session.commit()
    login(client, admin_user.email)
    html = page(client, PAGE)
    assert 'data-on="web"' in html and 'data-web-list-url="/admin/messaging/live-chat/chats"' in html
    assert 'wa-rail.js' in html and 'dashboard.tawk.to' not in html and '<iframe' not in html
    rows = page(client, '/admin/messaging/live-chat/chats')
    meera = rows.split('Meera Iyer', 1)[1].split('</button>', 1)[0]
    arjun = rows.split('Arjun Mehta', 1)[1].split('</button>', 1)[0]
    assert 'On the site now · Travel insurance' in meera and 'lc-dot' in meera
    assert 'Left 12 min ago' in arjun and 'lc-dot' not in arjun
    assert 'New chat on' not in rows and 'Find a live chat' in rows and 'data-waiting="2"' in rows


def test_one_chat_has_the_box_on_live_chat(app, client, admin_user):
    _r, d = begin(client)
    chat = CrmLiveChat.query.one()
    login(client, admin_user.email)
    html = page(client, '/admin/messaging/live-chat/%d' % chat.person_id)
    assert 'Is my mother covered for diabetes?' in html
    assert 'data-typing-url="/admin/messaging/live-chat/%d/typing"' % chat.person_id in html
    assert 'data-via="webchat"' in html and 'Live chat' in html and 'data-box-tpl' not in html
    assert 'On the site now' in html and 'data-live-gone' not in html
    assert 'href="https://nriparentservice.com/travel-insurance"' in html          # their page
    chat.seen_at = datetime.utcnow() - timedelta(hours=2)
    _db.session.commit()
    assert 'data-live-gone' in page(client, '/admin/messaging/live-chat/%d' % chat.person_id)
    # the lead page shows the chat too (every lead of theirs: a person's channel), and answers in it
    lead_page = page(client, '/admin/crm/lead/%d' % chat.lead_id)
    assert 'Is my mother covered for diabetes?' in lead_page
    assert 'data-via="webchat"><i class="fa-regular fa-comment-dots"></i> Live chat' in lead_page
    assert 'data-box data-via="whatsapp"' not in lead_page                  # they left: no phone either, so ...
    chat.seen_at = datetime.utcnow()
    _db.session.commit()
    assert 'data-box data-via="webchat"' in page(client, '/admin/crm/lead/%d' % chat.lead_id)   # on the site: first


def test_live_chat_is_on_the_rail_beside_whatsapp_chats(app, client, admin_user, two_numbers):
    _r, d = begin(client)
    login(client, admin_user.email)
    html = page(client, INBOX)
    rail = html.split('data-wr', 1)[1].split('</nav>', 1)[0]
    live = rail.split('data-wr-num="web"', 1)[1].split('</button>', 1)[0]
    assert 'Live chat' in live and '>1</em>' in live and 'tawk' not in rail
    html = page(client, INBOX + '?num=web')
    assert 'data-on="web"' in html and 'data-new-chat hidden' in html
    # their lead on the right says it is a live chat: nothing of WhatsApp's 24 hours
    chat = CrmLiveChat.query.one()
    panel = page(client, '/admin/messaging/lead-panel?person=%d&num=web' % chat.person_id)
    assert 'Live chat on our website with Meera Iyer' in panel
    assert 'approved template' not in panel and 'writes back' not in panel


def test_live_chat_is_for_people_who_work_conversations(app, client, user):
    login(client, user.email)
    assert client.get(PAGE).status_code in (302, 403)
    assert client.get('/admin/messaging/live-chat/chats').status_code in (302, 403)


# ------------------------------------------------------------------------------------------------ the bubble

def test_the_script_carries_its_words_and_can_be_switched_off(app, client, admin_user):
    js = client.get('/live-chat.js')
    assert js.status_code == 200 and 'javascript' in js.headers['Content-Type']
    body = js.get_data(as_text=True)
    assert body.startswith('window.__liveChat = ') and '"title": "NRI Parent Service"' in body
    assert 'attachShadow' in body and 'Care at home (Sahayak)' in body
    livechat.save_config({'on': '', 'title': 'NRI Parent Service', 'greeting': 'Hi', 'away': 'Away',
                          'color': '#0F1F3D'}, admin_user)
    _db.session.commit()
    assert client.get('/live-chat.js').get_data(as_text=True).startswith('/* live chat is switched off */')
    r, d = begin(client)
    assert r.status_code == 404 and not d['ok']


def test_a_colour_too_light_for_white_words_is_not_kept(app, admin_user):
    assert livechat.dark_enough('#0F1F3D') and not livechat.dark_enough('#F5A623') and not livechat.dark_enough('x')
    assert livechat.save_config({'on': '1', 'color': '#FFF6EA'}, admin_user) is False
    assert livechat.config()['color'] == '#0F1F3D' and livechat.config()['title'] == 'NRI Parent Service'


def test_our_pages_carry_our_bubble_not_tawks(app, client):
    html = client.get('/contact-us').get_data(as_text=True)
    assert 'src="/live-chat.js"' in html and 'embed.tawk.to' not in html


def test_another_website_may_use_it_once_listed(app, client, admin_user):
    other = {'Origin': 'https://preventia360.com'}
    r = client.get('/api/live-chat/hello', headers=other)
    assert r.status_code == 200 and 'Access-Control-Allow-Origin' not in r.headers
    integrations.save_origins('https://preventia360.com', admin_user)
    _db.session.commit()
    r = client.get('/api/live-chat/hello', headers=other)
    assert r.headers['Access-Control-Allow-Origin'] == 'https://preventia360.com'
    r = client.open(START, method='OPTIONS', headers=other)
    assert r.status_code == 204 and 'POST' in r.headers['Access-Control-Allow-Methods']


def test_who_is_online_is_staff_with_the_page_seen_lately(app, client, admin_user, user):
    fresh_online()
    assert livechat.online(now=datetime.utcnow()) == []
    login(client, admin_user.email)                       # signing in makes a session, seen now
    client.get(PAGE)
    traveller = app.test_client()
    login(traveller, user.email)                          # not staff: never promised to a visitor
    traveller.get('/')
    assert livechat.online(now=datetime.utcnow()) == ['Admin']
    fresh_online()
    assert app.test_client().get('/api/live-chat/hello').get_json()['online'] == ['Admin']    # what a visitor hears
    fresh_online()


def test_the_integration_card_has_the_line_for_a_website(app, client, admin_user):
    login(client, admin_user.email)
    html = page(client, '/admin/crm/integrations/livechat?tab=install')
    assert '<script src="' in html and '/live-chat.js" async></script>' in html and 'tawk.to plugin' in html
    html = page(client, '/admin/crm/integrations/livechat?tab=settings')
    assert 'data-lc-form' in html and 'The chat bubble is on' in html
    r = client.post('/admin/crm/integrations/livechat/save', data={'on': '1', 'title': 'Preventia 360',
                                                                    'greeting': 'Hello!', 'away': 'Back soon',
                                                                    'color': '#123456'})
    assert r.status_code == 302 and livechat.config()['title'] == 'Preventia 360'


def test_migration_c1chat034_goes_up_down_up_on_sqlite(tmp_path):
    import importlib.util
    import os
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations', 'versions',
                        'c1chat034_live_chat.py')
    spec = importlib.util.spec_from_file_location('c1chat034', path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    assert mig.revision == 'c1chat034' and mig.down_revision == 'b1mkt033'
    engine = sa.create_engine('sqlite:///%s' % (tmp_path / 'm.db'))
    meta = sa.MetaData()
    for name in ('users', 'crm_people', 'crm_leads'):
        sa.Table(name, meta, sa.Column('id', sa.Integer, primary_key=True))
    sa.Table('crm_touchpoints', meta, sa.Column('id', sa.Integer, primary_key=True), sa.Column('body', sa.Text))
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO crm_touchpoints (id, body) VALUES (1, 'kept')"))
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig.upgrade()
        insp = sa.inspect(conn)
        assert {'token', 'person_id', 'lead_id', 'seen_at', 'read_upto', 'agent_typing_at', 'closed_at'} <= \
            {c['name'] for c in insp.get_columns('crm_live_chats')}
        assert 'live_chat_id' in {c['name'] for c in insp.get_columns('crm_touchpoints')}
        with Operations.context(ctx):
            mig.downgrade()
        insp = sa.inspect(conn)
        assert 'crm_live_chats' not in insp.get_table_names()
        assert 'live_chat_id' not in {c['name'] for c in insp.get_columns('crm_touchpoints')}
        assert conn.execute(sa.text('SELECT body FROM crm_touchpoints WHERE id = 1')).scalar() == 'kept'
        with Operations.context(ctx):
            mig.upgrade()
        assert 'crm_live_chats' in sa.inspect(conn).get_table_names()
