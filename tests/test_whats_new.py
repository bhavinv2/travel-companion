"""The floating "what's new" button on staff pages.

Three promises worth holding, because each is the kind that quietly rots:

  * A count means what its words say. Three lists are shared queues ("nobody has dealt with
    it"), two are personal ("since you last looked"), and a number that drifts from the list it
    opens is a number staff learn to ignore.
  * It never shows anybody something they would be turned away from. A CS agent narrowed to the
    Sahayak queue sees the Sahayak count and nothing else.
  * It cannot cost the page. It floats over every staff screen, so a count that fails must fail
    to zero, not to a 500.
"""
from datetime import date, datetime, timedelta

import pytest

from conftest import login
from app import db as _db
from app.models import (CompanionRequest, ContactMessage, InsuranceQuote, Match, MatchParty, StaffRead,
                        SahayakBooking, User)
from app.services import whats_new


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def quote(created=None):
    q = InsuranceQuote(email='lead@example.com', phone='+919000000000', insurance_type='visitors',
                       citizenship='IND', start_date=date.today() + timedelta(days=5),
                       end_date=date.today() + timedelta(days=30), status='quoted',
                       travellers=[{'age': '62'}])
    if created:
        q.created_at = created
    _db.session.add(q)
    _db.session.commit()
    return q


def post(created=None, status='open', by=None):
    t = CompanionRequest(travel_type='air', trip_type='one_way', role='seeking_help',
                         flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                         from_date=date.today() + timedelta(days=30), created_by_id=by)
    t.set_status(status)
    if created:
        t.created_at = created
    _db.session.add(t)
    _db.session.commit()
    return t


def match(status='suggested', attention=True, a=None, b=None):
    a, b = a or post(), b or post()
    m = Match(trip_a_id=a.id, trip_b_id=b.id, score=80, status=status,
              needs_cs_attention=attention)
    _db.session.add(m)
    _db.session.flush()
    # b has been reached, a is the side somebody still has to move along -- so the queue files
    # the match under a alone, as it does for most real ones
    _db.session.add_all([MatchParty(match_id=m.id, trip_id=a.id, token='a%d' % m.id, status='pending'),
                         MatchParty(match_id=m.id, trip_id=b.id, token='b%d' % m.id, status='viewed')])
    _db.session.commit()
    return m


def enquiry(topic='companion', status='new'):
    _db.session.add(ContactMessage(name='Asha', email='a@example.com', topic=topic,
                                   status=status, message='please call me'))
    _db.session.commit()


def booking(status='new'):
    _db.session.add(SahayakBooking(service_key='lab_work', service_name='Lab Work',
                                   patient_name='Lakshmi', phone='+919000000000',
                                   address='12 Green Park', when_type='asap', status=status))
    _db.session.commit()


def counts(user, console='cs'):
    return {i['key']: i['count'] for i in whats_new.snapshot(user, console)['items']}


def by_email(email):
    return User.query.filter_by(email=email).one()


# ---------------------------------------------------------------------------
# What each number means
# ---------------------------------------------------------------------------

def test_shared_queues_count_what_nobody_has_dealt_with(app, db, admin_user):
    enquiry('companion')
    enquiry('insurance')
    closed = ContactMessage(name='Bina', email='b@example.com', topic='companion',
                            status='closed', message='sorted, thanks')
    _db.session.add(closed)
    booking('new')
    booking('assigned')
    match('suggested')
    seen = match('suggested')
    match('suggested', attention=False)       # not in the CS queue at all
    admin = by_email('admin@test.com')
    # what this admin has opened; the other enquiries and the first match they have not
    _db.session.flush()
    _db.session.add_all([StaffRead(user_id=admin.id, kind='contact', item_id=closed.id),
                         StaffRead(user_id=admin.id, kind='match', item_id=seen.id)])
    _db.session.commit()
    with app.test_request_context():
        n = counts(admin)
    assert n['contact'] == 2
    assert n['sahayak'] == 1
    assert n['matches'] == 1


def test_sahayak_applications_count_as_contact_enquiries(app, db, admin_user):
    """The contact icon opens the enquiry inbox filtered to unread, which lists every topic -- a
    Sahayak application included. Counting fewer than the list shows is the mismatch this whole
    widget exists to avoid."""
    enquiry('sahayak')
    with app.test_request_context():
        assert counts(by_email('admin@test.com'))['contact'] == 1


