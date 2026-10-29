"""The rail beside WhatsApp chats (Messaging Hub, 2026-10-29): our numbers one by one, and a chat found on any of them.

    rail          each WhatsApp number of ours as an icon (its country code, its colour, how many wait on us), the
                  WhatsApp CRM's first; a number the website offers that nothing hears, greyed; ?num= opens on a number
    a number      a Meta-direct number's chats, newest first, with its search and "whose" tabs -- only that number's
    one chat      their messages with that number and the lead page's own box; when they last wrote to another number,
                  it says the reply goes from that one
    find          people with a WhatsApp chat on any number, each with the numbers they talk on
    the panel     beside a chat on a number: that number's 24 hours
"""
from datetime import datetime, timedelta
from html import unescape

from conftest import login
from app import db as _db
from app.services import crm, crm_timeline, offices

from test_wa_numbers_shown import two_numbers, wrote          # noqa: F401  (the fixture and its helper)

INBOX = '/admin/messaging/inbox'


def chats(line):
    return '/admin/messaging/number/%d/chats' % line.id


def chat(line, lead):
    return '/admin/messaging/number/%d/chat/%d' % (line.id, lead.person_id)


def page(client, url):
    r = client.get(url)
    assert r.status_code == 200, (url, r.status_code)
    return unescape(r.get_data(as_text=True))


def test_the_rail_lists_every_number_with_how_many_wait_on_us(app, client, admin_user, two_numbers):
    wrote('Anita Rao', '+919000012345')
    wrote('Ravi Kumar', '+19175550199', line=two_numbers)
    wrote('Sam Lee', '+19175550188', line=two_numbers, hours=2)
    offices.save_numbers([{'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': True},
                          {'label': 'USA', 'iso': 'US', 'number': '+1 917 900 5094', 'whatsapp': True},
                          {'label': 'Canada', 'iso': 'CA', 'number': '+1 (647) 770-2288', 'whatsapp': True}])
    login(client, admin_user.email)
    html = page(client, INBOX)
    rail = html.split('data-wr', 1)[1].split('</nav>', 1)[0]
    india = rail.split('data-wr-num="crm"', 1)[1].split('</button>', 1)[0]
    usa = rail.split('data-wr-num="%d"' % two_numbers.id, 1)[1].split('</button>', 1)[0]
    assert rail.index('data-wr-num="crm"') < rail.index('data-wr-num="%d"' % two_numbers.id)   # the CRM's first
    assert '<b>IN</b>' in india and 'India' in india and '+91 80191 11360' in india and 'Our WhatsApp CRM' in india
    assert '<b>US</b>' in usa and '+1 (917) 900-5094' in usa and 'Meta direct' in usa
    assert 'aria-pressed="true"' in india and 'aria-pressed="false"' in usa          # it opens on the CRM's inbox
    assert '>2</em>' in usa and '2 waiting on us' in usa and '>1</em>' in india
    off = rail.split('data-wr-off', 1)[1].split('</li>', 1)[0]
    assert '<b>CA</b>' in off and 'Not connected' in off and 'never reaches us' in rail
    assert 'Find a contact' in rail and 'All conversations' in rail
    # the iframe is there, the number's pane is not shown, New chat is
    assert 'data-wa-frame' in html and 'data-num-pane hidden' in html
    assert 'wa-rail.js' in html


def test_the_rail_opens_on_a_number_and_chat_from_the_address(app, client, admin_user, two_numbers):
    ravi = wrote('Ravi Kumar', '+19175550199', line=two_numbers)
    login(client, admin_user.email)
    html = page(client, INBOX + '?num=%d&chat=%d' % (two_numbers.id, ravi.person_id))
    assert 'data-on="%d" data-chat="%d"' % (two_numbers.id, ravi.person_id) in html
    assert 'data-num-pane hidden' not in html and 'data-new-chat hidden' not in html      # New chat on USA too
    rail = html.split('data-wr', 1)[1].split('</nav>', 1)[0]
    assert 'aria-pressed="true"' in rail.split('data-wr-num="%d"' % two_numbers.id, 1)[1].split('</button>', 1)[0]
    # a number that is not ours opens on the CRM's
    assert 'data-on="crm"' in page(client, INBOX + '?num=999')


