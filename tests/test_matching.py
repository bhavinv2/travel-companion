from datetime import date, timedelta

from conftest import login, logout, TRIP_JSON
from app.models import CompanionRequest, Match, MatchParty, Notification, ContactPoint
from app.services import matching, bridge, mailer


FUTURE = (date.today() + timedelta(days=20)).isoformat()
FUTURE_1 = (date.today() + timedelta(days=21)).isoformat()
FUTURE_5 = (date.today() + timedelta(days=25)).isoformat()


def _post(client, **overrides):
    payload = {**TRIP_JSON, 'from_date': FUTURE, **overrides}
    r = client.post('/api/post-trip', json=payload)
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _make(db, user, **kw):
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


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def test_score_pair_perfect_complementary_match(app, db, user, other_user):
    a = _make(db, user, airline='Qatar Airways', flight_number='QR573', preferred_languages=['Telugu'])
    b = _make(db, other_user, role='offering_help', airline='Qatar Airways', flight_number='QR 573',
              preferred_languages=['telugu', 'Hindi'])
    score, criteria = matching.score_pair(a, b)
    assert score >= 95
    assert all(c['ok'] for c in criteria)
    assert {c['key'] for c in criteria} == set(matching.WEIGHTS)


def test_score_pair_metro_and_flexible_date(app, db, user, other_user):
    a = _make(db, user, flying_from='Hyderabad (HYD)', destination='Dallas (DFW)')
    b = _make(db, other_user, role='offering_help', flying_from='Hyderabad (HYD)', destination='Dallas (DAL)',
              from_date=date.today() + timedelta(days=25), from_date_flexible=True)
    score, criteria = matching.score_pair(a, b)
    by = {c['key']: c for c in criteria}
    assert by['route']['sub'] == 80 and 'Same cities' in by['route']['detail']
    assert by['date']['sub'] == 60 and 'flexible' in by['date']['detail']


def test_score_prefs_two_sided(app, db, user, other_user):
    a = _make(db, user, pref_gender='female', pref_age_min=30, pref_age_max=50, traveler_gender='female',
              traveler_age_group='60_plus')
    b = _make(db, other_user, role='offering_help', traveler_gender='female', traveler_age_group='31_45',
              pref_gender='any')
    sub, detail = matching.score_prefs(a, b)
    assert sub == 100
    c = _make(db, other_user, role='offering_help', traveler_gender='male', traveler_age_group='18_30')
    sub2, detail2 = matching.score_prefs(a, c)
    assert sub2 < 60 and 'wants female' in detail2


def test_role_scoring():
    class T:  # minimal stand-in
        def __init__(self, role): self.role = role
    assert matching.score_role(T('seeking_help'), T('offering_help'))[0] == 100
    assert matching.score_role(T('seeking_help'), T('open'))[0] == 70
    assert matching.score_role(T('seeking_help'), T('seeking_help'))[0] == 50
    assert matching.score_role(T('offering_help'), T('offering_help'))[0] == 20


# ---------------------------------------------------------------------------
# Candidates & persistence
# ---------------------------------------------------------------------------

def test_candidates_exclude_same_person_other_routes_and_far_dates(app, db, user, other_user):
    a = _make(db, user)
    _make(db, user, role='offering_help')                                     # same account
    _make(db, other_user, flying_from='Chennai (MAA)', destination='Dallas (DFW)')  # other route
    _make(db, other_user, from_date=date.today() + timedelta(days=40))         # too far
    _make(db, other_user, status='closed')                                     # closed
    ok = _make(db, other_user, role='offering_help')
    cands = matching.candidates_for(a)
    assert [c.id for c in cands] == [ok.id]


def test_same_contact_value_never_matched(app, db, user):
    a = _make(db, user)
    b = _make(db, None, poster_name='Same Person', source='facebook')
    for t in (a, b):
        db.session.add(ContactPoint(trip=t, type='mobile', value='+12145550100', consent_to_share=True))
    db.session.commit()
    assert matching.compute_matches_for(a) == []


