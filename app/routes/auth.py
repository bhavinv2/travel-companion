import os
import re
import secrets
from urllib.parse import urlparse, urlencode
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User, ContactPoint, ActivityEvent
from app.services.storage import save_public_image
from app.services import mailer, tokens
from app.services.ratelimit import rate_limit
from datetime import datetime
import requests as http_requests

auth_bp = Blueprint('auth', __name__)

USERNAME_RE = re.compile(r'^[A-Za-z0-9_.-]{3,30}$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _safe_next(target):
    """Only allow relative redirects on this site (prevents open redirects)."""
    if not target:
        return None
    p = urlparse(target)
    if p.scheme or p.netloc or not target.startswith('/') or target.startswith('//'):
        return None
    return target


# ---------------------------------------------------------------------------
# Verification / reset e-mails
# ---------------------------------------------------------------------------

def send_verification_email(user):
    link = url_for('auth.verify_email', token=tokens.make_verify_token(user), _external=True)
    return mailer.send_template('Welcome to Connecting Desis — please confirm your e-mail', [user.email],
                                'email/verify_email.txt', user=user, link=link,
                                site_url=current_app.config['SITE_URL'],
                                support_email=current_app.config['SUPPORT_EMAIL'])


def send_password_reset_email(user):
    link = url_for('auth.reset_password', token=tokens.make_reset_token(user), _external=True)
    return mailer.send_template('[Connecting Desis] Reset your password', [user.email],
                                'email/password_reset.txt', user=user, link=link,
                                site_url=current_app.config['SITE_URL'],
                                support_email=current_app.config['SUPPORT_EMAIL'])


def mark_email_verified(user):
    user.is_verified = True
    # Contact points that equal the verified address become verified too.
    ContactPoint.query.filter_by(user_id=user.id, type='email', value=user.email).update({'verified': True})


@auth_bp.route('/verify/<token>')
def verify_email(token):
    data = tokens.load_verify_token(token)
    user = db.session.get(User, data['uid']) if data else None
    if not user or user.email != data.get('email'):
        flash('That verification link is invalid or has expired. Log in and request a new one.', 'danger')
        return redirect(url_for('auth.login'))
    if not user.is_verified:
        mark_email_verified(user)
        ActivityEvent.log('email_verified', actor=user)
        db.session.commit()
    flash('Your e-mail address is confirmed. Thank you!', 'success')
    if not current_user.is_authenticated:
        login_user(user)
    return redirect(url_for('main.dashboard'))


@auth_bp.route('/resend-verification', methods=['POST'])
@login_required
@rate_limit(3, 600)
def resend_verification():
    if current_user.is_verified:
        flash('Your e-mail is already confirmed.', 'info')
    elif send_verification_email(current_user):
        flash(f'We sent a new confirmation link to {current_user.email}.', 'success')
    else:
        flash('E-mail is not configured on this server — contact support to get verified.', 'danger')
    return redirect(_safe_next(request.form.get('next')) or url_for('main.dashboard'))


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

def _google_get_user_info(token):
    resp = http_requests.get(
        'https://www.googleapis.com/oauth2/v2/userinfo',
        headers={'Authorization': f'Bearer {token}'},
        timeout=10,
    )
    return resp.json() if resp.ok else None


@auth_bp.route('/google')
def google_login():
    client_id = current_app.config.get('GOOGLE_OAUTH_CLIENT_ID')
    if not client_id:
        flash('Google login is not configured.', 'danger')
        return redirect(url_for('auth.login'))
    state = secrets.token_urlsafe(24)
    session['oauth_state'] = state
    params = {
        'client_id': client_id,
        'redirect_uri': url_for('auth.google_callback', _external=True),
        'response_type': 'code',
        'scope': 'openid email profile',
        'access_type': 'offline',
        'state': state,
    }
    return redirect('https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params))


@auth_bp.route('/google/authorized')
def google_callback():
    code = request.args.get('code')
    error = request.args.get('error')
    expected_state = session.pop('oauth_state', None)
    if error or not code:
        flash('Google login was cancelled or failed.', 'danger')
        return redirect(url_for('auth.login'))
    if not expected_state or request.args.get('state') != expected_state:
        flash('Google login could not be verified. Please try again.', 'danger')
        return redirect(url_for('auth.login'))

    client_id = current_app.config.get('GOOGLE_OAUTH_CLIENT_ID')
    client_secret = current_app.config.get('GOOGLE_OAUTH_CLIENT_SECRET')
    redirect_uri = url_for('auth.google_callback', _external=True)

    token_resp = http_requests.post('https://oauth2.googleapis.com/token', data={
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code',
    }, timeout=10)

    if not token_resp.ok:
        flash('Failed to authenticate with Google.', 'danger')
        return redirect(url_for('auth.login'))

    access_token = token_resp.json().get('access_token')
    user_info = _google_get_user_info(access_token)
    if not user_info or not user_info.get('email'):
        flash('Could not retrieve Google account info.', 'danger')
        return redirect(url_for('auth.login'))

    google_id = user_info.get('id')
    email = user_info.get('email', '').lower()
    first_name = user_info.get('given_name', '')
    last_name = user_info.get('family_name', '')
    photo_url = user_info.get('picture')

    user = User.query.filter_by(oauth_provider='google', oauth_id=google_id).first()
    if not user:
        user = User.query.filter_by(email=email).first()

    is_new = False
    if user:
        if not user.oauth_id:
            user.oauth_provider = 'google'
            user.oauth_id = google_id
        if not user.is_verified and user_info.get('verified_email'):
            mark_email_verified(user)
    else:
        is_new = True
        base_username = re.sub(r'[^a-z0-9]', '', (first_name + last_name).lower())[:30] or 'user'
        if len(base_username) < 3:
            base_username = (base_username + 'user')[:30]
        username = base_username
        counter = 1
        while User.query.filter_by(username=username).first():
            username = f'{base_username}{counter}'
            counter += 1
        user = User(
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            oauth_provider='google',
            oauth_id=google_id,
            photo_url=photo_url,
            show_photo=True,
            is_verified=bool(user_info.get('verified_email', True)),
        )
        user.set_password(os.urandom(24).hex())
        db.session.add(user)

    if not login_user(user):
        db.session.rollback()
        flash('This account has been deactivated. Contact support if you think this is a mistake.', 'danger')
        return redirect(url_for('auth.login'))
    user.last_login = datetime.utcnow()
    db.session.commit()
    if is_new:
        flash(f'Welcome to Connecting Desis, {first_name or user.username}!', 'success')
    else:
        flash(f'Welcome back, {user.first_name or user.username}!', 'success')
    return redirect(_safe_next(session.pop('next', None)) or url_for('main.index'))


# ---------------------------------------------------------------------------
# Register / login / logout
# ---------------------------------------------------------------------------

@auth_bp.route('/register', methods=['GET', 'POST'])
@rate_limit(10, 3600)
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        first_name = request.form.get('first_name', '').strip()[:100]
        last_name = request.form.get('last_name', '').strip()[:100]
        phone = request.form.get('phone', '').strip()[:30]
        dob_str = request.form.get('dob', '')
        marketing_consent = request.form.get('marketing_consent') == 'on'
        show_photo = request.form.get('show_photo') == 'on'
        agreed = request.form.get('agree_terms') == 'on'

        errors = []
        if not email or not EMAIL_RE.match(email):
            errors.append('Valid email is required.')
        if not USERNAME_RE.match(username):
            errors.append('Username must be 3-30 characters: letters, numbers, dot, dash or underscore.')
        if not password or len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        if not first_name:
            errors.append('First name is required.')
        if not agreed:
            errors.append('Please accept the Terms of Use and Privacy Policy.')
        if User.query.filter_by(email=email).first():
            errors.append('Email already registered.')
        if User.query.filter(db.func.lower(User.username) == username.lower()).first():
            errors.append('Username already taken.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('auth/register.html', form=request.form)

        dob = None
        if dob_str:
            try:
                dob = datetime.strptime(dob_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        user = User(
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            dob=dob,
            marketing_consent=marketing_consent,
            show_photo=show_photo,
            is_verified=False,
        )
        user.set_password(password)

        photo = request.files.get('photo')
        if photo and photo.filename:
            url = save_public_image(photo, prefix=f"user_{username}")
            if url:
                user.photo_url = url
            else:
                flash('Profile photo must be a JPG, PNG, GIF or WebP image — skipped.', 'info')

        try:
            db.session.add(user)
            db.session.commit()
            sent = send_verification_email(user)
            login_user(user)
            flash('Account created! Welcome to Connecting Desis.' +
                  (' Please confirm your e-mail using the link we just sent.' if sent else ''), 'success')
            return redirect(url_for('main.index'))
        except Exception:
            db.session.rollback()
            flash('Registration failed. Please try again.', 'danger')

    return render_template('auth/register.html', form=None)


@auth_bp.route('/login', methods=['GET', 'POST'])
@rate_limit(10, 300)
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    next_page = _safe_next(request.args.get('next'))
    if next_page:
        session['next'] = next_page

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.is_active:
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=remember)
            flash(f'Welcome back, {user.first_name or user.username}!', 'success')
            target = _safe_next(session.pop('next', None)) or next_page
            return redirect(target or url_for('main.index'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@rate_limit(5, 900)
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email, is_active=True).first()
        if user:
            send_password_reset_email(user)
        # Same answer whether or not the account exists.
        flash('If an account exists for that e-mail, a reset link is on its way (valid for 2 hours).', 'info')
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot.html')


@auth_bp.route('/reset/<token>', methods=['GET', 'POST'])
@rate_limit(10, 900)
def reset_password(token):
    data = tokens.load_reset_token(token)
    user = db.session.get(User, data['uid']) if data else None
    if not user or (user.password_hash or '')[-12:] != data.get('pw'):
        flash('That reset link is invalid, expired or already used. Request a new one.', 'danger')
        return redirect(url_for('auth.forgot_password'))
    if request.method == 'POST':
        pw = request.form.get('password') or ''
        if len(pw) < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return render_template('auth/reset.html', token=token)
        if pw != (request.form.get('confirm') or ''):
            flash('Passwords do not match.', 'danger')
            return render_template('auth/reset.html', token=token)
        user.set_password(pw)
        if not user.is_verified:
            mark_email_verified(user)   # they proved they control the mailbox
        ActivityEvent.log('password_reset', actor=user)
        db.session.commit()
        login_user(user)
        flash('Your password has been changed.', 'success')
        return redirect(url_for('main.dashboard'))
    return render_template('auth/reset.html', token=token)
