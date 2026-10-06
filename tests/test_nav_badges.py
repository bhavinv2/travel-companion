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
from app.models import ContactMessage, Feedback, MatchReport, StaffRead, User  # noqa: E402
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


def shows_badge(html):
    """A count is on screen. A zero stays in the page, hidden, so it can come back live."""
    import re
    return bool(re.search(r'<span class="nav-badge"(?![^>]*\shidden)[^>]*>', html))


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


def test_an_enquiry_you_answered_stops_counting_for_you(client, db, app, admin_user):
    """Nobody moves an enquiry on without having read it, so handling one reads it -- for the
    person who handled it. A colleague who never opened it still sees it as new."""
    enquiry('companion')
    enquiry('companion', name='Bina')
    enquiry('companion', name='Cara')
    admin = User.query.filter_by(email='admin@test.com').one()
    for m in ContactMessage.query.filter(ContactMessage.name != 'Asha'):
        m.set_status('closed', by=admin)
    _db.session.commit()
    with app.test_request_context():
        assert nav_badges.unread(admin)['voices_contact'] == 1
    with app.test_request_context():
        assert nav_badges.unread()['voices_contact'] == 1, 'closed work is unread for nobody'


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
    assert not shows_badge(nav)


def test_the_menu_shows_the_number(client, db, admin_user):
    enquiry('companion')
    enquiry('companion')
    login(client, 'admin@test.com')
    nav = sidebar(client, '/admin/listings')
    assert shows_badge(nav)
    assert '>2<' in nav
    # on the line it belongs to, and not on its neighbours
    contact = nav.split('Contact us', 1)[1].split('</a>', 1)[0]
    assert shows_badge(contact)
    listings = nav.split('Listings', 1)[1].split('</a>', 1)[0]
    assert not shows_badge(listings)


def test_a_product_with_nothing_waiting_shows_nothing(client, db, admin_user):
    """An insurance enquiry must not put a number on a Sahayak line."""
    enquiry('insurance')
    login(client, 'admin@test.com')
    nav = sidebar(client, '/admin/sahayak')
    assert not shows_badge(nav)


def test_the_sahayak_line_counts_its_own(client, db, admin_user):
    enquiry('sahayak')
    login(client, 'admin@test.com')
    nav = sidebar(client, '/admin/sahayak')
    applications = nav.split('Applications', 1)[1].split('</a>', 1)[0]
    assert shows_badge(applications)


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
    assert not shows_badge(r.data.decode())


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
    assert shows_badge(line) and '>2<' in line
    # the shared queues are untouched by one agent's own unread count
    assert not shows_badge(nav.split('User voices', 1)[1].split('</a>', 1)[0])


def test_one_agents_notifications_are_not_anothers(client, db, cs_user, admin_user):
    from app.models import Notification

    _db.session.add(Notification(user_id=cs_user.id, type='cs_escalation', title='a',
                                 is_read=False))
    _db.session.commit()
    login(client, 'admin@test.com')
    nav = sidebar(client, '/admin/notification-log')
    assert not shows_badge(nav)


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
    assert not shows_badge(log_line)


# ---------------------------------------------------------------------------
# The numbers on User Voices, and where the message starts
# ---------------------------------------------------------------------------

def _msg(topic, status='new', name='Asha', text='please call me'):
    _db.session.add(ContactMessage(name=name, email='%s@example.com' % name.lower(),
                                   topic=topic, status=status, message=text))
    _db.session.commit()


def _chips(html):
    """{'New': 5, 'In progress': 1, ...} as the screen prints them."""
    import re
    return {m[0].strip(): int(m[1]) for m in re.findall(r'>([A-Za-z ]+) \((\d+)\)<', html)}


def test_the_counts_describe_the_slice_on_screen(client, db, admin_user):
    """They were totals for every topic, so filtering to one product left the chips saying six
    new while five were under them. A number that disagrees with the list below it is wrong."""
    _msg('companion', 'new')
    _msg('companion', 'new', name='Bina')
    _msg('companion', 'closed', name='Cara')
    _msg('insurance', 'new', name='Dev')

    login(client, 'admin@test.com')
    html = client.get('/admin/voices?tab=contact&topic=companion').data.decode()
    chips = _chips(html)
    assert chips['New'] == 2 and chips['Closed'] == 1
    assert chips['All'] == 3, 'the insurance one is not on this screen, so it is not in the count'

    chips = _chips(client.get('/admin/voices?tab=contact&topic=insurance').data.decode())
    assert chips['New'] == 1 and chips['All'] == 1


def test_unfiltered_still_counts_everything(client, db, admin_user):
    _msg('companion', 'new')
    _msg('insurance', 'new', name='Dev')
    login(client, 'admin@test.com')
    assert _chips(client.get('/admin/voices?tab=contact').data.decode())['New'] == 2


