"""The blog, in the admin portal, as a workspace of its own the way WordPress has it: a dark menu down the
left (Dashboard, All posts, Add new, Categories, Tags, Media, Import from Word), and the editor full screen
-- the post in the middle as it will look, its settings on the right (Post, SEO, Checks), Publish behind a
last look ("Ready to publish?").

The work is in services/blog_engine.py (the post: Word in, the allowlist, the checks) and
services/blog_posts.py (around it: statuses, categories and tags, versions, the picture library, posts
that go live later); these routes read forms and draw pages. They are added to admin_bp (imported in
app/__init__ before the blueprint is registered), and reached through the same roles (access.py:
"Blog posts" for the lists and the dashboard, "New blog post" for writing, "Import blog posts").

A new post and a saved one are the same editor: /blog/new until its first Save draft or Publish makes the
post, /blog/<id>/edit after that. The checks, the preview, picture uploads and "Replace from Word" answer
for both (a new post has no id yet). Word-imported posts are ordinary posts: they open in the same editor.
"""
import io
from datetime import datetime
from types import SimpleNamespace

from flask import abort, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from slugify import slugify

from app import db
from app.models import Blog, BlogMedia, BlogRevision, BlogTerm, User
from app.routes.admin import _page_args, admin_bp, admin_required
from app.services import blog_engine as be
from app.services import blog_posts as bp


def _post_or_404(post_id):
    if post_id is None:
        return None
    post = db.session.get(Blog, post_id)
    if post is None:
        abort(404)
    return post


def _back(default='admin.blog_list'):
    """Where a button on a list goes back to: the same view, filters and page."""
    nxt = request.form.get('next') or ''
    return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else url_for(default))


# ============================================================================== dashboard

@admin_bp.route('/blog/dashboard')
@login_required
@admin_required
def blog_dashboard():
    now = datetime.utcnow()
    live = bp.by_status(Blog.query, 'published', now)
    return render_template(
        'admin/blog/dashboard.html', counts=bp.counts(now),
        terms={k: BlogTerm.query.filter_by(kind=k).count() for k in BlogTerm.KINDS},
        drafts=bp.by_status(Blog.query, 'draft', now).order_by(Blog.updated_at.desc()).limit(6).all(),
        scheduled=bp.by_status(Blog.query, 'scheduled', now).order_by(Blog.published_at.asc()).limit(6).all(),
        recent=live.order_by(Blog.published_at.desc()).limit(6).all(),
        activity=(BlogRevision.query.join(Blog, Blog.id == BlogRevision.blog_id)
                  .order_by(BlogRevision.saved_at.desc(), BlogRevision.id.desc()).limit(10).all()),
        media=BlogMedia.query.count())


@admin_bp.route('/blog/quick-draft', methods=['POST'])
@login_required
@admin_required
def blog_quick_draft():
    title = (request.form.get('title') or '').strip()
    if not title:
        flash('Give the draft a title.', 'warning')
        return redirect(url_for('admin.blog_dashboard'))
    post = bp.quick_draft(title, request.form.get('content'), current_user)
    db.session.commit()
    flash('Draft saved. Finish it here.', 'success')
    return redirect(url_for('admin.blog_edit', post_id=post.id))


# ============================================================================== all posts

def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@admin_bp.route('/blog')
@login_required
@admin_required
def blog_list():
    """Every post, by status (All, Published, Scheduled, Drafts, From Word, Trash), filtered, sorted, a
    page at a time, with what each one still needs (its red checks)."""
    a = request.args
    status = a.get('status') if a.get('status') in dict(bp.STATUSES) else 'all'
    f = {'q': (a.get('q') or '').strip(), 'category': _int(a.get('category')), 'tag': _int(a.get('tag')),
         'author': _int(a.get('author')), 'month': a.get('month') or '',
         'sort': a.get('sort') if a.get('sort') in bp.SORTS else 'date',
         'direction': 'asc' if a.get('dir') == 'asc' else 'desc'}
    page, per_page = _page_args(20)
    query = bp.find(status, **f)
    total = query.count()
    pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, pages)
    posts = query.offset((page - 1) * per_page).limit(per_page).all()
    red = {p.id: sum(1 for c in be.checks(p.title, p.slug, p.summary, p.content, p.cover_image_url, p.cover_alt,
                                          p.id, p.focus_keyword, p.seo_title) if c['level'] == 'error')
           for p in posts}
    return render_template('admin/blog/posts.html', posts=posts, red=red, status=status, f=f, counts=bp.counts(),
                           total=total, page=page, pages=pages, categories=bp.terms('category'),
                           tags=bp.terms('tag'), authors=bp.authors(), months=bp.months(), statuses=bp.STATUSES)


