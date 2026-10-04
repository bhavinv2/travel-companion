"""The group's contact page at /contact-us.

It replaces a page on the old WordPress site, so it has to carry the same facts -- five offices,
two helplines, an e-mail -- and it has to be reachable at the address those are printed against.

What is worth protecting is that the facts have ONE source. The same addresses appear on this
page, in the structured data and in the footer, and the moment one of them is a literal in a
template the three start to disagree.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import ContactMessage  # noqa: E402
from app.services import contact_form, offices  # noqa: E402


def test_the_page_answers(client, db):
    assert client.get('/contact-us').status_code == 200


def test_every_office_is_on_it(client, db):
    html = client.get('/contact-us').data.decode()
    for office in offices.all_offices():
        assert office['label'] in html, office['label']
        assert office['street'] in html, office['street']
    assert html.count('class="cu-office') >= 5


def test_the_ways_to_reach_us_are_all_actionable(client, db):
    """A phone number you cannot tap and an address you cannot click are decoration on a page
    whose entire job is being contacted."""
    html = client.get('/contact-us').data.decode()
    for line in offices.helplines():
        assert 'tel:+%s' % line['digits'] in html, line['label']
        assert line['display'] in html
    assert 'mailto:%s' % offices.email() in html
    assert 'wa.me/%s' % offices.whatsapp() in html


def test_it_asks_what_the_popup_asks(client, db):
    """Same fields, from the same lists, so an enquiry reaches CS looking the same whichever
    form somebody found."""
    html = client.get('/contact-us').data.decode()
    for topic in contact_form.TOPICS:
        assert topic in html, topic
    for via in contact_form.VIA:
        assert 'value="%s"' % via in html, via
    for field in ('name="name"', 'name="email"', 'name="phone"', 'name="message"',
                  'name="topic"', 'name="via"', 'name="time"', 'name="zone"'):
        assert field in html, field


def test_sending_a_message_reaches_the_shared_inbox(client, db):
    r = client.post('/contact-us', data={
        'name': 'Asha Reddy', 'email': 'asha@example.com', 'phone': '+91 90000 00000',
        'topic': 'Travel insurance', 'via': 'WhatsApp', 'time': 'Any time',
        'zone': 'India (IST)', 'message': 'Please call me about cover for my parents.',
    }, follow_redirects=True)
    assert r.status_code == 200

    msg = ContactMessage.query.one()
    assert (msg.name, msg.email) == ('Asha Reddy', 'asha@example.com')
    # the preferences travel with it, composed by the server rather than the browser
    assert 'Topic: Travel insurance' in msg.message
    assert 'Preferred contact: WhatsApp' in msg.message
    assert 'Please call me about cover' in msg.message


def test_a_half_filled_form_comes_back_with_what_was_typed(client, db):
    r = client.post('/contact-us', data={'name': 'Asha', 'email': '', 'message': 'hello there',
                                         'topic': 'Travel insurance'})
    assert r.status_code == 200, 'it should redraw, not redirect'
    assert ContactMessage.query.count() == 0
    html = r.data.decode()
    assert 'value="Asha"' in html
    assert 'hello there' in html


def test_an_invented_choice_is_not_stored(client, db):
    """The choices are rendered from a list, so anything else did not come from the form."""
    client.post('/contact-us', data={
        'name': 'Asha', 'email': 'a@example.com', 'message': 'A long enough message.',
        'phone': '917 900 5094', 'phone_cc': 'US',
        'topic': '<script>alert(1)</script>', 'via': 'Carrier pigeon'})
    msg = ContactMessage.query.one()
    assert 'script' not in msg.message
    assert 'pigeon' not in msg.message


# ---------------------------------------------------------------------------
# One address for it
# ---------------------------------------------------------------------------

def test_the_old_address_leads_to_the_new_one(client, db):
    r = client.get('/contact')
    assert r.status_code == 301
    assert r.headers['Location'].endswith('/contact-us')


def test_an_old_form_still_posting_to_it_does_not_lose_the_message(client, db):
    """Somebody with the previous page open in a tab. Losing what they wrote to a redirect would
    be the worst possible moment for it."""
    r = client.post('/contact', data={'name': 'Ravi', 'email': 'r@example.com',
                                      'message': 'Sent from an old tab.'},
                    follow_redirects=True)
    assert r.status_code == 200
    assert ContactMessage.query.one().name == 'Ravi'


def test_it_is_offered_as_its_own_front_door(app):
    """Printed on cards and in ads, so it answers beside the app's prefix like the other two."""
    assert '/contact-us' in app.config['APP_ALIAS_PATHS']


