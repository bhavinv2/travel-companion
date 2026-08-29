import io
import re
from datetime import date, timedelta

from conftest import login, logout, make_user
from app.models import User, CompanionRequest, ContactPoint, Match, ClaimToken
from app.services import mailer, jobs, matching, storage, ratelimit
from test_matching import _make


def _link(body, path):
    m = re.search(r'https?://[^\s]+' + path + r'[^\s]+', body)
    return m.group(0).split('localhost', 1)[1] if m else None


# ---------------------------------------------------------------------------
# E-mail verification
# ---------------------------------------------------------------------------

def test_register_sends_verification_and_link_verifies(client, db):
    mailer.OUTBOX.clear()
    r = client.post('/auth/register', data={'email': 'new@test.com', 'username': 'newbie', 'password': 'password123',
                                            'first_name': 'New', 'agree_terms': 'on'})
    assert r.status_code == 302
    mail = next(o for o in mailer.OUTBOX if o['recipients'] == ['new@test.com'])
    link = _link(mail['body'], '/auth/verify/')
    assert link
    u = User.query.filter_by(email='new@test.com').first()
    assert u.is_verified is False
    assert b'confirm your e-mail' in client.get('/dashboard').data   # banner shown
    r = client.get(link)
    assert r.status_code == 302
    assert db.session.get(User, u.id).is_verified is True
    assert b'confirm your e-mail' not in client.get('/dashboard').data
    # tampered token
    assert client.get('/auth/verify/not-a-token').headers['Location'].endswith('/auth/login')


def test_resend_verification_requires_login(client, user):
    assert client.post('/auth/resend-verification').status_code == 302
    login(client, 'bob@test.com')
    mailer.OUTBOX.clear()
    client.post('/auth/resend-verification', data={})
    assert mailer.OUTBOX and mailer.OUTBOX[-1]['recipients'] == ['bob@test.com']


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

def test_password_reset_flow(client, user, db):
    mailer.OUTBOX.clear()
    assert client.get('/auth/forgot-password').status_code == 200
    r = client.post('/auth/forgot-password', data={'email': 'bob@test.com'})
    assert r.status_code == 302
    link = _link(mailer.OUTBOX[-1]['body'], '/auth/reset/')
    assert link
    # unknown e-mail gives the same response and sends nothing
    n = len(mailer.OUTBOX)
    client.post('/auth/forgot-password', data={'email': 'nobody@test.com'})
    assert len(mailer.OUTBOX) == n
    assert client.get(link).status_code == 200
    r = client.post(link, data={'password': 'newpassword1', 'confirm': 'newpassword1'})
    assert r.status_code == 302
    logout(client)
    assert login(client, 'bob@test.com', 'newpassword1').status_code == 302
    assert client.get('/api/my-trips').status_code == 200
    assert db.session.get(User, user.id).is_verified is True
    # the link is single-use: the password hash changed, so the token no longer validates
    logout(client)
    assert client.get(link).headers['Location'].endswith('/auth/forgot-password')


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def test_login_rate_limit(client, app, user):
    ratelimit.reset()
    app.config['RATELIMIT_ENABLED'] = True
    try:
        for _ in range(10):
            client.post('/auth/login', data={'email': 'bob@test.com', 'password': 'wrong'})
        r = client.post('/auth/login', data={'email': 'bob@test.com', 'password': 'wrong'})
        assert r.status_code == 429
    finally:
        app.config['RATELIMIT_ENABLED'] = False
        ratelimit.reset()


def test_api_rate_limit_returns_json(client, app, user):
    ratelimit.reset()
    app.config['RATELIMIT_ENABLED'] = True
    login(client, 'bob@test.com')
    try:
        for _ in range(10):
            client.post('/api/post-trip', json={})
        r = client.post('/api/post-trip', json={})
        assert r.status_code == 429 and 'Too many' in r.get_json()['error']
    finally:
        app.config['RATELIMIT_ENABLED'] = False
        ratelimit.reset()


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def test_retention_deletes_old_attachments_and_stale_unconfirmed_posts(app, db, user, cs_user, tmp_path):
    old = _make(db, user, from_date=date.today() - timedelta(days=40), status='closed')
    folder = app.config['PRIVATE_UPLOAD_FOLDER']
    import os
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'ticket_x.pdf'), 'wb') as f:
        f.write(b'%PDF-1.4')
    old.ticket_attachment = 'ticket_x.pdf'
    stale = _make(db, None, source='facebook', poster_name='Never Confirmed', created_by_id=cs_user.id,
                  from_date=date.today() - timedelta(days=2), status='closed')
    db.session.add(ContactPoint(trip=stale, type='mobile', value='+12145550100'))
    ClaimToken.issue(stale, days=14)
    keep = _make(db, None, source='facebook', poster_name='Future', created_by_id=cs_user.id,
                 from_date=date.today() + timedelta(days=5), status='unconfirmed')
    organic_old = _make(db, user, from_date=date.today() - timedelta(days=10), status='closed')
    db.session.commit()
    stale_id, keep_id, organic_id = stale.id, keep.id, organic_old.id

    result = jobs.run_retention()
    assert result['attachments_deleted'] == 1 and result['unconfirmed_deleted'] == 1
    assert not os.path.exists(os.path.join(folder, 'ticket_x.pdf'))
    assert db.session.get(CompanionRequest, old.id).ticket_attachment is None
    assert db.session.get(CompanionRequest, stale_id) is None
    assert ContactPoint.query.filter_by(value='+12145550100').count() == 0
    assert db.session.get(CompanionRequest, keep_id) is not None        # still in the future
    assert db.session.get(CompanionRequest, organic_id) is not None     # organic posts are kept
    assert 'attachments_deleted' in jobs.run_all()