@admin_bp.route('/blog/bulk', methods=['POST'])
@login_required
@admin_required
def blog_bulk():
    """The posts ticked on All posts: published, back to drafts, to the Trash, or out of it. Publishing
    skips a post with a red check -- and says which."""
    action = request.form.get('action')
    ids = [i for i in (_int(x) for x in request.form.getlist('ids')) if i]
    posts = Blog.query.filter(Blog.id.in_(ids or [0])).all()
    if not posts or action not in ('publish', 'draft', 'trash', 'restore'):
        flash('Tick some posts and choose what to do with them.', 'warning')
        return _back()
    done, skipped = 0, []
    for post in posts:
        if action == 'publish':
            if post.trashed_at or post.is_published:
                continue
            if be.has_errors(be.checks(post.title, post.slug, post.summary, post.content, post.cover_image_url,
                                       post.cover_alt, post.id)):
                skipped.append(post.title)
                continue
            post.is_published = True
            post.published_at = post.published_at or datetime.utcnow()
            bp.remember(post, current_user, 'Published')
            if post.published_at <= datetime.utcnow():
                bp.went_live(post)
        elif action == 'draft':
            if not post.is_published:
                continue
            post.is_published = False
        elif action == 'trash':
            if post.trashed_at:
                continue
            bp.trash(post)
        elif action == 'restore':
            if not post.trashed_at:
                continue
            bp.restore(post)
        done += 1
    db.session.commit()
    verb = {'publish': 'published', 'draft': 'moved to drafts', 'trash': 'moved to the Trash',
            'restore': 'restored as drafts'}[action]
    flash('%d post%s %s.' % (done, '' if done == 1 else 's', verb) + (
        ' Not published (fix their red checks first): %s.' % '; '.join(skipped[:5]) if skipped else ''),
        'success' if not skipped else 'warning')
    return _back()


@admin_bp.route('/blog/<int:post_id>/trash', methods=['POST'])
@login_required
@admin_required
def blog_trash(post_id):
    post = _post_or_404(post_id)
    bp.trash(post)
    db.session.commit()
    flash('"%s" moved to the Trash. It is off the site; Restore brings it back as a draft.' % post.title, 'success')
    return _back()


@admin_bp.route('/blog/<int:post_id>/restore', methods=['POST'])
@login_required
@admin_required
def blog_restore(post_id):
    post = _post_or_404(post_id)
    bp.restore(post)
    db.session.commit()
    flash('"%s" restored as a draft.' % post.title, 'success')
    return _back()


@admin_bp.route('/blog/<int:post_id>/duplicate', methods=['POST'])
@login_required
@admin_required
def blog_duplicate(post_id):
    copy = bp.duplicate(_post_or_404(post_id), current_user)
    db.session.commit()
    flash('A copy is ready as a draft.', 'success')
    return redirect(url_for('admin.blog_edit', post_id=copy.id))


# ============================================================================== categories and tags

@admin_bp.route('/blog/categories', defaults={'kind': 'category'}, methods=['GET', 'POST'])
@admin_bp.route('/blog/tags', defaults={'kind': 'tag'}, methods=['GET', 'POST'])
@login_required
@admin_required
def blog_terms(kind):
    """Categories (the blog's sections) or tags: add one on the left, the list on the right, each
    renamed in its row."""
    editing = db.session.get(BlogTerm, _int(request.values.get('edit')) or 0)
    if editing is not None and editing.kind != kind:
        editing = None
    if request.method == 'POST':
        term = db.session.get(BlogTerm, _int(request.form.get('id')) or 0)
        if term is not None and term.kind != kind:
            abort(404)
        saved, err = bp.save_term(kind, request.form.get('name'), request.form.get('slug'),
                                  request.form.get('description'), term)
        if err:
            flash(err, 'danger')
        else:
            db.session.commit()
            flash('%s "%s" %s.' % (bp.TERM_LABELS[kind][0], saved.name, 'saved' if term else 'added'), 'success')
        return redirect(url_for('admin.blog_terms', kind=kind))
    q = (request.args.get('q') or '').strip().lower()
    rows = [t for t in bp.terms(kind) if not q or q in t.name.lower() or q in (t.description or '').lower()]
    return render_template('admin/blog/terms.html', kind=kind, label=bp.TERM_LABELS[kind], rows=rows,
                           used=bp.term_counts(kind), q=request.args.get('q') or '', editing=editing)