def test_compute_matches_persists_and_dismisses_on_change(app, db, user, other_user):
    a = _make(db, user)
    b = _make(db, other_user, role='offering_help')
    found = matching.compute_matches_for(a)
    assert len(found) == 1 and found[0].score >= matching.MIN_SCORE
    pair = Match.ordered_ids(a.id, b.id)
    assert Match.query.filter_by(trip_a_id=pair[0], trip_b_id=pair[1]).count() == 1
    # recomputing is idempotent
    matching.compute_matches_for(a)
    assert Match.query.count() == 1
    # b moves far away -> match dismissed as post_changed
    b.from_date = date.today() + timedelta(days=60)
    db.session.commit()
    matching.compute_matches_for(a)
    m = Match.query.first()
    assert m.status == 'dismissed' and m.dismissed_reason == 'post_changed'


def test_unconfirmed_posts_only_visible_to_cs(app, db, user):
    a = _make(db, user)
    _make(db, None, role='offering_help', source='facebook', poster_name='Ravi', status='unconfirmed')
    assert matching.compute_matches_for(a) == []
    assert len(matching.compute_matches_for(a, include_unconfirmed=True)) == 1
    assert matching.ranked_matches_for(a) == []
    assert len(matching.ranked_matches_for(a, include_unconfirmed=True)) == 1


# ---------------------------------------------------------------------------
# Bridge: channels, notify, contact page
# ---------------------------------------------------------------------------

def test_channel_selection(app, db, user):
    t = _make(db, None, source='facebook', poster_name='Ravi')
    assert bridge.channel_for(t)[0] == 'none'
    db.session.add(ContactPoint(trip=t, type='facebook', value='https://facebook.com/ravi', consent_to_share=True))
    db.session.commit()
    assert bridge.channel_for(t)[0] == 'manual_facebook'
    db.session.add(ContactPoint(trip=t, type='whatsapp', value='+12145550100', consent_to_share=True))
    db.session.commit()
    assert bridge.channel_for(t)[0] == 'manual_whatsapp'      # whatsapp preferred over facebook
    db.session.add(ContactPoint(trip=t, type='email', value='ravi@example.com', consent_to_share=False))
    db.session.commit()
    assert bridge.channel_for(t)[0] == 'manual_whatsapp'      # unconsented e-mail doesn't count
    u = _make(db, user)
    assert bridge.channel_for(u)[0] == 'inapp'                 # account, no consented contact


def test_instant_match_and_notify_flow(client, user, other_user, db):
    mailer.OUTBOX.clear()
    login(client, 'bob@test.com')
    a = _post(client)                                            # bob seeks help, consented mobile
    assert a['matches_count'] == 0
    logout(client)
    login(client, 'alice@test.com')
    b = _post(client, role='offering_help', contact_points=[{'type': 'auto', 'value': 'alice@test.com'}])
    assert b['matches_count'] == 1
    ms = client.get(f"/api/trip/{b['trip']['id']}/matches").get_json()['matches']
    assert ms[0]['other']['author']['username'] == 'bob' and ms[0]['my_status'] is None
    mid = ms[0]['id']

    r = client.post(f'/api/matches/{mid}/notify', json={})
    d = r.get_json()
    assert d['success'] and d['status'] == 'notified' and d['problems'] == []
    chans = {p['trip_id']: (p['channel'], p['status']) for p in d['parties']}
    assert chans[b['trip']['id']] == ('email', 'sent')          # alice: consented e-mail -> automatic e-mail
    assert chans[a['trip']['id']] == ('inapp', 'sent')          # bob: account, no e-mail -> in-app
    assert mailer.OUTBOX and mailer.OUTBOX[-1]['recipients'] == ['alice@test.com']
    assert '/match/' in mailer.OUTBOX[-1]['body']
    assert db.session.get(CompanionRequest, a['trip']['id']).status == 'matched'
    logout(client)

    # bob sees an in-app notification with his contact link
    login(client, 'bob@test.com')
    notes = client.get('/api/notifications').get_json()['notifications']
    link = next(n['link'] for n in notes if n['type'] == 'match_found' and n['link'].startswith('/match/'))
    r = client.get(link)
    assert r.status_code == 200
    body = r.data.decode()
    assert 'alice@test.com' in body and 'alice' in body          # consented e-mail shown
    m = db.session.get(Match, mid)
    party_bob = m.party_for(a['trip']['id'])
    assert party_bob.status == 'contact_viewed' and party_bob.viewed_at is not None
    assert m.status == 'viewed'

    client.post(link + '/contacted', data={})
    m = db.session.get(Match, mid)
    assert m.status == 'connected' and m.party_for(a['trip']['id']).status == 'connected'


