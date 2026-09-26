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


def test_a_support_request_carries_what_they_actually_asked(client, db):
    """The Support popup is the one form with a message box. CS has to see the question, what it
    was about and how the person wants to be reached, or the record is just another name."""
    r = client.post('/api/insurance-enquiry', json={
        'kind': 'support', 'name': 'Ravi', 'email': 'ravi@example.com', 'phone': '+91 98765 43210',
        'subject': 'Pre-existing conditions', 'preferred': 'WhatsApp',
        'message': 'My father has a heart condition. Which plan covers him in Dallas?'})
    assert r.status_code == 201 and r.get_json()['success']

    msg = ContactMessage.query.one()
    assert msg.topic == 'insurance'                 # same inbox, same tag as every other enquiry
    assert 'Support request' in msg.message
    assert 'Pre-existing conditions' in msg.message
    assert 'Preferred contact: WhatsApp' in msg.message
    assert 'heart condition' in msg.message


def test_a_support_request_needs_an_actual_question(client, db):
    """A two-word message gives CS nothing to answer, so it is refused rather than filed."""
    r = client.post('/api/insurance-enquiry', json={
        'kind': 'support', 'name': 'Ravi', 'email': 'ravi@example.com',
        'phone': '+91 98765 43210', 'message': 'help'})
    assert r.status_code == 400
    assert ContactMessage.query.count() == 0

    # the lead forms have no message box at all, so the rule must not reach them
    r = client.post('/api/insurance-enquiry', json={
        'name': 'Ravi', 'email': 'ravi@example.com', 'phone': '+91 98765 43210'})
    assert r.status_code == 201


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


def test_the_brand_line_names_this_product(client, db):
    """On its own page the logo reads "Travel Insurance"; everywhere else it is the group line.
    Getting this wrong would tell a visitor they had wandered off the page they came for."""
    assert 'logo-sub">Travel Insurance<' in client.get('/travel-insurance').data.decode()
    assert 'logo-sub">Connecting Desis<' in client.get('/help').data.decode()


def test_support_still_works_without_javascript(client, db):
    """The popup is an enhancement. The link underneath it has to be a real destination, or
    somebody with a blocked bundle has no way to reach us at all."""
    html = client.get('/travel-insurance').data.decode()
    assert 'id="navSupport"' in html and 'href="/help"' in html
    assert client.get('/help').status_code == 200


# ---------------------------------------------------------------------------
# Being found at all
# ---------------------------------------------------------------------------

def test_the_page_describes_itself_to_search_engines(client, db):
    """With no description Google writes its own out of whatever text it finds first, which on a
    page that opens with a form is the field labels."""
    html = client.get('/travel-insurance').data.decode()
    m = re.search(r'<meta name="description" content="([^"]+)"', html)
    assert m, 'no meta description'
    assert 'compare 65+' in m.group(1).lower()
    # and it is this page's own, not the site-wide default
    assert 'companion' not in m.group(1).lower()


def test_the_structured_data_declares_the_questions_the_page_shows(client, db, insurance_faq):
    """Schema promising an answer the page does not display is what earns a manual penalty, so
    the two are generated from one list."""
    html = client.get('/travel-insurance').data.decode()
    blob = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert blob, 'no JSON-LD'
    graph = {n['@type']: n for n in json.loads(blob.group(1))['@graph']}
    assert set(graph) == {'Organization', 'WebPage', 'Service', 'FAQPage'}

    shown = {f['question'] for f in injected(client)[0]['faqs']}
    declared = {q['name'] for q in graph['FAQPage']['mainEntity']}
    assert declared == shown
    assert 'What is visitor insurance?' in declared        # the admin one, from the fixture


def test_no_rating_is_invented_in_the_structured_data(client, db):
    """An aggregateRating with no verified reviews behind it is a lie told to a search engine."""
    html = client.get('/travel-insurance').data.decode()
    blob = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert 'aggregateRating' not in blob.group(1)
    assert 'reviewCount' not in blob.group(1)


def test_the_default_questions_answer_what_the_page_was_missing(client, db):
    """With nothing filed in admin the page still has to answer the questions somebody actually
    has before buying -- exclusions, pre-existing conditions, waiting periods, claiming."""
    faqs = injected(client)[0]['faqs']
    asked = ' '.join(f['question'].lower() for f in faqs)
    for topic in ('not covered', 'pre-existing', 'waiting period', 'claim', 'when should i buy'):
        assert topic in asked, topic
    # and every answer defers to the policy rather than promising specifics we cannot know
    assert any('policy wording' in f['answer'].lower() for f in faqs)


def test_the_page_is_in_the_sitemap(client, db):
    """It was not, which is most of why nothing found it."""
    xml = client.get('/sitemap.xml').data.decode()
    assert '/travel-insurance<' in xml
    assert '/sahayak<' in xml


def test_the_services_menu_links_to_our_own_page_internally(client, db):
    """It pointed at the production URL with a trailing slash: a redirect on every click, and on
    staging or locally a link that leaves the site altogether."""
    html = client.get('/help').data.decode()
    assert 'href="/travel-insurance"' in html
    assert 'nriparentservice.com/travel-insurance' not in html


