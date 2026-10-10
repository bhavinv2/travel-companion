"""Every screen that lists records gives an admin a way to delete them -- and gives a CS agent
looking at the same screen nothing of the sort.

The delete itself is tested in test_admin_hard_delete.py; this is about the buttons being where
the owner asked for them ("the admin can hard delete all the data in any place") and nowhere an
agent would find a button that only answers 403.
"""
import pytest
from flask import url_for

from conftest import login
from app import db as _db
from app.models import (ActivityEvent, Blog, ClaimToken, Feedback, MatchReport, Notification,
                        SavedFilter, User)
from test_admin_hard_delete import (_add, _booking, _contact, _quote, _scrape, by_email, match_between,
                                    post)


@pytest.fixture
def people(admin_user, cs_user, user):
    return {'admin': by_email('admin@test.com'), 'cs': by_email('cs@test.com'), 'user': by_email('bob@test.com')}


def page(app, client, who, endpoint, **args):
    login(client, who)
    with app.test_request_context():
        url = url_for(endpoint, **args)
    r = client.get(url)
    assert r.status_code == 200, (endpoint, r.status_code)
    client.post('/auth/logout')
    return r.get_data(as_text=True)


def admin_sees(html, kind, obj_id, bulk=True, single=True):
    assert 'data-hd-kind="%s"' % kind in html
    if single:
        assert 'data-hd-id="%s"' % obj_id in html
    assert 'data-hd-row="%s-%s"' % (kind, obj_id) in html
    if bulk:
        assert 'class="hd-check" data-hd-kind="%s" value="%s"' % (kind, obj_id) in html
        assert 'hd-bulk-del" data-hd-kind="%s"' % kind in html


def agent_sees_nothing(html):
    assert 'hd-del' not in html and 'hd-check' not in html and 'hd-bulk' not in html
    assert 'hardDeleteModal' not in html            # the dialog is for admins too


# ---------------------------------------------------------------------------- user voices

@pytest.mark.parametrize('tab,kind,make', [
    ('contact', 'contact_message', lambda p: _contact()),
    ('feedback', 'feedback', lambda p: _add(Feedback(user_id=p['user'].id, rating=4, comment='lovely'))),
    ('report', 'match_report', None),
])
def test_user_voices_in_both_consoles(app, client, people, tab, kind, make):
    if make is None:
        a, b = post(owner=people['user']), post(owner=None, source='facebook', role='offering_help')
        obj = _add(MatchReport(match_id=match_between(a, b).id, trip_id=a.id, reason='rude', status='open'))
    else:
        obj = make(people)
    # a review's single delete is Reject, a report's its own trash; both pre-date this
    single = tab == 'contact'
    admin_sees(page(app, client, 'admin@test.com', 'admin.voices', tab=tab), kind, obj.id, single=single)
    admin_sees(page(app, client, 'admin@test.com', 'cs.voices', tab=tab), kind, obj.id, single=single)
    agent_sees_nothing(page(app, client, 'cs@test.com', 'cs.voices', tab=tab))


# ---------------------------------------------------------------------------- leads

@pytest.mark.parametrize('kind,make,admin_ep,cs_ep', [
    ('insurance_quote', _quote, 'admin.insurance_quotes', 'cs.insurance_quotes'),
    ('sahayak_booking', _booking, 'admin.sahayak_bookings', 'cs.sahayak_bookings'),
])
def test_leads_in_both_consoles(app, client, people, kind, make, admin_ep, cs_ep):
    obj = make()
    admin_sees(page(app, client, 'admin@test.com', admin_ep), kind, obj.id)
    admin_sees(page(app, client, 'admin@test.com', cs_ep), kind, obj.id)
    agent_sees_nothing(page(app, client, 'cs@test.com', cs_ep))


def test_a_bookings_notes_row_goes_with_it(app, client, people):
    b = _booking(notes='Ring the bell twice')
    html = page(app, client, 'admin@test.com', 'admin.sahayak_bookings')
    assert 'class="sk-notes-row" data-hd-also="sahayak_booking-%d"' % b.id in html


# ---------------------------------------------------------------------------- posts

def test_the_cs_posts_list(app, client, people):
    t = post(owner=people['user'])
    admin_sees(page(app, client, 'admin@test.com', 'cs.posts'), 'post', t.id)
    agent_sees_nothing(page(app, client, 'cs@test.com', 'cs.posts'))


def test_the_cs_home_tables(app, client, people):
    t = post(owner=people['user'])
    admin_sees(page(app, client, 'admin@test.com', 'cs.home'), 'post', t.id, bulk=False)
    agent_sees_nothing(page(app, client, 'cs@test.com', 'cs.home'))