def test_a_quote_is_new_until_you_open_the_list(app, db, admin_user):
    admin = by_email('admin@test.com')
    quote()
    with app.test_request_context():
        assert counts(admin)['insurance'] == 1
        whats_new.mark_seen(admin, 'insurance', when=datetime.utcnow() + timedelta(seconds=1))
        _db.session.commit()
        assert counts(admin)['insurance'] == 0
    # ...and the next one is new again
    quote(created=datetime.utcnow() + timedelta(seconds=5))
    with app.test_request_context():
        assert counts(admin)['insurance'] == 1


def test_someone_who_never_looked_sees_two_days_not_all_history(app, db, admin_user):
    quote(created=datetime.utcnow() - timedelta(days=3))
    quote(created=datetime.utcnow() - timedelta(hours=2))
    with app.test_request_context():
        assert counts(by_email('admin@test.com'))['insurance'] == 1


def test_one_persons_look_does_not_clear_it_for_another(app, db, admin_user, cs_user):
    """The personal counts are personal: the admin checking quotes this morning must not hide
    them from the agent who has not."""
    quote()
    admin, agent = by_email('admin@test.com'), by_email('cs@test.com')
    with app.test_request_context():
        whats_new.mark_seen(admin, 'insurance', when=datetime.utcnow() + timedelta(seconds=1))
        _db.session.commit()
        assert counts(admin)['insurance'] == 0
        assert counts(agent)['insurance'] == 1


def test_a_post_you_created_is_not_news_to_you(app, db, admin_user, cs_user):
    agent = by_email('cs@test.com')
    post(by=agent.id)
    post(by=None)
    with app.test_request_context():
        assert counts(agent)['posts'] == 1
        assert counts(by_email('admin@test.com'))['posts'] == 2


def test_a_closed_post_is_not_new(app, db, admin_user):
    post(status='closed')
    with app.test_request_context():
        assert counts(by_email('admin@test.com'))['posts'] == 0


def test_the_words_say_which_kind_of_number_it_is(app, db, admin_user):
    quote()
    enquiry()
    with app.test_request_context():
        items = {i['key']: i for i in whats_new.snapshot(by_email('admin@test.com'))['items']}
    assert items['insurance']['hint'] == '1 new since you last looked'
    assert items['contact']['hint'] == '1 not opened yet'
    assert items['sahayak']['hint'] == 'nothing waiting'


def test_the_total_is_the_sum_of_what_is_shown(app, db, admin_user):
    enquiry()
    booking()
    with app.test_request_context():
        snap = whats_new.snapshot(by_email('admin@test.com'))
    assert snap['total'] == sum(i['count'] for i in snap['items']) == 2


def test_an_unreadable_mark_counts_as_never_looked(app, db, admin_user):
    admin = by_email('admin@test.com')
    admin.seen_marks = {'insurance': 'not a date'}
    _db.session.commit()
    quote()
    with app.test_request_context():
        assert counts(admin)['insurance'] == 1


# ---------------------------------------------------------------------------
# Opening a list is what "I have looked" means
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('url', ['/admin/insurance-quotes', '/cs/insurance-quotes'])
def test_opening_the_quotes_list_moves_the_mark(client, app, db, admin_user, url):
    quote()
    login(client, 'admin@test.com')
    assert client.get(url).status_code == 200
    with app.test_request_context():
        assert counts(by_email('admin@test.com'))['insurance'] == 0


@pytest.mark.parametrize('url', ['/admin/listings', '/cs/posts'])
def test_opening_the_posts_list_moves_the_mark(client, app, db, admin_user, url):
    post()
    login(client, 'admin@test.com')
    assert client.get(url).status_code == 200
    with app.test_request_context():
        assert counts(by_email('admin@test.com'))['posts'] == 0


def test_opening_some_other_screen_moves_nothing(client, app, db, admin_user):
    quote()
    login(client, 'admin@test.com')
    client.get('/admin/sahayak')
    with app.test_request_context():
        assert counts(by_email('admin@test.com'))['insurance'] == 1


# ---------------------------------------------------------------------------
# Who sees what, and where it takes them
# ---------------------------------------------------------------------------

