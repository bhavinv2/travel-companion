"""An admin can permanently delete any record shown in the admin panel or the CS console.

Every test here runs with SQLite's foreign keys ENFORCED. Production is PostgreSQL, which always
enforces them, and the suite otherwise runs SQLite without -- which is how deleting nearly any
staff account came to raise an IntegrityError in production while every test passed. A delete
that leaves a dangling reference must fail here the way it would fail there.
"""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import event, text

from conftest import login
from app import db as _db
from app.models import (ActivityEvent, AppSetting, Blog, ChatMessage, ChatRoom, ClaimToken,
                        CompanionRequest, ConnectionRequest, ContactMessage, ContactReply, Feedback,
                        InsuranceQuote, Match, MatchParty, MatchReport, Notification, SahayakBooking,
                        SavedFilter, ScrapeRecipe, ScrapeRow, ScrapeRun, StaffRead, User)
from app.services import admin_delete


@pytest.fixture(autouse=True)
def foreign_keys(app, db):
    """Enforce foreign keys for the rest of the test, as PostgreSQL does."""
    _db.session.execute(text('PRAGMA foreign_keys=ON'))
    _db.session.commit()
    assert _db.session.execute(text('PRAGMA foreign_keys')).scalar() == 1
    yield
    _db.session.rollback()
    _db.session.execute(text('PRAGMA foreign_keys=OFF'))
    _db.session.commit()


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------

def by_email(email):
    return User.query.filter_by(email=email).one()


def post(owner=None, created_by=None, **kw):
    t = CompanionRequest(user_id=owner.id if owner else None,
                         created_by_id=created_by.id if created_by else None,
                         travel_type='air', trip_type='one_way', role=kw.pop('role', 'seeking_help'),
                         flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                         from_date=kw.pop('from_date', date.today() + timedelta(days=30)),
                         source=kw.pop('source', 'organic'), **kw)
    t.set_status('open')
    _db.session.add(t)
    _db.session.commit()
    return t


def match_between(a, b, attention=False):
    m = Match(trip_a_id=a.id, trip_b_id=b.id, score=80, needs_cs_attention=attention)
    _db.session.add(m)
    _db.session.commit()
    return m


def admin_delete_one(client, kind, obj_id):
    login(client, 'admin@test.com')
    return client.post('/admin/delete/%s/%d' % (kind, obj_id), json={})


# ---------------------------------------------------------------------------
# One row of every kind
# ---------------------------------------------------------------------------

def _contact(**kw):
    m = ContactMessage(name='Asha', email='asha@example.com', message='please call me', topic='companion', **kw)
    _db.session.add(m)
    _db.session.commit()
    _db.session.add(ContactReply(message_id=m.id, body='We will call today.'))
    _db.session.commit()
    return m


def _quote(**kw):
    q = InsuranceQuote(email='lead@example.com', phone='+919000000000', insurance_type='visitors',
                       citizenship='IND', start_date=date.today() + timedelta(days=5),
                       end_date=date.today() + timedelta(days=30), status='quoted',
                       travellers=[{'age': '62'}], **kw)
    _db.session.add(q)
    _db.session.commit()
    return q


def _booking(**kw):
    b = SahayakBooking(service_key='lab_work', service_name='Lab Work', patient_name='Lakshmi',
                       phone='+919000000000', address='12 Green Park', when_type='asap', **kw)
    _db.session.add(b)
    _db.session.commit()
    return b


BUILDERS = {
    'contact_message': lambda users: _contact(),
    'insurance_quote': lambda users: _quote(),
    'sahayak_booking': lambda users: _booking(),
    'notification': lambda users: _add(Notification(user_id=users['user'].id, type='blog', title='x')),
    'feedback': lambda users: _add(Feedback(user_id=users['user'].id, rating=4, comment='good')),
    'saved_filter': lambda users: _add(SavedFilter(owner_id=users['cs'].id, name='Team view')),
    'blog': lambda users: _add(Blog(author_id=users['admin'].id, title='Hello', slug='hello', content='x')),
    'scrape_row': lambda users: _scrape()[2],
    'scrape_run': lambda users: _scrape()[1],
    'scrape_recipe': lambda users: _scrape()[0],
}


def _add(obj):
    _db.session.add(obj)
    _db.session.commit()
    return obj