def test_a_search_narrows_the_counts_too(client, db, admin_user):
    """The list is searched; counting past the search would describe rows nobody can see."""
    _msg('companion', 'new', name='Asha', text='about a wheelchair at the gate')
    _msg('companion', 'new', name='Bina', text='something else entirely')
    login(client, 'admin@test.com')
    chips = _chips(client.get('/admin/voices?tab=contact&q=wheelchair').data.decode())
    assert chips['New'] == 1 and chips['All'] == 1


def test_the_tab_badge_agrees_with_the_chip(client, db, admin_user):
    """Two numbers for the same thing, a few pixels apart, must not differ."""
    _msg('companion', 'new')
    _msg('insurance', 'new', name='Dev')
    login(client, 'admin@test.com')
    html = client.get('/admin/voices?tab=contact&topic=companion').data.decode()
    # the sidebar line is also called "Contact us", so scope to the tab row
    tabs = html.split('hx-tabs', 1)[1]
    tab = tabs.split('Contact us', 1)[1].split('</a>', 1)[0]
    assert '>1</span>' in tab and 'vt-n' in tab
    assert _chips(html)['New'] == 1
    # ...and the sidebar line for this product says the same
    nav = sidebar(client, '/admin/voices?tab=contact&topic=companion')
    assert '>1<' in nav.split('Contact us', 1)[1].split('</a>', 1)[0]


def test_the_cs_console_counts_the_same_way(client, db, cs_user):
    _msg('companion', 'new')
    _msg('insurance', 'new', name='Dev')
    login(client, 'cs@test.com')
    chips = _chips(client.get('/cs/voices?tab=contact&topic=insurance').data.decode())
    assert chips['New'] == 1 and chips['All'] == 1


def test_the_message_starts_where_the_column_starts(client, db, admin_user):
    """The cell preserves the sender's own line breaks, so the template's indentation was
    printed with them -- every message began eight spaces in while its wrapped lines sat flush
    left. The text now sits in its own element, tight against the tag."""
    _msg('companion', text='First line.\nSecond line.')
    login(client, 'admin@test.com')
    html = client.get('/admin/voices?tab=contact').data.decode()
    assert '<div class="cm-msg">First line.\nSecond line.</div>' in html, \
        'no whitespace may sit between the tag and the text'


def test_the_senders_own_line_breaks_survive(client, db, admin_user):
    """Which is why the cell had pre-wrap in the first place. Moving it must not lose it."""
    _msg('companion', text='Line one.\n\nLine three.')
    login(client, 'admin@test.com')
    html = client.get('/admin/voices?tab=contact').data.decode()
    assert 'Line one.\n\nLine three.' in html


# ---------------------------------------------------------------------------
# Opening a row is what moves the number
# ---------------------------------------------------------------------------

def test_reading_an_enquiry_takes_it_off_the_count(client, db, cs_user, app):
    """The badge counted what nobody had *finished*, so reading down the list never moved it.
    It counts what nobody has *opened* now: one click, one fewer."""
    enquiry('companion')
    enquiry('companion', name='Bina')
    m = ContactMessage.query.first()
    login(client, 'cs@test.com')
    r = client.post('/cs/voices/read/contact/%d' % m.id)
    assert r.status_code == 200
    badges = r.get_json()['badges']
    assert badges['voices_contact'] == 1 and badges['voices'] == 1
    assert ContactMessage.query.get(m.id).status == 'new', 'reading is not handling it'
    # a second opening, by anybody, changes nothing
    assert client.post('/cs/voices/read/contact/%d' % m.id).get_json()['badges']['voices'] == 1


def test_reviews_and_reports_count_down_the_same_way(client, db, cs_user, user):
    fb = Feedback(user_id=user.id, rating=5, comment='lovely', is_approved=False)
    rp = MatchReport(reason='never replied')
    _db.session.add_all([fb, rp])
    _db.session.commit()
    login(client, 'cs@test.com')
    assert client.post('/cs/voices/read/feedback/%d' % fb.id).get_json()['badges']['voices'] == 1
    badges = client.post('/cs/voices/read/report/%d' % rp.id).get_json()['badges']
    assert badges['voices_report'] == 0 and badges['voices'] == 0
    assert Feedback.query.get(fb.id).is_approved is False, 'opening it is not approving it'


def test_acting_on_an_enquiry_marks_it_read(client, db, admin_user):
    enquiry('companion')
    m = ContactMessage.query.first()
    login(client, 'admin@test.com')
    client.post('/admin/voices/%d/status' % m.id, data={'status': 'in_progress'})
    assert StaffRead.query.filter_by(user_id=admin_user.id, kind='contact', item_id=m.id).count() == 1


def test_an_unread_row_is_marked_and_a_read_one_is_not(client, db, admin_user):
    enquiry('companion', name='Asha')
    enquiry('companion', status='closed', name='Bina')
    bina = ContactMessage.query.filter_by(name='Bina').one()
    _db.session.add(StaffRead(user_id=admin_user.id, kind='contact', item_id=bina.id))
    _db.session.commit()
    login(client, 'admin@test.com')
    html = client.get('/admin/voices?tab=contact').data.decode()
    assert html.count('data-read="contact/') == 1
    unread_only = client.get('/admin/voices?tab=contact&unread=1').data.decode()
    assert 'Asha' in unread_only.split('vc-table', 1)[1] and 'Bina' not in unread_only.split('vc-table', 1)[1]


