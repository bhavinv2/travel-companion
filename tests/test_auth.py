import os
import pytest

from conftest import login, logout
from app.models import User


def test_register_requires_terms(client, db):
    r = client.post('/auth/register', data={
        'email': 'x@test.com', 'password': 'password123',
        'first_name': 'X', 'last_name': 'Y', 'phone': '+1 555 010 1234',
    })
    assert r.status_code == 200
    assert User.query.count() == 0


def test_register_success_logs_in(client, db):
    r = client.post('/auth/register', data={
        'email': 'x@test.com', 'password': 'password123',
        'first_name': 'X', 'last_name': 'Y', 'phone': '+1 555 010 1234', 'agree_terms': 'on',
    })
    assert r.status_code == 302
    u = User.query.filter_by(email='x@test.com').first()
    assert u is not None and u.role == 'user' and not u.is_cs
    assert client.get('/api/my-trips').status_code == 200


def test_signup_never_asks_for_a_username(client, db):
    """Sign-up takes the name people already have; a handle is an implementation detail."""
    assert b'name="username"' not in client.get('/auth/register').data
    assert b'name="username"' not in client.get('/').data          # landing sign-up prompt


def test_username_is_derived_from_the_name_and_stays_unique(client, db):
    def signup(email, first, last):
        r = client.post('/auth/register', data={
            'email': email, 'password': 'password123', 'first_name': first, 'last_name': last,
            'phone': '+1 555 010 1234', 'agree_terms': 'on'})
        assert r.status_code == 302
        logout(client)
        return User.query.filter_by(email=email).first().username

    assert signup('r1@test.com', 'Ramesh', 'Kumar') == 'rameshkumar'
    # same name again -> numbered, never a collision or an error shown to the second person
    assert signup('r2@test.com', 'Ramesh', 'Kumar') == 'rameshkumar1'
    # punctuation and spacing in a name can't leak into the handle
    assert signup('r3@test.com', "D'Souza  Priya", 'Rao-Naidu') == 'dsouzapriyaraonaidu'
    assert signup('r4@test.com', '<img src=x>', '') == 'imgsrcx'


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
