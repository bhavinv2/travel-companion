"""Who may send what, and getting into an account.

Three promises:

  * Sign-in and sign-up mail -- verification, password reset, a new staff member's invite -- always
    goes out. It is not a notification, and switching notifications off used to stop password reset
    for everybody without a word.
  * The Gmail mailbox carries that mail and nothing else. Match alerts, CS replies and blog
    announcements go through SendGrid when it is set up, and are not e-mailed when it is not.
  * A signed-in person can change their own password without e-mail at all.
"""
import pytest

from conftest import login
from app import db as _db
from app.models import User
from app.services import mailer, settings


@pytest.fixture
def gmail(app):
    """The production default: the SMTP server is Gmail, and there is no SendGrid."""
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    app.config['SENDGRID_API_KEY'] = None
    app.config['MAIL_PROVIDER'] = 'smtp'
    mailer.OUTBOX.clear()
    return app


# ---------------------------------------------------------------------------
# Gmail is kept for sign-in and sign-up
# ---------------------------------------------------------------------------

def test_a_password_reset_goes_through_gmail(client, user, gmail):
    client.post('/auth/forgot-password', data={'email': 'bob@test.com'})
    assert len(mailer.OUTBOX) == 1
    sent = mailer.OUTBOX[0]
    assert sent['account'] is True and sent['transport'] == 'smtp'
    assert '/auth/reset/' in sent['body']


def test_a_signup_verification_goes_through_gmail(client, user, gmail):
    login(client, 'bob@test.com')
    client.post('/auth/resend-verification', data={})
    assert mailer.OUTBOX and mailer.OUTBOX[-1]['account'] is True


def test_everything_else_is_not_sent_through_gmail(app, gmail):
    with app.test_request_context():
        assert mailer.send('Match found', ['a@example.com'], 'hello', category='match_alerts') is False
        assert mailer.send('Reply', ['a@example.com'], 'hello', category='cs', force=True) is False
    assert mailer.OUTBOX == []


def test_everything_else_uses_sendgrid_when_it_is_set_up(app, gmail):
    app.config['SENDGRID_API_KEY'] = 'SG.test'
    with app.test_request_context():
        assert mailer.send('Match found', ['a@example.com'], 'hello', category='match_alerts') is True
        assert mailer.send('Reset', ['a@example.com'], 'link', category='account', account=True) is True
    transports = [m['transport'] for m in mailer.OUTBOX]
    assert transports == ['sendgrid', 'smtp'], 'and sign-in mail still goes through Gmail'


def test_a_server_that_is_not_gmail_carries_both(app):
    app.config['MAIL_SERVER'] = 'smtp.mailgun.org'
    mailer.OUTBOX.clear()
    with app.test_request_context():
        assert mailer.send('Match found', ['a@example.com'], 'hello', category='match_alerts') is True


def test_a_cs_reply_says_why_it_was_not_e_mailed(client, cs_user, gmail):
    from app.models import ContactMessage, ContactReply
    m = ContactMessage(name='Asha', email='asha@example.com', message='please help', topic='companion')
    _db.session.add(m)
    _db.session.commit()
    login(client, 'cs@test.com')
    r = client.post('/cs/contact/%d/reply' % m.id, data={'body': 'We are on it, will call you today.'},
                    follow_redirects=True)
    assert b'kept for sign-in and sign-up' in r.data
    reply = ContactReply.query.one()
    assert reply.delivered is False


# ---------------------------------------------------------------------------
# Never switched off
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('switches', [
    {'enabled': False},
    {'enabled': True, 'channels': {'email': False}},
    {'enabled': True, 'categories': {'account': False}},
])
def test_password_reset_survives_every_switch(client, user, gmail, switches):
    settings.set_notification_switches(switches)
    client.post('/auth/forgot-password', data={'email': 'bob@test.com'})
    assert mailer.OUTBOX and '/auth/reset/' in mailer.OUTBOX[-1]['body']


