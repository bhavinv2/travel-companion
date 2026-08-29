import io
from datetime import date, datetime, timedelta

from conftest import login, logout, TRIP_JSON, make_user
from app.models import CompanionRequest, ContactPoint, Match, MatchParty, Notification
from app.services import matching, bridge, jobs, importer, mailer
from test_matching import _make, _post, FUTURE


# ---------------------------------------------------------------------------
# Escalation job
# ---------------------------------------------------------------------------

def test_escalation_tiers(app, db, user):
    soon = _make(db, user, from_date=date.today() + timedelta(days=1))
    week = _make(db, user, from_date=date.today() + timedelta(days=5))
    later = _make(db, user, from_date=date.today() + timedelta(days=20))
    assert jobs.escalation_hours(soon) == 2
    assert jobs.escalation_hours(week) == 12
    assert jobs.escalation_hours(later) == 24


def test_run_escalation_flags_silent_sides_and_is_idempotent(app, db, user, other_user, cs_user):
    a = _make(db, user, from_date=date.today() + timedelta(days=1), created_by_id=cs_user.id)
    b = _make(db, other_user, role='offering_help', from_date=date.today() + timedelta(days=1))
    m = matching.compute_matches_for(a)[0]
    bridge.notify_match(m)                       # both sides: in-app -> 'sent'
    for p in m.parties:
        p.sent_at = datetime.utcnow() - timedelta(hours=3)
    db.session.commit()
    assert jobs.run_escalation() == 2
    m = db.session.get(Match, m.id)
    assert m.needs_cs_attention is True and all(p.escalated_at for p in m.parties)
    assert Notification.query.filter_by(user_id=cs_user.id, type='cs_escalation').count() >= 1
    assert jobs.run_escalation() == 0            # already escalated


def test_run_escalation_respects_window_and_opened_links(app, db, user, other_user):
    a = _make(db, user, from_date=date.today() + timedelta(days=20))
    b = _make(db, other_user, role='offering_help', from_date=date.today() + timedelta(days=20))
    m = matching.compute_matches_for(a)[0]
    bridge.notify_match(m)
    for p in m.parties:
        p.sent_at = datetime.utcnow() - timedelta(hours=3)   # 24 h window for far-off trips
    db.session.commit()
    assert jobs.run_escalation() == 0
    # past the window: a side that opened its link is never escalated, the silent side is
    for p in m.parties:
        p.sent_at = datetime.utcnow() - timedelta(hours=30)
    bridge.record_opened(m.party_for(a.id))
    db.session.commit()
    assert jobs.run_escalation() == 1            # only the other (silent) side
    assert m.party_for(a.id).escalated_at is None and m.party_for(b.id).escalated_at is not None


def test_close_departed_posts(app, db, user, other_user):
    old = _make(db, user, from_date=date.today() - timedelta(days=3))
    fresh = _make(db, other_user, role='offering_help', from_date=date.today() + timedelta(days=3))
    assert jobs.close_departed_posts() == 1
    assert db.session.get(CompanionRequest, old.id).status == 'closed'
    assert db.session.get(CompanionRequest, old.id).closed_reason == 'travelled'
    assert db.session.get(CompanionRequest, fresh.id).status == 'open'


def test_jobs_endpoint_requires_secret(client, app):
    assert client.post('/internal/jobs/run').status_code == 404       # disabled when unset
    app.config['JOBS_SECRET'] = 's3cret'
    assert client.post('/internal/jobs/run').status_code == 403
    r = client.post('/internal/jobs/run', headers={'X-Jobs-Secret': 's3cret'})
    assert r.status_code == 200 and r.get_json()['success'] and 'escalated' in r.get_json()


# ---------------------------------------------------------------------------
# New-match alerts (throttled heads-up, no contact sharing)
# ---------------------------------------------------------------------------

