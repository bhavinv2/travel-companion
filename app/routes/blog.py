from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models import Blog, Feedback

blog_bp = Blueprint('blog', __name__)


@blog_bp.route('/blog')
def blog_list():
    posts = Blog.query.filter_by(is_published=True).order_by(Blog.published_at.desc()).all()
    return render_template('pages/blog.html', posts=posts)


@blog_bp.route('/blog/<slug>')
def blog_post(slug):
    post = Blog.query.filter_by(slug=slug, is_published=True).first_or_404()
    return render_template('pages/blog_post.html', post=post)


@blog_bp.route('/api/feedback', methods=['POST'])
@login_required
def submit_feedback():
    data = request.get_json() or {}
    rating = data.get('rating')
    comment = data.get('comment', '').strip()

    if not rating or not (1 <= int(rating) <= 5):
        return jsonify({'error': 'Rating 1-5 required'}), 400

    fb = Feedback(
        user_id=current_user.id,
        rating=int(rating),
        comment=comment,
        is_approved=False,
    )
    try:
        db.session.add(fb)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Thank you! Your review is pending approval.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