def test_search_engines_are_told_where_it_lives(client, db):
    html = client.get('/contact-us').data.decode()
    assert '<link rel="canonical"' in html
    assert '/contact-us' in client.get('/sitemap.xml').data.decode()


# ---------------------------------------------------------------------------
# One source for the facts
# ---------------------------------------------------------------------------

def test_the_head_office_is_the_one_the_schema_claims(client, db):
    """The address a search engine is told and the address a visitor reads are the same string,
    because they are read from the same place."""
    from app.services import org
    with client.application.test_request_context('/'):
        schema = org.address()
    assert schema['streetAddress'] == offices.headquarters()['street']
    assert schema['streetAddress'] in client.get('/contact-us').data.decode()


def test_an_office_with_no_street_is_left_out(app, monkeypatch):
    """A heading with nothing under it is worse than one fewer card."""
    monkeypatch.setenv('OFFICE_UK_STREET', '')
    labels = [o['label'] for o in offices.all_offices()]
    assert 'United Kingdom' not in labels
    assert 'Head Quarters' in labels


def test_a_number_too_short_to_dial_is_not_published(app, db):
    """Dropped on save rather than printed. A button that dials nothing is worse than no button."""
    offices.save_numbers([
        {'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': True, 'sites': []},
        {'label': 'Typo', 'iso': 'US', 'number': '+1', 'whatsapp': False, 'sites': []},
    ])
    assert [n['label'] for n in offices.numbers()] == ['India']


def test_a_country_can_be_added_without_touching_the_code(app, db):
    """The whole point of the list: Canada is a row."""
    offices.save_numbers([
        {'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': True, 'sites': []},
        {'label': 'Canada', 'iso': 'CA', 'number': '416 555 0199', 'whatsapp': False, 'sites': []},
    ])
    rows = {n['label']: n for n in offices.numbers()}
    assert set(rows) == {'India', 'Canada'}
    assert rows['Canada']['e164'] == '+14165550199', 'stored dialable, whatever was typed'


def test_a_number_can_be_shown_on_one_page_only(app, db):
    offices.save_numbers([
        {'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': True, 'sites': []},
        {'label': 'Canada', 'iso': 'CA', 'number': '416 555 0199', 'whatsapp': False,
         'sites': ['contact']},
    ])
    assert [n['label'] for n in offices.numbers('contact')] == ['India', 'Canada']
    assert [n['label'] for n in offices.numbers('insurance')] == ['India']


# ---------------------------------------------------------------------------
# The artwork
# ---------------------------------------------------------------------------

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'app', 'static')
# contact/ is this page's own artwork; flags/ is shared with the WhatsApp chooser, which is on
# every page of the site.
ART_RE = r'/static/img/((?:contact|flags)/[a-z0-9-]+\.webp)'


def test_every_picture_the_page_asks_for_exists(client, db):
    """A misspelt filename is invisible in the markup and invisible in a template assertion --
    it is only a hole on the page. These are rendered from services/offices, so a new office
    naming a file nobody added fails here instead of in production."""
    import re
    html = client.get('/contact-us').data.decode()
    names = set(re.findall(ART_RE, html))
    assert names, 'the page should be using the artwork'
    missing = [n for n in sorted(names)
               if not os.path.exists(os.path.join(STATIC, 'img', *n.split('/')))]
    assert missing == [], missing


