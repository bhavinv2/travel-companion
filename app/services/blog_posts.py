"""The blog workspace (admin/blog/*): posts by status, categories and tags, saved versions, the picture
library, and posts that go live later.

blog_engine is the post itself (Word in, the allowlist, the checks); this is everything around it,
the way WordPress has it: All posts with its status views (Published, Scheduled, Drafts, From Word,
Trash), Categories, Tags, Media, and Revisions on every post.

A post's status is one of four words (Blog.status): draft, published, scheduled (published with a time
still to come -- Blog.live() leaves it off the site until then) and trash (off the site, back with
Restore). "Went live" is handled once per post (went_live): everybody is told, if the post says so --
straight away on Publish, or by the jobs (run_scheduled) when a scheduled post's time comes.
"""
import difflib
import re
from datetime import datetime, timedelta
from html import escape, unescape

from slugify import slugify

from app import db
from app.models import Blog, BlogMedia, BlogRevision, BlogTerm, User

STATUSES = (('all', 'All'), ('published', 'Published'), ('scheduled', 'Scheduled'), ('draft', 'Drafts'),
            ('word', 'From Word'), ('trash', 'Trash'))
SORTS = ('date', 'title', 'modified')
KEEP_REVISIONS = 50
TERM_LABELS = {'category': ('Category', 'Categories'), 'tag': ('Tag', 'Tags')}
IST = timedelta(hours=5, minutes=30)


def parse_ist(text):
    """'2026-10-25T09:30' typed in the shown time (India unless the header's clock says otherwise), as the
    database keeps times (UTC); None when blank."""
    from app.services import clock
    try:
        return clock.to_utc(datetime.strptime((text or '').strip()[:16], '%Y-%m-%dT%H:%M'))
    except ValueError:
        return None


def ist_input(when):
    """A time as a datetime-local field shows it, in the shown time."""
    from app.services import clock
    return clock.fmt(when, '%Y-%m-%dT%H:%M') if when else ''


# ============================================================================== posts

def by_status(query, status, now=None):
    now = now or datetime.utcnow()
    if status == 'trash':
        return query.filter(Blog.trashed_at.isnot(None))
    query = query.filter(Blog.trashed_at.is_(None))
    if status == 'published':
        return query.filter(Blog.is_published.is_(True), db.or_(Blog.published_at.is_(None), Blog.published_at <= now))
    if status == 'scheduled':
        return query.filter(Blog.is_published.is_(True), Blog.published_at > now)
    if status == 'draft':
        return query.filter(db.or_(Blog.is_published.is_(False), Blog.is_published.is_(None)))
    if status == 'word':
        return query.filter(Blog.source_file.isnot(None))
    return query


def counts(now=None):
    return {k: by_status(Blog.query, k, now).count() for k, _ in STATUSES}


def _when(post):
    return post.published_at or post.created_at


def months():
    """[('2026-10', 'October 2026')] -- the months posts are dated in, newest first."""
    seen = {}
    for pub, made in db.session.query(Blog.published_at, Blog.created_at):
        d = pub or made
        if d:
            seen[d.strftime('%Y-%m')] = d.strftime('%B %Y')
    return sorted(seen.items(), reverse=True)


def month_range(ym):
    try:
        first = datetime.strptime(ym or '', '%Y-%m')
    except ValueError:
        return None
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, nxt


def find(status='all', q='', category=None, tag=None, author=None, month='', sort='date', direction='desc'):
    """The All posts screen's query: one status view, narrowed by the filters above the table."""
    query = by_status(Blog.query, status)
    if q:
        pat = '%%%s%%' % q
        query = query.filter(db.or_(Blog.title.ilike(pat), Blog.slug.ilike(pat), Blog.source_file.ilike(pat)))
    for term_id in (category, tag):
        if term_id:
            query = query.filter(Blog.terms.any(BlogTerm.id == term_id))
    if author:
        query = query.filter(Blog.author_id == author)
    span = month_range(month)
    if span:
        when = db.func.coalesce(Blog.published_at, Blog.created_at)
        query = query.filter(when >= span[0], when < span[1])
    col = {'title': Blog.title, 'modified': Blog.updated_at}.get(sort, db.func.coalesce(Blog.published_at, Blog.created_at))
    order = col.asc() if direction == 'asc' else col.desc()
    return query.order_by(order, Blog.id.desc())