def test_the_price_line_is_never_invented(client, db):
    """It is a claim about the business. Empty until staff make it; then it shows."""
    data, _ = injected(client)
    assert data['priceFrom'] == '' and data['assurances'] == []

    insurance_page.save_page('from $1.20 a day', ['Policy documents by e-mail within minutes'])
    data, _ = injected(client)
    assert data['priceFrom'] == 'from $1.20 a day'
    assert data['assurances'] == ['Policy documents by e-mail within minutes']


def test_the_page_speaks_with_one_cta_vocabulary(db):
    """There are two actions on this page -- get priced, or reach a person. There were eight
    labels for them, which reads as indecision and stops a repeated CTA building any
    recognition. Checked in the source, because it is the source that drifts."""
    import os
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'frontend', 'insurance', 'src', 'components')
    text = ''
    for name in sorted(os.listdir(root)):
        if name.endswith('.tsx'):
            text += open(os.path.join(root, name), encoding='utf-8').read()

    for stale in ('Get free quotes', 'Get Your Free Quote', 'Get Quotes',
                  'Check Your Coverage Options', 'Book Your Free Consultation',
                  'Get a Consultation', 'Book Consultation Now'):
        assert stale not in text, stale
    assert text.count('Get a Free Quote') >= 5
    assert text.count('Talk to an Expert') >= 3


def test_the_date_field_is_left_to_the_browser(db):
    """"Coverage ends" used to have a hand-drawn dd-mm-yyyy hint positioned over it, with the
    native text forced transparent whenever React believed the field was empty.

    That made the display depend on a React copy of the value agreeing with the DOM, and when they
    disagreed the field showed a placeholder on top of a date somebody had just picked -- it looked
    empty until you clicked back into it. The browser already knows whether a date input is empty.
    """
    import os
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'frontend', 'insurance', 'src')
    css = open(os.path.join(root, 'styles', 'global.css'), encoding='utf-8').read()
    form = open(os.path.join(root, 'components', 'InsuranceQuoteForm.tsx'), encoding='utf-8').read()

    assert 'date-ph' not in css and 'date-ph' not in form
    assert 'is-empty' not in css and 'is-empty' not in form
    assert '::-webkit-datetime-edit' not in css


def test_a_focused_field_is_not_drawn_a_box_around(db):
    """The site shell this page is embedded in styles every input[type=...]:focus with a 3.5px
    ring in its own blue, !important, which out-specifies a plain .inp:focus. Focus is shown by
    the border colour instead -- #DCE3F0 to #004EFE on a 1.5px border, which is change enough."""
    import os
    css = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'frontend', 'insurance', 'src', 'styles', 'global.css')
    text = open(css, encoding='utf-8').read()

    assert '#root input:focus, #root select:focus, #root textarea:focus{box-shadow:none}' in text
    assert '#root .inp:focus' in text and 'border-color:var(--blue) !important' in text
    # no glow rings left on any field -- including the country combo's button, which looks
    # like one. (.vpin is a pulsing map marker, not a field, and keeps its ring.)
    for selector in ('.inp:focus', '.xinp:focus', '.idest-btn:focus-visible'):
        rule = text.split(selector, 1)[1].split('}', 1)[0]
        assert 'box-shadow' not in rule, selector


def test_the_quote_form_has_no_client_side_partner_url(db):
    """The page used to fall back to a URL built in the browser whenever our endpoint did not
    answer -- and that URL is /get-travel-insurance-quotes/, the partner's own BLANK form, not
    /retrieve-insurance-quotes/?id=..., the priced results the endpoint produces. So a validation
    error looked like success: somebody landed back on a form they had just filled in, and the
    lead was never recorded. The builder is gone; re-importing it is how this would come back."""
    import os
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'frontend', 'insurance', 'src')
    assert not os.path.exists(os.path.join(root, 'utils', 'quoteUrl.ts'))

    text = ''
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if name.endswith(('.ts', '.tsx')):
                text += open(os.path.join(dirpath, name), encoding='utf-8').read()

    # Comments stripped first: the ones explaining this fix necessarily name what was removed.
    code = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    code = re.sub(r'(?m)^\s*//.*$', '', code)

    assert 'get-travel-insurance-quotes' not in code
    assert 'buildPlanQuoteUrl' not in code
    assert 'buildQuoteUrl' not in code
    # and the results are handed over the way the companion drawer does it: a new tab, not a
    # navigation, so the page the visitor was reading survives
    assert 'window.open(url' in code
    assert 'window.location.assign' not in code


def test_the_social_profiles_are_the_current_ones(client, db):
    from app.services import nri_services
    by_label = {label: href for label, href, _icon in nri_services.SOCIAL}
    assert by_label == {
        'Facebook': 'https://www.facebook.com/profile.php?id=61590811413987',
        'LinkedIn': 'https://www.linkedin.com/company/nriparentservice/',
        'X': 'https://x.com/NRIParentHelp',
        'Instagram': 'https://www.instagram.com/nriparentservice_/',
        'YouTube': 'https://www.youtube.com/@NRIParentService',
    }
    html = client.get('/help').data.decode()
    for href in by_label.values():
        assert href in html, href
    assert '61590630328535' not in html          # the superseded Facebook page


