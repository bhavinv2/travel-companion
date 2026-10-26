"""Sign-in security (2026-10-26): every signed-in browser is a session row; ending one (yourself, an admin, a
password change, idle) signs that browser out; two-step sign-in with an authenticator app and backup codes; the rules
under Team > Security; the audit log.

    sessions   a row per browser, the audit lines, ending one from another browser, idle staff signed out
    password   changing it signs every other browser and "remember me" cookie out, this one stays in
    two-step   set-up, the gate after the password, wrong codes, backup codes once, a trusted browser, the rules
    admin      Team > Security: the tabs, ending a session, signing somebody out, turning their two-step off
"""
from datetime import datetime, timedelta

import pytest

from conftest import login, logout, make_user
from app import db as _db
from app.models import ActivityEvent, User, UserSession
from app.services import signin, totp


def events(name):
    return ActivityEvent.query.filter_by(event=name).all()


def turn_on_two_step(user):
    user.totp_secret = totp.new_secret()
    user.totp_on_at = datetime.utcnow()
    plain, user.backup_codes = totp.new_backup_codes()
    _db.session.commit()
    return plain


@pytest.fixture()
def staff(app):
    return make_user('agent@test.com', 'agent', role='cs')


# ============================================================================================ sessions

def test_a_sign_in_makes_a_session_and_signing_out_ends_it(app, client, staff):
    login(client, staff.email)
    client.get('/cs/')
    row = UserSession.query.filter_by(user_id=staff.id).one()
    assert row.ended_at is None and row.how == 'password'
    assert len(events('signin')) == 1
    logout(client)
    assert _db.session.get(UserSession, row.id).ended_at is not None
    assert _db.session.get(UserSession, row.id).ended_reason == 'signed_out' and len(events('signout')) == 1


def test_a_failed_sign_in_is_in_the_audit_log(app, client, staff):
    login(client, staff.email, 'wrong-password')
    ev = events('signin_failed')
    assert len(ev) == 1 and ev[0].meta['email'] == staff.email and ev[0].actor_id is None


def test_an_old_session_without_a_version_still_works(app, client, staff):
    """Sessions made before the version existed carry the bare id: still good while the version is 0."""
    assert staff.get_id() == str(staff.id)
    login(client, staff.email)
    assert client.get('/cs/').status_code == 200


def test_ending_a_browser_from_another_signs_it_out(app, staff):
    a, b = app.test_client(), app.test_client()
    login(a, staff.email)
    a.get('/cs/')
    login(b, staff.email)
    b.get('/cs/')
    rows = UserSession.query.filter_by(user_id=staff.id).order_by(UserSession.id).all()
    assert len(rows) == 2
    page = a.get('/auth/security').get_data(as_text=True)
    assert 'This browser' in page and 'Sign out everywhere else' in page
    a.post('/auth/security', data={'sid': rows[1].id})
    r = b.get('/cs/')
    assert r.status_code == 302 and '/auth/login' in r.headers['Location']
    assert a.get('/cs/').status_code == 200          # the one that ended it is still in


def test_sign_out_everywhere_else_keeps_this_browser(app, staff):
    a, b, c = app.test_client(), app.test_client(), app.test_client()
    for x in (a, b, c):
        login(x, staff.email)
        x.get('/cs/')
    a.post('/auth/security', data={'action': 'others'})
    assert b.get('/cs/').status_code == 302 and c.get('/cs/').status_code == 302
    assert a.get('/cs/').status_code == 200


def test_idle_staff_are_signed_out_and_travellers_are_not(app, client, staff, user):
    login(client, staff.email)
    client.get('/cs/')
    row = UserSession.query.filter_by(user_id=staff.id).one()
    row.last_seen_at = datetime.utcnow() - timedelta(hours=13)
    _db.session.commit()
    r = client.get('/cs/')
    assert r.status_code == 302 and '/auth/login' in r.headers['Location']
    assert _db.session.get(UserSession, row.id).ended_reason == 'idle'
    t = app.test_client()
    login(t, user.email)
    t.get('/dashboard')
    trow = UserSession.query.filter_by(user_id=user.id).one()
    trow.last_seen_at = datetime.utcnow() - timedelta(hours=48)
    _db.session.commit()
    assert t.get('/dashboard').status_code == 200


