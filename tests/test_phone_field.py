"""Phone numbers: one list of dialling codes, one rule, every form.

Every form here used a bare <input type="tel"> with a hint in the placeholder, so people typed
nine digits with no country, a trunk-prefixed 0, or 0091 -- and nothing noticed until somebody
tried to ring it. The number is stored dialable now, whatever was typed.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import phone  # noqa: E402

# Every server-rendered form that asks for a number. A new one must use the shared field too,
# which is what the last test in this file is for.
FORMS = ['/contact-us', '/auth/register']


# ---------------------------------------------------------------------------
# The rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw,iso,expected', [
    ('9848000000', 'IN', '+919848000000'),          # bare national number
    ('098480 00000', 'IN', '+919848000000'),        # trunk prefix, dropped not dialled
    ('0091 98480 00000', 'IN', '+919848000000'),    # 00 is how much of the world writes +
    ('+91 98480 00000', 'IN', '+919848000000'),     # already international
    ('91 98480 00000', 'IN', '+919848000000'),      # code typed without the plus
    ('917 900 5094', 'US', '+19179005094'),
    ('416 555 0199', 'CA', '+14165550199'),         # a country the site did not used to know
])
def test_whatever_was_typed_is_stored_dialable(app, raw, iso, expected):
    assert phone.normalise(raw, iso)[0] == expected


@pytest.mark.parametrize('raw,why', [
    ('123', 'too short'),
    ('1' * 20, 'too long'),
    ('+999 12345678', 'no such dialling code'),
])
def test_a_number_nobody_could_ring_is_refused(app, raw, why):
    value, error = phone.normalise(raw, 'IN')
    assert value == '' and error, why


def test_an_empty_number_is_not_an_error(app):
    """Most of these fields are optional; whether a missing one matters is the caller's call."""
    assert phone.normalise('', 'IN') == ('', None)


def test_the_country_is_chosen_not_guessed(app):
    """The same digits mean different numbers in different countries, which is exactly why the
    picker exists rather than a parser."""
    assert phone.normalise('9848000000', 'IN')[0] == '+919848000000'
    assert phone.normalise('9848000000', 'US')[0] == '+19848000000'


def test_the_picker_offers_the_common_ones_first(app):
    popular, rest = phone.choices()
    assert [c['iso'] for c in popular][:3] == ['IN', 'US', 'CA']
    assert len(popular) + len(rest) == len(phone.BY_ISO)
    assert all(c['dial'].isdigit() for c in rest)


# ---------------------------------------------------------------------------
# The field
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('path', FORMS)
def test_every_form_uses_the_shared_field(client, db, path):
    html = client.get(path).data.decode()
    assert 'data-phone-field' in html, path
    assert 'name="phone_cc"' in html, path
    assert 'phone-field.js' in html, path


@pytest.mark.parametrize('path', FORMS)
def test_the_picker_carries_the_dialling_code(client, db, path):
    """The browser check reads it off the chosen option, so there is no second copy of the
    country table in JavaScript."""
    html = client.get(path).data.decode()
    field = html.split('data-phone-field', 1)[1]
    assert 'data-dial="91"' in field and 'data-dial="1"' in field


def test_no_form_is_left_with_a_bare_phone_box(client, db):
    """A new form that asks for a number has to use the field, or it is back to nine digits and
    no country."""
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'app', 'templates')
    offenders = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith('.html'):
                continue
            path = os.path.join(folder, name)
            body = open(path, encoding='utf-8').read()
            for m in re.finditer(r'<input[^>]*name="phone"[^>]*>', body):
                offenders.append(os.path.relpath(path, root) + ': ' + m.group(0)[:70])
    assert not offenders, 'bare phone inputs left: %s' % offenders


def test_what_the_contact_form_stores_is_dialable(app, db, client):
    from app.models import ContactMessage
    client.post('/contact-us', data={
        'name': 'Asha', 'email': 'a@example.com', 'message': 'Please ring me back.',
        'phone': '09848000000', 'phone_cc': 'IN'})
    assert ContactMessage.query.one().phone == '+919848000000'


def test_a_number_from_another_country_survives_the_form(app, db, client):
    from app.models import ContactMessage
    client.post('/contact-us', data={
        'name': 'Ravi', 'email': 'r@example.com', 'message': 'Please ring me back.',
        'phone': '416 555 0199', 'phone_cc': 'CA'})
    assert ContactMessage.query.one().phone == '+14165550199'
