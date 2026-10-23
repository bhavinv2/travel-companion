from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models import Blog, BlogTerm, Feedback, REVIEW_SITES

blog_bp = Blueprint('blog', __name__)

PER_PAGE = 12


def _listing(query, term=None):
    """The blog's list -- all of it, one category or one tag -- a page at a time. On the first page of the
    whole blog the newest featured post is the big one on top; ?q= searches titles and summaries."""
    try:
        page = max(int(request.args.get('page') or 1), 1)
    except ValueError:
        page = 1
    q = (request.args.get('q') or '').strip()[:80]
    if q:
        pat = '%%%s%%' % q
        query = query.filter(db.or_(Blog.title.ilike(pat), Blog.summary.ilike(pat)))
    hero = None
    if term is None and not q and page == 1:
        hero = query.filter(Blog.is_featured.is_(True)).order_by(Blog.published_at.desc()).first()
    if hero is not None:
        query = query.filter(Blog.id != hero.id)
    query = query.order_by(Blog.published_at.desc())
    total = query.count()
    pages = max((total + PER_PAGE - 1) // PER_PAGE, 1)
    page = min(page, pages)
    posts = query.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
    from app.services.blog_posts import live_terms
    return render_template('pages/blog.html', posts=posts, page=page, pages=pages, hero=hero, term=term, q=q,
                           sections=live_terms('category'))


@blog_bp.route('/blog')
def blog_list():
    return _listing(Blog.live())


@blog_bp.route('/blog/category/<slug>', defaults={'kind': 'category'})
@blog_bp.route('/blog/tag/<slug>', defaults={'kind': 'tag'})
def blog_term(slug, kind):
    term = BlogTerm.query.filter_by(kind=kind, slug=slug).first_or_404()
    return _listing(Blog.live().filter(Blog.terms.any(BlogTerm.id == term.id)), term)


@blog_bp.route('/blog/<slug>')
def blog_post(slug):
    post = Blog.live().filter(Blog.slug == slug).first_or_404()
    return render_template('pages/blog_post.html', post=post, related=related(post), **share_card(post))


def related(post, n=3):
    """Posts on the same subjects (a category or tag in common), newest first; the newest posts after."""
    ids = [t.id for t in post.terms]
    near = (Blog.live().filter(Blog.id != post.id, Blog.terms.any(BlogTerm.id.in_(ids)))
            .order_by(Blog.published_at.desc()).limit(n).all()) if ids else []
    if len(near) < n:
        near += (Blog.live().filter(Blog.id.notin_([post.id] + [p.id for p in near]))
                 .order_by(Blog.published_at.desc()).limit(n - len(near)).all())
    return near


def share_card(post):
    """The cover as the picture WhatsApp and Facebook show when the post is shared (base.html)."""
    if not post.cover_image_url:
        return {}
    from app.services.blog_engine import site_url
    url = site_url(post.cover_image_url)
    if url.startswith('/'):
        url = request.host_url.rstrip('/') + url
    return {'share_image': url, 'share_image_alt': post.cover_alt or post.title}


@blog_bp.app_template_filter('blog_html')
def blog_html(content):
    """A post's content as its public page shows it: rebuilt through the blog allowlist (a script,
    an iframe, an onclick never reach a reader, whoever wrote the post), its pictures and site links
    inside the app's prefix, and a picture nobody uploaded left out."""
    from markupsafe import Markup
    from app.services.blog_engine import render
    return Markup(render(content or ''))


@blog_bp.route('/api/feedback', methods=['POST'])
@login_required
def submit_feedback():
    """A review, filed against the product it was written about.

    `site` comes from the form the reviewer used, and an unknown value is treated as the
    companion app rather than rejected: the worst case is a review on the wrong page, and losing
    somebody's words to a validation error is worse than that.
    """
    data = request.get_json() or {}
    rating = data.get('rating')
    comment = data.get('comment', '').strip()
    site = (data.get('site') or '').strip().lower()
    if site not in REVIEW_SITES:
        site = 'companion'

    if not rating or not (1 <= int(rating) <= 5):
        return jsonify({'error': 'Rating 1-5 required'}), 400

    fb = Feedback(
        user_id=current_user.id,
        rating=int(rating),
        comment=comment,
        site=site,
        is_approved=False,
    )
    try:
        db.session.add(fb)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Thank you! Your review is pending approval.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
