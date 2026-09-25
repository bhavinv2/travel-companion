"""The travel-insurance page, and the places its content is managed from.

The page is the React app in frontend/insurance, built into static/insurance and mounted by the
Flask template. The server hands it everything that is not marketing copy as window.__INSURANCE__
before the bundle runs, so these tests read that payload rather than the DOM -- rendering is the
bundle's job and is checked in a browser, but what the server decides is checked here.

What matters and is protected below: testimonials come from the admin screen, questions from the
same Help & FAQ screen the rest of the site uses, the quote goes through our own endpoint so the
lead is recorded, and an enquiry lands in the one inbox CS already works from.
"""
import json
import re
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

def injected(client):
    """window.__INSURANCE__ -- everything the server decides for the bundle."""
    html = client.get('/travel-insurance').data.decode()
    blob = re.search(r'window\.__INSURANCE__ = (\{.*?\});', html, re.S)
    assert blob, 'the page must hand the bundle its data'
    return json.loads(blob.group(1)), html


def test_the_page_mounts_the_react_app_inside_the_site_shell(client, db):
    data, html = injected(client)
    assert '<div id="root"></div>' in html
    assert 'insurance/travel-insurance.js' in html and 'insurance/travel-insurance.css' in html
    assert 'nav-logo' in html                      # the site's own navbar
    assert data['chrome'] is False                 # so the bundle skips its own header/footer


def test_the_built_bundle_is_committed_and_served(client, db):
    """The Railway image is Python only; the bundle is built here and committed, so it has to be
    present and reachable or the page is a blank div."""
    for path in ('/static/insurance/travel-insurance.js',
                 '/static/insurance/travel-insurance.css',
                 '/static/insurance/photos/hero-banner.jpg'):
        assert client.get(path).status_code == 200, path


def test_the_asset_base_is_resolved_at_request_time(client, db):
    """Baking the URL prefix into the bundle means a rebuild whenever it changes, and 404s on any
    deployment that uses a different one. The server states it instead."""
    data, _ = injected(client)
    assert data['assetBase'].endswith('/static/insurance/')
    assert '?' not in data['assetBase']            # static URLs carry a cache-busting ?v=


def test_questions_come_from_the_admin_help_centre(client, db, insurance_faq):
    data, _ = injected(client)
    assert {'question': 'What is visitor insurance?',
            'answer': 'Travel medical cover for people visiting another country.'} in data['faqs']


def test_only_the_insurance_questions_appear(client, db, insurance_faq):
    """The help centre holds every FAQ on the site; this page gets its own category."""
    data, _ = injected(client)
    sent = {f['question'] for f in data['faqs']}
    other = [f for f in help_center.faqs() if f['category'] != insurance_page.FAQ_CATEGORY]
    assert other, 'fixture should leave some non-insurance FAQs'
    assert other[0]['question'] not in sent


def test_the_public_never_sees_invented_customers(client, db, cs_user):
    """Three made-up testimonials on an insurance page cost more trust than no section at all,
    so until real ones are entered none are sent to the bundle."""
    data, _ = injected(client)
    assert data['reviews'] == []

    # staff still get the samples, so the section can be previewed before it is filled
    login(client, 'cs@test.com')
    data, _ = injected(client)
    assert len(data['reviews']) == 3 and data['reviewsAreSamples'] is True


def test_contact_details_come_from_settings(client, db):
    """The bundle ships a hard-coded support address and two numbers; the server overrides them,
    so the page can never advertise a mailbox or a line nobody is watching."""
    data, _ = injected(client)
    assert data['supportEmail'] == 'support@connectingdesis.com'
    # Nothing is set in a fresh install, so nothing is published. The bundle then shows what it
    # shipped with -- but the server never invents a number on the business's behalf.
    assert data['supportPhones'] == []
    assert data['whatsapp'] == ''


def test_both_support_teams_are_published_with_their_country(client, db):
    """+91 and +1 mean nothing on their own. Whoever is calling should be able to pick the team in
    their own country instead of paying for a long-distance call to the other one."""
    from app.services import settings
    settings.set_landing_settings({'whatsapp_in': '+91 80191 11360', 'whatsapp_us': '+1 917 900 5094'})

    data, _ = injected(client)
    assert [p['label'] for p in data['supportPhones']] == ['India', 'USA']
    india = data['supportPhones'][0]
    assert india['display'] == '+91 80191 11360'   # as staff typed it, for reading
    assert india['digits'] == '918019111360'       # digits only, for tel: and wa.me
    # the forms' WhatsApp hand-off uses the first team
    assert data['whatsapp'] == '918019111360'


def test_a_cleared_number_stops_being_published(client, db):
    """Taking a line out of the admin screen has to take it off the page, or the page keeps
    advertising a number that now rings nowhere."""
    from app.services import settings
    settings.set_landing_settings({'whatsapp_in': '+91 80191 11360', 'whatsapp_us': ''})

    data, _ = injected(client)
    assert [p['label'] for p in data['supportPhones']] == ['India']


def test_the_quote_goes_through_our_own_endpoint(client, db):
    """The page used to send people straight to the partner, which left no record of who asked.
    Routing it through /api/insurance-quote records the lead and uses the parameters we have
    verified against the partner's widget."""
    data, _ = injected(client)
    assert data['quoteUrl'].endswith('/api/insurance-quote')
    # the browser has to speak ISO-3 to that endpoint, so the server ships the lookup
    assert data['countries']['United States'] == 'USA'
    assert data['countries']['India'] == 'IND'


def test_the_enquiry_endpoint_is_handed_over_with_a_csrf_token(client, db):
    """Both lead forms POST to it; without the token every submission would be rejected."""
    data, _ = injected(client)
    assert data['enquiryUrl'].endswith('/api/insurance-enquiry')
    assert data['csrfToken']


def test_the_react_source_lives_in_this_repo(db):
    """One codebase: the page's source is here, not in a sibling project that can drift."""
    import os
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'frontend', 'insurance')
    assert os.path.isfile(os.path.join(root, 'package.json'))
    assert os.path.isfile(os.path.join(root, 'src', 'App.tsx'))
    assert os.path.isdir(os.path.join(root, 'public', 'photos'))


def test_saved_testimonials_are_shown_to_everyone(client, db):
    insurance_page.save_reviews([
        {'quote': 'Cover sorted in ten minutes.', 'name': 'K. Rao', 'place': 'United States',
         'cc': 'us', 'tag': 'Parents visiting children', 'photo': ''}])
    data, _ = injected(client)
    assert len(data['reviews']) == 1
    assert data['reviews'][0]['name'] == 'K. Rao'
    assert data['reviews'][0]['cc'] == 'US'            # upper-cased on save
    assert data['reviewsAreSamples'] is False


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