def authors():
    """Who a post can be put under: admins, and everybody who has written one."""
    ids = {a for (a,) in db.session.query(Blog.author_id).distinct()}
    return (User.query.filter(db.or_(User.is_admin.is_(True), User.id.in_(list(ids) or [0])))
            .order_by(User.username).all())


def trash(post):
    post.trashed_at = datetime.utcnow()


def restore(post):
    """Out of the Trash as a draft, like WordPress: putting it back on the site is a decision of its own."""
    post.trashed_at = None
    post.is_published = False


def duplicate(post, user):
    """A draft copy: the words, the pictures, the categories and tags; a new address, nobody told yet."""
    title = ('Copy of %s' % post.title)[:300]
    copy = Blog(author_id=user.id, title=title, slug=_free_slug(slugify(title, max_length=80, word_boundary=True)),
                content=post.content, summary=post.summary, cover_image_url=post.cover_image_url,
                cover_alt=post.cover_alt, seo_title=post.seo_title, focus_keyword=post.focus_keyword,
                is_published=False, send_notification=post.send_notification)
    copy.terms = list(post.terms)
    db.session.add(copy)
    db.session.flush()
    remember(copy, user, 'Copied from "%s"' % post.title[:80])
    return copy


def _free_slug(base):
    from app.services.blog_engine import unique_slug
    return unique_slug(base or 'post')


def quick_draft(title, text, user):
    """The dashboard's Quick draft: a title and a few lines, saved as a draft to finish in the editor."""
    from app.services.blog_engine import sanitize
    paras = [p.strip() for p in re.split(r'\n\s*\n', (text or '').replace('\r', '')) if p.strip()]
    post = Blog(author_id=user.id, title=title[:300], is_published=False, send_notification=True,
                slug=_free_slug(slugify(title, max_length=80, word_boundary=True)),
                content=sanitize(''.join('<p>%s</p>' % escape(p).replace('\n', '<br>') for p in paras)))
    db.session.add(post)
    db.session.flush()
    remember(post, user, 'Quick draft')
    return post


# ============================================================================== going live

def went_live(post, now=None):
    """Once per post: tell everybody (if the post says so) that it is on the site. Returns True when told."""
    if post.notified_at:
        return False
    post.notified_at = now or datetime.utcnow()
    if post.send_notification:
        from app.routes.admin import _notify_all_blog
        _notify_all_blog(post)
        return True
    return False


def run_scheduled(now=None):
    """The jobs: scheduled posts whose time has come are on the site now (Blog.live) -- tell everybody."""
    now = now or datetime.utcnow()
    due = (Blog.query.filter(Blog.is_published.is_(True), Blog.trashed_at.is_(None), Blog.notified_at.is_(None),
                             Blog.published_at.isnot(None), Blog.published_at <= now).all())
    told = sum(1 for post in due if went_live(post, now))
    db.session.commit()
    return {'blog_went_live': len(due), 'blog_told': told}


# ============================================================================== categories and tags

def terms(kind):
    return BlogTerm.query.filter_by(kind=kind).order_by(db.func.lower(BlogTerm.name)).all()


def term_counts(kind):
    """{term id: posts not in the Trash}"""
    from app.models import blog_post_terms as pt
    rows = (db.session.query(pt.c.term_id, db.func.count(pt.c.blog_id))
            .join(Blog, Blog.id == pt.c.blog_id).join(BlogTerm, BlogTerm.id == pt.c.term_id)
            .filter(BlogTerm.kind == kind, Blog.trashed_at.is_(None)).group_by(pt.c.term_id))
    return dict(rows)


def live_terms(kind):
    """The categories (or tags) that have a post on the site, with how many: the blog's own menu."""
    from app.models import blog_post_terms as pt
    live = Blog.live().with_entities(Blog.id).subquery()
    rows = (db.session.query(BlogTerm, db.func.count(pt.c.blog_id))
            .join(pt, pt.c.term_id == BlogTerm.id).filter(pt.c.blog_id.in_(db.select(live.c.id)))
            .filter(BlogTerm.kind == kind).group_by(BlogTerm.id).order_by(db.func.lower(BlogTerm.name)))
    return rows.all()