def test_the_chooser_everywhere_else_uses_the_same_flags(client, db, admin_user):
    """"Which team would you like to reach?" drew the emoji, which on Windows is the country's
    two letters in a box -- the one platform where a picture was most needed."""
    import re
    offices.save_numbers([
        {'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': True, 'sites': []},
        {'label': 'Canada', 'iso': 'CA', 'number': '+1 (647) 770-2288', 'whatsapp': False,
         'sites': []},
    ], admin_user)
    html = client.get('/').data.decode()
    chooser = html.split('id="waChooser"', 1)[1].split('</div>', 1)[0] + \
        html.split('id="waChooser"', 1)[1][:3000]
    for name in ('flags/flag-india.webp', 'flags/flag-canada.webp'):
        assert name in chooser, name
    missing = [n for n in set(re.findall(ART_RE, html))
               if not os.path.exists(os.path.join(STATIC, 'img', *n.split('/')))]
    assert missing == [], missing


def test_a_country_with_no_artwork_still_gets_a_marker(client, db, admin_user):
    """An empty circle says nothing. The two letters at least name the country."""
    offices.save_numbers([
        {'label': 'Nepal', 'iso': 'NP', 'number': '+977 9801 234567', 'whatsapp': True,
         'sites': []},
        {'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': False,
         'sites': []},
    ], admin_user)
    html = client.get('/').data.decode()
    assert 'flags/flag-nepal.webp' not in html
    assert 'class="wa-flag flag-txt"' in html


def test_an_office_with_no_photograph_of_its_own_still_gets_one(client, db):
    """There is no picture of the UK office. A card with an empty frame is worse than a card
    with the generic skyline in it."""
    uk = [o for o in offices.all_offices() if o['key'] == 'uk'][0]
    assert uk['photo'] == offices.FALLBACK_PHOTO
    assert uk['flag'] == '', 'no round flag for GB; the page falls back to the emoji'
    assert offices.FALLBACK_PHOTO in client.get('/contact-us').data.decode()


def test_the_pictures_are_decoration_and_say_so(client, db):
    """Every fact on this page is text. An alt on the Charminar would be read out to somebody
    on a screen reader in the middle of an address."""
    import re
    html = client.get('/contact-us').data.decode()
    tags = re.findall(r'<img[^>]*/static/img/(?:contact|flags)/[^>]*>', html)
    assert len(tags) >= 14, 'the page should be drawing the artwork'
    for tag in tags:
        assert 'alt=""' in tag and 'aria-hidden="true"' in tag, tag


def test_the_heading_counts_the_countries_it_shows(client, db, monkeypatch):
    """"Four countries, one team" over three cards is the kind of thing nobody notices for a
    year. Clearing an office has to take the number down with it."""
    assert 'Four countries, one team' in client.get('/contact-us').data.decode()
    monkeypatch.setenv('OFFICE_AU_STREET', '')
    monkeypatch.setenv('OFFICE_UK_STREET', '')
    html = client.get('/contact-us').data.decode()
    assert 'Two countries, one team' in html
    # the lead is wrapped across source lines, so compare on collapsed whitespace
    flat = ' '.join(html.lower().split())
    assert 'we work across two countries' in flat


def test_a_published_number_brings_its_flag(app, db):
    """The flag beside a helpline is looked up, not written down, so Canada arrived with one."""
    offices.save_numbers([
        {'label': 'Canada', 'iso': 'CA', 'number': '+1 (647) 770-2288', 'whatsapp': False,
         'sites': []},
        {'label': 'Nepal', 'iso': 'NP', 'number': '+977 9801 234567', 'whatsapp': False,
         'sites': []},
    ])
    rows = {n['label']: n for n in offices.numbers()}
    assert rows['Canada']['flag'] == 'flag-canada'
    assert rows['Nepal']['flag'] == '', 'no artwork for it; the page draws the emoji instead'


# ---------------------------------------------------------------------------
# "What is it about?" -- five services, and the answer files the enquiry
# ---------------------------------------------------------------------------

def test_the_list_is_short_and_about_services(client, db):
    """It was seven rows, five of them questions within the companion service, so somebody
    after insurance read past four irrelevant ones to find it."""
    assert len(contact_form.TOPICS) <= 5
    assert 'Travel companion' in contact_form.TOPICS
    assert 'Travel insurance' in contact_form.TOPICS
    html = client.get('/contact-us').data.decode()
    chosen = html.split('id="cuTopic"', 1)[1].split('</select>', 1)[0]
    assert chosen.count('<option') == len(contact_form.TOPICS)