def test_an_agent_sees_only_what_they_can_open(app, db, cs_user):
    agent = by_email('cs@test.com')
    agent.cs_access = ['home', 'sahayak']
    _db.session.commit()
    with app.test_request_context():
        keys = [i['key'] for i in whats_new.snapshot(agent)['items']]
    assert keys == ['sahayak']


def test_an_admin_on_the_admin_panel_goes_to_admin_lists(app, db, admin_user):
    with app.test_request_context():
        urls = {i['key']: i['url'] for i in whats_new.snapshot(by_email('admin@test.com'), 'admin')['items']}
    assert urls['insurance'].endswith('/admin/insurance-quotes')
    assert urls['sahayak'].endswith('/admin/sahayak?status=new')
    assert '/admin/voices' in urls['contact'] and 'unread=1' in urls['contact']


def test_anybody_on_the_console_stays_in_the_console(app, db, admin_user, cs_user):
    with app.test_request_context():
        for who in ('admin@test.com', 'cs@test.com'):
            urls = [i['url'] for i in whats_new.snapshot(by_email(who), 'cs')['items']]
            assert all(u.startswith('/cs/') for u in urls), urls


def test_an_agent_asking_for_admin_links_still_gets_console_ones(app, db, cs_user):
    with app.test_request_context():
        urls = [i['url'] for i in whats_new.snapshot(by_email('cs@test.com'), 'admin')['items']]
    assert all(u.startswith('/cs/') for u in urls)


# ---------------------------------------------------------------------------
# On the page
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('who, url', [('admin@test.com', '/admin/sahayak'),
                                      ('cs@test.com', '/cs/voices')])
def test_it_floats_on_both_consoles(client, db, admin_user, cs_user, who, url):
    login(client, who)
    html = client.get(url).data.decode()
    assert 'id="whatsNew"' in html and 'id="wnFab"' in html
    assert 'whats-new.js' in html


