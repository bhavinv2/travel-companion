"""The travel-insurance landing page, and the places its content is managed from.

The page was a separate React project; it now lives in this app at /travel-insurance. What
these tests protect is the part that made it worth merging rather than linking: nothing on the
page is hard-coded any more. Testimonials come from the admin screen, questions come from the
same Help & FAQ screen the rest of the site uses, and an enquiry lands in the one inbox CS
already works from instead of a second system nobody remembers to check.
"""
from datetime import date, timedelta

import pytest

from conftest import login
from app import db as _db
from app.models import ContactMessage, InsuranceQuote
from app.services import help_center, insurance_page


@pytest.fixture()
def insurance_faq(app, db):
    """One FAQ filed under the insurance category, the way the admin screen would save it."""
    cats = help_center.categories() + [{'key': insurance_page.FAQ_CATEGORY, 'title': 'Travel insurance',
                                        'icon': 'fa-shield-halved', 'blurb': 'Cover and claims'}]
    faqs = help_center.faqs() + [
        {'id': 'ti-visitor', 'category': insurance_page.FAQ_CATEGORY,
         'question': 'What is visitor insurance?',
         'answer': 'Travel medical cover for people visiting another country.'}]
    help_center.save(cats, faqs)
    return faqs


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def test_the_page_is_served_from_this_app(client, db):
    r = client.get('/travel-insurance')
    assert r.status_code == 200
    html = r.data.decode()
    assert 'Travel Insurance for Every Journey' in html
    # inside the site's own shell, not a standalone build
    assert 'nav-logo' in html and 'travel-insurance.css' in html
    # the ported stylesheet is scoped, or it would fight the site's own
    assert 'class="ti-page"' in html


def test_the_pages_images_are_served_locally(client, db):
    """They were base64-inlined into one 1.3 MB file; a page that heavy is a page nobody waits for."""
    html = client.get('/travel-insurance').data.decode()
    assert 'data:image' not in html
    assert '/static/img/insurance/' in html


def test_questions_come_from_the_admin_help_centre(client, db, insurance_faq):
    html = client.get('/travel-insurance').data.decode()
    assert 'What is visitor insurance?' in html
    # rendered by the server: a question built by script after load is invisible to search engines
    assert 'faqList' in html and 'Travel medical cover' in html


def test_only_the_insurance_questions_appear(client, db, insurance_faq):
    """The help centre holds every FAQ on the site; this page shows its own category."""
    html = client.get('/travel-insurance').data.decode()
    other = [f for f in help_center.faqs() if f['category'] != insurance_page.FAQ_CATEGORY]
    assert other, 'fixture should leave some non-insurance FAQs'
    assert other[0]['question'] not in html


def test_the_public_never_sees_invented_customers(client, db, cs_user):
    """Three made-up testimonials on an insurance page cost more trust than no section at all,
    so until real ones are entered the section is simply absent for visitors."""
    html = client.get('/travel-insurance').data.decode()
    assert html.count('card lift rev') == 0
    assert 'What Travellers Say' not in html

    # staff can still see the samples, so the section can be previewed before it is filled
    login(client, 'cs@test.com')
    staff_html = client.get('/travel-insurance').data.decode()
    assert staff_html.count('card lift rev') == 3
    assert 'Sample reviews' in staff_html