def test_new_post_alerts_existing_side_once_per_hour(client, user, other_user, db):
    mailer.OUTBOX.clear()
    login(client, 'bob@test.com')
    bob = _post(client, contact_points=[{'type': 'auto', 'value': 'bob@test.com'}])   # consented e-mail
    logout(client)
    login(client, 'alice@test.com')
    _post(client, role='offering_help', contact_points=[{'type': 'auto', 'value': 'alice@test.com'}])
    notes = Notification.query.filter_by(user_id=user.id, type='match_found').all()
    assert len(notes) == 1 and notes[0].link == '/dashboard'
    assert any(o['recipients'] == ['bob@test.com'] and 'New possible companion' in o['subject'] for o in mailer.OUTBOX)
    assert '/match/' not in [o for o in mailer.OUTBOX if o['recipients'] == ['bob@test.com']][-1]['body']
    logout(client)
    carol = make_user('carol@test.com', 'carol')
    login(client, 'carol@test.com')
    _post(client, role='offering_help', contact_points=[{'type': 'auto', 'value': 'carol@test.com'}])
    assert Notification.query.filter_by(user_id=user.id, type='match_found').count() == 1   # throttled


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------

SCRAPER_CSV = (
    "title,origin,flight,destination,start,end,role,message,languages,contact,_page,_url,_fetched_at,_key\n"
    "My mom is travelling from BLR to DFW,BLR,QR573,DFW,\"8/24/2099, 4:00:00 AM\",\"8/24/2099, 3:40:00 PM\",Seeking Help,"
    "She is set for wheelchair,TELUGU,2149293427,1,https://travelcompanions.netlify.app/,2026-08-29T18:08:22+05:30,a5d9fe4d\n"
    "Can help,HYD,,DFW,2099-08-25,N/A,Offering Help,Happy to assist,\"Telugu, Hindi\",ravi@example.com,1,https://travelcompanions.netlify.app/,2026-08-29,k2\n"
    "Bad row,Atlantis,,DFW,not a date,,Seeking Help,,,,,,,k3\n"
)


def test_importer_parses_scraper_csv(app, db):
    records, err = importer.parse_file(io.BytesIO(SCRAPER_CSV.encode('utf-8')), 'companions.csv')
    assert err is None and len(records) == 3
    rows = importer.annotate_duplicates([importer.build_row(r, i) for i, r in enumerate(records)])
    r0, r1, r2 = rows
    assert r0['status'] == 'ok'
    assert r0['flying_from'].endswith('(BLR)') and r0['destination'].endswith('(DFW)')
    assert r0['from_date'] == '2099-08-24' and r0['to_date'] == '2099-08-24' or r0['to_date'] is None
    assert r0['airline'] == 'Qatar Airways' and r0['flight_number'] == 'QR573'
    assert r0['role'] == 'seeking_help' and r0['languages'] == ['Telugu']
    assert r0['contacts'] == [{'type': 'mobile', 'value': '2149293427'}]
    assert r0['import_key'] == 'a5d9fe4d'
    assert r1['role'] == 'offering_help' and r1['languages'] == ['Telugu', 'Hindi']
    assert r1['contacts'][0]['type'] == 'email'
    assert r2['status'] == 'error' and any('Origin' in e for e in r2['errors']) and any('date' in e for e in r2['errors'])


def test_importer_parses_xlsx_rows_sheet(app, db):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'rows'
    ws.append(['origin', 'destination', 'start', 'role', 'languages', 'contact', '_key'])
    ws.append(['HYD', 'DFW', datetime(2099, 9, 1, 4, 0), 'Seeking Help', 'Telugu', '+1 469 555 0100', 'x1'])
    wb.create_sheet('runs').append(['run', 'when'])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    records, err = importer.parse_file(buf, 'export.xlsx')
    assert err is None and len(records) == 1
    row = importer.build_row(records[0], 0)
    assert row['from_date'] == '2099-09-01' and row['contacts'][0]['value'] == '+14695550100'