@admin_bp.route('/blog/terms/<int:term_id>/delete', methods=['POST'])
@login_required
@admin_required
def blog_term_delete(term_id):
    """Gone from every post that had it; the posts themselves stay as they are."""
    term = db.session.get(BlogTerm, term_id) or abort(404)
    kind, name = term.kind, term.name
    db.session.delete(term)
    db.session.commit()
    flash('%s "%s" deleted.' % (bp.TERM_LABELS[kind][0], name), 'success')
    return redirect(url_for('admin.blog_terms', kind=kind))


@admin_bp.route('/blog/terms/add', methods=['POST'])
@login_required
@admin_required
def blog_term_add():
    """"Add new category" in the editor: made (or found) without leaving the post."""
    kind = request.form.get('kind') if request.form.get('kind') in BlogTerm.KINDS else 'category'
    name = (request.form.get('name') or '').strip()
    found = BlogTerm.query.filter(BlogTerm.kind == kind, db.func.lower(BlogTerm.name) == name.lower()).first()
    term, err = (found, None) if found else bp.save_term(kind, name)
    if err:
        return jsonify({'error': err}), 400
    db.session.commit()
    return jsonify({'id': term.id, 'name': term.name, 'slug': term.slug})


# ============================================================================== media

@admin_bp.route('/blog/media')
@login_required
@admin_required
def blog_media():
    """Every picture the blog has, newest first: upload more, describe one, see which posts show it, delete
    one nobody uses. ?format=json is the editor's "Media library" (pictures only)."""
    q = (request.args.get('q') or '').strip()
    show = request.args.get('show') if request.args.get('show') in ('used', 'unused') else 'all'
    items = bp.library(q, show)
    if request.args.get('format') == 'json':
        return jsonify({'items': [{'id': i['id'], 'url': i['url'], 'src': i['src'], 'name': i['name'], 'alt': i['alt'],
                                   'width': i['width'], 'height': i['height']} for i in items[:300]]})
    return render_template('admin/blog/media.html', items=items, q=q, show=show)


@admin_bp.route('/blog/media/upload', methods=['POST'])
@login_required
@admin_required
def blog_media_upload():
    files = [f for f in request.files.getlist('files') if f and f.filename]
    if not files:
        return jsonify({'error': 'Choose a picture.'}), 400
    done, errors = [], []
    for f in files[:30]:
        if f.filename.rsplit('.', 1)[-1].lower() not in be.IMAGE_EXT:
            errors.append('%s: use a JPG, PNG or WebP picture.' % f.filename)
            continue
        data = f.read()
        if len(data) > be.MAX_IMAGE_BYTES:
            errors.append('%s is larger than 10 MB.' % f.filename)
            continue
        try:
            done.append(be.store_image(data, f.filename, be.BODY_WIDTH))
        except be.ImageError as e:
            errors.append(str(e))
    db.session.commit()
    return jsonify({'uploaded': len(done), 'errors': errors}), 200 if done else 400


@admin_bp.route('/blog/media/<int:media_id>', methods=['POST'])
@login_required
@admin_required
def blog_media_save(media_id):
    """A picture's description: offered as its alt text wherever it is put in a post from the library."""
    m = db.session.get(BlogMedia, media_id) or abort(404)
    m.alt = (request.form.get('alt') or '').strip()[:300] or None
    db.session.commit()
    return jsonify({'ok': True, 'alt': m.alt or ''})


@admin_bp.route('/blog/media/<int:media_id>/delete', methods=['POST'])
@login_required
@admin_required
def blog_media_delete(media_id):
    """Only a picture no post shows: deleting one in use would leave a hole in a post."""
    m = db.session.get(BlogMedia, media_id) or abort(404)
    if bp.usage().get(bp._key(m.url)):
        flash('That picture is in a post: take it out of the post first.', 'danger')
        return redirect(url_for('admin.blog_media'))
    url, name = m.url, m.name
    db.session.delete(m)
    db.session.commit()
    try:
        from app.services import storage
        storage.delete_public(url)
    except Exception:          # noqa: BLE001 -- the library row is gone either way
        pass
    flash('%s deleted.' % (name or 'The picture'), 'success')
    return redirect(url_for('admin.blog_media'))