def test_a_numbers_chats_are_only_that_numbers(app, client, admin_user, two_numbers):
    wrote('Anita Rao', '+919000012345')
    ravi = wrote('Ravi Kumar', '+19175550199', line=two_numbers)
    sam = wrote('Sam Lee', '+19175550188', line=two_numbers, hours=3)
    crm.log_touch(sam, 'whatsapp', 'out', body='Here is the cover we talked about', user=admin_user,
                  at=datetime.utcnow() - timedelta(hours=2), line_id=two_numbers.id, status='delivered')
    _db.session.commit()
    login(client, admin_user.email)
    html = page(client, chats(two_numbers))
    assert 'Ravi Kumar' in html and 'Sam Lee' in html and 'Anita Rao' not in html
    assert html.index('Ravi Kumar') < html.index('Sam Lee')                         # newest first
    assert 'data-num-chat="%d"' % ravi.person_id in html and 'Find a chat on USA' in html
    assert 'data-waiting="1"' in html                                               # Sam was answered
    ravi_row = html.split('data-num-chat="%d"' % ravi.person_id, 1)[1].split('</li>', 1)[0]
    assert 'Waiting' in ravi_row and 'Hello from Ravi Kumar' in ravi_row
    sam_row = html.split('data-num-chat="%d"' % sam.person_id, 1)[1].split('</li>', 1)[0]
    assert 'Here is the cover' in sam_row and 'Waiting' not in sam_row
    waiting = page(client, chats(two_numbers) + '?who=waiting')
    assert 'Ravi Kumar' in waiting and 'Sam Lee' not in waiting
    found = page(client, chats(two_numbers) + '?q=Sam')
    assert 'Sam Lee' in found and 'Ravi Kumar' not in found
    assert client.get('/admin/messaging/number/999/chats').status_code == 404


def test_one_chat_is_that_numbers_messages_with_the_lead_pages_box(app, client, admin_user, two_numbers):
    ravi = wrote('Ravi Kumar', '+19175550199', hours=30)                             # India, long ago
    crm.log_touch(ravi, 'whatsapp', 'in', body='Is cover for my mother available from March?', external_id='wamid.us9',
                  at=datetime.utcnow() - timedelta(minutes=4), line_id=two_numbers.id)
    ravi.person.wa_line_id = two_numbers.id
    _db.session.commit()
    login(client, admin_user.email)
    html = page(client, chat(two_numbers, ravi))
    assert 'data-lead-page data-lead="%d"' % ravi.id in html
    assert 'Is cover for my mother' in html and 'Hello from Ravi Kumar' not in html  # only this number's
    assert 'on our' in html and 'USA · +1 (917) 900-5094' in html
    assert 'data-box' in html and 'data-wa-state="open"' in html
    box = html.split('WhatsApp goes from', 1)[1][:400]
    assert 'USA · +1 (917) 900-5094' in box and 'data-num-other' not in html
    assert client.get('/admin/messaging/number/%d/chat/99999' % two_numbers.id).status_code == 404


def test_a_reply_goes_from_the_number_they_last_wrote_to_and_the_chat_says_so(app, client, admin_user, two_numbers):
    ravi = wrote('Ravi Kumar', '+19175550199', line=two_numbers, hours=5)
    crm.record_whatsapp_in(phone='19175550199', name='Ravi Kumar', wamid='wamid.in2', text='Now on India',
                           at=datetime.utcnow() - timedelta(minutes=2))
    _db.session.commit()
    login(client, admin_user.email)
    html = page(client, chat(two_numbers, ravi))
    other = html.split('data-num-other', 1)[1].split('</p>', 1)[0]
    assert 'last wrote to our' in other and 'India ·1360' in other and 'reply goes from that number' in other


