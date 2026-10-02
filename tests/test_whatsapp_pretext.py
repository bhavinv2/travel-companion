"""WhatsApp links open with the first line already written.

Somebody who taps a button and lands on an empty chat usually types nothing -- the first line is
the hardest one. It also tells whoever answers which page the message came from, which no amount
of "Hi" does.
"""
import os
import sys
from urllib.parse import parse_qs, unquote, urlparse

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import offices  # noqa: E402


@pytest.fixture()
def two_numbers(app, db):
    offices.save_numbers([
        {'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360', 'whatsapp': True, 'sites': []},
        {'label': 'USA', 'iso': 'US', 'number': '+1 917 900 5094', 'whatsapp': False, 'sites': []},
    ])


def opener(href):
    return unquote(parse_qs(urlparse(href).query).get('text', [''])[0])


def test_the_link_carries_an_opener(app, db):
    offices.save_numbers([{'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360',
                           'whatsapp': True, 'sites': []}])
    link = offices.wa_link('contact')
    assert link.startswith('https://wa.me/918019111360?text=')
    assert 'NRI Parent Service' in opener(link)


def test_each_product_says_what_it_is_about(app, db):
    offices.save_numbers([{'label': 'India', 'iso': 'IN', 'number': '+91 80191 11360',
                           'whatsapp': True, 'sites': []}])
    assert 'travel insurance' in opener(offices.wa_link('insurance')).lower()
    assert 'travel companion' in opener(offices.wa_link('companion')).lower()
    assert 'sahayak' in opener(offices.wa_link('sahayak')).lower()


def test_one_line_replaces_the_lot(app, db, monkeypatch):
    """So whoever runs this does not need a deploy to change what it says."""
    monkeypatch.setenv('WHATSAPP_GREETING', 'Namaste! How can we help?')
    assert offices.greeting('insurance') == 'Namaste! How can we help?'


def test_nothing_published_means_no_link(app, db):
    offices.save_numbers([])
    assert offices.wa_link('contact') == ''


def test_every_link_on_the_contact_page_has_one(client, db, two_numbers):
    import re
    html = client.get('/contact-us').data.decode()
    links = re.findall(r'href="(https://wa\.me/[^"]+)"', html)
    assert links, 'the page should offer WhatsApp'
    for href in links:
        assert 'text=' in href, href


def test_the_shared_chooser_has_one_too(client, db, two_numbers):
    import re
    html = client.get('/help').data.decode()
    links = re.findall(r'href="(https://wa\.me/[^"]+)"', html)
    assert links
    for href in links:
        assert 'text=' in href, href


def test_the_form_button_is_rebuilt_from_what_was_typed(client, db, two_numbers):
    """Not on click: a tap opens the new tab immediately, and an href edited in the click
    handler can be read before it is updated."""
    html = client.get('/contact-us').data.decode()
    assert 'id="cuWaSend"' in html and 'data-wa-base=' in html
    assert "form.addEventListener('input', build)" in html