# ============================================================================== import from Word

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
                           image_rules=be.IMAGE_RULES, check_rules=be.CHECK_RULES, advanced_rules=be.ADVANCED_RULES,
                           advanced_image_rules=be.ADVANCED_IMAGE_RULES)


@admin_bp.route('/blog/template.docx')
@login_required
@admin_required
def blog_template():
    return send_file(io.BytesIO(be.template_docx()), mimetype=be.DOCX_MIME, as_attachment=True,
                     download_name='nri-blog-template.docx')


@admin_bp.route('/blog/new/word', methods=['POST'], defaults={'post_id': None})
@admin_bp.route('/blog/<int:post_id>/word', methods=['POST'])
@login_required
@admin_required
def blog_word(post_id):
    """"Replace from Word" in the editor: the document's title, summary, text and pictures, for the editor
    to show in place of what is there. Nothing is saved until the writer saves; Undo brings the old back."""
    post = _post_or_404(post_id)
    f = request.files.get('document')
    if not f or not f.filename:
        return jsonify({'error': 'Choose a Word document (.docx).'}), 400
    if not f.filename.lower().endswith('.docx'):
        return jsonify({'error': 'Only Word documents (.docx) can be read: save it as .docx first.'}), 400
    try:
        got = be.read_word(f.read(), post)
    except be.DocxError as e:
        return jsonify({'error': str(e)}), 400
    db.session.commit()                    # the pictures it brought, in the library
    got['file'] = f.filename
    return jsonify(got)


# ============================================================================== the editor

def _fields(post):
    f = request.form
    title = (f.get('title') or '').strip()[:300]
    cover = be._safe_url((f.get('cover_image_url') or '').strip(), image=True)
    slug = slugify((f.get('slug') or '').strip() or title, max_length=80, word_boundary=True)
    if post is None and f.get('slug_auto') == '1' and slug:
        slug = be.unique_slug(slug)          # made from the title, not typed: "-2" rather than a red check
    shown = 'settings_shown' in f            # the settings panel was on the page (not a check from an old tab)
    author = db.session.get(User, _int(f.get('author_id')) or 0) if shown else None
    return {'title': title,
            'slug': slug,
            'summary': (f.get('summary') or '').strip()[:300],
            'content': be.sanitize(f.get('content') or ''),
            'cover_image_url': (cover or '')[:500] or None,
            'cover_alt': (f.get('cover_alt') or '').strip()[:300],
            'seo_title': (f.get('seo_title') or '').strip()[:300],
            'focus_keyword': (f.get('focus_keyword') or '').strip()[:100],
            'is_featured': f.get('is_featured') == 'on' if shown else bool(post and post.is_featured),
            'author_id': author.id if author else (post.author_id if post else current_user.id),
            'publish_at': bp.parse_ist(f.get('publish_at')) if shown else (post.published_at if post else None),
            'categories': [i for i in (_int(x) for x in f.getlist('categories')) if i] if shown else None,
            'tags': f.get('tags', '') if shown else None,
            'send_notification': f.get('send_notification') == 'on' if 'send_notification_shown' in f
            else bool(post.send_notification) if post else True}


def _found(d, post):
    return be.checks(d['title'], d['slug'], d['summary'], d['content'], d['cover_image_url'], d['cover_alt'],
                     post.id if post else None, d.get('focus_keyword'), d.get('seo_title'))


def _saved(post):
    """The editor's fields as the post has them."""
    if post is None:
        return {'title': '', 'slug': '', 'summary': '', 'content': '', 'cover_image_url': None, 'cover_alt': '',
                'seo_title': '', 'focus_keyword': '', 'is_featured': False, 'author_id': current_user.id,
                'publish_at': None, 'categories': [], 'tags': '', 'send_notification': True}
    return {'title': post.title, 'slug': post.slug, 'summary': post.summary or '', 'content': post.content or '',
            'cover_image_url': post.cover_image_url, 'cover_alt': post.cover_alt or '',
            'seo_title': post.seo_title or '', 'focus_keyword': post.focus_keyword or '',
            'is_featured': bool(post.is_featured), 'author_id': post.author_id, 'publish_at': post.published_at,
            'categories': [t.id for t in post.categories], 'tags': ', '.join(t.name for t in post.tags),
            'send_notification': bool(post.send_notification)}