def test_the_post_page(app, client, people):
    t = post(owner=None, source='facebook')
    tok = ClaimToken.issue(t, created_by=people['cs'])
    note = ActivityEvent.log('note', t, actor=people['cs'], note='rang, no answer')
    system = ActivityEvent.log('post_created', t, actor=people['cs'])
    _db.session.commit()
    html = page(app, client, 'admin@test.com', 'cs.post_detail', trip_id=t.id)
    assert 'data-hd-kind="post" data-hd-id="%d"' % t.id in html
    assert 'data-hd-redirect="' in html
    assert 'data-hd-kind="claim_token" data-hd-id="%d"' % tok.id in html
    assert 'data-hd-kind="activity_event" data-hd-id="%d"' % note.id in html
    # the audit trail has no trash
    assert 'data-hd-kind="activity_event" data-hd-id="%d"' % system.id not in html
    agent_sees_nothing(page(app, client, 'cs@test.com', 'cs.post_detail', trip_id=t.id))


# ---------------------------------------------------------------------------- admin screens

def test_the_dashboard(app, client, people):
    t = post(owner=people['user'])
    html = page(app, client, 'admin@test.com', 'admin.dashboard')
    admin_sees(html, 'user', people['user'].id, bulk=False)
    admin_sees(html, 'post', t.id, bulk=False)
    # not their own account
    assert 'data-hd-kind="user" data-hd-id="%d"' % people['admin'].id not in html


def test_the_cs_agents_screen(app, client, people):
    html = page(app, client, 'admin@test.com', 'admin.cs_agents')
    admin_sees(html, 'user', people['cs'].id, bulk=False)


# ---------------------------------------------------------------------------- notifications

def test_the_notification_logs(app, client, people):
    n = _add(Notification(user_id=people['user'].id, type='blog', title='hello'))
    for ep in ('admin.notification_log', 'cs.notifications'):
        html = page(app, client, 'admin@test.com', ep)
        admin_sees(html, 'notification', n.id)
        assert 'id="nmDelMatching"' in html
        # one row's delete is the admin URL from both consoles; the CS console grows none
        assert "/notifications/${id}/delete" not in html
    html = page(app, client, 'cs@test.com', 'cs.notifications')
    agent_sees_nothing(html)
    assert 'nmDelMatching' not in html


def test_delete_all_matching_carries_the_filter_the_list_used(app, client, people):
    _add(Notification(user_id=people['user'].id, type='blog', title='hello'))
    html = page(app, client, 'admin@test.com', 'admin.notification_log',
                user_id=people['user'].id, q='hel')
    assert 'data-filter="{&#34;q&#34;: &#34;hel&#34;, &#34;user_id&#34;: &#34;%d&#34;}"' % people['user'].id in html


def test_delete_all_matching_honours_one_users_filter(client, people):
    other = _add(User(email='z@test.com', username='zed', is_active=True))
    _add(Notification(user_id=people['user'].id, type='blog', title='hello'))
    _add(Notification(user_id=other.id, type='blog', title='hello'))
    login(client, 'admin@test.com')
    r = client.post('/admin/notification-log/delete-matching',
                    json={'q': 'hello', 'user_id': str(people['user'].id)})
    assert r.get_json()['deleted'] == 1
    assert [n.user_id for n in Notification.query.all()] == [other.id]


# ---------------------------------------------------------------------------- saved views, blog

def test_shared_saved_views(app, client, people):
    f = _add(SavedFilter(owner_id=people['cs'].id, name='Team view', shared=True))
    html = page(app, client, 'admin@test.com', 'saved.manage')
    admin_sees(html, 'saved_filter', f.id, bulk=False)


def test_the_blog_list(app, client, people):
    b = _add(Blog(author_id=people['admin'].id, title='Draft', slug='draft', content='x'))
    admin_sees(page(app, client, 'admin@test.com', 'admin.blog_list'), 'blog', b.id)


# ---------------------------------------------------------------------------- scraper

def test_the_scraper_screens(app, client, people):
    rec, run, row = _scrape()
    admin_sees(page(app, client, 'admin@test.com', 'scraper.recipes'), 'scrape_recipe', rec.id, bulk=False)
    admin_sees(page(app, client, 'admin@test.com', 'scraper.recipe_runs', recipe_id=rec.id),
               'scrape_run', run.id, bulk=False)
    html = page(app, client, 'admin@test.com', 'scraper.run_detail', run_id=run.id)
    assert 'data-hd-kind="scrape_row" data-hd-id="%d"' % row.id in html
    assert 'class="inc" data-hd-kind="scrape_row"' in html
    assert 'hd-bulk-del" data-hd-kind="scrape_row"' in html
    assert 'id="rowModalDel"' in html


def test_a_recipe_deleted_from_its_runs_page(client, people):
    rec, run, row = _scrape()
    login(client, 'admin@test.com')
    r = client.post('/cs/scraper/recipes/%d/delete' % rec.id)
    assert r.status_code == 302
    assert ActivityEvent.query.filter_by(event='scrape_recipe_deleted').count() == 1