# ============================================================================================ password

def test_a_password_change_signs_out_every_other_browser_and_cookie(app, staff):
    a, b = app.test_client(), app.test_client()
    login(a, staff.email)
    a.get('/cs/')
    b.post('/auth/login', data={'email': staff.email, 'password': 'password123', 'remember': 'on'})
    b.get('/cs/')
    r = a.post('/auth/change-password', data={'current': 'password123', 'password': 'new-password-1',
                                              'confirm': 'new-password-1'})
    assert r.status_code == 302
    assert a.get('/cs/').status_code == 200                       # this browser stays in
    assert b.get('/cs/').status_code == 302                       # the other is out
    assert _db.session.get(User, staff.id).session_version == 1
    # the old "remember me" cookie alone does not get back in either
    b2 = app.test_client()
    cookie = b.get_cookie('remember_token')
    if cookie is not None:
        b2.set_cookie('remember_token', cookie.value)
        assert b2.get('/cs/').status_code == 302


# ============================================================================================ two-step

def test_turning_two_step_on_shows_the_qr_code_and_backup_codes_once(app, client, staff):
    login(client, staff.email)
    client.post('/auth/security/two-step', data={'action': 'start'})
    page = client.get('/auth/security').get_data(as_text=True)
    assert '<svg' in page and 'Type this key instead' in page
    with client.session_transaction() as s:
        pending = s['totp_pending']
    bad = client.post('/auth/security/two-step', data={'action': 'confirm', 'code': '000000'})
    assert bad.status_code == 302 and not _db.session.get(User, staff.id).two_step_on
    r = client.post('/auth/security/two-step', data={'action': 'confirm', 'code': totp.code(pending)})
    html = r.get_data(as_text=True)
    u = _db.session.get(User, staff.id)
    assert r.status_code == 200 and u.two_step_on and len(u.backup_codes) == 10
    assert html.count('<li><code>') == 10
    assert pending not in client.get('/auth/security').get_data(as_text=True)      # the key is never shown again
    assert len(events('two_step_on')) == 1


def test_the_code_is_asked_after_the_password(app, client, staff):
    turn_on_two_step(staff)
    login(client, staff.email)
    r = client.get('/cs/')
    assert r.status_code == 302 and '/auth/two-step' in r.headers['Location']
    assert client.get('/api/unread-count', headers={'Accept': 'application/json'}).status_code == 401
    wrong = client.post('/auth/two-step', data={'code': '000000'})
    assert wrong.status_code == 400 and len(events('two_step_failed')) == 1
    ok = client.post('/auth/two-step', data={'code': totp.code(staff.totp_secret)})
    assert ok.status_code == 302 and '/cs' in ok.headers['Location']
    assert client.get('/cs/').status_code == 200
    assert UserSession.query.filter_by(user_id=staff.id).one().two_step is True


def test_a_backup_code_works_once(app, staff):
    plain = turn_on_two_step(staff)
    a = app.test_client()
    login(a, staff.email)
    assert a.post('/auth/two-step', data={'code': plain[0].upper()}).status_code == 302
    assert len(_db.session.get(User, staff.id).backup_codes) == 9
    b = app.test_client()
    login(b, staff.email)
    assert b.post('/auth/two-step', data={'code': plain[0]}).status_code == 400


def test_a_trusted_browser_is_not_asked_again(app, staff):
    turn_on_two_step(staff)
    a = app.test_client()
    login(a, staff.email)
    a.post('/auth/two-step', data={'code': totp.code(staff.totp_secret), 'trust': 'on'})
    assert a.get_cookie(signin.DEVICE_COOKIE) is not None
    logout(a)
    login(a, staff.email)
    assert a.get('/cs/').status_code == 200          # the cookie stands in for the code
    # turning two-step off and on again forgets every trusted browser
    u = _db.session.get(User, staff.id)
    u.totp_on_at = datetime.utcnow() + timedelta(seconds=5)
    _db.session.commit()
    logout(a)
    login(a, staff.email)
    assert a.get('/cs/').status_code == 302