def test_the_insurance_page_keeps_a_warm_accent(db):
    """The design carries two accents -- blue for actions, a warm one for the handwritten asides.
    --marigold had been set to the same blue as --blue, which flattened the page to one colour and
    left it sharing nothing with the amber the shared navbar is built on."""
    import os
    css = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'frontend', 'insurance', 'src', 'styles', 'global.css')
    text = open(css, encoding='utf-8').read()
    assert '--marigold:#004EFE' not in text      # the same blue as --blue
    assert '--marigold:#B76C0C' in text


def test_the_quote_cta_is_not_repeated_into_noise(db):
    """The page had 13 controls all saying "Get a Free Quote" and all doing the same thing --
    EIGHT of them at one scroll position, one inside every card of "Why You Need Travel
    Insurance". Repeating a CTA down a long page is right; eight times in one section is not a
    second chance, it is noise.

    Four remain, one per stage of the argument: the quote form, after the visitor-insurance
    explainer, after the four steps, and the close. Counted in the source because a card CTA
    inside a .map() is one line away from becoming eight again.
    """
    import os
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'frontend', 'insurance', 'src', 'components')
    per_file = {}
    for name in sorted(os.listdir(root)):
        if name.endswith('.tsx'):
            body = open(os.path.join(root, name), encoding='utf-8').read()
            body = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
            body = re.sub(r'(?m)^\s*//.*$', '', body)
            n = body.count('Get a Free Quote')
            if n:
                per_file[name] = n

    # Header renders only in the standalone build, and carries two -- the desktop nav and the
    # mobile drawer, which are the same control at two widths. The other four are the page's
    # own rhythm, one per stage of the argument.
    assert per_file == {
        'FinalCTA.tsx': 1,
        'Header.tsx': 2,
        'HowItWorks.tsx': 1,
        'InsuranceQuoteForm.tsx': 1,
        'VisitorInsurance.tsx': 1,
    }, per_file

    # the two that were removed, and the card button in particular
    whyrail = open(os.path.join(root, 'WhyRail.tsx'), encoding='utf-8').read()
    assert 'wtile-cta' not in whyrail
    assert 'openQuote' not in whyrail


def test_the_date_fields_are_left_uncontrolled(db):
    """"The coverage end date must be on or after the start date" was the server correctly
    describing an EMPTY field. The visitor had picked one, but `value={end}` meant every later
    keystroke in the form re-rendered the input and wrote '' back over their date -- so it
    vanished between choosing it and pressing the button.

    The browser owns these values now; React reads them from refs on submit.
    """
    import os
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'frontend', 'insurance', 'src', 'components', 'InsuranceQuoteForm.tsx')
    src = open(p, encoding='utf-8').read()
    dates = re.findall(r'<input\b[^>]*type="date"[^>]*(?:/>|>)', src, re.S)
    assert len(dates) == 2, len(dates)
    for tag in dates:
        assert 'ref={' in tag, tag[:90]
        assert re.search(r'\bvalue=\{', tag) is None, 'a controlled date field is back: ' + tag[:90]
    # and submit reads the fields, not the mirrored state
    assert 'startRef.current?.value' in src and 'endRef.current?.value' in src


def test_no_bare_number_can_leak_into_the_quote_form(db):
    """`{'' || list.length && <x/>}` renders 0 as text when the list is empty -- which is where a
    stray "0" above the quote button came from."""
    import os
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'frontend', 'insurance', 'src', 'components', 'InsuranceQuoteForm.tsx')
    src = open(p, encoding='utf-8').read()
    assert 'Boolean(site.priceFrom || site.assurances?.length)' in src
    assert '{(site.priceFrom || site.assurances?.length) &&' not in src


def test_the_site_widgets_leave_the_react_app_alone(db):
    """searchselect.js wraps every <select> on the page in its own button+popup, and it watches
    the whole body -- so it caught the ones the bundle renders inside its modals, replacing a
    working control with a hidden select and a widget it positioned itself. It also writes back to
    select.value directly, which React never hears."""
    import os
    js = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'app', 'static', 'js', 'searchselect.js')
    text = open(js, encoding='utf-8').read()
    assert "if (sel.closest('#root')) return;" in text


def test_a_modal_covers_the_whatsapp_button(db):
    """At z-index 9010 it floated on top of every open dialog -- which is why CountryCombo carries
    code to dodge it when placing a popover."""
    import os
    css = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'frontend', 'insurance', 'src', 'styles', 'global.css')
    text = open(css, encoding='utf-8').read()
    fab = int(re.search(r'\.wafab\{[^}]*z-index:(\d+)', text).group(1))
    overlay = int(re.search(r'\.ov\{[^}]*z-index:(\d+)', text).group(1))
    assert fab < overlay, 'FAB %d should sit under the overlay %d' % (fab, overlay)