# ---------------------------------------------------------------------------
# Metrics, weights, storage, mail provider, health
# ---------------------------------------------------------------------------

def test_metrics_page(client, cs_user, user, other_user, db):
    a = _make(db, user)
    b = _make(db, other_user, role='offering_help')
    m = matching.compute_matches_for(a)[0]
    from app.services import bridge
    bridge.notify_match(m)
    login(client, 'cs@test.com')
    r = client.get('/cs/metrics?days=30')
    assert r.status_code == 200
    html = r.data.decode()
    assert 'Claim rate' in html and 'Weight tuning hints' in html and 'Matches suggested' in html
    logout(client)
    login(client, 'bob@test.com')
    assert client.get('/cs/metrics').status_code == 302


def test_match_weights_override_normalises_to_100(app, db, user, other_user):
    a = _make(db, user, airline='Qatar Airways', flight_number='QR573', preferred_languages=['Telugu'])
    b = _make(db, other_user, role='offering_help', airline='Emirates', preferred_languages=['Telugu'])
    base_score, _ = matching.score_pair(a, b)
    app.config['MATCH_WEIGHTS'] = {'flight': 0, 'bogus': 99}
    try:
        w = matching.get_weights()
        assert w['flight'] == 0 and 'bogus' not in w
        score, criteria = matching.score_pair(a, b)
        assert abs(sum(c['weight'] for c in criteria) - 100) < 0.5
        assert score > base_score            # airline mismatch no longer penalised
        assert score <= 100
    finally:
        app.config['MATCH_WEIGHTS'] = {}


class _FakeS3:
    def __init__(self):
        self.objects = {}
        self.deleted = []

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None):
        self.objects[key] = fileobj.read()

    def generate_presigned_url(self, op, Params=None, ExpiresIn=None):
        return f"https://signed.example/{Params['Key']}?exp={ExpiresIn}"

    def delete_object(self, Bucket=None, Key=None):
        self.deleted.append(Key)


def test_s3_storage_backend(app, client, cs_user, monkeypatch, db):
    from PIL import Image
    fake = _FakeS3()
    monkeypatch.setattr(storage, '_s3_client', lambda: fake)
    app.config.update(STORAGE_BACKEND='s3', S3_BUCKET='bucket', S3_PUBLIC_BASE_URL='https://cdn.example')
    try:
        buf = io.BytesIO()
        Image.new('RGB', (4, 4)).save(buf, format='PNG')
        buf.seek(0)
        from werkzeug.datastructures import FileStorage
        url = storage.save_public_image(FileStorage(stream=buf, filename='p.png'), prefix='user_x')
        assert url.startswith('https://cdn.example/public/user_x_') and url.endswith('.png')
        assert any(k.startswith('public/user_x_') for k in fake.objects)
        key = storage.save_private_document(FileStorage(stream=io.BytesIO(b'%PDF-1.4'), filename='t.pdf'), prefix='ticket')
        assert key and f'private/{key}' in fake.objects
        trip = _make(db, None, source='facebook', poster_name='S3', created_by_id=cs_user.id)
        trip.ticket_attachment = key
        db.session.commit()
        login(client, 'cs@test.com')
        r = client.get(f'/files/private/{key}')
        assert r.status_code == 302 and r.headers['Location'].startswith(f'https://signed.example/private/{key}')
        storage.delete_private(key)
        assert fake.deleted == [f'private/{key}']
    finally:
        app.config.update(STORAGE_BACKEND='local')


def test_sendgrid_provider(app, monkeypatch):
    calls = []

    class Resp:
        def __init__(self, code):
            self.status_code, self.text = code, ''

    import requests
    monkeypatch.setattr(requests, 'post', lambda url, **kw: (calls.append((url, kw)), Resp(202))[1])
    app.config.update(TESTING=False, MAIL_PROVIDER='sendgrid', SENDGRID_API_KEY='sg-key', MAIL_SUPPRESS_SEND=False)
    try:
        assert mailer.send('Subject', 'x@test.com', 'Body') is True
        url, kw = calls[-1]
        assert url.startswith('https://api.sendgrid.com') and kw['headers']['Authorization'] == 'Bearer sg-key'
        assert kw['json']['personalizations'][0]['to'] == [{'email': 'x@test.com'}]
        monkeypatch.setattr(requests, 'post', lambda url, **kw: Resp(400))
        assert mailer.send('Subject', 'x@test.com', 'Body') is False
        app.config['SENDGRID_API_KEY'] = None
        assert mailer.send('Subject', 'x@test.com', 'Body') is False
    finally:
        app.config.update(TESTING=True, MAIL_PROVIDER='smtp', SENDGRID_API_KEY=None)


def test_healthz(client):
    r = client.get('/healthz')
    assert r.status_code == 200 and r.get_json()['status'] == 'ok'
