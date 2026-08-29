import os
import pytest

from conftest import login, logout
from app.models import User


def test_register_rejects_bad_username_and_missing_terms(client, db):
    r = client.post('/auth/register', data={
        'email': 'x@test.com', 'username': '<img src=x>', 'password': 'password123',
        'first_name': 'X', 'last_name': 'Y',
    })
    assert r.status_code == 200
    assert User.query.count() == 0


def test_register_success_logs_in(client, db):
    r = client.post('/auth/register', data={
        'email': 'x@test.com', 'username': 'xuser', 'password': 'password123',
        'first_name': 'X', 'last_name': 'Y', 'agree_terms': 'on',
    })
    assert r.status_code == 302
    u = User.query.filter_by(email='x@test.com').first()
    assert u is not None and u.role == 'user' and not u.is_cs
    assert client.get('/api/my-trips').status_code == 200


def test_login_open_redirect_blocked(client, user):
    r = client.post('/auth/login?next=https://evil.example.com', data={'email': 'bob@test.com', 'password': 'password123'})
    assert r.status_code == 302
    assert 'evil.example.com' not in r.headers['Location']


def test_login_relative_next_allowed(client, user):
    r = client.post('/auth/login?next=/connections', data={'email': 'bob@test.com', 'password': 'password123'})
    assert r.headers['Location'].endswith('/connections')


def test_deactivated_user_loses_session(client, user, db):
    login(client, 'bob@test.com')
    assert client.get('/api/my-trips').status_code == 200
    user.is_active = False
    db.session.commit()
    assert client.get('/api/my-trips').status_code in (302, 401)


def test_google_login_sets_state(client, app):
    app.config['GOOGLE_OAUTH_CLIENT_ID'] = 'cid'
    r = client.get('/auth/google')
    assert r.status_code == 302 and 'state=' in r.headers['Location']
    # callback without matching state must be rejected
    r = client.get('/auth/google/authorized?code=abc&state=wrong')
    assert r.status_code == 302 and r.headers['Location'].endswith('/auth/login')


def test_legacy_send_message_endpoint_removed(client, user):
    login(client, 'bob@test.com')
    assert client.post('/api/send-message', json={'recipient_id': 1, 'body': 'hi'}).status_code == 404


def test_secret_key_required_in_production(monkeypatch):
    from app import create_app
    monkeypatch.setenv('FLASK_ENV', 'production')
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.delenv('FLASK_SECRET_KEY', raising=False)
    with pytest.raises(RuntimeError):
        create_app()