def test_contact_page_hides_unconsented_and_handles_dismiss(client, user, other_user, db):
    a = _make(db, user)
    db.session.add(ContactPoint(trip=a, type='mobile', value='+12145550100', consent_to_share=False))
    b = _make(db, other_user, role='offering_help')
    db.session.commit()
    m = matching.compute_matches_for(a)[0]
    parties, problems = bridge.notify_match(m)
    p_alice = m.party_for(b.id)
    r = client.get(f'/match/{p_alice.token}')
    assert r.status_code == 200
    assert '+12145550100' not in r.data.decode()                 # bob did not consent to share his mobile
    r = client.post(f'/match/{p_alice.token}/not-suitable', data={})
    assert r.status_code == 302
    assert db.session.get(Match, m.id).status == 'dismissed'
    assert client.get(f'/match/{p_alice.token}').status_code == 410
    assert client.get('/match/nope').status_code == 404


def test_notify_blocked_when_no_consent_and_no_account(app, db, user):
    a = _make(db, user)
    b = _make(db, None, role='offering_help', source='facebook', poster_name='Ravi')
    db.session.commit()
    m = matching.compute_matches_for(a)[0]
    parties, problems = bridge.notify_match(m)
    assert len(problems) == 1 and 'claim link' in problems[0]
    assert m.needs_cs_attention is True
    assert m.party_for(b.id).channel == 'none'


def test_manual_intro_text_only_includes_consented_contacts(app, db, user):
    a = _make(db, user, poster_name='Bob Test')
    db.session.add(ContactPoint(trip=a, type='mobile', value='+12145550100', consent_to_share=True, label='son'))
    db.session.add(ContactPoint(trip=a, type='email', value='secret@test.com', consent_to_share=False))
    b = _make(db, None, role='offering_help', source='facebook', poster_name='Ravi Kumar')
    db.session.add(ContactPoint(trip=b, type='facebook', value='https://facebook.com/ravi', consent_to_share=True))
    db.session.commit()
    m = matching.compute_matches_for(a)[0]
    text = bridge.intro_text(m, b)
    assert text.startswith('Hi Ravi,')
    assert '+12145550100' in text and '(son)' in text
    assert 'secret@test.com' not in text
    assert '/match/' in text


def test_cs_match_view_and_actions(client, cs_user, user, db):
    a = _make(db, user)
    b = _make(db, None, role='offering_help', source='facebook', poster_name='Ravi Kumar')
    db.session.add(ContactPoint(trip=b, type='whatsapp', value='+12145550199', consent_to_share=True))
    db.session.commit()
    login(client, 'cs@test.com')
    r = client.get(f'/cs/posts/{a.id}/matches')
    assert r.status_code == 200 and b'Ravi Kumar' in r.data and b'Notify both' in r.data
    m = Match.query.first()
    r = client.post(f'/cs/matches/{m.id}/notify', data={})
    assert r.status_code == 302
    m = db.session.get(Match, m.id)
    assert m.party_for(a.id).status == 'sent'          # bob: in-app
    assert m.party_for(b.id).status == 'pending' and m.party_for(b.id).channel == 'manual_whatsapp'
    assert m.needs_cs_attention is True
    assert b'Ravi Kumar' in client.get('/cs/matches').data
    # intro text for Ravi's side, then mark sent
    r = client.post(f'/cs/matches/{m.id}/intro-text', json={'for_trip_id': b.id})
    assert r.status_code == 200 and 'Hi Ravi' in r.get_json()['text']
    pid = r.get_json()['party_id']
    r = client.post(f'/cs/match-parties/{pid}/mark-sent', json={'channel': 'manual_whatsapp'})
    assert r.get_json()['success']
    m = db.session.get(Match, m.id)
    assert m.party_for(b.id).status == 'sent' and m.needs_cs_attention is False
    # disallowed contact ids are rejected
    r = client.post(f'/cs/matches/{m.id}/intro-text', json={'for_trip_id': b.id, 'contact_point_ids': [9999]})
    assert r.status_code == 400
    # dismiss
    client.post(f'/cs/matches/{m.id}/dismiss', data={'reason': 'duplicate'})
    assert db.session.get(Match, m.id).status == 'dismissed'


