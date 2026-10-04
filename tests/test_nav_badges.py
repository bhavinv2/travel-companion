"""The counts on the staff menu.

The sidebar named the screens but never said which of them had anything waiting, so the only
way to learn that enquiries had arrived was to open the inbox -- and the inbox is four menu
lines now, split by product, so "open it" meant opening four.

Two things worth holding here. A line's number must mean the same thing the line does: the
Travel Companion "Contact us" badge counts companion enquiries, not every enquiry, or all four
lines would show one number and none of them would be worth reading. And the count must never
be able to take a screen down -- it decorates a menu, and a menu that cannot be drawn costs the
whole console.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import login  # noqa: E402
from app import db as _db  # noqa: E402
from app.models import ContactMessage, Feedback  # noqa: E402
from app.services import nav_badges  # noqa: E402


def enquiry(topic, status='new', name='Asha'):
    _db.session.add(ContactMessage(name=name, email='a@example.com', topic=topic,
                                   status=status, message='please call me'))
    _db.session.commit()


def sidebar(client, url):
    """Just the menu. The page title says "Notifications" too, and splitting the whole
    document on a label finds that first."""
    html = client.get(url).data.decode()
    aside = html.split('admin-sidebar', 1)[1]
    return aside.split('<nav', 1)[1].rsplit('</nav>', 1)[0]


def test_each_line_counts_what_that_line_shows(client, db, app):
    enquiry('companion')
    enquiry('companion')
    enquiry('insurance')
    enquiry('sahayak')
    with app.test_request_context():
        n = nav_badges.unread()
    assert n['voices_contact'] == 2
    assert n['voices_insurance'] == 1
    assert n['voices_sahayak'] == 1
    assert n['voices_general'] == 0


def test_an_answered_enquiry_stops_counting(client, db, app):
    """"Waiting" is the state nobody has acted on. A closed one still in the badge would mean
    the number never goes down and staff stop reading it."""
    enquiry('companion', status='new')
    enquiry('companion', status='in_progress')
    enquiry('companion', status='closed')
    with app.test_request_context():
        assert nav_badges.unread()['voices_contact'] == 1


def test_the_cs_line_carries_every_slice(client, db, app, user):
    """The CS console has one "User voices" line for the whole screen, so its badge is the lot
    -- including a topic the admin menu has no separate line for."""
    enquiry('companion')
    enquiry('sahayak')
    enquiry('general')
    _db.session.add(Feedback(user_id=user.id, rating=4, comment='good', is_approved=False))
    _db.session.commit()
    with app.test_request_context():
        n = nav_badges.unread()
    assert n['voices_feedback'] == 1
    assert n['voices'] == 4


def test_nothing_waiting_means_no_badge(client, db, admin_user):
    login(client, 'admin@test.com')
    nav = sidebar(client, '/admin/listings')
    assert 'nav-badge' not in nav


def test_the_menu_shows_the_number(client, db, admin_user):
    enquiry('companion')
    enquiry('companion')
    login(client, 'admin@test.com')
    nav = sidebar(client, '/admin/listings')
    assert 'nav-badge' in nav
    assert '>2<' in nav
    # on the line it belongs to, and not on its neighbours
    contact = nav.split('Contact us', 1)[1].split('</a>', 1)[0]
    assert 'nav-badge' in contact
    listings = nav.split('Listings', 1)[1].split('</a>', 1)[0]
    assert 'nav-badge' not in listings


def test_a_product_with_nothing_waiting_shows_nothing(client, db, admin_user):
    """An insurance enquiry must not put a number on a Sahayak line."""
    enquiry('insurance')
    login(client, 'admin@test.com')
    nav = sidebar(client, '/admin/sahayak')
    assert 'nav-badge' not in nav


def test_the_sahayak_line_counts_its_own(client, db, admin_user):
    enquiry('sahayak')
    login(client, 'admin@test.com')
    nav = sidebar(client, '/admin/sahayak')
    applications = nav.split('Applications', 1)[1].split('</a>', 1)[0]
    assert 'nav-badge' in applications


def test_a_hundred_or_more_is_not_printed_in_full(client, db, app):
    """Three digits in a 20px pill is a pill nobody can read."""
    for _ in range(101):
        _db.session.add(ContactMessage(name='Asha', email='a@example.com', topic='companion',
                                       status='new', message='x'))
    _db.session.commit()
    with app.test_request_context():
        assert nav_badges.unread()['voices_contact'] == 101


def test_the_count_is_asked_for_once_per_request(client, db, app):
    """Both sidebars and the header can each ask, and the queries are not free."""
    enquiry('companion')
    with app.test_request_context():
        first = nav_badges.unread()
        assert nav_badges.unread() is first


def test_a_count_that_cannot_be_read_does_not_take_the_console_down(client, db, admin_user,
                                                                   monkeypatch):
    """An install mid-migration would lose every staff screen over a number nobody needs."""
    monkeypatch.setattr(nav_badges, '_compute',
                        lambda: (_ for _ in ()).throw(RuntimeError('no such column')))
    login(client, 'admin@test.com')
    r = client.get('/admin/listings')
    assert r.status_code == 200
    assert 'nav-badge' not in r.data.decode()


def test_the_notifications_line_counts_this_agents_own(client, db, cs_user, app):
    """The one personal count. Everything else here is a shared queue that reads the same for
    everybody; "notifications" means the ones addressed to whoever is signed in."""
    from app.models import Notification

    _db.session.add_all([
        Notification(user_id=cs_user.id, type='cs_escalation', title='a', is_read=False),
        Notification(user_id=cs_user.id, type='cs_escalation', title='b', is_read=False),
        Notification(user_id=cs_user.id, type='cs_escalation', title='c', is_read=True),
    ])
    _db.session.commit()

    login(client, 'cs@test.com')
    nav = sidebar(client, '/cs/notifications')
    line = nav.split('Notifications', 1)[1].split('</a>', 1)[0]
    assert 'nav-badge' in line and '>2<' in line
    # the shared queues are untouched by one agent's own unread count
    assert 'nav-badge' not in nav.split('User voices', 1)[1].split('</a>', 1)[0]


def test_one_agents_notifications_are_not_anothers(client, db, cs_user, admin_user):
    from app.models import Notification

    _db.session.add(Notification(user_id=cs_user.id, type='cs_escalation', title='a',
                                 is_read=False))
    _db.session.commit()
    login(client, 'admin@test.com')
    nav = sidebar(client, '/admin/notification-log')
    assert 'nav-badge' not in nav


def test_the_sent_notification_log_is_not_badged(client, db, admin_user):
    """Admin -> Site -> Notifications is a log of what we sent other people, not an inbox.
    A count there would read as "you have 3 to read", which is not what the screen is."""
    from app.models import Notification

    _db.session.add(Notification(user_id=admin_user.id, type='cs_escalation', title='a',
                                 is_read=False))
    _db.session.commit()
    login(client, 'admin@test.com')
    nav = sidebar(client, '/admin/notification-log')
    log_line = nav.split('Notifications', 1)[1].split('</a>', 1)[0]
    assert 'nav-badge' not in log_line
