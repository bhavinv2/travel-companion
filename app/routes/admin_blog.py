"""Blog studio, in the admin portal: import Word documents as draft posts, edit a post with the
rules it breaks beside it, preview it as the public page, publish it.

The work is in services/blog_engine.py; these routes read forms and draw pages. They are added to
admin_bp (imported in app/__init__ before the blueprint is registered), so they live in the admin
portal like the rest of the blog screens and are reached through the same roles (access.py:
"New blog post" and "Import blog posts").
"""
import io
from datetime import datetime
from types import SimpleNamespace

from flask import abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from slugify import slugify

from app import db
from app.models import Blog
from app.routes.admin import admin_bp, admin_required
from app.services import blog_engine as be


def _post_or_404(post_id):
    post = db.session.get(Blog, post_id)
    if post is None:
        abort(404)
    return post


@admin_bp.route('/blog/import', methods=['GET', 'POST'])
@login_required
@admin_required
def blog_import():
    results = notes = None
    if request.method == 'POST':
        docs = [f for f in request.files.getlist('documents') if f and f.filename]
        pictures = [f for f in request.files.getlist('pictures') if f and f.filename]
        if not docs:
            flash('Choose at least one Word document (.docx).', 'warning')
        else:
            results, notes = be.import_upload(docs, pictures, current_user)
            made = [r for r in results if r['post'] is not None]
            failed = len(results) - len(made)
            if made:
                flash('%d draft%s ready to check.%s' % (len(made), '' if len(made) == 1 else 's',
                                                       ' %d document%s could not be imported.' % (failed, '' if failed == 1 else 's') if failed else ''),
                      'success' if not failed else 'warning')
            else:
                flash('Nothing was imported: see why below.', 'danger')
    return render_template('admin/blog_import.html', results=results, notes=notes, rules=be.FORMAT_RULES,
                           image_rules=be.IMAGE_RULES, advanced_rules=be.ADVANCED_RULES,
                           advanced_image_rules=be.ADVANCED_IMAGE_RULES)


@admin_bp.route('/blog/template.docx')
@login_required
@admin_required
def blog_template():
    return send_file(io.BytesIO(be.template_docx()), mimetype=be.DOCX_MIME, as_attachment=True,
                     download_name='nri-blog-template.docx')


def _fields(post):
    f = request.form
    title = (f.get('title') or '').strip()[:300]
    cover = be._safe_url((f.get('cover_image_url') or '').strip(), image=True)
    return {'title': title,
            'slug': slugify((f.get('slug') or '').strip() or title, max_length=80, word_boundary=True),
            'summary': (f.get('summary') or '').strip()[:300],
            'content': be.sanitize(f.get('content') or ''),
            'cover_image_url': (cover or '')[:500] or None,
            'cover_alt': (f.get('cover_alt') or '').strip()[:300],
            'send_notification': f.get('send_notification') == 'on' if 'send_notification_shown' in f
            else bool(post.send_notification)}


def _found(d, post):
    return be.checks(d['title'], d['slug'], d['summary'], d['content'], d['cover_image_url'], d['cover_alt'], post.id)


def _editor(post, d=None, found=None, status=200):
    d = d or {'title': post.title, 'slug': post.slug, 'summary': post.summary or '', 'content': post.content or '',
              'cover_image_url': post.cover_image_url, 'cover_alt': post.cover_alt or '',
              'send_notification': bool(post.send_notification)}
    return render_template('admin/blog_edit.html', post=post, d=d, body=be.for_editor(d['content']),
                           checks=found if found is not None else _found(d, post), rules=be.FORMAT_RULES), status