def test_the_switches_screen_shows_account_mail_as_always_on(client, admin_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/notifications').data.decode()
    assert 'name="cat_account"' not in html
    assert 'always on' in html


def test_the_staff_invite_link_is_built_like_the_reset_link(client, admin_user, gmail):
    login(client, 'admin@test.com')
    client.post('/admin/users/new', data={'email': 'newagent@example.com', 'username': 'newagent',
                                          'roles': 'cs', 'send_link': 'on'})
    invite = [m for m in mailer.OUTBOX if 'newagent@example.com' in m['recipients']]
    assert invite and invite[0]['account'] is True
    with client.application.test_request_context():
        from flask import url_for
        assert url_for('auth.login', _external=True) in invite[0]['body']


# ---------------------------------------------------------------------------
# The admin's test button
# ---------------------------------------------------------------------------

def test_the_test_button_explains_a_missing_password(client, admin_user, gmail):
    gmail.config['TESTING'] = False         # so diagnose() really looks at the settings
    try:
        login(client, 'admin@test.com')
        r = client.post('/admin/messages/test-email', follow_redirects=True)
    finally:
        gmail.config['TESTING'] = True
    assert b'MAIL_PASSWORD is not set' in r.data
    assert b'App Password' in r.data


def test_the_messages_screen_shows_how_mail_is_delivered(client, admin_user, gmail):
    login(client, 'admin@test.com')
    html = client.get('/admin/messages').data.decode()
    assert 'E-mail delivery' in html and 'Send a test e-mail to me' in html
    assert 'not e-mailed' in html               # Gmail and no SendGrid: the rest is held back


def test_the_test_button_is_admin_only(client, cs_user):
    login(client, 'cs@test.com')
    r = client.post('/admin/messages/test-email')
    assert r.status_code in (302, 403)


# ---------------------------------------------------------------------------
# Changing your own password
# ---------------------------------------------------------------------------

def _change(client, current, new, confirm=None):
    return client.post('/auth/change-password', data={'current': current, 'password': new,
                                                      'confirm': new if confirm is None else confirm})


def test_an_admin_can_replace_a_weak_password_without_e_mail(client, admin_user):
    login(client, 'admin@test.com')
    r = _change(client, 'password123', 'a-much-better-one-2026')
    assert r.status_code == 302
    u = User.query.filter_by(email='admin@test.com').one()
    assert u.check_password('a-much-better-one-2026')
    assert not u.check_password('password123')


@pytest.mark.parametrize('current, new, confirm, why', [
    ('wrong-current', 'a-much-better-one-2026', None, b'current password is not right'),
    ('password123', 'short', None, b'at least 8 characters'),
    ('password123', 'a-much-better-one-2026', 'different-one-2026', b'do not match'),
    ('password123', 'password123', None, b'password you have now'),
])
def test_a_bad_change_is_refused_and_nothing_changes(client, admin_user, current, new, confirm, why):
    login(client, 'admin@test.com')
    r = _change(client, current, new, confirm)
    assert r.status_code == 400 and why in r.data
    assert User.query.filter_by(email='admin@test.com').one().check_password('password123')


def test_changing_it_kills_reset_links_already_sent(client, user):
    from app.services import tokens
    u = User.query.filter_by(email='bob@test.com').one()
    token = tokens.make_reset_token(u)
    login(client, 'bob@test.com')
    _change(client, 'password123', 'a-much-better-one-2026')
    client.post('/auth/logout')
    r = client.get('/auth/reset/' + token)
    assert r.status_code == 302 and '/auth/forgot-password' in r.headers['Location']


def test_change_password_needs_you_signed_in(client, db):
    assert client.get('/auth/change-password').status_code == 302


def test_everybody_signed_in_finds_it_in_their_menu(client, user):
    login(client, 'bob@test.com')
    assert '/auth/change-password' in client.get('/').data.decode()