def test_the_thread_has_only_messages_of_that_number(app, two_numbers):
    ravi = wrote('Ravi Kumar', '+19175550199', hours=30)
    crm.log_touch(ravi, 'whatsapp', 'in', body='On the US number', external_id='wamid.us8',
                  at=datetime.utcnow() - timedelta(minutes=8), line_id=two_numbers.id)
    crm.log_touch(ravi, 'note', 'none', body='Called the mother', at=datetime.utcnow() - timedelta(minutes=6))
    _db.session.commit()
    us = [i for i in crm_timeline.number_thread(ravi, two_numbers) if i['kind'] == 'msg']
    assert [i['text'] for i in us] == ['On the US number'] and us[0]['via_label'] is None
    india = [i['text'] for i in crm_timeline.number_thread(ravi, None) if i['kind'] == 'msg']
    assert india == ['Hello from Ravi Kumar']
    assert all(i['kind'] in ('msg', 'day') for i in crm_timeline.number_thread(ravi, None))


def test_find_a_contact_lists_the_numbers_they_talk_to_us_on(app, client, admin_user, two_numbers):
    ravi = wrote('Ravi Kumar', '+19175550199', hours=30)
    crm.log_touch(ravi, 'whatsapp', 'in', body='Now on the US number', external_id='wamid.us7',
                  at=datetime.utcnow() - timedelta(minutes=5), line_id=two_numbers.id)
    wrote('Anita Rao', '+919000012345')
    _db.session.commit()
    login(client, admin_user.email)
    html = page(client, '/admin/messaging/find?q=Ravi')
    assert 'Ravi Kumar' in html and 'Anita Rao' not in html
    hit = html.split('Ravi Kumar', 1)[1].split('</li>', 1)[0]
    assert 'data-wr-open="%d"' % two_numbers.id in hit and 'data-wr-open="crm"' in hit
    assert hit.index('data-wr-open="%d"' % two_numbers.id) < hit.index('data-wr-open="crm"')   # newest first
    assert 'No WhatsApp chat with “Zed”' in page(client, '/admin/messaging/find?q=Zed')
    assert client.get('/admin/messaging/find?q=R').get_data(as_text=True) == ''


def test_the_panel_beside_a_chat_on_a_number_counts_that_numbers_24_hours(app, client, admin_user, two_numbers):
    ravi = wrote('Ravi Kumar', '+19175550199', line=two_numbers)
    login(client, admin_user.email)
    html = page(client, '/admin/messaging/lead-panel?person=%d&num=%d' % (ravi.person_id, two_numbers.id))
    assert 'Chat on our' in html and 'USA · +1 (917) 900-5094' in html and 'Free to write' in html
    # the same person beside the WhatsApp CRM's inbox: India's 24 hours, which never opened
    crm_side = page(client, '/admin/messaging/lead-panel?conversation=c-9&phone=19175550199')
    assert 'India · +91 80191 11360' in crm_side and 'Free to write' not in crm_side


def test_the_rail_is_for_people_who_work_leads(app, client, user, two_numbers):
    ravi = wrote('Ravi Kumar', '+19175550199', line=two_numbers)
    login(client, user.email)
    assert client.get(chats(two_numbers)).status_code == 403
    assert client.get(chat(two_numbers, ravi)).status_code == 403
    assert client.get('/admin/messaging/find?q=Ravi').status_code == 403


def test_waiting_on_us_is_counted_on_the_number_the_unanswered_message_went_to(app, client, admin_user, two_numbers):
    """Ravi wrote to India yesterday and to the US number now: he waits on USA, not on India -- in the rail, the
    number's chats and All conversations' number tabs alike."""
    from app.services import crm_inbox
    ravi = wrote('Ravi Kumar', '+19175550199', hours=30)
    crm.log_touch(ravi, 'whatsapp', 'in', body='Now on the US number', external_id='wamid.us6',
                  at=datetime.utcnow() - timedelta(minutes=5), line_id=two_numbers.id)
    _db.session.commit()
    assert crm_inbox.waiting_by_number(admin_user) == {'crm': 0, str(two_numbers.id): 1}
    login(client, admin_user.email)
    rail = page(client, INBOX).split('data-wr', 1)[1].split('</nav>', 1)[0]
    india = rail.split('data-wr-num="crm"', 1)[1].split('</button>', 1)[0]
    assert 'data-wr-count hidden' in india and 'waiting on us' not in india
    us = page(client, chats(two_numbers))
    assert 'data-waiting="1"' in us and 'Waiting' in us.split('data-num-chat', 1)[1].split('</li>', 1)[0]
    india_tab = page(client, '/admin/crm/inbox?num=crm&who=waiting')
    assert 'Ravi Kumar' not in india_tab
    assert 'Ravi Kumar' in page(client, '/admin/crm/inbox?num=%d&who=waiting' % two_numbers.id)
    # we answer on the US number: nobody waits anywhere
    crm.log_touch(ravi, 'whatsapp', 'out', body='Yes, from March', user=admin_user, line_id=two_numbers.id,
                  at=datetime.utcnow() - timedelta(minutes=1), status='sent')
    _db.session.commit()
    assert crm_inbox.waiting_by_number(admin_user) == {'crm': 0, str(two_numbers.id): 0}