def _scrape():
    rec = _add(ScrapeRecipe(name='r', start_url='http://example.test', mode='source',
                            field_mapping={'origin': 'origin'}, default_source='website'))
    run = _add(ScrapeRun(recipe_id=rec.id, kind='run', status='done'))
    row = _add(ScrapeRow(recipe_id=rec.id, run_id=run.id, row_index=0, key='k1', status='new',
                         data={'origin': 'Hyderabad'}))
    return rec, run, row


@pytest.fixture
def users(admin_user, cs_user, user):
    return {'admin': by_email('admin@test.com'), 'cs': by_email('cs@test.com'), 'user': by_email('bob@test.com')}


@pytest.mark.parametrize('kind', sorted(BUILDERS))
def test_an_admin_deletes_any_kind(client, users, kind):
    obj = BUILDERS[kind](users)
    model = type(obj)
    r = admin_delete_one(client, kind, obj.id)
    assert r.status_code == 200, r.get_json()
    _db.session.expire_all()
    assert _db.session.get(model, obj.id) is None
    ev = ActivityEvent.query.filter_by(event=admin_delete.KINDS[kind].event).one()
    assert ev.meta.get('label')


@pytest.mark.parametrize('kind', sorted(BUILDERS))
def test_a_cs_agent_cannot_delete_anything(client, users, kind):
    obj = BUILDERS[kind](users)
    login(client, 'cs@test.com')
    r = client.post('/admin/delete/%s/%d' % (kind, obj.id), json={})
    assert r.status_code == 403
    assert r.get_json()['error'] == 'Only an admin can delete this.'
    assert _db.session.get(type(obj), obj.id) is not None


def test_an_unknown_kind_is_refused(client, users):
    r = admin_delete_one(client, 'chat_room', 1)
    assert r.status_code == 404


def test_bulk_deletes_and_reports_what_it_could_not(client, users):
    a, b = _quote(), _quote()
    login(client, 'admin@test.com')
    d = client.post('/admin/delete/insurance_quote/bulk', json={'ids': [a.id, b.id, 999999]}).get_json()
    assert d['deleted'] == 2
    assert d['skipped'] == [{'id': 999999, 'error': 'Not found -- it may already have been deleted.'}]
    assert InsuranceQuote.query.count() == 0


# ---------------------------------------------------------------------------
# The cascades that used to fail on PostgreSQL
# ---------------------------------------------------------------------------

def test_a_cs_agent_with_a_history_can_be_deleted(client, users):
    """Created posts, handled enquiries, assigned bookings, saved a setting, made a connection
    request somebody was notified about -- every one of these blocked the delete on PostgreSQL."""
    from app.services import settings
    agent, owner = users['cs'], users['user']
    created = post(owner=None, created_by=agent, source='facebook')
    theirs = post(owner=owner)
    _contact(handled_by_id=agent.id)
    reply_author = ContactReply.query.first()
    reply_author.author_id = agent.id
    _db.session.commit()
    _booking(assigned_by_id=agent.id)
    settings.set_setting('landing', {'note': 'by the agent'}, agent)
    conn = _add(ConnectionRequest(requester_id=agent.id, trip_id=theirs.id))
    _add(Notification(user_id=owner.id, type='connection_request', title='x', connection_id=conn.id))
    _add(SavedFilter(owner_id=agent.id, name='mine'))
    _add(StaffRead(user_id=agent.id, kind='contact', item_id=1))

    r = admin_delete_one(client, 'user', agent.id)
    assert r.status_code == 200, r.get_json()
    _db.session.expire_all()
    assert _db.session.get(User, agent.id) is None
    assert _db.session.get(CompanionRequest, created.id).created_by_id is None     # the post stays
    assert ContactMessage.query.one().handled_by_id is None
    assert SahayakBooking.query.one().assigned_by_id is None
    assert AppSetting.query.filter_by(key='landing').one().updated_by_id is None
    assert Notification.query.filter_by(user_id=owner.id).one().connection_id is None
    assert SavedFilter.query.count() == 0 and StaffRead.query.count() == 0


def test_deleting_an_admin_keeps_the_blog_they_wrote(client, users):
    """author_id is NOT NULL; the posts used to be deleted with the account."""
    other_admin = users['admin']
    writer = User(email='writer@test.com', username='writer', role='admin')
    writer.set_password('x' * 10)
    _db.session.add(writer)
    _db.session.commit()
    b = _add(Blog(author_id=writer.id, title='Our story', slug='our-story', content='x'))
    r = admin_delete_one(client, 'user', writer.id)
    assert r.status_code == 200
    assert _db.session.get(Blog, b.id).author_id == other_admin.id


