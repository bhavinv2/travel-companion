"""`flask seed-demo-match` creates two travellers whose posts match, with working logins."""
from conftest import login
from app.models import User, CompanionRequest, Match, Notification


def test_seed_demo_content_fills_every_content_screen(app, client, db):
    from app.models import Blog, ClaimToken, ContactMessage, Feedback, MatchParty
    r = app.test_cli_runner().invoke(args=['seed-demo-match'])       # a match to escalate
    assert r.exit_code == 0, r.output
    r = app.test_cli_runner().invoke(args=['seed-demo-content'])
    assert r.exit_code == 0, r.output

    assert Blog.query.count() == 5 and Blog.query.filter_by(is_published=False).count() == 1
    assert Feedback.query.count() == 9 and Feedback.query.filter_by(is_approved=False).count() == 3
    assert {s: ContactMessage.query.filter_by(status=s).count() for s in ('new', 'in_progress', 'closed')} \
        == {'new': 2, 'in_progress': 1, 'closed': 2}
    assert CompanionRequest.query.filter_by(status='unconfirmed').count() == 2
    assert ClaimToken.query.count() == 1
    flagged = Match.query.filter_by(needs_cs_attention=True).all()
    assert flagged and MatchParty.query.filter_by(match_id=flagged[0].id).count() == 2

    # the documented logins exist and land on their screens with data
    assert login(client, 'cs@connectingdesis.com', 'Cs#Desis2026').status_code == 302
    assert client.get('/cs/').status_code == 200
    voices = client.get('/cs/voices?tab=feedback')
    assert voices.status_code == 200 and b'Found a companion for my mother' in voices.data
    client.get('/auth/logout')
    assert login(client, 'user@connectingdesis.com', 'User#Desis2026').status_code == 302
    assert client.get('/dashboard').status_code == 200
    client.get('/auth/logout')

    # idempotent: a second run adds nothing
    before = (Blog.query.count(), Feedback.query.count(), ContactMessage.query.count(),
              CompanionRequest.query.count(), User.query.count())
    r = app.test_cli_runner().invoke(args=['seed-demo-content'])
    assert r.exit_code == 0, r.output
    assert (Blog.query.count(), Feedback.query.count(), ContactMessage.query.count(),
            CompanionRequest.query.count(), User.query.count()) == before


def test_seed_demo_match_creates_matched_users(app, client, db):
    r = app.test_cli_runner().invoke(args=['seed-demo-match'])
    assert r.exit_code == 0, r.output
    assert 'user1@connectingdesis.com' in r.output and 'user2@connectingdesis.com' in r.output
    u1 = User.query.filter_by(email='user1@connectingdesis.com').first()
    u2 = User.query.filter_by(email='user2@connectingdesis.com').first()
    t1 = CompanionRequest.query.filter_by(user_id=u1.id, flight_number='QR573').one()
    t2 = CompanionRequest.query.filter_by(user_id=u2.id).one()
    assert t1.role == 'seeking_help' and t2.role == 'offering_help' and t1.status == t2.status == 'open'
    a, b = Match.ordered_ids(t1.id, t2.id)
    m = Match.query.filter_by(trip_a_id=a, trip_b_id=b).one()
    assert m.status == 'suggested' and m.score >= 90
    assert all(cp.consent_to_share for cp in t1.contact_points + t2.contact_points)
    # user2 was alerted about the new match; both can log in and see it on the dashboard
    assert Notification.query.filter_by(user_id=u2.id, type='match_found').count() >= 1
    for email in ('user1@connectingdesis.com', 'user2@connectingdesis.com'):
        assert login(client, email, 'Demo#Desis2026').status_code == 302
        page = client.get('/dashboard')
        assert page.status_code == 200 and b'Your matches' in page.data and b'score-tab' in page.data
        client.get('/auth/logout')
    # idempotent: running again neither duplicates users/posts nor the match
    r = app.test_cli_runner().invoke(args=['seed-demo-match'])
    assert r.exit_code == 0, r.output
    assert User.query.filter(User.email.like('user_@connectingdesis.com')).count() == 6
    assert CompanionRequest.query.count() == 8
    assert Match.query.count() >= 5
    # user1's HYD->DFW post has several matches, the BLR->SFO one has none
    from app.services import matching as _matching
    assert len(_matching.ranked_matches_for(t1)) >= 3
    blr = CompanionRequest.query.filter_by(user_id=u1.id, flying_from='Bengaluru (BLR)').one()
    assert _matching.ranked_matches_for(blr) == []


def test_seed_demo_user6_covers_all_trip_types_with_five_matches(app, client, db):
    from app.services import matching
    r = app.test_cli_runner().invoke(args=['seed-demo-user6'])
    assert r.exit_code == 0, r.output
    u6 = User.query.filter_by(email='user6@connectingdesis.com').one()
    posts = CompanionRequest.query.filter_by(user_id=u6.id).all()
    assert sorted(t.trip_type for t in posts) == ['multi_destination', 'one_way', 'round_trip']
    assert all(t.status == 'open' for t in posts)
    per_type = {t.trip_type: len(matching.ranked_matches_for(t)) for t in posts}
    assert all(n >= 1 for n in per_type.values()), per_type
    assert sum(per_type.values()) >= 5, per_type
    # leg-level matching is on show: one-way travellers pair with the round trip's outbound
    # AND its return, and with a single hop of the multi-stop itinerary
    rt = next(t for t in posts if t.trip_type == 'round_trip')
    kinds = {(m.leg_a if m.trip_a_id == rt.id else m.leg_b).kind for m in matching.live_matches_for(rt)}
    assert {'outbound', 'return'} <= kinds
    multi = next(t for t in posts if t.trip_type == 'multi_destination')
    assert len(multi.legs) == 3 and len(matching.live_matches_for(multi)) >= 2
    assert all(cp.consent_to_share for t in posts for cp in t.contact_points)
    # the seeded login works and sees the matches
    assert login(client, 'user6@connectingdesis.com', 'Demo#Desis2026').status_code == 302
    page = client.get('/dashboard')
    assert page.status_code == 200 and b'Your matches' in page.data
    client.get('/auth/logout')
    # idempotent: a second run adds no users, posts or matches
    before = (User.query.count(), CompanionRequest.query.count(), Match.query.count())
    r = app.test_cli_runner().invoke(args=['seed-demo-user6'])
    assert r.exit_code == 0, r.output
    assert (User.query.count(), CompanionRequest.query.count(), Match.query.count()) == before
    # composes with seed-demo-match: user6's one-way post is the same row, not a duplicate
    r = app.test_cli_runner().invoke(args=['seed-demo-match'])
    assert r.exit_code == 0, r.output
    assert CompanionRequest.query.filter_by(user_id=u6.id).count() == 3
    assert CompanionRequest.query.filter_by(user_id=u6.id, flight_number='QR574').count() == 1
