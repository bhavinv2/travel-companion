"""Reported matches: the /match/<token> report box -> a CS-visible, resolvable report + notifications."""
from datetime import date, timedelta

from conftest import login, logout
from app.models import Match, MatchReport, Notification, CompanionRequest, User
from app.services import matching, bridge
from app.services.locations import apply_route


def _make(db, user, **kw):
    t = CompanionRequest(user_id=user.id if user else None, travel_type='air', trip_type='one_way',
                         flying_from='Hyderabad (HYD)', destination='Dallas (DFW)',
                         from_date=date.today() + timedelta(days=20), role='seeking_help', source='organic')
    for k, v in kw.items():
        setattr(t, k, v)
    apply_route(t)
    t.set_status('open')
    db.session.add(t)
    db.session.commit()
    return t


def _reported(client, db, user, other_user, reason='Never replied; the phone number looks wrong.'):
    a = _make(db, user)
    b = _make(db, other_user, role='offering_help')
    m = matching.compute_matches_for(a)[0]
    bridge.notify_match(m)
    db.session.commit()
    party = m.party_for(a.id)
    r = client.post(f'/match/{party.token}/report', data={'reason': reason})
    return m, a, r


def test_report_creates_row_flags_match_and_notifies_all_staff(client, db, user, other_user, cs_user, admin_user):
    m, a, r = _reported(client, db, user, other_user)
    assert r.status_code == 302
    rep = MatchReport.query.filter_by(match_id=m.id).first()
    assert rep is not None and rep.status == 'open' and 'Never replied' in rep.reason
    assert db.session.get(Match, m.id).needs_cs_attention is True

    staff = {u.id for u in User.query.all() if u.is_cs and u.is_active}
    assert len(staff) >= 2                                            # cs_user + admin_user
    reported_to = {n.user_id for n in Notification.query.filter_by(type='cs_escalation', title='Match reported')}
    assert staff <= reported_to


def test_report_shows_in_cs_voices_and_queue(client, db, user, other_user, cs_user):
    m, a, r = _reported(client, db, user, other_user)
    login(client, 'cs@test.com')
    voices = client.get('/cs/voices?tab=report')
    assert voices.status_code == 200 and 'Never replied' in voices.data.decode()
    home = client.get('/cs/').data.decode()
    assert 'Reported matches' in home and 'Never replied' in home


def test_cs_can_resolve_which_clears_the_queue_flag(client, db, user, other_user, cs_user):
    m, a, r = _reported(client, db, user, other_user)
    rep = MatchReport.query.filter_by(match_id=m.id).first()
    login(client, 'cs@test.com')
    res = client.post(f'/cs/reports/{rep.id}/resolve', json={'cs_notes': 'checked'})
    assert res.get_json()['status'] == 'resolved'
    db.session.refresh(rep)
    assert rep.status == 'resolved' and rep.cs_notes == 'checked'
    assert db.session.get(Match, m.id).needs_cs_attention is False    # last open report cleared


def test_cs_cannot_delete_report_but_admin_can(client, db, user, other_user, cs_user, admin_user):
    m, a, r = _reported(client, db, user, other_user)
    rep = MatchReport.query.filter_by(match_id=m.id).first()
    login(client, 'cs@test.com')
    assert client.post(f'/cs/reports/{rep.id}/delete', json={}).status_code == 403
    assert db.session.get(MatchReport, rep.id) is not None
    logout(client)
    login(client, 'admin@test.com')
    assert client.post(f'/cs/reports/{rep.id}/delete', json={}).get_json()['success'] is True
    assert db.session.get(MatchReport, rep.id) is None


def test_reports_screen_requires_staff(client, db, user):
    login(client, 'bob@test.com')
    assert client.get('/cs/voices?tab=report').status_code in (302, 403)
    assert client.post('/cs/reports/1/resolve', json={}).status_code in (302, 403, 404)
