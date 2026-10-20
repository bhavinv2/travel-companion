"""Only accounts made on the sign-up page are asked to confirm their e-mail (the reminder bar, the mail, resend):
accounts staff make or invite, accounts that claimed a post and staff accounts are never asked.
"""
from conftest import login, logout, make_user
from app import db as _db
from app.models import User
from app.services import access, mailer

BAR = b'confirm your e-mail'


def test_a_sign_up_is_asked_and_stops_being_asked_once_confirmed_or_staff(client, db):
    mailer.OUTBOX.clear()
    client.post('/auth/register', data={'email': 'new@test.com', 'password': 'password123', 'first_name': 'New',
                                        'phone': '+1 555 010 9999', 'agree_terms': 'on'})
    u = User.query.filter_by(email='new@test.com').one()
    assert u.signed_up and u.needs_email_check
    assert any(o['recipients'] == ['new@test.com'] for o in mailer.OUTBOX)
    assert BAR in client.get('/dashboard').data
    u.set_roles(['user', 'cs'])                                   # made staff: never asked
    _db.session.commit()
    assert not _db.session.get(User, u.id).needs_email_check


def test_accounts_not_made_by_signing_up_are_never_asked(client, app, admin_user, user):
    assert not user.needs_email_check                            # e.g. made by staff, or by an import
    login(client, user.email)
    assert BAR not in client.get('/dashboard').data
    mailer.OUTBOX.clear()
    client.post('/auth/resend-verification', data={})
    assert mailer.OUTBOX == []
    logout(client)
    ws = access.ensure_defaults()
    login(client, admin_user.email)
    client.post('/admin/workspace/members/add', data={'email': 'invited@test.com', 'role_id': access.system_role(ws, 'cs').id})
    invited = User.query.filter_by(email='invited@test.com').one()
    assert not invited.signed_up and not invited.needs_email_check


def test_google_and_facebook_accounts_are_never_asked(app):
    u = make_user('g@test.com', 'goo')
    u.signed_up, u.oauth_provider = True, 'google'
    _db.session.commit()
    assert not u.needs_email_check
