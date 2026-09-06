"""Inline subtree on /cs/posts: matches with score % + possible-duplicate detection."""
from datetime import date, timedelta

from conftest import login
from app.models import CompanionRequest, ContactPoint


def _make(db, user=None, **kw):
    t = CompanionRequest(user_id=user.id if user else None, travel_type='air', trip_type='one_way',
                         flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                         from_date=date.today() + timedelta(days=20), role='seeking_help', source='organic')
    for k, v in kw.items():
        setattr(t, k, v)
    from app.services.locations import apply_route
    apply_route(t)
    t.set_status(kw.get('status', 'open'))
    db.session.add(t)
    db.session.commit()
    return t


def test_tree_requires_cs(client, db, user):
    t = _make(db, user)
    login(client, 'bob@test.com')
    assert client.get(f'/cs/posts/{t.id}/tree').status_code in (302, 403)


def test_tree_matches_with_scores(client, db, cs_user, user, other_user):
    a = _make(db, user)
    b = _make(db, other_user, role='offering_help')
    login(client, 'cs@test.com')
    d = client.get(f'/cs/posts/{a.id}/tree').get_json()
    assert d['trip_id'] == a.id and d['all_matches_url'].endswith(f'/cs/posts/{a.id}/matches')
    scores = {m['other']['id']: m['score'] for m in d['matches']}
    assert b.id in scores and scores[b.id] >= 40
    assert all(0 <= s <= 100 for s in scores.values())
    m = next(x for x in d['matches'] if x['other']['id'] == b.id)
    assert m['criteria'] and all('label' in c and 'ok' in c for c in m['criteria'])
    assert m['other']['route'].startswith('Hyderabad')


def test_tree_duplicate_signals(client, db, cs_user, user, other_user):
    a = _make(db, user, poster_name='Priya P')
    b = _make(db, other_user, role='offering_help')             # good match, NOT a duplicate
    dup = _make(db, None, poster_name='priya p')                # same poster + route + date
    db.session.add_all([ContactPoint(trip_id=a.id, type='email', value='dup@x.com'),
                        ContactPoint(trip_id=dup.id, type='email', value='dup@x.com')])
    same_acct = _make(db, user, from_date=date.today() + timedelta(days=40))   # same account & route
    db.session.commit()
    login(client, 'cs@test.com')
    d = client.get(f'/cs/posts/{a.id}/tree').get_json()
    dups = {x['id']: x['reasons'] for x in d['duplicates']}
    assert dup.id in dups
    assert 'same poster, route & date' in dups[dup.id] and 'shared contact' in dups[dup.id]
    assert same_acct.id in dups and 'same account & route' in dups[same_acct.id]
    assert b.id not in dups                                     # a match is not a duplicate


def test_posts_page_has_tree_toggles(client, db, cs_user, user):
    _make(db, user)
    login(client, 'cs@test.com')
    html = client.get('/cs/posts').data.decode()
    assert 'tree-toggle' in html and 'buildTree' in html


def test_posts_list_flags_rows_with_matches(client, db, cs_user, user, other_user):
    a = _make(db, user)
    _make(db, other_user, role='offering_help')
    from app.services import matching
    matching.compute_matches_for(a, include_unconfirmed=True)
    db.session.commit()
    login(client, 'cs@test.com')
    html = client.get('/cs/posts').data.decode()
    # tinted row, plus the Matches column: a count and the best score. The count used to
    # hang under the post id; it has its own column now.
    assert 'has-match' in html and 'm-count' in html and 'Matches</th>' in html


def test_same_flight_different_accounts_is_a_match_not_duplicate(client, db, cs_user, user, other_user):
    a = _make(db, user, flight_number='QR573')                      # user5-style: seeking, QR573
    b = _make(db, other_user, flight_number='QR573')                # user1-style: SAME role, SAME flight, own account
    login(client, 'cs@test.com')
    d = client.get(f'/cs/posts/{a.id}/tree').get_json()
    assert b.id not in {x['id'] for x in d['duplicates']}           # different accounts -> never a duplicate
    assert b.id in {m['other']['id'] for m in d['matches']}         # it still shows up as a scored match


def test_same_flight_same_name_still_flagged(client, db, cs_user):
    a = _make(db, None, poster_name='Ravi K', flight_number='QR573')
    dup = _make(db, None, poster_name='ravi k', flight_number='QR573')     # CS re-entered the same person
    other = _make(db, None, poster_name='Sita M', flight_number='QR573')   # different named person, same flight
    login(client, 'cs@test.com')
    d = client.get(f'/cs/posts/{a.id}/tree').get_json()
    dups = {x['id']: x['reasons'] for x in d['duplicates']}
    assert dup.id in dups and 'same flight, date & role' in dups[dup.id]
    assert other.id not in dups


def test_posts_list_filters_by_journey_type(client, db, cs_user, user, other_user):
    """One-way, round trip and multi-trip are separable in the CS list."""
    from datetime import date, timedelta
    one = _make(db, user)
    rt = _make(db, other_user, trip_type='round_trip',
               to_date=date.today() + timedelta(days=27))
    login(client, 'cs@test.com')

    # match on the row id, not "#<id>" -- that also matches every hex colour in the CSS
    row = lambda t: f'id="trip-{t.id}"'

    html = client.get('/cs/posts?trip_type=round_trip').data.decode()
    assert row(rt) in html and row(one) not in html
    assert 'Round trip' in html

    html = client.get('/cs/posts?trip_type=one_way').data.decode()
    assert row(one) in html and row(rt) not in html

    # no filter still shows both
    html = client.get('/cs/posts').data.decode()
    assert row(one) in html and row(rt) in html


def test_posts_search_finds_a_post_by_its_account(client, db, cs_user, user):
    """A signed-in traveller's post has no poster_name -- the name is on their account.

    The Person column shows that username, so searching for it has to find the post.
    """
    t = _make(db, user)                       # user fixture: bob / bob@test.com
    assert t.poster_name is None              # exactly the shape that used to be unfindable
    login(client, 'cs@test.com')
    row = f'id="trip-{t.id}"'

    for term in ('bob', 'bob@test.com'):
        assert row in client.get(f'/cs/posts?q={term}').data.decode(), term
    assert row not in client.get('/cs/posts?q=nobodyhere').data.decode()