def test_closing_a_post_dismisses_its_matches(client, user, other_user, db):
    login(client, 'bob@test.com')
    a = _post(client)
    logout(client)
    login(client, 'alice@test.com')
    b = _post(client, role='offering_help', contact_points=[{'type': 'auto', 'value': 'alice@test.com'}])
    assert Match.query.count() == 1
    client.delete(f"/api/trip/{b['trip']['id']}", json={'reason': 'travelled'})
    m = Match.query.first()
    assert m.status == 'dismissed' and m.dismissed_reason == 'post_closed'


def test_user_cannot_manage_someone_elses_match(client, user, other_user, db):
    a = _make(db, user)
    b = _make(db, other_user, role='offering_help')
    third = __import__('conftest').make_user('carol@test.com', 'carol')
    m = matching.compute_matches_for(a)[0]
    login(client, 'carol@test.com')
    assert client.post(f'/api/matches/{m.id}/notify', json={}).status_code == 403
    assert client.get(f'/api/trip/{a.id}/matches').status_code == 403


# ---------------------------------------------------------------------------
# Per-leg matching across trip types
#
# A post is matched leg by leg, so trip type never limits who you can be paired with:
#   * a round trip offers its outbound and its return separately
#   * a multi-destination post offers every hop
#   * a one-way post can partner any of them
# ---------------------------------------------------------------------------

D20 = date.today() + timedelta(days=20)
D27 = date.today() + timedelta(days=27)
D34 = date.today() + timedelta(days=34)


def _round_trip(db, user, out_date=D20, back_date=D27, **kw):
    return _make(db, user, trip_type='round_trip', from_date=out_date, to_date=back_date, **kw)


def _multi(db, user, hops, **kw):
    """hops: [(from, to, 'YYYY-MM-DD'), ...]"""
    legs = [{'from': f, 'to': t, 'date': d, 'airline': None, 'flight_number': None}
            for f, t, d in hops]
    return _make(db, user, trip_type='multi_destination', legs=legs,
                 flying_from=hops[0][0], destination=hops[-1][1],
                 from_date=date.fromisoformat(hops[0][2]),
                 to_date=date.fromisoformat(hops[-1][2]), **kw)


def _legs(trip):
    return [(l.kind, l.origin_iata, l.dest_iata, l.depart_date) for l in trip.leg_rows]


def test_legs_are_derived_for_each_trip_type(app, db, user):
    one = _make(db, user)
    assert _legs(one) == [('leg', 'HYD', 'DFW', D20)]

    rt = _round_trip(db, user)
    assert _legs(rt) == [('outbound', 'HYD', 'DFW', D20), ('return', 'DFW', 'HYD', D27)]

    mt = _multi(db, user, [('Hyderabad (HYD)', 'Dubai (DXB)', D20.isoformat()),
                           ('Dubai (DXB)', 'London (LHR)', D27.isoformat())])
    assert _legs(mt) == [('leg', 'HYD', 'DXB', D20), ('leg', 'DXB', 'LHR', D27)]