def test_every_icon_says_what_it_is_for(client, db, admin_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/sahayak').data.decode()
    for label in ('Insurance quote requests', 'Companion posts', 'Match queue',
                  'Sahayak bookings', 'Contact-us enquiries'):
        assert '<b>%s</b>' % label in html, label          # the hover label
        assert 'aria-label="%s:' % label in html, label     # and for a screen reader


def test_it_is_not_on_public_pages_for_a_traveller(client, db, user):
    login(client, 'bob@test.com')
    assert 'id="whatsNew"' not in client.get('/').data.decode()


def test_the_numbers_are_on_the_first_paint(client, db, admin_user):
    """No flash of zeros while a request goes out: the server draws the counts."""
    enquiry()
    enquiry()
    login(client, 'admin@test.com')
    html = client.get('/admin/sahayak').data.decode()
    fab = html.split('id="wnFab"', 1)[1].split('</button>', 1)[0]
    assert '<span class="wn-total">2</span>' in fab


def test_the_poll_endpoint_answers_json(client, db, admin_user):
    enquiry()
    login(client, 'admin@test.com')
    r = client.get('/cs/api/whats-new?console=admin')
    assert r.status_code == 200 and r.is_json
    assert r.get_json()['total'] == 1


def test_the_poll_endpoint_is_staff_only(client, db, user):
    login(client, 'bob@test.com')
    r = client.get('/cs/api/whats-new')
    assert not r.is_json


def test_a_count_that_fails_costs_zero_not_the_page(client, db, admin_user, monkeypatch):
    real = whats_new._count

    def flaky(item, user, now):
        if item['key'] == 'matches':
            raise RuntimeError('no such column')
        return real(item, user, now)

    monkeypatch.setattr(whats_new, '_count', flaky)
    enquiry()
    login(client, 'admin@test.com')
    r = client.get('/admin/sahayak')
    assert r.status_code == 200
    assert '<span class="wn-total">1</span>' in r.data.decode()


def test_a_widget_that_cannot_be_built_leaves_the_page_alone(client, db, admin_user, monkeypatch):
    monkeypatch.setattr(whats_new, 'snapshot',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    login(client, 'admin@test.com')
    r = client.get('/admin/sahayak')
    assert r.status_code == 200
    assert 'id="whatsNew"' not in r.data.decode()



# ---------------------------------------------------------------------------
# The match queue counts posts nobody has opened
# ---------------------------------------------------------------------------

def test_the_match_icon_counts_posts_not_matches(app, db, admin_user):
    """The queue is grouped by post, so two unopened matches on one post are one thing to open."""
    a = post()
    match(a=a)
    match(a=a)
    match()
    with app.test_request_context():
        assert counts(by_email('admin@test.com'))['matches'] == 2


def test_opening_a_posts_matches_takes_it_off_the_count(client, app, db, cs_user):
    a = post()
    m1, m2 = match(a=a), match(a=a)
    match()
    login(client, 'cs@test.com')
    assert client.get('/cs/posts/%d/matches' % a.id).status_code == 200
    cs = by_email('cs@test.com')
    assert {r.item_id for r in StaffRead.query.filter_by(user_id=cs.id, kind='match')} >= {m1.id, m2.id}
    with app.test_request_context():
        assert counts(by_email('cs@test.com'))['matches'] == 1


def test_the_queue_can_show_only_unopened(client, db, cs_user):
    fresh = match()
    seen = match()
    _db.session.add(StaffRead(user_id=cs_user.id, kind='match', item_id=seen.id))
    _db.session.commit()
    login(client, 'cs@test.com')
    html = client.get('/cs/matches?unread=1').data.decode()
    assert '#%d</strong><br/>' % fresh.id in html and '#%d</strong><br/>' % seen.id not in html
    assert 'New</span>' in html


def test_a_match_back_in_the_queue_is_new_again(client, app, db, cs_user):
    """An escalation on a post the agent opened last week has to light the button up again."""
    a = post()
    m = match(a=a)
    login(client, 'cs@test.com')
    client.get('/cs/posts/%d/matches' % a.id)
    m = Match.query.get(m.id)
    m.needs_cs_attention = False
    _db.session.commit()
    m.needs_cs_attention = True          # the escalation job, a report, the bridge...
    _db.session.commit()
    assert StaffRead.query.filter_by(kind='match', item_id=m.id).count() == 0


def test_the_minute_refresh_carries_the_menu_counts_too(client, db, cs_user):
    """So a menu count rises when something arrives, not only falls when you read it."""
    login(client, 'cs@test.com')
    assert client.get('/cs/api/whats-new').get_json()['badges']['voices'] == 0
    enquiry()
    assert client.get('/cs/api/whats-new').get_json()['badges']['voices'] == 1


def test_a_zero_count_stays_in_the_page_hidden(client, db, cs_user):
    """It has to be there for the refresh to show it again when something arrives."""
    login(client, 'cs@test.com')
    html = client.get('/cs/voices?tab=contact').data.decode()
    assert 'data-badge="voices" aria-label="0 not read" hidden' in html
    assert 'data-badge="voices_inbox" hidden' in html


def test_a_click_in_the_queue_reads_the_whole_post(client, app, db, cs_user):
    """Any match row of a post marks all of the post's matches read -- Open all, without leaving
    the queue. Only for the person who clicked."""
    a = post()
    m1, m2 = match(a=a), match(a=a)
    other = match()
    login(client, 'cs@test.com')
    assert 'data-post="%d" data-unread' % a.id in client.get('/cs/matches').data.decode()
    d = client.post('/cs/posts/%d/matches/read' % a.id).get_json()
    assert sorted(d['match_ids']) == sorted([m1.id, m2.id])
    assert d['badges']['matches'] == 1, 'the other post is still new'
    html = client.get('/cs/matches').data.decode()
    assert 'data-post="%d" data-unread' % a.id not in html
    assert 'data-post="%d" data-unread' % other.trip_a_id in html
    # a second click changes nothing
    assert client.post('/cs/posts/%d/matches/read' % a.id).get_json()['match_ids'] == []


def test_the_list_being_viewed_is_not_shown_as_new_on_it(client, db, admin_user):
    """The mark that clears the quotes count is written after the page renders, so the button on
    the quotes list itself used to say "1 new" about the list it was sitting on."""
    quote()
    login(client, 'admin@test.com')
    html = client.get('/admin/insurance-quotes').data.decode()
    item = html.split('data-key="insurance"', 1)[1].split('</a>', 1)[0]
    assert 'class="wn-n" hidden' in item
    assert 'nothing new' in item
