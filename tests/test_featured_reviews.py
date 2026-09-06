"""Hand-picking which approved reviews appear on the public home page."""
from conftest import login, logout
from app.models import Feedback


def _fb(db, user, comment, approved=True, featured=False, rating=5):
    fb = Feedback(user_id=user.id, rating=rating, comment=comment,
                  is_approved=approved, is_featured=featured)
    db.session.add(fb)
    db.session.commit()
    return fb


def test_feature_requires_approval_first(client, db, cs_user, user):
    fb = _fb(db, user, 'pending review', approved=False)
    login(client, 'cs@test.com')
    r = client.post(f'/cs/voices/feedback/{fb.id}/feature')
    assert r.status_code == 400 and 'Approve' in r.get_json()['error']


def test_cs_toggle_and_admin_toggle(client, db, cs_user, admin_user, user):
    fb = _fb(db, user, 'great help on my flight')
    login(client, 'cs@test.com')
    d = client.post(f'/cs/voices/feedback/{fb.id}/feature').get_json()
    assert d['success'] and d['featured'] is True
    logout(client)
    login(client, 'admin@test.com')
    d2 = client.post(f'/admin/feedback/{fb.id}/feature').get_json()
    assert d2['featured'] is False                       # toggled back off


def test_home_shows_featured_only_when_any(client, db, cs_user, user, other_user):
    _fb(db, user, 'FEATURED-STORY-ALPHA', featured=True)
    _fb(db, other_user, 'PLAIN-APPROVED-BETA', featured=False)
    html = client.get('/').data.decode()
    assert 'FEATURED-STORY-ALPHA' in html
    assert 'PLAIN-APPROVED-BETA' not in html


def test_home_falls_back_to_newest_approved(client, db, user):
    _fb(db, user, 'ONLY-APPROVED-GAMMA', featured=False)
    html = client.get('/').data.decode()
    assert 'ONLY-APPROVED-GAMMA' in html                 # nothing featured yet -> section stays alive


def test_voices_table_has_feature_toggle(client, db, cs_user, user):
    _fb(db, user, 'some words')
    login(client, 'cs@test.com')
    html = client.get('/cs/voices?tab=feedback').data.decode()
    assert 'fb-feat-' in html and 'Home page' in html