START = '/admin/messaging/start-chat'


def test_new_chat_on_a_number_lists_its_leads_and_says_what_is_missing(app, client, admin_user, two_numbers):
    """New chat on USA: open leads with a +1 phone and no chat on USA yet; with no approved template it says so."""
    us_new = crm.capture('ti-quote', name='Nora Diaz', phone='+19175550111', utm={})
    in_new = crm.capture('ti-quote', name='Meera Iyer', phone='+919000012399', utm={})
    chatting = wrote('Ravi Kumar', '+19175550199', line=two_numbers)
    _db.session.commit()
    login(client, admin_user.email)
    html = page(client, START + '?who=all&num=%d' % two_numbers.id)
    assert 'Start a chat on' in html and 'USA ·5094' in html
    assert 'Nora Diaz' in html and 'Meera Iyer' not in html and 'Ravi Kumar' not in html
    assert 'with a +1 phone and no chat on USA yet' in html
    warn = html.split('data-start-warn', 1)[1].split('</p>', 1)[0]
    assert 'no approved templates yet' in warn and 'Copy our templates' in warn
    # a search finds anyone; somebody already on USA opens, nothing is posted
    found = page(client, START + '?q=Ravi&num=%d' % two_numbers.id)
    assert 'data-start-open="%d"' % chatting.person_id in found
    # the India list is as before: Meera, who has no chat in the WhatsApp CRM
    assert 'Meera Iyer' in page(client, START + '?who=all')
    assert us_new and in_new


def test_message_on_a_number_puts_their_chat_on_it_and_sends_nothing(app, client, admin_user, two_numbers):
    nora = crm.capture('ti-quote', name='Nora Diaz', phone='+19175550111', utm={})
    two_numbers.templates, two_numbers.templates_at = [], datetime.utcnow()      # Meta listed none (the hourly job)
    _db.session.commit()
    login(client, admin_user.email)
    d = client.post(START, data={'lead': nora.id, 'num': two_numbers.id}).get_json()
    assert d == {'ok': True, 'person': nora.person_id, 'num': str(two_numbers.id), 'name': 'Nora Diaz'}
    _db.session.expire_all()
    from app.models import CrmPerson, CrmTouchpoint
    assert _db.session.get(CrmPerson, nora.person_id).wa_line_id == two_numbers.id
    assert CrmTouchpoint.query.filter_by(person_id=nora.person_id, direction='out').count() == 0
    # her chat on USA opens with the box: the first message goes from USA, as an approved template
    html = page(client, chat(two_numbers, nora))
    assert 'USA · +1 (917) 900-5094' in html.split('WhatsApp goes from', 1)[1][:300]
    assert 'data-wa-state="never"' in html and 'No approved templates on USA' in html
    # a chat we started is in the number's chats, not in All conversations' WhatsApp (people who wrote to us)
    crm.log_touch(nora, 'whatsapp', 'out', body='[template] hello_followup', user=admin_user, line_id=two_numbers.id,
                  status='sent')
    _db.session.commit()
    assert 'Nora Diaz' in page(client, chats(two_numbers))
    assert 'Nora Diaz' not in page(client, '/admin/crm/inbox?ch=whatsapp')       # she wrote by form, not WhatsApp
    # a number that is not connected sends nothing
    two_numbers.status = 'paused'
    _db.session.commit()
    d = client.post(START, data={'lead': nora.id, 'num': two_numbers.id}).get_json()
    assert d['ok'] is False and 'not connected' in d['error']
