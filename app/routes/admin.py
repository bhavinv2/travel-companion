from functools import wraps
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user, login_user
from app import db, mail
from app.models import User, CompanionRequest, Feedback, Blog, Notification
from flask_mail import Message as MailMessage
from datetime import datetime
from slugify import slugify

admin_bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated and current_user.is_admin:
        return redirect(url_for('admin.dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.is_admin:
            login_user(user)
            user.last_login = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('admin.dashboard'))
        flash('Invalid credentials or not an admin account.', 'danger')
    return render_template('admin/login.html')


@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    stats = {
        'total_users': User.query.count(),
        'active_listings': CompanionRequest.query.filter_by(is_active=True).count(),
        'total_messages': Notification.query.count(),
        'pending_feedback': Feedback.query.filter_by(is_approved=False).count(),
    }
    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
    recent_trips = CompanionRequest.query.order_by(CompanionRequest.created_at.desc()).limit(10).all()
    return render_template('admin/dashboard.html', stats=stats, recent_users=recent_users, recent_trips=recent_trips)


@admin_bp.route('/users')
@login_required
@admin_required
def users():
    search = request.args.get('q', '')
    query = User.query
    if search:
        query = query.filter(
            (User.username.ilike(f'%{search}%')) | (User.email.ilike(f'%{search}%'))
        )
    users_list = query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users_list, search=search)


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    return jsonify({'success': True, 'is_active': user.is_active})


@admin_bp.route('/listings')
@login_required
@admin_required
def listings():
    trips = CompanionRequest.query.order_by(CompanionRequest.created_at.desc()).all()
    return render_template('admin/listings.html', trips=trips)


@admin_bp.route('/listings/<int:trip_id>/disable', methods=['POST'])
@login_required
@admin_required
def disable_listing(trip_id):
    trip = CompanionRequest.query.get_or_404(trip_id)
    trip.is_active = False
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/feedback')
@login_required
@admin_required
def feedback():
    feedbacks = Feedback.query.order_by(Feedback.created_at.desc()).all()
    return render_template('admin/feedback.html', feedbacks=feedbacks)


@admin_bp.route('/feedback/<int:fid>/approve', methods=['POST'])
@login_required
@admin_required
def approve_feedback(fid):
    fb = Feedback.query.get_or_404(fid)
    fb.is_approved = True
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/feedback/<int:fid>/reject', methods=['POST'])
@login_required
@admin_required
def reject_feedback(fid):
    fb = Feedback.query.get_or_404(fid)
    db.session.delete(fb)
    db.session.commit()
    return jsonify({'success': True})


@admin_bp.route('/blog/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_blog():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        is_published = request.form.get('is_published') == 'on'
        send_notif = request.form.get('send_notification') == 'on'

        if not title or not content:
            flash('Title and content are required.', 'danger')
            return render_template('admin/blog_form.html')

        post = Blog(
            author_id=current_user.id,
            title=title,
            slug=slugify(title),
            content=content,
            is_published=is_published,
            published_at=datetime.utcnow() if is_published else None,
            send_notification=send_notif,
        )
        db.session.add(post)
        db.session.commit()

        if is_published and send_notif:
            _notify_all_blog(post)

        flash('Blog post created!', 'success')
        return redirect(url_for('admin.dashboard'))

    return render_template('admin/blog_form.html')


def _notify_all_blog(post):
    users = User.query.filter_by(is_active=True).all()
    for user in users:
        notif = Notification(
            user_id=user.id,
            type='blog',
            title=f'New Blog Post: {post.title}',
            body=post.excerpt(100),
            link=f'/blog/{post.slug}',
        )
        db.session.add(notif)
        try:
            msg = MailMessage(
                subject=f"[Connecting Desis] New Story: {post.title}",
                recipients=[user.email],
                body=f"Check out our latest blog post!\n\n{post.title}\n\n{post.excerpt(200)}\n\nRead more: https://connectingdesis.com/blog/{post.slug}"
            )
            mail.send(msg)
        except Exception:
            pass
    db.session.commit()


@admin_bp.route('/broadcast', methods=['POST'])
@login_required
@admin_required
def broadcast():
    data = request.get_json() or {}
    title = data.get('title', '')
    body = data.get('body', '')
    if not title or not body:
        return jsonify({'error': 'title and body required'}), 400

    users = User.query.filter_by(is_active=True).all()
    for user in users:
        notif = Notification(user_id=user.id, type='message', title=title, body=body, link='/')
        db.session.add(notif)
    db.session.commit()
    return jsonify({'success': True, 'sent_to': len(users)})