def test_round_trip_return_leg_finds_its_own_companion(app, db, user, other_user):
    """Rule 1: each leg of a round trip matches one-way and multi-stop travellers."""
    rt = _round_trip(db, user)
    # somebody flying the *return* direction only, on the return date
    back = _make(db, other_user, role='offering_help',
                 flying_from='Dallas (DFW)', destination='Hyderabad (HYD)', from_date=D27)
    ms = matching.compute_matches_for(rt)
    assert len(ms) == 1
    m = ms[0]
    assert m.leg_for(rt.id).kind == 'return'
    assert m.other_trip(rt.id).id == back.id
    # ...and the outbound is still free to match somebody else
    out = _make(db, None, role='offering_help', poster_name='Ravi', from_date=D20)
    ms = matching.compute_matches_for(rt)
    kinds = {m.leg_for(rt.id).kind for m in ms}
    assert kinds == {'outbound', 'return'} and len(ms) == 2
    assert {m.other_trip(rt.id).id for m in ms} == {back.id, out.id}


def test_multi_stop_matches_each_hop_independently(app, db, user, other_user, third_user):
    """Rule 2: every hop of a multi-destination post is matched on its own."""
    mt = _multi(db, user, [('Hyderabad (HYD)', 'Dubai (DXB)', D20.isoformat()),
                           ('Dubai (DXB)', 'London (LHR)', D27.isoformat())])
    hop1 = _make(db, other_user, role='offering_help',
                 flying_from='Hyderabad (HYD)', destination='Dubai (DXB)', from_date=D20)
    hop2 = _make(db, third_user, role='offering_help',
                 flying_from='Dubai (DXB)', destination='London (LHR)', from_date=D27)
    ms = matching.compute_matches_for(mt)
    by_other = {m.other_trip(mt.id).id: m for m in ms}
    assert set(by_other) == {hop1.id, hop2.id}
    # each match points at the hop it belongs to, not at the post's overall HYD -> LHR
    assert by_other[hop1.id].leg_for(mt.id).dest_iata == 'DXB'
    assert by_other[hop2.id].leg_for(mt.id).origin_iata == 'DXB'


def test_one_way_matches_round_trip_and_multi_stop(app, db, user, other_user, third_user):
    """Rule 3: a one-way post can pair with any trip type."""
    one = _make(db, user, flying_from='Dubai (DXB)', destination='London (LHR)', from_date=D27)
    rt = _round_trip(db, other_user, role='offering_help',
                     flying_from='Dubai (DXB)', destination='London (LHR)',
                     out_date=D27, back_date=D34)
    mt = _multi(db, third_user, [('Hyderabad (HYD)', 'Dubai (DXB)', D20.isoformat()),
                                 ('Dubai (DXB)', 'London (LHR)', D27.isoformat())],
                role='offering_help')
    ms = matching.compute_matches_for(one)
    assert {m.other_trip(one.id).id for m in ms} == {rt.id, mt.id}
    for m in ms:
        assert m.leg_for(one.id).origin_iata == 'DXB'          # my only leg
        assert m.other_leg(one.id).dest_iata == 'LHR'          # the hop that lines up
    # the round trip matched on its outbound, the multi-stop on its second hop
    kinds = {m.other_trip(one.id).id: m.other_leg(one.id).kind for m in ms}
    assert kinds[rt.id] == 'outbound' and kinds[mt.id] == 'leg'


def test_two_round_trips_match_on_both_legs(app, db, user, other_user):
    """Sharing an outbound and a return is two introductions, not one."""
    a = _round_trip(db, user)
    b = _round_trip(db, other_user, role='offering_help')
    ms = matching.compute_matches_for(a)
    assert len(ms) == 2
    assert {m.leg_for(a.id).kind for m in ms} == {'outbound', 'return'}
    # a return is never paired with an outbound: the route runs the other way
    for m in ms:
        assert m.leg_for(a.id).kind == m.other_leg(a.id).kind