def test_no_placeholder_contact_details_are_published(client, db):
    """[support@domain] on an insurance page does more damage than any design flaw."""
    import re
    html = client.get('/travel-insurance').data.decode()
    # scripts and styles are not visible text, and their comments legitimately mention example.com
    html = re.sub(r'<(script|style)\b.*?</\1>', ' ', html, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', html)
    for junk in ('[support@domain]', '[+91 00000 00000]', '[Name]', 'example.com'):
        assert junk not in text, junk
    assert 'support@' in text                       # the real one is there instead


def test_the_price_line_and_assurances_only_appear_once_set(client, db):
    """Both are claims about the business. Nothing is invented on its behalf: an empty setting
    renders nothing rather than a plausible-sounding default."""
    html = client.get('/travel-insurance').data.decode()
    assert 'ti-price' not in html and 'ti-assure' not in html

    insurance_page.save_page('Plans from $1.20 a day',
                             ['Policy documents by e-mail within minutes', 'Free look period'])
    html = client.get('/travel-insurance').data.decode()
    assert 'Plans from $1.20 a day' in html
    assert html.count('<li><svg class="ico sm"') == 2


def test_the_page_speaks_with_one_cta_vocabulary(client, db):
    """Seven different ways to say the same thing reads as indecision, not choice."""
    import re
    html = client.get('/travel-insurance').data.decode()
    for stale in ('Get Your Free Quote', 'Check Your Coverage Options',
                  'Explore Travel Insurance Options', 'Book Your Free Consultation'):
        assert stale not in html, stale
    assert html.count('data-quote>Get a free quote') >= 3      # one primary label, repeated


def test_saved_testimonials_are_shown_to_everyone(client, db):
    insurance_page.save_reviews([
        {'quote': 'Cover sorted in ten minutes.', 'name': 'K. Rao', 'place': 'United States',
         'cc': 'us', 'tag': 'Parents visiting children', 'photo': ''}])
    html = client.get('/travel-insurance').data.decode()
    assert html.count('card lift rev') == 1
    assert 'K. Rao' in html and '>US<' in html          # country code is upper-cased on save
    assert 'Sample reviews' not in html


# ---------------------------------------------------------------------------
# Enquiries
# ---------------------------------------------------------------------------

def test_an_enquiry_lands_in_the_shared_inbox(client, db):
    r = client.post('/api/insurance-enquiry', json={
        'name': 'Asha', 'email': 'Asha@Example.com', 'phone': '+1 555 0100', 'destination': 'Canada'})
    assert r.status_code == 201 and r.get_json()['success']

    msg = ContactMessage.query.one()
    assert (msg.name, msg.email, msg.topic, msg.status) == ('Asha', 'asha@example.com', 'insurance', 'new')
    assert 'Canada' in msg.message


@pytest.mark.parametrize('bad, why', [
    ({'name': ''}, 'no name'),
    ({'email': 'nope'}, 'not an email'),
    ({'email': ''}, 'no email'),
    ({'phone': ''}, 'no phone, which is how we call them back'),
])
def test_an_incomplete_enquiry_is_refused_and_stored_nowhere(client, db, bad, why):
    body = {'name': 'Asha', 'email': 'a@example.com', 'phone': '+1 555 0100'}
    body.update(bad)
    r = client.post('/api/insurance-enquiry', json=body)
    assert r.status_code == 400, why
    assert ContactMessage.query.count() == 0


# ---------------------------------------------------------------------------
# Both consoles
# ---------------------------------------------------------------------------

def _enquiry(client):
    client.post('/api/insurance-enquiry', json={'name': 'Asha', 'email': 'asha@example.com',
                                                'phone': '+1 555 0100', 'destination': 'Canada'})


def _companion_message():
    _db.session.add(ContactMessage(name='Bob', email='bob@example.com', message='About a trip'))
    _db.session.commit()


@pytest.mark.parametrize('who, url', [
    ('cs@test.com', '/cs/voices?tab=contact'),
    ('admin@test.com', '/admin/voices?tab=contact'),
])
def test_both_consoles_show_insurance_enquiries(client, db, cs_user, admin_user, who, url):
    _enquiry(client)
    _companion_message()
    login(client, who)
    html = client.get(url).data.decode()
    assert 'asha@example.com' in html and 'bob@example.com' in html
    assert 'Travel insurance' in html and 'Travel companion' in html      # the topic chips


@pytest.mark.parametrize('who, url', [
    ('cs@test.com', '/cs/voices?tab=contact&topic=%s'),
    ('admin@test.com', '/admin/voices?tab=contact&topic=%s'),
])
def test_both_consoles_can_filter_by_service(client, db, cs_user, admin_user, who, url):
    _enquiry(client)
    _companion_message()
    login(client, who)
    insurance = client.get(url % 'insurance').data.decode()
    companion = client.get(url % 'companion').data.decode()
    assert 'asha@example.com' in insurance and 'bob@example.com' not in insurance
    assert 'bob@example.com' in companion and 'asha@example.com' not in companion


@pytest.mark.parametrize('who, url', [
    ('cs@test.com', '/cs/insurance-quotes'),
    ('admin@test.com', '/admin/insurance-quotes'),
])
def test_both_consoles_see_the_insurance_leads(client, db, cs_user, admin_user, who, url):
    """CS follows these up, so the list cannot be admin-only."""
    _db.session.add(InsuranceQuote(email='lead@example.com', phone='+91 90000 00000',
                                   insurance_type='visitors', citizenship='IND',
                                   start_date=date.today() + timedelta(days=5),
                                   end_date=date.today() + timedelta(days=30),
                                   status='quoted', travellers=[{'age': '62'}]))
    _db.session.commit()
    login(client, who)
    r = client.get(url)
    assert r.status_code == 200
    assert 'lead@example.com' in r.data.decode()


def test_the_leads_list_is_not_public(client, db, user):
    assert client.get('/cs/insurance-quotes').status_code in (301, 302)
    login(client, 'bob@test.com')
    assert client.get('/cs/insurance-quotes').status_code in (302, 403)


# ---------------------------------------------------------------------------
# The admin screen behind the testimonials
# ---------------------------------------------------------------------------

def test_admin_saves_testimonials_and_drops_the_blanks(client, db, admin_user):
    login(client, 'admin@test.com')
    assert client.get('/admin/insurance-page').status_code == 200

    r = client.post('/admin/insurance-page', data={
        'id': ['', '', ''],
        'quote': ['Cover sorted in ten minutes.', '', 'A second real one'],
        'name': ['K. Rao', '', 'M. Iyer'], 'place': ['United States', '', 'Australia'],
        'cc': ['us', '', 'au'], 'tag': ['Parents', '', 'Family trip'], 'photo': ['', '', ''],
    }, follow_redirects=True)
    assert r.status_code == 200 and 'Saved 2 testimonials' in r.data.decode()

    saved = insurance_page.reviews()
    assert [s['name'] for s in saved] == ['K. Rao', 'M. Iyer']
    assert all(s['id'] for s in saved), 'every row needs a stable id'
    assert not insurance_page.is_using_samples()


def test_the_testimonial_screen_is_admin_only(client, db, cs_user):
    login(client, 'cs@test.com')
    assert client.get('/admin/insurance-page').status_code in (302, 403)