def test_turning_two_step_off_needs_a_code(app, client, staff):
    turn_on_two_step(staff)
    login(client, staff.email)
    client.post('/auth/two-step', data={'code': totp.code(staff.totp_secret)})
    client.post('/auth/security/two-step', data={'action': 'off', 'code': '000000'})
    assert _db.session.get(User, staff.id).two_step_on
    client.post('/auth/security/two-step', data={'action': 'off', 'code': totp.code(staff.totp_secret)})
    assert not _db.session.get(User, staff.id).two_step_on and len(events('two_step_off')) == 1


def test_the_rules_send_admins_to_set_it_up_and_keep_it_on(app, client, admin_user):
    signin.save_rules(admin_user, two_step='admins')
    _db.session.commit()
    login(client, admin_user.email)
    r = client.get('/admin/health')
    assert r.status_code == 302 and '/auth/security' in r.headers['Location'] and 'setup=1' in r.headers['Location']
    assert 'required for your account' in client.get('/auth/security?setup=1').get_data(as_text=True)
    turn_on_two_step(admin_user)
    with client.session_transaction() as s:
        s['two_step_ok'] = True
    client.post('/auth/security/two-step', data={'action': 'off', 'code': totp.code(admin_user.totp_secret)})
    assert _db.session.get(User, admin_user.id).two_step_on                 # required: cannot be turned off
    assert client.get('/admin/health').status_code == 200


def test_a_person_waiting_for_their_code_cannot_turn_it_off(app, client, staff):
    turn_on_two_step(staff)
    login(client, staff.email)
    r = client.post('/auth/security/two-step', data={'action': 'off', 'code': '123456'})
    assert r.status_code == 302 and '/auth/two-step' in r.headers['Location']
    assert _db.session.get(User, staff.id).two_step_on


# ============================================================================================ admin

def test_team_security_tabs_open_for_an_admin_only(app, client, admin_user, staff):
    login(client, staff.email, 'wrong')
    login(client, admin_user.email)
    for tab in ('rules', 'people', 'sessions', 'log'):
        assert client.get('/admin/security/?tab=%s' % tab).status_code == 200, tab
    log = client.get('/admin/security/?tab=log&kind=signin').get_data(as_text=True)
    assert 'Sign-in failed' in log and staff.email in log and 'Signed in' in log
    c = app.test_client()
    login(c, staff.email)
    assert c.get('/admin/security/').status_code == 302


def test_an_admin_ends_a_session_signs_somebody_out_and_turns_their_two_step_off(app, admin_user, staff):
    adm, agent = app.test_client(), app.test_client()
    login(adm, admin_user.email)
    adm.get('/admin/health')
    turn_on_two_step(staff)
    login(agent, staff.email)
    agent.post('/auth/two-step', data={'code': totp.code(staff.totp_secret)})
    assert agent.get('/cs/').status_code == 200
    row = UserSession.query.filter_by(user_id=staff.id, ended_at=None).one()
    adm.post('/admin/security/sessions/%d/end' % row.id)
    assert agent.get('/cs/').status_code == 302
    assert events('session_ended')[-1].actor_id == admin_user.id
    adm.post('/admin/security/people/%d/two-step-off' % staff.id)
    u = _db.session.get(User, staff.id)
    assert not u.two_step_on and u.session_version >= 1 and len(events('two_step_reset')) == 1
    adm.post('/admin/security/rules', data={'two_step': 'staff', 'idle_hours': '8'})
    assert signin.rules() == {'two_step': 'staff', 'idle_hours': 8}


def test_the_command_line_turns_two_step_off(app, staff):
    turn_on_two_step(staff)
    r = CliRunner().invoke(app.cli, ['two-step-off', staff.email], obj=None) if False else \
        app.test_cli_runner().invoke(args=['two-step-off', staff.email])
    assert r.exit_code == 0, r.output
    u = _db.session.get(User, staff.id)
    assert not u.two_step_on and u.session_version == 1