def test_import_commit_creates_unconfirmed_posts_and_dedupes(client, cs_user, db):
    login(client, 'cs@test.com')
    r = client.post('/cs/import', data={'file': (io.BytesIO(SCRAPER_CSV.encode('utf-8')), 'companions.csv'),
                                        'default_source': 'website'}, content_type='multipart/form-data')
    assert r.status_code == 200
    html = r.data.decode()
    assert '2 ready' in html and '1 error' in html
    import re
    payload = re.search(r'name="payload" value="([^"]+)"', html).group(1)
    import html as _html
    payload = _html.unescape(payload)
    r = client.post('/cs/import', data={'step': 'commit', 'payload': payload, 'include': ['0', '1']})
    assert r.status_code == 302
    posts = CompanionRequest.query.filter(CompanionRequest.import_key.in_(['a5d9fe4d', 'k2'])).all()
    assert len(posts) == 2 and all(p.status == 'unconfirmed' and p.created_by_id == cs_user.id for p in posts)
    assert all(not cp.consent_to_share and cp.added_by == 'import' for p in posts for cp in p.contact_points)
    assert 'post_imported' in [e.event for e in posts[0].events]
    # Re-uploading the same file marks both rows as duplicates
    r = client.post('/cs/import', data={'file': (io.BytesIO(SCRAPER_CSV.encode('utf-8')), 'companions.csv')},
                    content_type='multipart/form-data')
    assert '2 duplicate' in r.data.decode() and '0 ready' in r.data.decode()
    # unconfirmed imports are invisible publicly
    assert client.post('/api/search', json={}).get_json()['count'] == 0


def test_import_requires_cs(client, user):
    login(client, 'bob@test.com')
    assert client.get('/cs/import').status_code == 302


# ---------------------------------------------------------------------------
# Dashboard & modify-in-place
# ---------------------------------------------------------------------------

def test_dashboard_shows_matches_and_requires_login(client, user, other_user, db):
    assert client.get('/dashboard').status_code == 302
    a = _make(db, user)
    b = _make(db, other_user, role='offering_help', preferred_languages=['Telugu'])
    matching.compute_matches_for(a)
    login(client, 'bob@test.com')
    r = client.get('/dashboard')
    assert r.status_code == 200
    html = r.data.decode()
    assert 'Your matches' in html and 'alice' in html and 'Share my contact' in html
    assert 'editTripModal' in html


def test_modify_trip_in_place_recomputes_matches(client, user, other_user, db):
    login(client, 'bob@test.com')
    a = _post(client)
    logout(client)
    login(client, 'alice@test.com')
    b = _post(client, role='offering_help', contact_points=[{'type': 'auto', 'value': 'alice@test.com'}])
    assert Match.query.filter(Match.status != 'dismissed').count() == 1
    far = (date.today() + timedelta(days=60)).isoformat()
    r = client.put(f"/api/trip/{b['trip']['id']}", json={'from_date': far, 'flying_from': 'Hyderabad (HYD)',
                                                         'destination': 'Dallas (DFW)', 'airline': 'Emirates',
                                                         'preferred_languages': ['Hindi'], 'to_date': ''})
    assert r.status_code == 200 and r.get_json()['trip']['from_date'] == far
    assert Match.query.filter(Match.status != 'dismissed').count() == 0
    trip = db.session.get(CompanionRequest, b['trip']['id'])
    assert trip.airline == 'Emirates' and trip.preferred_languages == ['Hindi']
    r = client.put(f"/api/trip/{b['trip']['id']}", json={'flying_from': ''})
    assert r.status_code == 400


def test_search_language_and_days_filters(client, user):
    login(client, 'bob@test.com')
    _post(client, preferred_languages=['Telugu'])
    _post(client, preferred_languages=['Gujarati'], from_date=(date.today() + timedelta(days=80)).isoformat())
    assert client.post('/api/search', json={'language': 'Telugu'}).get_json()['count'] == 1
    assert client.post('/api/search', json={'days': 30}).get_json()['count'] == 1
    assert client.post('/api/search', json={}).get_json()['count'] == 2
