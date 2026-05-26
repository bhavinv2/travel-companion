import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from app import db, mail
from app.models import User
from flask_mail import Message as MailMessage
from datetime import datetime
import re
import requests as http_requests

auth_bp = Blueprint('auth', __name__)


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
    redirect_uri = url_for('auth.google_callback', _external=True)
    scope = 'openid email profile'
    google_auth_url = (
        'https://accounts.google.com/o/oauth2/v2/auth'
        f'?client_id={client_id}'
        f'&redirect_uri={redirect_uri}'
        f'&response_type=code'
        f'&scope={scope}'
        f'&access_type=offline'
    )
    return redirect(google_auth_url)


@auth_bp.route('/google/authorized')
def google_callback():
    code = request.args.get('code')
    error = request.args.get('error')
    if error or not code:
        flash('Google login was cancelled or failed.', 'danger')
        return redirect(url_for('auth.login'))

    client_id = current_app.config.get('GOOGLE_OAUTH_CLIENT_ID')
    client_secret = current_app.config.get('GOOGLE_OAUTH_CLIENT_SECRET')
    redirect_uri = url_for('auth.google_callback', _external=True)

    # Exchange code for token
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
    if not user_info:
        flash('Could not retrieve Google account info.', 'danger')
        return redirect(url_for('auth.login'))

    google_id = user_info.get('id')
    email = user_info.get('email', '').lower()
    first_name = user_info.get('given_name', '')
    last_name = user_info.get('family_name', '')
    photo_url = user_info.get('picture')

    # Find existing user by google id or email
    user = User.query.filter_by(oauth_provider='google', oauth_id=google_id).first()
    if not user:
        user = User.query.filter_by(email=email).first()

    if user:
        # Update oauth info if missing
        if not user.oauth_id:
            user.oauth_provider = 'google'
            user.oauth_id = google_id
        user.last_login = datetime.utcnow()
        db.session.commit()
    else:
        # Create new user
        base_username = re.sub(r'[^a-z0-9]', '', (first_name + last_name).lower()) or 'user'
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
            is_verified=True,
        )
        user.set_password(os.urandom(24).hex())
        db.session.add(user)
        db.session.commit()
        flash(f'Welcome to Connecting Desis, {first_name}!', 'success')

    login_user(user)
    flash(f'Welcome back, {user.first_name or user.username}!', 'success') if user.last_login else None
    return redirect(url_for('main.index'))


def send_welcome_email(user):
    if not current_app.config.get('MAIL_PASSWORD'):
        return
    try:
        msg = MailMessage(
            subject="Welcome to Connecting Desis!",
            recipients=[user.email],
            body=f"Hi {user.first_name},\n\nWelcome to Connecting Desis! Your account has been created successfully.\n\nSafe travels!\nThe Connecting Desis Team"
        )
        mail.send(msg)
    except Exception:
        pass  # don't break registration if mail fails


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip()
        dob_str = request.form.get('dob', '')
        marketing_consent = request.form.get('marketing_consent') == 'on'
        show_photo = request.form.get('show_photo') == 'on'

        errors = []
        if not email or not re.match(r'^[^@]+@[^@]+\.[^@]+$', email):
            errors.append('Valid email is required.')
        if not username or len(username) < 3:
            errors.append('Username must be at least 3 characters.')
        if not password or len(password) < 8:
            errors.append('Password must be at least 8 characters.')
        if User.query.filter_by(email=email).first():
            errors.append('Email already registered.')
        if User.query.filter_by(username=username).first():
            errors.append('Username already taken.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('auth/register.html')

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

        # Handle photo upload
        photo = request.files.get('photo')
        if photo and photo.filename:
            ext = photo.filename.rsplit('.', 1)[-1].lower()
            if ext in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
                filename = f"user_{username}_{int(datetime.utcnow().timestamp())}.{ext}"
                upload_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                photo.save(upload_path)
                user.photo_url = f"/static/uploads/{filename}"

        try:
            db.session.add(user)
            db.session.commit()
            send_welcome_email(user)
            login_user(user)
            flash('Account created! Welcome to Connecting Desis.', 'success')
            return redirect(url_for('main.index'))
        except Exception as e:
            db.session.rollback()
            flash('Registration failed. Please try again.', 'danger')

    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.is_active:
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user, remember=remember)
            next_page = request.args.get('next')
            flash(f'Welcome back, {user.first_name or user.username}!', 'success')
            return redirect(next_page or url_for('main.index'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            flash('If an account exists, a reset link has been sent.', 'info')
        else:
            flash('If an account exists, a reset link has been sent.', 'info')
    return render_template('auth/login.html')
