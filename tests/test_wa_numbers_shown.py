"""Messaging Hub, phase 1 (2026-10-29): every screen says which of our WhatsApp numbers a chat is on.

    the chip        the WhatsApp CRM's number is named after its country, a Meta-direct number by its label; both
                    with a country code (never a flag) and the last four digits, one colour each
    inbox           a chip on every WhatsApp row (India's too), a tab per number, "Also on" for a second number
    lead page       "WhatsApp goes from … to …" on the box, the number in the WhatsApp strip, the timeline names India
                    too once there are two numbers
    beside chats    the panel says which number the chat is on, and counts the 24 hours on that number only; the
                    banner over WhatsApp chats names its number and links the others' chats
    website         a WhatsApp button that offers a number nothing of ours hears is flagged
"""
from datetime import datetime, timedelta
from html import unescape

import pytest

from conftest import login
from app import db as _db
from app.models import CrmChannelLine
from app.services import access, channels, crm, offices, wa_templates, wacrm, wacrm_team

IN_PHONE = '+918019111360'


@pytest.fixture
def two_numbers(app, monkeypatch):
    """The WhatsApp CRM linked with India's number, and the US number as a live Meta-direct number. Nothing leaves."""
    monkeypatch.setenv('WACRM_URL', 'https://crm.example/crm')
    monkeypatch.setenv('WACRM_API_KEY', 'wacrm_live_test')
    monkeypatch.setenv('WACRM_PORTAL_SECRET', 'x' * 40)
    monkeypatch.setattr(wacrm, '_call', lambda *a, **k: {})
    monkeypatch.setattr(wacrm_team, '_api', lambda *a, **k: {})
    wa_templates.forget()
    crm.ensure_defaults()
    ws = access.ensure_defaults()
    ws.wacrm = {'account_id': 'acc-1', 'name': ws.name, 'phone': IN_PHONE}
    line = CrmChannelLine(key='usa', label='USA', provider='meta', phone='+19179005094',
                          phone_number_id='1339068212613709', waba_id='2149016299364820', verify_token='v-123',
                          prefixes=['+1'], status='live', connected_at=datetime.utcnow())
    _db.session.add(line)
    _db.session.flush()
    channels.ensure_source(line)
    crm.save_settings(whatsapp_mode='send')
    _db.session.commit()
    return line


def wrote(name, phone, line=None, hours=1, wamid=None):
    lead = crm.capture('ti-quote', name=name, phone=phone, utm={})
    crm.log_touch(lead, 'whatsapp', 'in', body='Hello from %s' % name, external_id=wamid or 'wamid.' + phone[-6:],
                  at=datetime.utcnow() - timedelta(hours=hours), line_id=line.id if line else None)
    _db.session.commit()
    return lead


def test_each_number_has_a_country_code_a_name_and_its_last_four_digits(app, two_numbers):
    crm_num, us = channels.badge(None), channels.badge(two_numbers)
    assert (crm_num['code'], crm_num['name'], crm_num['last4'], crm_num['key'], crm_num['tone']) == \
        ('IN', 'India', '1360', 'crm', 'onum0')
    assert (us['code'], us['name'], us['last4'], us['key'], us['short']) == ('US', 'USA', '5094', str(two_numbers.id),
                                                                           'USA ·5094')
    assert us['tone'] != crm_num['tone'] and us['engine'] == 'Meta direct'
    assert [b['key'] for b in channels.badges()] == ['crm', str(two_numbers.id)] and channels.several()


def test_with_one_number_there_is_nothing_to_tell_apart(app):
    access.ensure_defaults()
    assert channels.badges() == [] and not channels.several()


def test_all_conversations_names_the_number_of_every_whatsapp_row(app, client, admin_user, two_numbers):
    wrote('Anita Rao', '+919000012345')
    wrote('Ravi Kumar', '+19175550199', line=two_numbers)
    login(client, admin_user.email)
    html = unescape(client.get('/admin/crm/inbox').get_data(as_text=True))
    assert 'Our number:' in html and 'All numbers' in html
    assert 'India ·1360' in html and 'USA ·5094' in html
    only_us = unescape(client.get('/admin/crm/inbox?num=%d' % two_numbers.id).get_data(as_text=True))
    assert 'Ravi Kumar' in only_us and 'Anita Rao' not in only_us
    only_in = unescape(client.get('/admin/crm/inbox?num=crm').get_data(as_text=True))
    assert 'Anita Rao' in only_in and 'Ravi Kumar' not in only_in
    assert 'Anita Rao' in unescape(client.get('/admin/crm/inbox?num=nonsense').get_data(as_text=True))


