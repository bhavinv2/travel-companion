"""The staff menu: modules, their pages, and which line is lit.

One menu for both consoles, built from services/access.MODULES (the pages) and the person's roles.
It replaced two hand-kept menus -- the admin panel's product tabs and the CS console's screen
list -- that described the same screens differently and drifted apart.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login  # noqa: E402
from app.services import access  # noqa: E402


def test_every_page_belongs_to_exactly_one_module(app):
    seen = {}
    for m in access.MODULES:
        for p in m['pages']:
            assert p['key'] not in seen, '%s is in both %s and %s' % (p['key'], seen.get(p['key']), m['key'])
            seen[p['key']] = m['key']
    assert len(seen) >= 40


def test_every_page_points_at_real_routes(app):
    """A typo here is a 500 on every staff page, because the menu renders on all of them."""
    endpoints = set(app.view_functions)
    for p in access.PAGES.values():
        for ep in p['endpoints']:
            assert ep in endpoints, '%s (%s)' % (ep, p['label'])
        for ep in p['links'].values():
            assert ep is None or ep in endpoints, '%s (%s)' % (ep, p['label'])
    for ep in access.STAFF_ANY:
        assert ep in endpoints, ep


def test_every_staff_screen_is_a_page(app):
    """A staff route no page claims could only be opened by a site admin, with nobody able to
    give it to anyone else -- exactly the hard-coding roles replaced."""
    staff = ('admin.', 'admin_crm.', 'cs.', 'crm.', 'imports.', 'scraper.', 'saved.', 'workspace.', 'messaging.')
    loose = [ep for ep in app.view_functions if ep.startswith(staff) and not access.claims(ep)]
    assert loose == ['admin.admin_login']


def test_the_right_line_is_lit_for_a_shared_screen(app):
    """Six lines share the voices inbox; the query string tells them apart."""
    cases = [
        ('/admin/voices?tab=contact&topic=sahayak', 'voices_sahayak'),
        ('/admin/voices?tab=contact&topic=insurance', 'voices_insurance'),
        ('/admin/voices?tab=contact&topic=general', 'voices_general'),
        ('/admin/voices?tab=contact', 'voices_contact'),
        ('/admin/voices?tab=feedback', 'voices_feedback'),
        ('/cs/voices?tab=report', 'voices_report'),
        ('/admin/help?site=insurance', 'help_insurance'),
        ('/admin/help', 'help'),
        ('/cs/crm/today', 'crm_today'),
        ('/admin/crm/lead/1', 'crm_board'),
    ]
    for url, key in cases:
        with app.test_request_context(url):
            assert access.active_page() == key, url


def test_the_menu_has_every_module_with_the_current_one_open(client, db, admin_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/sahayak').data.decode()
    nav = html.split('admin-nav-items', 1)[1].split('</nav>', 1)[0]
    for label in ('Sales', 'Travel Companion', 'Travel Insurance', 'Sahayak', 'Set-up', 'Team'):
        assert label in nav, label
    sahayak = nav.split('data-group="sahayak"', 1)[0].rsplit('<div', 1)[1]
    assert 'open' in sahayak                               # the module being worked in is open
    assert 'Applications &amp; enquiries' in nav and 'Bookings' in nav


def test_a_menu_line_stays_in_the_console_you_are_in(client, db, admin_user, cs_user):
    """The same screen exists in both consoles; an admin's links stay in /admin, an agent's in /cs."""
    login(client, 'admin@test.com')
    nav = client.get('/admin/sahayak').data.decode().split('admin-nav-items', 1)[1]
    assert 'href="/admin/insurance-quotes"' in nav
    client.post('/auth/logout')
    login(client, 'cs@test.com')
    nav = client.get('/cs/').data.decode().split('admin-nav-items', 1)[1]
    assert 'href="/cs/insurance-quotes"' in nav and '/admin/insurance-quotes' not in nav


def test_the_menu_is_not_offered_to_travellers(client, db, user):
    login(client, 'bob@test.com')
    html = client.get('/').data.decode()
    assert 'admin-nav-items' not in html and 'site-sw' not in html


def test_the_enquiry_inbox_really_filters_by_topic(client, db, admin_user):
    """The menu promises a slice; the screen has to deliver one."""
    from app import db as _db
    from app.models import ContactMessage
    _db.session.add_all([
        ContactMessage(name='Asha', email='a@example.com', message='about a trip', topic='companion'),
        ContactMessage(name='Ravi', email='r@example.com', message='about cover', topic='insurance'),
    ])
    _db.session.commit()
    login(client, 'admin@test.com')
    html = client.get('/admin/voices?tab=contact&topic=insurance').data.decode()
    assert 'Ravi' in html and 'Asha' not in html


def test_a_workspace_without_a_module_has_no_menu_for_it(client, db, admin_user):
    login(client, 'admin@test.com')
    ws = access.ensure_defaults()
    ws.modules = ['crm', 'insurance']
    from app import db as _db
    _db.session.commit()
    nav = client.get('/admin/insurance-quotes').data.decode().split('admin-nav-items', 1)[1].split('</nav>', 1)[0]
    assert 'Travel Insurance' in nav and 'Sales' in nav and 'Team' in nav
    assert 'data-group="sahayak"' not in nav and 'data-group="companion"' not in nav