def test_an_admin_cannot_delete_themselves(client, users):
    r = admin_delete_one(client, 'user', users['admin'].id)
    assert r.status_code == 400
    assert _db.session.get(User, users['admin'].id) is not None


def test_a_post_with_matches_parties_reports_and_scraped_rows_goes(client, users):
    a, b = post(owner=users['user']), post(owner=None, source='facebook', role='offering_help')
    m = match_between(a, b, attention=True)
    _add(MatchParty(match_id=m.id, trip_id=a.id, token='party-a'))
    _add(MatchReport(match_id=m.id, trip_id=a.id, reason='no reply', status='open'))
    rec, run, row = _scrape()
    row.imported_post_id = a.id
    row.status = 'imported'
    _db.session.commit()

    r = admin_delete_one(client, 'post', a.id)
    assert r.status_code == 200, r.get_json()
    _db.session.expire_all()
    assert _db.session.get(CompanionRequest, a.id) is None
    assert Match.query.count() == 0 and MatchParty.query.count() == 0 and MatchReport.query.count() == 0
    row = _db.session.get(ScrapeRow, row.id)
    assert row.imported_post_id is None and row.status == 'skipped', 'purged by retention, not kept forever'


def test_a_post_delete_keeps_the_pairs_chat(client, users):
    a, b = post(owner=users['user']), post(owner=users['admin'], role='offering_help')
    room = _add(ChatRoom(user1_id=users['user'].id, user2_id=users['admin'].id, trip_id=a.id))
    _add(ChatMessage(room_id=room.id, sender_id=users['user'].id, message='about another trip too'))
    admin_delete_one(client, 'post', a.id)
    _db.session.expire_all()
    room = _db.session.get(ChatRoom, room.id)
    assert room is not None and room.trip_id is None
    assert ChatMessage.query.filter_by(room_id=room.id).count() == 1


def test_the_retention_purge_survives_an_imported_post(app, users):
    """It used to delete matches without their parties and leave scraped rows pointing at the
    post: refused by PostgreSQL, and one failure rolled the whole nightly run back."""
    from app.services import jobs
    stale = post(owner=None, source='facebook', from_date=date.today() - timedelta(days=5))
    other = post(owner=users['user'], role='offering_help')
    m = match_between(stale, other)
    _add(MatchParty(match_id=m.id, trip_id=stale.id, token='party-s'))
    rec, run, row = _scrape()
    row.imported_post_id = stale.id
    row.status = 'imported'
    _db.session.commit()
    with app.test_request_context():
        out = jobs.run_retention()
    assert out['unconfirmed_deleted'] == 1
    assert _db.session.get(CompanionRequest, stale.id) is None


# ---------------------------------------------------------------------------
# Kind-specific rules
# ---------------------------------------------------------------------------

def test_deleting_the_last_open_report_takes_the_match_off_the_queue(client, users):
    a, b = post(owner=users['user']), post(owner=None, source='facebook', role='offering_help')
    m = match_between(a, b, attention=True)
    report = _add(MatchReport(match_id=m.id, trip_id=a.id, reason='no reply', status='open'))
    admin_delete_one(client, 'match_report', report.id)
    _db.session.expire_all()
    assert _db.session.get(Match, m.id).needs_cs_attention is False


def test_only_manual_activity_entries_can_be_deleted(client, users):
    t = post(owner=users['user'])
    note = ActivityEvent.log('note', t, actor=users['cs'], note='rang, no answer')
    system = ActivityEvent.log('post_created', t, actor=users['cs'])
    _db.session.commit()
    assert admin_delete_one(client, 'activity_event', note.id).status_code == 200
    r = client.post('/admin/delete/activity_event/%d' % system.id, json={})
    assert r.status_code == 400 and 'audit trail' in r.get_json()['error']


def test_a_running_scrape_cannot_be_deleted(client, users):
    rec, run, row = _scrape()
    run.status = 'running'
    _db.session.commit()
    r = admin_delete_one(client, 'scrape_run', run.id)
    assert r.status_code == 400 and 'still going' in r.get_json()['error']