def test_somebody_on_both_numbers_shows_the_other_one(app, client, admin_user, two_numbers):
    lead = wrote('Ravi Kumar', '+19175550199', hours=30)                      # India first
    crm.log_touch(lead, 'whatsapp', 'in', body='Now on the US number', external_id='wamid.us1',
                  at=datetime.utcnow() - timedelta(minutes=5), line_id=two_numbers.id)
    _db.session.commit()
    login(client, admin_user.email)
    html = unescape(client.get('/admin/crm/inbox').get_data(as_text=True))
    row = html.split('Ravi Kumar', 1)[1].split('</li>', 1)[0]
    assert 'USA ·5094' in row and 'Also on' in row and 'India ·1360' in row.split('Also on', 1)[1]


def test_the_lead_page_says_from_which_number_to_whom(app, client, admin_user, two_numbers):
    india = wrote('Anita Rao', '+919000012345')
    usa = wrote('Ravi Kumar', '+19175550199', line=two_numbers)
    login(client, admin_user.email)
    page = unescape(client.get('/admin/crm/lead/%d' % india.id).get_data(as_text=True))
    assert 'WhatsApp goes from' in page and 'India · +91 80191 11360' in page.split('WhatsApp goes from', 1)[1][:400]
    page = unescape(client.get('/admin/crm/lead/%d' % usa.id).get_data(as_text=True))
    box = page.split('WhatsApp goes from', 1)[1][:400]
    assert 'USA · +1 (917) 900-5094' in box and 'Ravi Kumar' in box


def test_the_timeline_names_india_too_once_there_are_two_numbers(app, two_numbers):
    from app.services import crm_timeline
    lead = wrote('Anita Rao', '+919000012345')
    items = [i for i in crm_timeline.build(lead) if i.get('kind') == 'msg']
    assert items and items[-1]['via_label'] == 'WhatsApp · India'


def test_the_panel_beside_whatsapp_chats_counts_the_24_hours_on_its_own_number(app, client, admin_user,
                                                                               two_numbers):
    """Ravi wrote to the US number an hour ago and never to India: the chat beside it (India's) is closed."""
    wrote('Ravi Kumar', '+19175550199', line=two_numbers)
    login(client, admin_user.email)
    html = unescape(client.get('/admin/messaging/lead-panel?conversation=c-9&phone=19175550199')
                    .get_data(as_text=True))
    assert 'Chat on our' in html and 'India · +91 80191 11360' in html
    assert "hasn't written on WhatsApp yet" in html and 'Free to write' not in html


def test_whatsapp_chats_names_its_number_and_links_the_others(app, client, admin_user, two_numbers):
    login(client, admin_user.email)
    html = unescape(client.get('/admin/messaging/inbox').get_data(as_text=True))
    banner = html.split('data-inbox-number', 1)[1].split('</p>', 1)[0]
    assert 'Every chat here is on our number' in banner and 'India · +91 80191 11360' in banner
    assert 'USA ·5094' in banner and 'num=%d' % two_numbers.id in banner


def test_a_website_whatsapp_button_nobody_hears_is_flagged(app, client, admin_user, two_numbers):
    offices.save_numbers([{'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': True},
                          {'label': 'USA', 'iso': 'US', 'number': '+1 917 900 5094', 'whatsapp': True},
                          {'label': 'Canada', 'iso': 'CA', 'number': '+1 (647) 770-2288', 'whatsapp': True}])
    assert [r['label'] for r in channels.unheard()] == ['Canada']
    login(client, admin_user.email)
    html = unescape(client.get('/admin/crm/channels').get_data(as_text=True))
    assert 'Canada · +1 (647) 770-2288' in html and 'nothing of ours hears that number' in html
    assert 'India ·1360' in html and 'USA ·5094' in html