def save_term(kind, name, slug='', description='', term=None):
    """(term, None) or (None, why not). A new one when `term` is None."""
    name = re.sub(r'\s+', ' ', name or '').strip()[:80]
    if not name:
        return None, 'Give it a name.'
    slug = slugify(slug or name, max_length=80, word_boundary=True) or slugify(name) or 'term'
    clash = BlogTerm.query.filter(BlogTerm.kind == kind, BlogTerm.id != (term.id if term else 0),
                                  db.or_(BlogTerm.slug == slug, db.func.lower(BlogTerm.name) == name.lower())).first()
    if clash:
        return None, 'There is already a %s called "%s".' % (TERM_LABELS[kind][0].lower(), clash.name)
    if term is None:
        term = BlogTerm(kind=kind)
        db.session.add(term)
    term.name, term.slug, term.description = name, slug, (description or '').strip()[:300] or None
    db.session.flush()
    return term, None


def tags_from(text, make=True):
    """The tags typed as "visa, parents, Air India": found, or made (make=False: a new one is only shown,
    not saved -- the preview)."""
    out, seen = [], set()
    for raw in (text or '').split(','):
        name = re.sub(r'\s+', ' ', raw).strip()[:80]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        term = (BlogTerm.query.filter(BlogTerm.kind == 'tag', db.func.lower(BlogTerm.name) == name.lower()).first()
                or BlogTerm.query.filter_by(kind='tag', slug=slugify(name, max_length=80, word_boundary=True)).first())
        if term is None and not make:
            term = BlogTerm(kind='tag', name=name, slug=slugify(name, max_length=80, word_boundary=True))
        elif term is None:
            term, _err = save_term('tag', name)
        if term is not None:
            out.append(term)
    return out


def set_terms(post, category_ids, tag_text):
    cats = BlogTerm.query.filter(BlogTerm.kind == 'category', BlogTerm.id.in_(category_ids or [0])).all()
    post.terms = cats + tags_from(tag_text)


# ============================================================================== saved versions

def _same(rev, post):
    return (rev.title, rev.summary or '', rev.content or '') == (post.title, post.summary or '', post.content or '')


def newest(post):
    return post.revisions.order_by(BlogRevision.saved_at.desc(), BlogRevision.id.desc()).first()


def remember_before(post):
    """A post saved before versions were kept: what it says now becomes its first version, so the first
    save in the editor can be undone too."""
    if post.id and post.revisions.count() == 0 and (post.content or post.title):
        db.session.add(BlogRevision(blog_id=post.id, title=post.title or '', summary=post.summary,
                                    content=post.content, note='As it was before versions were kept',
                                    saved_by_id=post.author_id,
                                    saved_at=post.updated_at or post.created_at or datetime.utcnow()))


def remember(post, user, note):
    """Keep the post as it is now as a version (unless the newest one says the same), and only the last
    KEEP_REVISIONS."""
    last = newest(post)
    if last is not None and _same(last, post):
        return None
    rev = BlogRevision(blog_id=post.id, title=post.title or '', summary=post.summary, content=post.content,
                       note=note[:120], saved_by_id=user.id if user else None, saved_at=datetime.utcnow())
    db.session.add(rev)
    db.session.flush()
    old = [r.id for r in post.revisions.order_by(BlogRevision.saved_at.desc(), BlogRevision.id.desc())
           .offset(KEEP_REVISIONS)]
    if old:
        BlogRevision.query.filter(BlogRevision.id.in_(old)).delete(synchronize_session=False)
    return rev


_BLOCK_END = re.compile(r'</(?:p|h2|h3|li|blockquote|aside|figure|tr|th|td)>|<hr\s*/?>', re.I)
_IMG = re.compile(r'<img\b[^>]*>', re.I)


def blocks(html):
    """A post as a list of lines to compare: one per paragraph, heading, list item, table row; a picture
    as [Picture: what it shows]."""
    def picture(m):
        alt = re.search(r'\balt="([^"]+)"', m.group(0))
        return ' [Picture%s] ' % (': ' + unescape(alt.group(1)) if alt else '')
    html = _IMG.sub(picture, html or '')
    out = []
    for part in _BLOCK_END.split(html):
        text = re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', ' ', part))).strip()
        if text:
            out.append(text)
    return out


def _words(a, b):
    """One changed line, word by word: removed words struck through, new ones marked."""
    aw, bw = a.split(' '), b.split(' ')
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, aw, bw, autojunk=False).get_opcodes():
        if op == 'equal':
            out.append(escape(' '.join(aw[i1:i2])))
            continue
        if i2 > i1:
            out.append('<del>%s</del>' % escape(' '.join(aw[i1:i2])))
        if j2 > j1:
            out.append('<ins>%s</ins>' % escape(' '.join(bw[j1:j2])))
    return ' '.join(out)


