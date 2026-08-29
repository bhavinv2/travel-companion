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
