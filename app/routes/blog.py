from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, make_response
from flask_login import login_required, current_user
from app import db
from app.models import Blog, BlogTerm, Feedback, REVIEW_SITES

blog_bp = Blueprint('blog', __name__)

PER_PAGE = 12
SAVED_MAX = 60             # slugs a reader's "Saved" list can ask for at once


def _stories():
    """The categories as the round pictures across the top of the blog (the way a phone app shows stories):
    each with the cover of its newest post that has one."""
    from app.services.blog_posts import live_terms
    out = []
    for t, n in live_terms('category'):
        newest = (Blog.live().filter(Blog.terms.any(BlogTerm.id == t.id), Blog.cover_image_url.isnot(None),
                                     Blog.cover_image_url != '')
                  .order_by(Blog.published_at.desc()).first())
        out.append({'term': t, 'count': n, 'cover': newest.cover_image_url if newest else None})
    return out


def _listing(query, term=None, saved=None):
    """The blog's list -- all of it, one category, one tag, or the posts a reader saved on their phone -- a page
    at a time. On the first page of the whole blog the newest featured post (else the newest post) is the big one
    on top; ?q= searches titles and summaries. ?chunk=1 answers only the next page's cards, for the list that goes
    on as it is scrolled (X-Next: the page after, empty at the end)."""
    try:
        page = max(int(request.args.get('page') or 1), 1)
    except ValueError:
        page = 1
    q = (request.args.get('q') or '').strip()[:80]
    if q:
        pat = '%%%s%%' % q
        query = query.filter(db.or_(Blog.title.ilike(pat), Blog.summary.ilike(pat)))
    if saved is not None:
        query = query.filter(Blog.slug.in_(saved or ['']))
    from app.services.blog_posts import in_blog_order
    whole = term is None and saved is None and not q
    # the posts given a place (Order on the blog) first, then newest first -- the same order every time, so a page
    # fetched later carries on exactly where the last stopped
    # the featured post is the big one on top of the first page, so it is out of every page's list -- the pages
    # fetched as the list is scrolled too, or each would start one post early
    hero = in_blog_order(query.filter(Blog.is_featured.is_(True))).first() if whole else None
    if hero is not None:
        query = query.filter(Blog.id != hero.id)
    query = in_blog_order(query)
    total = query.count()
    pages = max((total + PER_PAGE - 1) // PER_PAGE, 1)
    page = min(page, pages)
    posts = query.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
    if hero is not None:
        total += 1                                 # the featured one is a story too
        if page > 1:
            hero = None                            # shown on the first page only
    elif whole and page == 1 and posts:
        hero, posts = posts[0], posts[1:]          # nothing featured: the newest is the big one
    view = request.view_args or {}
    args = {k: v for k, v in request.args.items() if k not in ('page', 'chunk') and k not in view}
    nxt = url_for(request.endpoint, **view, **args, page=page + 1) if page < pages else None
    if request.args.get('chunk'):
        resp = make_response(render_template('pages/_blog_cards.html', posts=posts))
        resp.headers['X-Next'] = nxt or ''
        return resp
    return render_template('pages/blog.html', posts=posts, page=page, pages=pages, hero=hero, term=term, q=q,
                           saved=saved, total=total, stories=_stories(), next_url=nxt)


@blog_bp.route('/blog')
def blog_list():
    saved = None
    if 'saved' in request.args:
        saved = [s.strip()[:350] for s in request.args.get('saved', '').split(',') if s.strip()][:SAVED_MAX]
    return _listing(Blog.live(), saved=saved)


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


@blog_bp.app_template_filter('ago')
def ago(when, now=None):
    """How long ago a post went up, the way a feed says it: 'just now', '5 minutes ago', 'yesterday', '3 days
    ago'; after a week the day itself (India time), the year only when it is not this one."""
    if not when:
        return ''
    now = now or datetime.utcnow()
    s = (now - when).total_seconds()
    if s < 60:
        return 'just now'
    if s < 3600:
        n, word = int(s // 60), 'minute'
    elif s < 86400:
        n, word = int(s // 3600), 'hour'
    elif s < 7 * 86400:
        n, word = int(s // 86400), 'day'
        if n == 1:
            return 'yesterday'
    else:
        day, today = when + timedelta(hours=5, minutes=30), now + timedelta(hours=5, minutes=30)
        return '%d %s' % (day.day, day.strftime('%b' if day.year == today.year else '%b %Y'))
    return '%d %s%s ago' % (n, word, '' if n == 1 else 's')


@blog_bp.app_template_filter('blog_layout')
def blog_layout(layout):
    """A post's layout as the classes its content wears (blog_posts.layout_classes)."""
    from app.services.blog_posts import layout_classes
    return layout_classes(layout)


@blog_bp.app_template_global('LAYOUT_CHOICES')
def layout_choices():
    from app.services.blog_posts import LAYOUT
    return LAYOUT


@blog_bp.app_template_global('LAYOUT_DEFAULT')
def layout_default():
    from app.services.blog_posts import LAYOUT_DEFAULT
    return LAYOUT_DEFAULT


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