@admin_bp.route('/blog/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def blog_edit(post_id):
    """Save keeps a draft a draft; Publish (or Update, on a live post) refuses while a red check is
    left -- a draft still keeps the changes, a live post does not change at all."""
    post = _post_or_404(post_id)
    if request.method == 'GET':
        return _editor(post)
    d = _fields(post)
    action = request.form.get('action') or 'save'
    found = _found(d, post)
    if not d['title'] or not d['slug'] or any('Another post' in c['text'] for c in found):
        flash('Not saved: %s' % ('add a title.' if not d['title'] else
                                 'another post already uses that address.' if d['slug'] else 'add the address.'), 'danger')
        return _editor(post, d, found, 400)
    going_live = action == 'publish' or (action == 'save' and post.is_published)
    if going_live and be.has_errors(found):
        if post.is_published:
            flash('Not updated: fix the red items first. The live post is unchanged.', 'danger')
            return _editor(post, d, found, 400)
        _apply(post, d)
        db.session.commit()
        flash('Saved as a draft, not published: fix the red items first.', 'danger')
        return redirect(url_for('admin.blog_edit', post_id=post.id))
    _apply(post, d)
    first = False
    if action == 'publish' and not post.is_published:
        first = post.published_at is None
        post.is_published = True
        post.published_at = post.published_at or datetime.utcnow()
    elif action == 'unpublish':
        post.is_published = False
    db.session.commit()
    if first and post.send_notification:
        from app.routes.admin import _notify_all_blog
        _notify_all_blog(post)
    flash({'publish': 'Published.', 'unpublish': 'Unpublished: only admins can see it now.'}.get(
        action, 'Updated.' if post.is_published else 'Draft saved.'), 'success')
    return redirect(url_for('admin.blog_edit', post_id=post.id))


def _apply(post, d):
    for k in ('title', 'slug', 'content', 'cover_image_url', 'send_notification'):
        setattr(post, k, d[k])
    post.summary = d['summary'] or None
    post.cover_alt = d['cover_alt'] or None


@admin_bp.route('/blog/<int:post_id>/check', methods=['POST'])
@login_required
@admin_required
def blog_check(post_id):
    post = _post_or_404(post_id)
    d = _fields(post)
    return jsonify({'checks': _found(d, post), 'words': be.word_count(d['content']), 'slug': d['slug']})


@admin_bp.route('/blog/<int:post_id>/preview', methods=['GET', 'POST'])
@login_required
@admin_required
def blog_preview(post_id):
    """The public page as it will look -- with what is in the editor now (POST), or as saved (GET)."""
    post = _post_or_404(post_id)
    shown = post
    if request.method == 'POST':
        d = _fields(post)
        shown = SimpleNamespace(id=post.id, title=d['title'] or post.title, slug=d['slug'], content=d['content'],
                                summary=d['summary'], cover_image_url=d['cover_image_url'], cover_alt=d['cover_alt'],
                                author=post.author, published_at=post.published_at or datetime.utcnow(),
                                is_published=post.is_published)
        shown.excerpt = lambda length=200: Blog.excerpt(shown, length)
    from app.routes.blog import share_card
    resp = render_template('pages/blog_post.html', post=shown, preview=True, **share_card(shown))
    return resp, 200, {'X-Robots-Tag': 'noindex'}


@admin_bp.route('/blog/<int:post_id>/image', methods=['POST'])
@login_required
@admin_required
def blog_image(post_id):
    """One picture from the editor: the cover (1200 wide) or one in the post."""
    post = _post_or_404(post_id)
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'Choose a picture.'}), 400
    if f.filename.rsplit('.', 1)[-1].lower() not in be.IMAGE_EXT:
        return jsonify({'error': 'Use a JPG, PNG or WebP picture.'}), 400
    data = f.read()
    if len(data) > be.MAX_IMAGE_BYTES:
        return jsonify({'error': 'That picture is larger than 10 MB.'}), 400
    width = be.COVER_WIDTH if request.form.get('purpose') == 'cover' else be.BODY_WIDTH
    try:
        url = be.store_image(data, f.filename, width)
    except be.ImageError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'url': url, 'src': be.site_url(url), 'name': f.filename})
