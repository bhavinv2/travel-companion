"""The newest posts on the WordPress site's blog (nriparentservice.com/blog), for the home page's
"Helpful Resources" cards -- so the four cards follow what is published instead of a list typed
into the page once and left to go stale.

WordPress answers its public REST API (/wp-json/wp/v2/posts) to anybody; nothing is signed in.
The answer is kept for an hour in this process. A failure is kept for five minutes (so a slow or
broken WordPress costs one page view a timeout, not every one) and answers [], which tells the
page to show the list it was built with.

    latest(n)   [{'title', 'url', 'date', 'summary', 'img', 'label'}], newest first; [] when unknown
"""
import html
import logging
import os
import re
import time
from datetime import datetime

import requests
from flask import current_app

log = logging.getLogger(__name__)

SITE_ENV = 'WP_SITE_URL'
DEFAULT_SITE = 'https://nriparentservice.com'
TIMEOUT = 3
KEEP_FOR = 3600
KEEP_FAILURE_FOR = 300
SUMMARY_MAX = 150
_cache = {}                                    # n -> (until, posts)


def _site():
    return (os.environ.get(SITE_ENV) or DEFAULT_SITE).rstrip('/')


def _text(fragment):
    """Words from a bit of WordPress HTML: tags out, entities undone, the "[...]" it adds removed."""
    t = html.unescape(re.sub(r'<[^>]+>', ' ', fragment or ''))
    t = re.sub(r'\s*\[(?:…|\.\.\.)\]\s*$', '', ' '.join(t.split()))
    return t


def _summary(text):
    if len(text) <= SUMMARY_MAX:
        return text
    return text[:SUMMARY_MAX].rsplit(' ', 1)[0].rstrip(',;:—-') + '…'


def _label(title):
    """The site files every post under one category, so the card's label names its subject."""
    return 'Travel Insurance' if 'insurance' in title.lower() else 'Parent Care'


def _image(post):
    media = ((post.get('_embedded') or {}).get('wp:featuredmedia') or [{}])[0] or {}
    sizes = (media.get('media_details') or {}).get('sizes') or {}
    for size in ('medium_large', 'large', 'medium'):
        if (sizes.get(size) or {}).get('source_url'):
            return sizes[size]['source_url']
    return media.get('source_url') or ''


def _shape(post):
    title = _text((post.get('title') or {}).get('rendered'))
    url = post.get('link') or ''
    if not title or not url.startswith(('https://', 'http://')):
        return None
    try:
        when = datetime.fromisoformat(post.get('date') or '')
        date = '%s %d, %d' % (when.strftime('%B'), when.day, when.year)
    except ValueError:
        date = ''
    return {'title': title, 'url': url, 'date': date, 'img': _image(post), 'label': _label(title),
            'summary': _summary(_text((post.get('excerpt') or {}).get('rendered')))}


def latest(n=4):
    """The newest `n` published posts, or [] (in the tests, or when WordPress does not answer)."""
    if current_app.testing:
        return []
    hit = _cache.get(n)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    try:
        r = requests.get(_site() + '/wp-json/wp/v2/posts', timeout=TIMEOUT,
                         params={'per_page': n, 'status': 'publish', '_embed': 'wp:featuredmedia'})
        r.raise_for_status()
        posts = [p for p in (_shape(x) for x in r.json() if isinstance(x, dict)) if p][:n]
        _cache[n] = (time.monotonic() + KEEP_FOR, posts)
        return posts
    except (requests.RequestException, ValueError, TypeError):
        log.warning('WordPress posts not read from %s', _site(), exc_info=True)
        _cache[n] = (time.monotonic() + KEEP_FAILURE_FOR, [])
        return []
