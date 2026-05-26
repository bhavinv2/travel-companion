import os
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app import db, mail
from app.models import User
from flask_mail import Message as MailMessage
from datetime import datetime
import re

auth_bp = Blueprint('auth', __name__)


def send_welcome_email(user):
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
