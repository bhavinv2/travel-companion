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
