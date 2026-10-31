"""Bring the WordPress blog's posts over to ours, before the WordPress site is switched off.

WordPress answers its public REST API to anybody (/wp-json/wp/v2/posts), so nothing is signed in.
Each published post becomes a published post on our blog with:

  * the same address word (slug) -- the old address, nriparentservice.com/<slug>/, then redirects
    to it (services/old_site.py), so Google and every shared link find it;
  * its date, its words, its summary (what Google showed) and its cover picture;
  * its tags, and its categories where our blog has one of the same name (none is made: ours are
    the blog's sections, chosen on purpose).

Pictures are copied, not linked: the WordPress server is going away. Nobody is told a post "went
live" -- they are old posts. A post that is already on our blog is left alone -- the same slug, the
same title, or a slug old_site.OLD_POSTS says lives here under another one -- so bringing them over
twice brings nothing twice, and the posts copied by hand before the switch are not copied again.

    fetch(site)              WordPress's published posts, newest first (raises WPError)
    bring_over(site, user)   {'added': [Blog], 'skipped': [(title, why)], 'pictures_failed': n}
"""
import html
import logging
import re
from datetime import datetime
from urllib.parse import urlparse

import requests

from app import db
from app.services import blog_engine, blog_posts, old_site, wp_blog

log = logging.getLogger(__name__)

TIMEOUT = 20
PICTURE_MAX = 15 * 1024 * 1024
PER_PAGE = 100
NOTE = 'Brought over from WordPress'
_IMG_RE = re.compile(r'<img\b[^>]*>', re.I)
_SRC_RE = re.compile(r'\bsrc="([^"]+)"', re.I)


class WPError(Exception):
    pass


def fetch(site):
    """Every published post, newest first."""
    posts, page = [], 1
    while True:
        try:
            r = requests.get(site.rstrip('/') + '/wp-json/wp/v2/posts', timeout=TIMEOUT,
                             params={'per_page': PER_PAGE, 'page': page, 'status': 'publish', '_embed': 1})
        except requests.RequestException as e:
            raise WPError('%s did not answer (%s).' % (site, e.__class__.__name__))
        if r.status_code != 200:
            raise WPError('%s answered %d: is it still the WordPress site?' % (site, r.status_code))
        try:
            got = r.json()
        except ValueError:
            raise WPError('%s did not answer with WordPress posts: is it still the WordPress site?' % site)
        posts += [p for p in got if isinstance(p, dict)]
        try:
            pages = int(r.headers.get('X-WP-TotalPages') or 1)
        except ValueError:
            pages = 1
        if page >= pages or not got:
            return posts
        page += 1


def _picture(url, width):
    """Our copy of a picture on the WordPress site, or None."""
    try:
        r = requests.get(html.unescape(url), timeout=TIMEOUT)
        if r.status_code != 200 or not r.content or len(r.content) > PICTURE_MAX:
            return None
        name = urlparse(r.url or url).path.rsplit('/', 1)[-1] or 'picture.jpg'
        return blog_engine.store_image(r.content, name, width)
    except (requests.RequestException, blog_engine.ImageError):
        log.warning('WordPress picture not copied: %s', url, exc_info=True)
        return None


def _copy_pictures(content):
    """The post's words with its pictures copied here (a picture that could not be copied is left out)."""
    failed = 0

    def swap(m):
        nonlocal failed
        tag = m.group(0)
        src = _SRC_RE.search(tag)
        ours = _picture(src.group(1), blog_engine.BODY_WIDTH) if src else None
        if not ours:
            failed += 1
            return ''
        tag = re.sub(r'\s(?:srcset|sizes|loading|decoding)="[^"]*"', '', tag, flags=re.I)
        return tag.replace(src.group(0), 'src="%s"' % ours)

    return _IMG_RE.sub(swap, content or ''), failed


def _when(post):
    try:
        return datetime.fromisoformat((post.get('date_gmt') or post.get('date') or '')[:19])
    except ValueError:
        return datetime.utcnow()


def _terms(post):
    """(category names, tag names) as WordPress files the post."""
    cats, tags = [], []
    for group in (post.get('_embedded') or {}).get('wp:term') or []:
        for t in group or []:
            if isinstance(t, dict) and t.get('name'):
                (cats if t.get('taxonomy') == 'category' else tags if t.get('taxonomy') == 'post_tag' else []).append(
                    html.unescape(t['name']))
    return cats, tags


def _same(title):
    return ' '.join((title or '').split()).casefold()


def bring_over(site, user):
    from app.models import Blog
    added, skipped, failed = [], [], 0
    titles = {_same(t) for (t,) in db.session.query(Blog.title)}
    for post in fetch(site):
        title = wp_blog._text((post.get('title') or {}).get('rendered'))[:300]
        slug = (post.get('slug') or '').strip()[:350]
        if not title or not slug:
            skipped.append((title or slug or '?', 'it has no title'))
            continue
        if Blog.query.filter_by(slug=slug).first():
            skipped.append((title, 'a post at this address is already on our blog'))
            continue
        if slug in old_site.OLD_POSTS or _same(title) in titles:
            skipped.append((title, 'it is already on our blog, at another address'))
            continue
        titles.add(_same(title))
        content, missing = _copy_pictures((post.get('content') or {}).get('rendered'))
        failed += missing
        seo = post.get('yoast_head_json') or {}
        summary = (seo.get('description') or seo.get('og_description')
                   or wp_blog._text((post.get('excerpt') or {}).get('rendered')))
        media = ((post.get('_embedded') or {}).get('wp:featuredmedia') or [{}])[0] or {}
        cover = _picture(media['source_url'], blog_engine.COVER_WIDTH) if media.get('source_url') else None
        if media.get('source_url') and not cover:
            failed += 1
        when = _when(post)
        p = Blog(author_id=user.id, title=title, slug=slug, content=blog_engine.sanitize(content),
                 summary=(summary or '')[:300] or None, cover_image_url=cover,
                 cover_alt=(media.get('alt_text') or '')[:300] or None,
                 is_published=True, published_at=when, created_at=when,
                 send_notification=False, notified_at=datetime.utcnow())
        cats, tags = _terms(post)
        p.terms = blog_posts.named_terms('category', cats)[0] + blog_posts.tags_from(', '.join(tags))
        db.session.add(p)
        db.session.flush()
        blog_posts.remember(p, user, NOTE)
        added.append(p)
    db.session.commit()
    return {'added': added, 'skipped': skipped, 'pictures_failed': failed}