def test_what_they_pick_decides_which_inbox_it_lands_in(client, db):
    """The choice used to be a line of text in the message body and nothing else -- every
    enquiry from this page was filed as 'general' whatever it said, so the CS console's
    insurance filter never showed any of them.

    Sahayak joined the three with a bucket of its own; "an existing booking" did not, because
    it spans all three products and the only honest inbox for it is the unfiltered one."""
    for topic, bucket in (('Travel insurance', 'insurance'),
                          ('Travel companion', 'companion'),
                          ('Sahayak - a health professional at home', 'sahayak'),
                          ('An existing booking or request', 'general'),
                          ('Something else', 'general')):
        ContactMessage.query.delete()
        client.post('/contact-us', data={
            'name': 'Asha', 'email': 'asha@example.com', 'topic': topic,
            'phone': '917 900 5094', 'phone_cc': 'US',
            'message': 'Please tell me more about this.'}, follow_redirects=True)
        msg = ContactMessage.query.one()
        assert msg.topic == bucket, topic
        assert 'Topic: %s' % topic in msg.message, 'and it still reads in the body'


def test_an_unanswered_dropdown_is_a_general_enquiry(client, db):
    client.post('/contact-us', data={'name': 'Asha', 'email': 'asha@example.com',
                                     'phone': '917 900 5094', 'phone_cc': 'US',
                                     'message': 'Please tell me more about this.'},
                follow_redirects=True)
    assert ContactMessage.query.one().topic == 'general'


def test_a_widget_inside_the_app_still_defaults_to_companion(client, db):
    """The home-page widget never asks which service; it is inside the companion app, so that
    is what it is about."""
    client.post('/api/contact', json={'name': 'Asha', 'email': 'asha@example.com',
                                      'message': 'Please tell me more about this.'})
    assert ContactMessage.query.one().topic == 'companion'


def test_the_popup_routes_the_same_way(client, db):
    """One form, one behaviour, wherever it was opened from."""
    client.post('/api/landing-contact', json={
        'name': 'Asha', 'email': 'asha@example.com', 'topic': 'Travel insurance',
        'phone': '917 900 5094', 'phone_cc': 'US',
        'message': 'Please tell me more about this.'})
    assert ContactMessage.query.one().topic == 'insurance'


def test_the_form_insists_on_a_number(client, db):
    """It offers a call back and a WhatsApp reply. Neither is possible without one, and an
    enquiry CS cannot answer the way the visitor asked is worse than one they never sent."""
    r = client.post('/contact-us', data={'name': 'Asha', 'email': 'asha@example.com',
                                         'message': 'Please tell me more about this.'})
    assert r.status_code == 200, 'it should redraw, not save'
    assert ContactMessage.query.count() == 0
    assert 'number we can call' in r.data.decode()


def test_the_popup_insists_on_one_too(client, db):
    r = client.post('/api/landing-contact', json={
        'name': 'Asha', 'email': 'asha@example.com', 'message': 'Please tell me more.'})
    assert r.status_code == 400
    assert ContactMessage.query.count() == 0


def test_the_in_app_widget_does_not(client, db):
    """It never asks for a number, so it cannot demand one."""
    r = client.post('/api/contact', json={'name': 'Asha', 'email': 'asha@example.com',
                                          'message': 'Please tell me more about this.'})
    assert r.get_json()['success']


def test_the_form_opens_on_what_most_people_write_in_about(client, db):
    from app.services import contact_form as cf
    html = client.get('/contact-us').data.decode()
    topic = html.split('id="cuTopic"', 1)[1].split('</select>', 1)[0]
    assert '<option selected>%s<' % cf.DEFAULT_TOPIC in topic
    zone = html.split('id="cuZone"', 1)[1].split('</select>', 1)[0]
    assert '<option selected>%s<' % cf.DEFAULT_ZONE in zone


def test_one_button_where_there_is_room_for_one(client, db):
    """The closing band has space for a single number. It used to print whichever was saved
    first; it prints the country the rest of the forms open on."""
    from app.services import offices, phone
    assert offices.primary('contact')['iso'] == phone.DEFAULT_ISO
    assert 'Call %s' % offices.primary('contact')['display'] in \
        client.get('/contact-us').data.decode()
