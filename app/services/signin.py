"""Signed-in sessions, two-step sign-in and the sign-in rules (Set-up › Security), 2026-10-26.

Every signed-in browser has a row in user_sessions: the cookie session holds a random token (session['sid']) and the
row its hash. guard() runs before each request (app/__init__.py):

  1. a browser whose row was ended -- by its owner, an admin, a password change, being idle -- is signed out there;
  2. a staff browser left idle longer than the rule (12 hours unless changed) is ended;
  3. two-step sign-in: somebody who has it on proves it once per browser (or once per 30 days on a browser they
     trust) before anything else opens; the rule can require it of admins or of all staff, who are sent to set it
     up first;
  4. a signed-in browser with no row yet (signed in before this existed, or "remember me") gets one.

Raising users.session_version ends every session and every "remember me" cookie at once (User.get_id). Every sign-in,
failed sign-in, sign-out and change here is written to the audit log (ActivityEvent).
"""
import hashlib
import secrets
from datetime import datetime, timedelta

from flask import current_app, request, session

from app import db
from app.models import ActivityEvent, User, UserSession
from app.services import settings

SETTING = 'security'
TWO_STEP_RULES = {'optional': 'Each person chooses',
                  'admins': 'Required for administrators',
                  'staff': 'Required for all staff'}
IDLE_CHOICES = (2, 4, 8, 12, 24, 72)
DEFAULTS = {'two_step': 'optional', 'idle_hours': 12}
SEEN_EVERY = timedelta(minutes=5)          # last_seen_at is written at most this often
DEVICE_COOKIE = 'nps_2s'
DEVICE_DAYS = 30
DEVICE_SALT = 'two-step-device'
# what a person may open while their code is awaited, and while the rules send them to set two-step sign-in up
OPEN_FOR_CODE = {'auth.two_step', 'auth.logout', 'static'}
OPEN_FOR_SETUP = {'auth.security', 'auth.security_two_step', 'auth.change_password', 'auth.logout', 'static'}
REASONS = {'signed_out': 'Signed out', 'ended': 'Ended from another browser', 'ended_by_admin': 'Ended by an admin',
           'idle': 'Idle too long', 'password': 'Password changed', 'everywhere': 'Signed out everywhere',
           'two_step': 'Two-step sign-in changed'}


# ============================================================================================ the rules

def rules():
    v = settings.get_setting(SETTING) or {}
    v = v if isinstance(v, dict) else {}
    out = dict(DEFAULTS)
    if v.get('two_step') in TWO_STEP_RULES:
        out['two_step'] = v['two_step']
    if v.get('idle_hours') in IDLE_CHOICES:
        out['idle_hours'] = v['idle_hours']
    return out


def save_rules(actor, two_step=None, idle_hours=None):
    """Commits. Returns the rules now."""
    now = rules()
    if two_step in TWO_STEP_RULES:
        now['two_step'] = two_step
    if idle_hours in IDLE_CHOICES:
        now['idle_hours'] = idle_hours
    ActivityEvent.log('security_rules', actor=actor, **now)
    settings.set_setting(SETTING, now, actor)
    return now


def is_staff(user):
    from app.services import access
    return bool(user is not None and getattr(user, 'is_authenticated', True) and access.is_staff(user))


def required_for(user):
    """Whether the rules make this person use two-step sign-in."""
    rule = rules()['two_step']
    if rule == 'staff':
        return is_staff(user)
    if rule == 'admins':
        return bool(user.is_admin or user.is_super)
    return False


# ============================================================================================ sessions

def _hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _ip():
    try:
        return (request.access_route[0] if request.access_route else request.remote_addr or '')[:64]
    except RuntimeError:
        return ''


ROW_KEY = 'signin.row'          # this request's row, kept on the request (an app context can outlive it)


def current_row():
    """This browser's row, or None."""
    env = request.environ
    sid = session.get('sid')
    hit = env.get(ROW_KEY)
    if hit is not None and hit[0] == sid:
        return hit[1]
    row = UserSession.query.filter_by(token_hash=_hash(sid)).first() if sid else None
    env[ROW_KEY] = (sid, row)
    return row


def _start(user, how):
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    row = UserSession(user_id=user.id, token_hash=_hash(token), how=how, ip=_ip(),
                      user_agent=(request.headers.get('User-Agent') or '')[:300], created_at=now, last_seen_at=now)
    db.session.add(row)
    session['sid'] = token
    request.environ[ROW_KEY] = (token, row)
    return row


def mark_how(how):
    """Called just before login_user by a sign-in that is not a password: google / facebook / reset / claim."""
    session['signin_how'] = how


def end(row, reason, by=None):
    if row is None or row.ended_at is not None:
        return
    row.ended_at = datetime.utcnow()
    row.ended_reason = reason
    row.ended_by_id = getattr(by, 'id', None)
    if by is not None and by.id != row.user_id:
        ActivityEvent.log('session_ended', actor=by, user_id=row.user_id, session_id=row.id, reason=reason)


def open_sessions(user):
    return (UserSession.query.filter_by(user_id=user.id, ended_at=None)
            .order_by(UserSession.last_seen_at.desc()).all())