def compare(old, new):
    """What changed from `old` to `new` (two versions, or a version and the post):
    {'title': html or None, 'summary': html or None, 'lines': [{'kind', 'html'}], 'added', 'removed'}.
    Unchanged lines far from a change are folded into one "N lines the same" row."""
    def line(kind, html):
        return {'kind': kind, 'html': html}
    a, b = blocks(old.content if old else ''), blocks(new.content)
    rows, added, removed = [], 0, 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == 'equal':
            same = [line('same', escape(t)) for t in a[i1:i2]]
            if len(same) > 4:
                same = same[:1] + [line('fold', '%d lines the same' % (len(same) - 2))] + same[-1:]
            rows += same
        elif op == 'replace' and (i2 - i1) == (j2 - j1):
            for x, y in zip(a[i1:i2], b[j1:j2]):
                rows.append(line('changed', _words(x, y)))
                added += 1
                removed += 1
        else:
            rows += [line('removed', escape(t)) for t in a[i1:i2]]
            rows += [line('added', escape(t)) for t in b[j1:j2]]
            removed += i2 - i1
            added += j2 - j1
    if rows and all(r['kind'] in ('same', 'fold') for r in rows):
        rows = []
    t_old, s_old = (old.title, old.summary or '') if old else ('', '')
    return {'title': _words(t_old, new.title or '') if t_old != (new.title or '') else None,
            'summary': _words(s_old, new.summary or '') if s_old != (new.summary or '') else None,
            'lines': rows, 'added': added, 'removed': removed}


# ============================================================================== the picture library

def _key(url):
    """A picture's file name: the same picture whatever prefix or host its address was written with."""
    return (url or '').split('?')[0].rstrip('/').rsplit('/', 1)[-1]


def record_media(url, name, data, user=None):
    """Remember a picture stored for the blog (blog_engine.store_image) so the library offers it."""
    if not url:
        return None
    with db.session.no_autoflush:          # mid-import: the post being made has no title yet
        if BlogMedia.query.filter_by(url=url).first():
            return None
    width = height = None
    try:
        import io
        from PIL import Image
        width, height = Image.open(io.BytesIO(data)).size
    except Exception:          # noqa: BLE001 -- the size is a nicety
        pass
    m = BlogMedia(url=url, name=(name or '')[:255], width=width, height=height, bytes=len(data or b''),
                  uploaded_by_id=getattr(user, 'id', None))
    db.session.add(m)
    return m


def usage():
    """{file name: [posts that show it]} -- in their text or as their cover."""
    used = {}
    for post in Blog.query.order_by(Blog.updated_at.desc()):
        found = {_key(u) for u in re.findall(r'<img\b[^>]*?\bsrc="([^"]+)"', post.content or '')}
        if post.cover_image_url:
            found.add(_key(post.cover_image_url))
        for k in found:
            used.setdefault(k, []).append(post)
    return used


def library(q='', show='all'):
    """Every picture the blog has: the ones uploaded (BlogMedia) and the ones older posts show, newest
    first, each with the posts it is in. `show`: all / used / unused."""
    from app.services.blog_engine import site_url
    used = usage()
    items, seen = [], set()
    for m in BlogMedia.query.order_by(BlogMedia.created_at.desc(), BlogMedia.id.desc()):
        seen.add(_key(m.url))
        items.append({'id': m.id, 'url': m.url, 'src': site_url(m.url), 'name': m.name or _key(m.url),
                      'width': m.width, 'height': m.height, 'bytes': m.bytes, 'alt': m.alt or '',
                      'at': m.created_at, 'by': m.uploaded_by.username if m.uploaded_by else '',
                      'posts': used.get(_key(m.url), [])})
    for post in Blog.query.order_by(Blog.updated_at.desc()):          # pictures from before the library
        urls = re.findall(r'<img\b[^>]*?\bsrc="([^"]+)"', post.content or '')
        if post.cover_image_url:
            urls.insert(0, post.cover_image_url)
        for u in urls:
            if _key(u) in seen or not u.startswith(('/', 'http')):
                continue
            seen.add(_key(u))
            items.append({'id': None, 'url': u, 'src': site_url(u), 'name': _key(u), 'width': None, 'height': None,
                          'bytes': None, 'alt': '', 'at': post.updated_at, 'by': '', 'posts': used.get(_key(u), [])})
    if q:
        ql = q.lower()
        items = [i for i in items if ql in i['name'].lower() or ql in i['alt'].lower()]
    if show == 'used':
        items = [i for i in items if i['posts']]
    elif show == 'unused':
        items = [i for i in items if not i['posts']]
    return items