def test_changing_a_route_rebuilds_legs_and_drops_stale_matches(app, db, user, other_user):
    rt = _round_trip(db, user)
    _make(db, other_user, role='offering_help',
          flying_from='Dallas (DFW)', destination='Hyderabad (HYD)', from_date=D27)
    assert len(matching.compute_matches_for(rt)) == 1
    # becoming a one-way drops the return leg, and with it the match that relied on it
    rt.trip_type = 'one_way'
    rt.to_date = None
    db.session.commit()
    assert [l.kind for l in rt.leg_rows] == ['leg']
    assert matching.compute_matches_for(rt) == []


def test_search_finds_a_post_by_a_middle_leg(app, db, client, user, other_user):
    """Somebody the matcher would pair you with must also be findable by hand."""
    _multi(db, other_user, [('Hyderabad (HYD)', 'Dubai (DXB)', D20.isoformat()),
                            ('Dubai (DXB)', 'London (LHR)', D27.isoformat())],
           role='offering_help')
    # Dubai is neither the post's origin nor its destination -- only a leg endpoint
    res = client.post('/api/search', json={'flying_from': 'Dubai', 'destination': 'London'})
    assert [r['trip_type'] for r in res.get_json()['results']] == ['multi_destination']


def test_search_finds_a_round_trip_by_its_return_direction(app, db, client, user, other_user):
    _round_trip(db, other_user, role='offering_help')      # HYD -> DFW, back DFW -> HYD
    res = client.post('/api/search', json={'flying_from': 'Dallas', 'destination': 'Hyderabad'})
    assert res.get_json()['count'] == 1


def test_contact_exchange_is_audited_on_both_posts(client, user, other_user, db):
    """Sharing your details, and someone viewing them, both have to reach the CS console.

    Each half is an interaction between two posts, and the audit question is usually asked
    from the side that was affected -- so both posts carry a record of both halves.
    """
    from app.models import ActivityEvent

    login(client, 'bob@test.com')
    a = _post(client)                                            # bob, in-app only
    logout(client)
    login(client, 'alice@test.com')
    b = _post(client, role='offering_help', contact_points=[{'type': 'auto', 'value': 'alice@test.com'}])
    mid = client.get(f"/api/trip/{b['trip']['id']}/matches").get_json()['matches'][0]['id']
    a_id, b_id = a['trip']['id'], b['trip']['id']

    # alice presses "Share my contact & notify"
    assert client.post(f'/api/matches/{mid}/notify', json={}).get_json()['success']
    shared = ActivityEvent.query.filter_by(trip_id=b_id, event='contact_shared').one()
    assert shared.meta['other_trip_id'] == a_id          # named, not just "someone"
    assert shared.actor.username == 'alice'
    logout(client)

    # bob opens the link he was sent and sees alice's details
    login(client, 'bob@test.com')
    link = next(n['link'] for n in client.get('/api/notifications').get_json()['notifications']
                if n['link'].startswith('/match/'))
    assert client.get(link).status_code == 200

    # bob's post records that he looked...
    assert ActivityEvent.query.filter_by(trip_id=a_id, event='contact_viewed').count() == 1
    # ...and alice's post records that hers were the details shown
    seen = ActivityEvent.query.filter_by(trip_id=b_id, event='contact_shown_to_match').one()
    assert seen.meta['other_trip_id'] == a_id