def end_others(user, reason, by=None):
    """End every open session of `user` but this browser's. Returns how many. Does not commit."""
    keep = current_row()
    n = 0
    for row in open_sessions(user):
        if keep is not None and row.id == keep.id:
            continue
        end(row, reason, by)
        n += 1
    return n


def sign_out_everywhere(user, reason, by=None, keep_this=True):
    """Every session and "remember me" cookie of `user` stops working (the session version goes up); this browser
    stays signed in when it is theirs and `keep_this`. Commits."""
    from flask_login import current_user, login_user
    mine = current_user.is_authenticated and current_user.id == user.id
    end_others(user, reason, by)
    user.session_version = (user.session_version or 0) + 1
    if mine and keep_this:
        db.session.commit()
        login_user(user)                 # this browser carries the new version from now on
    else:
        if mine:
            end(current_row(), reason, by)
        db.session.commit()


def failed(email, why='password'):
    """A sign-in that let nobody in: who it was for and from where. Commits."""
    ActivityEvent.log('signin_failed', email=(email or '')[:120], ip=_ip(), why=why)
    db.session.commit()


def signed_out(user):
    end(current_row(), 'signed_out')
    ActivityEvent.log('signout', actor=user)
    db.session.commit()
    session.pop('sid', None)
    session.pop('two_step_ok', None)


# ============================================================================================ two-step sign-in

def _serializer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(current_app.secret_key, salt=DEVICE_SALT)


def _device_value(user):
    return {'u': user.id, 'v': user.session_version or 0,
            't': user.totp_on_at.isoformat() if user.totp_on_at else ''}


def device_trusted(user):
    raw = request.cookies.get(DEVICE_COOKIE)
    if not raw:
        return False
    try:
        data = _serializer().loads(raw, max_age=DEVICE_DAYS * 86400)
    except Exception:          # noqa: BLE001 -- bad, old or forged: not trusted
        return False
    return data == _device_value(user)


def trust_device(response, user):
    response.set_cookie(DEVICE_COOKIE, _serializer().dumps(_device_value(user)), max_age=DEVICE_DAYS * 86400,
                        httponly=True, samesite='Lax', secure=bool(current_app.config.get('FORCE_HTTPS')))
    return response


def passed_two_step(user, row=None, how='code'):
    session['two_step_ok'] = True
    row = row or current_row()
    if row is not None:
        row.two_step = True
    ActivityEvent.log('two_step_ok', actor=user, how=how)
    db.session.commit()


# ============================================================================================ the guard

def _json():
    from app import wants_json
    return wants_json(request)


def _out(message, category='info'):
    from flask import flash, jsonify, redirect, url_for
    from flask_login import logout_user
    logout_user()
    for k in ('sid', 'two_step_ok', 'view', 'act_role'):
        session.pop(k, None)
    if _json():
        return jsonify(error=message, authenticated=False), 401
    flash(message, category)
    return redirect(url_for('auth.login'))


def guard():
    """Before each request: see the module docstring. Returns a response to send instead, or None."""
    from flask import jsonify, redirect, url_for
    from flask_login import current_user
    if not current_user.is_authenticated or request.endpoint in (None, 'static'):
        return None
    user = current_user._get_current_object()
    now = datetime.utcnow()
    row = current_row()
    if session.get('sid') and (row is None or row.user_id != user.id or row.ended_at is not None):
        reason = row.ended_reason if row is not None else None
        db.session.rollback()
        return _out({'idle': 'You were signed out after a while without activity. Please sign in again.',
                     'password': 'Your password was changed, so this browser was signed out. Please sign in again.'}
                    .get(reason, 'This browser was signed out. Please sign in again.'))
    staff = is_staff(user)
    if row is not None and staff:
        idle = timedelta(hours=rules()['idle_hours'])
        if now - row.last_seen_at > idle:
            end(row, 'idle')
            db.session.commit()
            return _out('You were signed out after %d hours without activity. Please sign in again.'
                        % rules()['idle_hours'])
    if row is None:          # a sign-in by any route (or "remember me"): its row, and the line in the audit log
        how = session.pop('signin_how', None) or ('remembered' if session.get('_fresh') is False else 'password')
        row = _start(user, how)
        ActivityEvent.log('signin', actor=user, how=how, ip=row.ip, device=row.device)
        db.session.commit()
    elif now - row.last_seen_at > SEEN_EVERY:
        row.last_seen_at = now
        db.session.commit()
    # two-step sign-in
    if user.two_step_on and not session.get('two_step_ok'):
        if request.endpoint in OPEN_FOR_CODE:
            return None
        if device_trusted(user):
            passed_two_step(user, row, how='trusted browser')
            return None
        if _json():
            return jsonify(error='Two-step sign-in is waiting.', two_step=True), 401
        if request.method == 'GET':
            from app.services.urls import here
            session['two_step_next'] = here()
        return redirect(url_for('auth.two_step'))
    if not user.two_step_on and required_for(user) and request.endpoint not in OPEN_FOR_SETUP:
        if _json():
            return jsonify(error='Set up two-step sign-in first.', two_step=True), 403
        return redirect(url_for('auth.security', setup=1))
    return None