def _editor(post, d=None, found=None, status=200, revision=None):
    if d is None:
        d = _saved(post)
    if d.get('categories') is None or d.get('tags') is None:     # a form without the settings panel
        kept = _saved(post)
        d['categories'] = kept['categories'] if d.get('categories') is None else d['categories']
        d['tags'] = kept['tags'] if d.get('tags') is None else d['tags']
    blank = post is None and not d['title'] and not d['content']
    found = [] if blank and found is None else found if found is not None else _found(d, post)
    return render_template('admin/blog_edit.html', post=post, d=d, body=be.for_editor(d['content']), checks=found,
                           rules=be.FORMAT_RULES, categories=bp.terms('category'), all_tags=bp.terms('tag'),
                           authors=bp.authors(), publish_at=bp.ist_input(d['publish_at']), revision=revision,
                           versions=post.revisions.count() if post else 0), status


@admin_bp.route('/blog/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_blog():
    """The editor with nothing in it yet: the first Save draft (or Publish) makes the post."""
    if request.method == 'GET':
        return _editor(None)
    return _save(None)


@admin_bp.route('/blog/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def blog_edit(post_id):
    """?revision=<id>: that saved version in the editor, to look at and -- by saving -- bring back."""
    post = _post_or_404(post_id)
    if request.method == 'GET':
        rev = db.session.get(BlogRevision, _int(request.args.get('revision')) or 0)
        if rev is not None and rev.blog_id == post.id:
            d = _saved(post)
            d.update(title=rev.title, summary=rev.summary or '', content=rev.content or '')
            return _editor(post, d, revision=rev)
        return _editor(post)
    return _save(post)


def _save(post):
    """Save keeps a draft a draft; Publish (or Update, on a live post) refuses while a red check is
    left -- a draft still keeps the changes, a live post does not change at all. Publish with a time
    still to come schedules the post: it is on the site, and everybody is told, from then."""
    d = _fields(post)
    action = request.form.get('action') or 'save'
    found = _found(d, post)
    if not d['title'] or not d['slug'] or any('Another post' in c['text'] for c in found):
        flash('Not saved: %s' % ('add a title.' if not d['title'] else
                                 'another post already uses that address.' if d['slug'] else 'add the address.'), 'danger')
        return _editor(post, d, found, 400)
    was_live = post is not None and post.status == 'published'
    if post is None:
        post = Blog(author_id=current_user.id, is_published=False)
        db.session.add(post)
    else:
        bp.remember_before(post)
    going_live = action == 'publish' or (action == 'save' and post.is_published)
    if going_live and be.has_errors(found):
        if post.is_published:
            flash('Not updated: fix the red items first. The live post is unchanged.', 'danger')
            db.session.rollback()
            return _editor(post, d, found, 400)
        _apply(post, d)
        db.session.flush()
        bp.remember(post, current_user, 'Draft saved')
        db.session.commit()
        flash('Saved as a draft, not published: fix the red items first.', 'danger')
        return redirect(url_for('admin.blog_edit', post_id=post.id))
    _apply(post, d)
    now = datetime.utcnow()
    if action == 'publish' and not post.is_published:
        post.is_published = True
        post.published_at = d['publish_at'] or post.published_at or now   # later: scheduled (run_scheduled)
    elif action == 'unpublish':
        post.is_published = False
    elif post.is_published and d['publish_at']:
        post.published_at = d['publish_at']   # a live post's date moved, or a scheduled one's time
    db.session.flush()
    later = post.is_published and post.published_at and post.published_at > now
    note = {'publish': 'Scheduled' if later else 'Published', 'unpublish': 'Switched to draft'}.get(
        action, 'Updated' if post.is_published else 'Draft saved')
    if request.args.get('revision') or request.form.get('revision'):
        note = 'Brought back an earlier version'
    bp.remember(post, current_user, note)
    db.session.commit()
    if post.is_published and not later:
        if was_live:
            post.notified_at = post.notified_at or now
        else:
            bp.went_live(post)                # once per post: the first time it is on the site
        db.session.commit()
    if later and action == 'publish':
        flash('Scheduled: on the site from %s (India time).' % (post.published_at + bp.IST).strftime('%d %b %Y, %H:%M'),
              'success')
    else:
        flash({'publish': 'Published.', 'unpublish': 'Switched to draft: only admins can see it now.'}.get(
            action, ('Scheduled post updated.' if later else 'Updated.') if post.is_published else 'Draft saved.'),
            'success')
    return redirect(url_for('admin.blog_edit', post_id=post.id))


def _apply(post, d):
    for k in ('title', 'slug', 'content', 'cover_image_url', 'send_notification', 'is_featured', 'author_id'):
        setattr(post, k, d[k])
    post.summary = d['summary'] or None
    post.cover_alt = d['cover_alt'] or None
    post.seo_title = d['seo_title'] or None
    post.focus_keyword = d['focus_keyword'] or None
    if d['categories'] is not None:
        bp.set_terms(post, d['categories'], d['tags'] or '')


@admin_bp.route('/blog/new/check', methods=['POST'], defaults={'post_id': None})
@admin_bp.route('/blog/<int:post_id>/check', methods=['POST'])
@login_required
@admin_required
def blog_check(post_id):
    post = _post_or_404(post_id)
    d = _fields(post)
    return jsonify({'checks': _found(d, post), 'words': be.word_count(d['content']), 'slug': d['slug']})


@admin_bp.route('/blog/new/preview', methods=['POST'], defaults={'post_id': None})
@admin_bp.route('/blog/<int:post_id>/preview', methods=['GET', 'POST'])
@login_required
@admin_required
def blog_preview(post_id):
    """The public page as it will look -- with what is in the editor now (POST), or as saved (GET)."""
    post = _post_or_404(post_id)
    shown = post
    if request.method == 'POST':
        d = _fields(post)
        terms = BlogTerm.query.filter(BlogTerm.kind == 'category', BlogTerm.id.in_(d['categories'] or [0])).all() \
            if d['categories'] is not None else (post.categories if post else [])
        shown = SimpleNamespace(id=post.id if post else 0, title=d['title'] or (post.title if post else 'Untitled'),
                                slug=d['slug'], content=d['content'], summary=d['summary'], seo_title=d['seo_title'],
                                cover_image_url=d['cover_image_url'], cover_alt=d['cover_alt'],
                                author=db.session.get(User, d['author_id']) or current_user,
                                published_at=d['publish_at'] or (post.published_at if post else None) or datetime.utcnow(),
                                is_published=bool(post and post.is_published), categories=terms,
                                tags=bp.tags_from(d['tags'] or '', make=False) if d['tags'] is not None
                                else (post.tags if post else []))
        shown.excerpt = lambda length=200: Blog.excerpt(shown, length)
        shown.reading_minutes = lambda: Blog.reading_minutes(shown)
    from app.routes.blog import share_card
    resp = render_template('pages/blog_post.html', post=shown, preview=True, related=[], **share_card(shown))
    return resp, 200, {'X-Robots-Tag': 'noindex'}


@admin_bp.route('/blog/image', methods=['POST'], defaults={'post_id': None})
@admin_bp.route('/blog/<int:post_id>/image', methods=['POST'])
@login_required
@admin_required
def blog_image(post_id):
    """One picture from the editor: the cover (1200 wide) or one in the post."""
    _post_or_404(post_id)
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
    db.session.commit()                    # in the picture library too
    return jsonify({'url': url, 'src': be.site_url(url), 'name': f.filename})


# ============================================================================== revisions

@admin_bp.route('/blog/<int:post_id>/revisions')
@login_required
@admin_required
def blog_revisions(post_id):
    """Every saved version of a post, newest first; one picked shows what changed from the one before
    it. "Bring this version back" opens it in the editor -- the post changes when it is saved."""
    post = _post_or_404(post_id)
    revs = post.revisions.order_by(BlogRevision.saved_at.desc(), BlogRevision.id.desc()).all()
    pick = next((r for r in revs if r.id == _int(request.args.get('r'))), revs[0] if revs else None)
    before = revs[revs.index(pick) + 1] if pick and revs.index(pick) + 1 < len(revs) else None
    return render_template('admin/blog/revisions.html', post=post, revs=revs, pick=pick, before=before,
                           diff=bp.compare(before, pick) if pick else None,
                           current=pick is not None and pick is revs[0] and bp._same(pick, post))