def test_activity_reads_as_sentences_in_ist_on_both_posts(client, user, other_user, db):
    """Both travellers' timelines describe the same exchange, each from its own side."""
    from datetime import datetime, timedelta as _td
    from conftest import make_user
    from app.models import ActivityEvent

    login(client, 'bob@test.com')
    a = _post(client)
    logout(client)
    login(client, 'alice@test.com')
    b = _post(client, role='offering_help', contact_points=[{'type': 'auto', 'value': 'alice@test.com'}])
    mid = client.get(f"/api/trip/{b['trip']['id']}/matches").get_json()['matches'][0]['id']
    a_id, b_id = a['trip']['id'], b['trip']['id']

    assert client.post(f'/api/matches/{mid}/notify', json={}).get_json()['success']
    # the share is recorded on both posts, not only on the sharer's
    assert ActivityEvent.query.filter_by(trip_id=b_id, event='contact_shared').count() == 1
    assert ActivityEvent.query.filter_by(trip_id=a_id, event='contact_shared_by_match').count() == 1
    logout(client)

    make_user('agent2@test.com', 'agent2', role='cs')
    login(client, 'agent2@test.com')
    sentence = 'Alice shared their contact details with Bob'
    for tid in (b_id, a_id):                      # the sharer's post and the recipient's
        html = client.get(f'/cs/posts/{tid}').data.decode()
        assert sentence in html, tid

    # timestamps are India Standard Time, not the stored UTC
    html = client.get(f'/cs/posts/{b_id}').data.decode()
    assert (datetime.utcnow() + _td(hours=5, minutes=30)).strftime('%d %b %Y') in html
    assert 'IST' in html


def test_search_returns_the_complement_not_more_of_the_same(client, db, user, other_user, third_user):
    """Someone who needs a companion must be shown people offering help.

    The home page posts the whole trip form, role included -- that role says who the
    searcher *is*. Filtering on it directly returned more people in the same position.
    """
    _make(db, other_user, role='offering_help')
    _make(db, third_user, role='open')
    _make(db, user, role='seeking_help')

    roles = lambda d: {r['role'] for r in d['results']}

    got = client.post('/api/search', json={'for_role': 'seeking_help'}).get_json()
    assert roles(got) == {'offering_help', 'open'}          # never another seeker

    got = client.post('/api/search', json={'for_role': 'offering_help'}).get_json()
    assert roles(got) == {'seeking_help', 'open'}

    # the dashboard's browse dropdown is a different question and still filters exactly
    got = client.post('/api/search', json={'role': 'seeking_help'}).get_json()
    assert roles(got) == {'seeking_help'}


def test_a_post_can_change_shape_and_its_legs_follow(client, db, user):
    """One-way <-> round trip <-> multi-stop, with matching rebuilt each time."""
    t = _make(db, user)
    login(client, 'bob@test.com')
    shape = lambda: (db.session.get(CompanionRequest, t.id).trip_type,
                     [l.kind for l in db.session.get(CompanionRequest, t.id).leg_rows])
    base = {'role': 'seeking_help', 'flying_from': 'Hyderabad (HYD)',
            'destination': 'Dallas (DFW)', 'from_date': D20.isoformat()}

    r = client.put(f'/api/trip/{t.id}', json={**base, 'trip_type': 'round_trip',
                                              'to_date': D27.isoformat()})
    assert r.status_code == 200 and shape() == ('round_trip', ['outbound', 'return'])

    r = client.put(f'/api/trip/{t.id}', json={**base, 'trip_type': 'multi_destination', 'legs': [
        {'from': 'Hyderabad (HYD)', 'to': 'Dubai (DXB)', 'date': D20.isoformat()},
        {'from': 'Dubai (DXB)', 'to': 'London (LHR)', 'date': D27.isoformat()},
    ]})
    assert r.status_code == 200 and shape() == ('multi_destination', ['leg', 'leg'])
    legs = db.session.get(CompanionRequest, t.id).leg_rows
    assert [l.short_route for l in legs] == ['HYD → DXB', 'DXB → LHR']

    r = client.put(f'/api/trip/{t.id}', json={**base, 'trip_type': 'one_way', 'legs': []})
    assert r.status_code == 200 and shape() == ('one_way', ['leg'])

    # and a half-filled itinerary is refused without changing what is stored
    for bad in ({'trip_type': 'multi_destination', 'legs': [{'from': 'A', 'to': 'B', 'date': D20.isoformat()}]},
                {'trip_type': 'round_trip', 'to_date': ''}):
        assert client.put(f'/api/trip/{t.id}', json={**base, **bad}).status_code == 400
    assert shape() == ('one_way', ['leg'])
