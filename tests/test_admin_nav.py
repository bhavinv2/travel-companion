"""The admin menu, grouped by product.

It had grown to sixteen links in one flat list covering three separate products plus the settings
that apply to all of them, so somebody who came in to answer a Sahayak booking read past insurance
testimonials and colour themes to find it. The tabs pick a product; the list shows only its
screens.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login  # noqa: E402
from app.services import admin_nav  # noqa: E402


def test_every_screen_belongs_to_exactly_one_product(app):
    """A link in two tabs would suggest there are two screens behind it."""
    seen = {}
    for section in admin_nav.SECTIONS:
        for item in section['items']:
            key = item['key']
            assert key not in seen, '%s is in both %s and %s' % (key, seen.get(key), section['key'])
            seen[key] = section['key']
    assert len(seen) >= 15


def test_every_link_points_at_a_real_route(app):
    """A typo here is a 500 on every admin page, because the sidebar renders on all of them."""
    endpoints = {r.endpoint for r in app.url_map.iter_rules()}
    for section in admin_nav.SECTIONS:
        for item in section['items']:
            assert item['endpoint'] in endpoints, '%s (%s)' % (item['endpoint'], item['label'])
    assert admin_nav.DASHBOARD['endpoint'] in endpoints


def test_each_page_lights_its_own_product(app):
    assert admin_nav.section_for('listings') == 'companion'
    assert admin_nav.section_for('insurance_page') == 'insurance'
    assert admin_nav.section_for('sahayak_services') == 'sahayak'
    assert admin_nav.section_for('themes') == 'site'


def test_a_screen_reached_from_another_still_lights_its_product(app):
    """The feedback view opens from User voices and has no menu entry of its own."""
    assert admin_nav.section_for('feedback') == 'companion'


def test_an_unknown_key_still_renders_a_menu(app):
    """A new page whose author forgot to register it must not produce an empty sidebar."""
    assert admin_nav.section_for('something-new') == admin_nav.SECTIONS[0]['key']


def test_the_dashboard_is_not_filed_under_one_product(app):
    """It reports across all three, so putting it in a tab would misdescribe what it shows."""
    assert admin_nav.is_dashboard('dashboard')
    in_tabs = {i['key'] for s in admin_nav.SECTIONS for i in s['items']}
    assert 'dashboard' not in in_tabs


ITEM = re.compile(r'<a href="([^"]+)"[^>]*class="site-sw-item(?: (on))?"[^>]*>'
                  r'\s*<i[^>]*></i><span>([^<]+)</span>')


def choices(html):
    """(url, current, label) for each entry in the header's site switcher.

    It lives in the header rather than the sidebar so that both consoles carry the same control in
    the same place, and so it survives the rail being collapsed.
    """
    chunk = html.split('site-sw-menu', 1)[1]
    return [(url, bool(on), label) for url, on, label in ITEM.findall(chunk)]


def test_the_sidebar_shows_only_the_current_product(client, db, admin_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/insurance-page').data.decode()

    nav = html.split('admin-nav-items', 1)[1]
    assert 'Quote leads' in nav and 'Page content' in nav
    # ...and nothing from the other products
    for elsewhere in ('Colour themes', 'Options &amp; dropdowns', 'Bookings', 'Listings'):
        assert elsewhere not in nav, elsewhere

    # all four are always offered, so switching never needs a trip via the dashboard
    labels = [c[2] for c in choices(html)]
    assert labels == ['Travel Companion', 'Travel Insurance', 'Sahayak', 'Site']


def test_the_switcher_says_which_product_you_are_on(client, db, admin_user):
    """A control offering four choices and marking none of them current asks you to remember
    where you are."""
    login(client, 'admin@test.com')
    html = client.get('/admin/insurance-page').data.decode()
    assert '<span class="site-sw-cur">Travel Insurance</span>' in html
    assert [c[2] for c in choices(html) if c[1]] == ['Travel Insurance']


def test_switching_lands_on_that_products_first_screen(client, db, admin_user):
    """Switching has to go somewhere useful rather than to a menu that asks you to choose again."""
    login(client, 'admin@test.com')
    urls = dict((label, url) for url, _, label in choices(client.get('/admin/themes').data.decode()))
    assert urls['Travel Companion'].endswith('/admin/listings')
    assert urls['Sahayak'].endswith('/admin/sahayak')


def test_the_switcher_is_not_offered_to_people_without_the_panel(client, db, user):
    """It is a view of the admin menu. Rendering it for a traveller would advertise screens the
    next click refuses."""
    login(client, 'bob@test.com')
    assert 'site-sw-menu' not in client.get('/').data.decode()


# ---------------------------------------------------------------------------
# Contact messages and feedback
# ---------------------------------------------------------------------------

def test_contact_and_feedback_are_named_in_the_menu(app):
    """They were reachable before but never named: three tabs inside one screen called
    "User voices", which tells you nothing about what is in it."""
    labels = {i['label'] for s in admin_nav.SECTIONS for i in s['items']}
    assert {'Contact us', 'Feedback', 'Reports', 'Enquiries'} <= labels


def test_enquiries_are_filed_under_the_product_they_are_about(app):
    """A travel-cover enquiry belongs with the insurance screens, not with the companion app.
    One screen, one URL, different slices -- the topic does the splitting."""
    by_key = {i['key']: (s['key'], i) for s in admin_nav.SECTIONS for i in s['items']}

    section, item = by_key['voices_insurance']
    assert section == 'insurance'
    assert item['args'] == {'tab': 'contact', 'topic': 'insurance'}

    section, item = by_key['voices_contact']
    assert section == 'companion'
    assert item['args'] == {'tab': 'contact', 'topic': 'companion'}


def test_the_right_line_is_lit_for_a_shared_screen(app):
    """Four lines share one endpoint, so `active` alone cannot say which is current."""
    assert admin_nav.current_key('voices', {}) == 'voices_contact'
    assert admin_nav.current_key('voices', {'tab': 'feedback'}) == 'voices_feedback'
    assert admin_nav.current_key('voices', {'tab': 'report'}) == 'voices_report'
    assert admin_nav.current_key('voices', {'tab': 'contact', 'topic': 'insurance'}) == 'voices_insurance'
    # and that last one pulls the sidebar over to the insurance tab
    assert admin_nav.section_for('voices', {'tab': 'contact', 'topic': 'insurance'}) == 'insurance'
    assert admin_nav.section_for('voices', {}) == 'companion'


def test_the_enquiry_inbox_really_filters_by_topic(client, db, admin_user):
    """The menu promises a slice; the screen has to deliver one."""
    from app import db as _db
    from app.models import ContactMessage
    _db.session.add_all([
        ContactMessage(name='Asha', email='a@example.com', message='about a trip',
                       topic='companion'),
        ContactMessage(name='Ravi', email='r@example.com', message='about cover',
                       topic='insurance'),
    ])
    _db.session.commit()

    login(client, 'admin@test.com')
    html = client.get('/admin/voices?tab=contact&topic=insurance').data.decode()
    assert 'Ravi' in html and 'Asha' not in html