def test_a_claim_link_can_be_revoked(client, users):
    t = post(owner=None, source='facebook')
    tok = ClaimToken.issue(t, created_by=users['cs'])
    _db.session.commit()
    assert admin_delete_one(client, 'claim_token', tok.id).status_code == 200
    assert ClaimToken.query.count() == 0


def test_an_enquiry_goes_with_its_replies_and_read_marks(client, users):
    m = _contact()
    _add(StaffRead(user_id=users['cs'].id, kind='contact', item_id=m.id))
    admin_delete_one(client, 'contact_message', m.id)
    assert ContactReply.query.count() == 0 and StaffRead.query.count() == 0


def test_a_deleted_blog_post_takes_its_notifications_with_it(client, users):
    b = _add(Blog(author_id=users['admin'].id, title='Hello', slug='hello', content='x'))
    _add(Notification(user_id=users['user'].id, type='blog', title='New', link='/blog/hello'))
    admin_delete_one(client, 'blog', b.id)
    assert Notification.query.count() == 0


# ---------------------------------------------------------------------------
# The screens' own routes
# ---------------------------------------------------------------------------

def test_the_blog_list_shows_drafts_with_their_delete_buttons(client, users):
    _add(Blog(author_id=users['admin'].id, title='Unfinished draft', slug='draft-one', content='x',
              is_published=False))
    login(client, 'admin@test.com')
    page = client.get('/admin/blog').get_data(as_text=True)
    assert 'Unfinished draft' in page and 'data-hd-kind="blog"' in page and 'data-hd-row="blog-' in page
    client.post('/auth/logout')
    login(client, 'cs@test.com')
    assert client.get('/admin/blog').status_code in (302, 403)


def test_delete_matching_removes_only_what_the_filter_shows(client, users):
    for title in ('alpha one', 'alpha two', 'beta'):
        _add(Notification(user_id=users['user'].id, type='blog', title=title))
    login(client, 'admin@test.com')
    r = client.post('/admin/notification-log/delete-matching', json={'q': 'alpha', 'status': ''})
    assert r.get_json() == {'success': True, 'deleted': 2}
    assert [n.title for n in Notification.query.all()] == ['beta']
    ev = ActivityEvent.query.filter_by(event='notifications_bulk_deleted').one()
    assert ev.meta['count'] == 2 and ev.meta['filter'] == {'q': 'alpha'}


def test_a_cs_agent_cannot_delete_matching_notifications(client, users):
    _add(Notification(user_id=users['user'].id, type='blog', title='alpha'))
    login(client, 'cs@test.com')
    r = client.post('/admin/notification-log/delete-matching', json={})
    assert r.status_code == 403 and Notification.query.count() == 1


def test_scraper_kinds_are_gone_when_the_scraper_is(app, client, users):
    rec, run, row = _scrape()
    app.config['SCRAPER_ENABLED'] = False
    assert admin_delete_one(client, 'scrape_row', row.id).status_code == 404
    assert client.post('/admin/delete/scrape_row/bulk', json={'ids': [row.id]}).status_code == 404
    assert ScrapeRow.query.count() == 1


def test_the_cs_report_delete_also_clears_the_queue(client, users):
    a, b = post(owner=users['user']), post(owner=None, source='facebook', role='offering_help')
    m = match_between(a, b, attention=True)
    report = _add(MatchReport(match_id=m.id, trip_id=a.id, reason='no reply', status='open'))
    login(client, 'admin@test.com')
    r = client.post('/cs/reports/%d/delete' % report.id, json={})
    assert r.get_json()['success'] is True
    _db.session.expire_all()
    assert MatchReport.query.count() == 0
    assert _db.session.get(Match, m.id).needs_cs_attention is False


@pytest.mark.parametrize('url,who', [('/admin/feedback/%d/reject', 'admin@test.com'),
                                     ('/cs/voices/feedback/%d/reject', 'cs@test.com')])
def test_rejecting_a_review_forgets_who_had_read_it(client, users, url, who):
    fb = _add(Feedback(user_id=users['user'].id, rating=2, comment='meh'))
    _add(StaffRead(user_id=users['cs'].id, kind='feedback', item_id=fb.id))
    login(client, who)
    assert client.post(url % fb.id).get_json()['success'] is True
    assert Feedback.query.count() == 0 and StaffRead.query.count() == 0