def test_an_unknown_kind_is_refused(client, db, cs_user):
    login(client, 'cs@test.com')
    assert client.post('/cs/voices/read/users/1').status_code == 404


# ---------------------------------------------------------------------------
# Read is per person: what one agent opened is still new to everybody else
# ---------------------------------------------------------------------------

def test_what_one_agent_read_is_still_unread_for_another(client, db, cs_user):
    """A new CS account must see every enquiry as unread, whoever else has already opened it --
    "I have looked at this" is about the person, not the message."""
    from conftest import logout, make_user

    enquiry('companion')
    enquiry('companion', name='Bina')
    m = ContactMessage.query.first()
    make_user('cs2@test.com', 'csagent2', role='cs')

    login(client, 'cs@test.com')
    assert client.post('/cs/voices/read/contact/%d' % m.id).get_json()['badges']['voices'] == 1
    logout(client)

    login(client, 'cs2@test.com')
    nav = sidebar(client, '/cs/voices?tab=contact')
    assert '>2<' in nav.split('User voices', 1)[1].split('</a>', 1)[0], \
        'the second agent has opened nothing, so both are new to them'
    html = client.get('/cs/voices?tab=contact').data.decode()
    assert html.count('data-read="contact/') == 2
    assert client.post('/cs/voices/read/contact/%d' % m.id).get_json()['badges']['voices'] == 1
    logout(client)

    # ...and the first agent's count is untouched by the second one reading
    login(client, 'cs@test.com')
    nav = sidebar(client, '/cs/voices?tab=contact')
    assert '>1<' in nav.split('User voices', 1)[1].split('</a>', 1)[0]


def test_a_mark_written_by_a_parallel_request_does_not_fail_this_one(client, db, cs_user, app):
    """A status button on an unread row sends the row's "read" and the form together. Whichever
    lands second finds the mark already there, and must carry on rather than error."""
    enquiry('companion')
    m = ContactMessage.query.first()
    agent = User.query.filter_by(email='cs@test.com').one()
    with app.test_request_context():
        from app.models import request_cache
        request_cache('staff_reads')[(agent.id, 'contact')] = set()   # read before the other wrote
        _db.session.add(StaffRead(user_id=agent.id, kind='contact', item_id=m.id))
        _db.session.commit()
        assert m.mark_read(by=agent) is False
        m.set_status('in_progress', by=agent)
        _db.session.commit()
    assert StaffRead.query.filter_by(user_id=agent.id, kind='contact').count() == 1
    assert ContactMessage.query.get(m.id).status == 'in_progress'


def test_a_reopened_report_is_new_again_for_everybody(client, db, cs_user, app):
    rp = MatchReport(reason='never replied')
    _db.session.add(rp)
    _db.session.commit()
    login(client, 'cs@test.com')
    client.post('/cs/voices/read/report/%d' % rp.id)
    client.post('/cs/reports/%d/resolve' % rp.id, json={})
    assert client.post('/cs/voices/read/report/%d' % rp.id).get_json()['badges']['voices_report'] == 0
    client.post('/cs/reports/%d/reopen' % rp.id, json={})
    assert StaffRead.query.filter_by(kind='report', item_id=rp.id).count() == 0



def test_a_new_agent_is_not_shown_the_closed_history(client, db, user, cs_user, app):
    """Somebody who joins today starts with the open work unread -- not every enquiry, review and
    report the team has ever finished. A badge of four hundred is a badge nobody reads."""
    from conftest import make_user

    enquiry('companion', status='new')
    enquiry('companion', status='in_progress', name='Bina')      # still open work
    enquiry('companion', status='closed', name='Cara')
    _db.session.add_all([Feedback(user_id=user.id, rating=5, comment='pending', is_approved=False),
                         Feedback(user_id=user.id, rating=5, comment='live', is_approved=True),
                         MatchReport(reason='open one'),
                         MatchReport(reason='done', status='resolved')])
    _db.session.commit()
    make_user('new@test.com', 'newagent', role='cs')

    login(client, 'new@test.com')
    html = client.get('/cs/voices?tab=contact').data.decode()
    nav = sidebar(client, '/cs/voices?tab=contact')
    assert '>4<' in nav.split('User voices', 1)[1].split('</a>', 1)[0], '2 enquiries, 1 review, 1 report'
    cara = ContactMessage.query.filter_by(name='Cara').one()
    assert 'data-read="contact/%d"' % cara.id not in html
    assert html.count('data-read="contact/') == 2


def test_closing_an_enquiry_clears_it_for_everybody(client, db, cs_user, app):
    """Once the work is finished it stops being news to the whole team, read or not."""
    enquiry('companion')
    m = ContactMessage.query.first()
    with app.test_request_context():
        assert nav_badges.unread()['voices_contact'] == 1
    m.set_status('closed')
    _db.session.commit()
    with app.test_request_context():
        assert nav_badges.unread()['voices_contact'] == 0
