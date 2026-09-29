"""What WhatsApp, Facebook and X show when somebody shares a link.

The travel-insurance page previewed as a bare logo because it had no Open Graph tags at all --
every page built on base.html had none. The fix is easy to half-do, so what is protected here is
the part that fails silently: an image too big for WhatsApp's fetcher, dimensions that do not
match the file, or a preview describing a different page from the one it opens.
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARE_DIR = os.path.join(ROOT, 'app', 'static', 'img', 'share')

# WhatsApp's link-preview fetcher skips images past roughly 300KB. The budget is under that
# rather than at it, because a preview that works on the day and stops working after somebody
# re-exports the image is worse than one that never worked.
BUDGET_KB = 280


def meta(html, key):
    m = re.search(r'<meta (?:property|name)="%s" content="([^"]*)"' % re.escape(key), html)
    return m.group(1) if m else None


def test_the_insurance_page_offers_an_image(client, db):
    """It had none, so the preview fell back to the site icon -- a logo where the hero should be."""
    html = client.get('/travel-insurance').data.decode()
    assert meta(html, 'og:image'), 'no og:image'
    assert meta(html, 'twitter:card') == 'summary_large_image'
    assert 'img/share/travel-insurance.jpg' in meta(html, 'og:image')


def test_the_image_is_small_enough_to_be_fetched(client, db):
    """The crux. The hero itself is 341KB, past what WhatsApp will take -- pointing the tag at it
    would be a tag that quietly does nothing, which is indistinguishable from having no tag."""
    path = os.path.join(SHARE_DIR, 'travel-insurance.jpg')
    assert os.path.isfile(path), 'the share crop is missing'
    kb = os.path.getsize(path) // 1024
    assert kb <= BUDGET_KB, 'share image is %dKB, past what WhatsApp will fetch' % kb


def test_the_declared_size_is_the_real_size(client, db):
    """Scrapers that trust the numbers reserve the wrong box; some skip the image outright."""
    pytest.importorskip('PIL')
    from PIL import Image
    html = client.get('/travel-insurance').data.decode()
    with Image.open(os.path.join(SHARE_DIR, 'travel-insurance.jpg')) as im:
        width, height = im.size
    assert (str(width), str(height)) == (meta(html, 'og:image:width'), meta(html, 'og:image:height'))
    assert (width, height) == (1200, 630), 'the ratio every scraper crops to'


def test_the_image_is_actually_served(client, db):
    html = client.get('/travel-insurance').data.decode()
    path = meta(html, 'og:image').split('://', 1)[-1].split('/', 1)[1]
    r = client.get('/' + path)
    assert r.status_code == 200
    assert r.headers['Content-Type'].startswith('image/')


def test_the_preview_describes_the_page_it_opens(client, db):
    """Title and description come from the page's own blocks, so the two cannot drift."""
    html = client.get('/travel-insurance').data.decode()
    title = re.search(r'<title>(.*?)</title>', html, re.S).group(1)
    desc = re.search(r'<meta name="description" content="([^"]*)"', html).group(1)
    assert meta(html, 'og:title') == title
    assert meta(html, 'og:description') == desc
    assert meta(html, 'twitter:title') == title


def test_the_preview_links_to_the_canonical_address(client, db):
    """Not the prefixed spelling: a shared link should open the address the page calls its own."""
    html = client.get('/travel-insurance').data.decode()
    canonical = re.search(r'<link rel="canonical" href="([^"]+)"', html).group(1)
    assert meta(html, 'og:url') == canonical


def test_the_image_url_is_absolute(client, db):
    """A relative og:image is fetched by nobody."""
    html = client.get('/travel-insurance').data.decode()
    assert re.match(r'https?://', meta(html, 'og:image'))
    assert meta(html, 'og:image:secure_url') == meta(html, 'og:image')


# ---------------------------------------------------------------------------
# The rest of the site
# ---------------------------------------------------------------------------

def test_a_page_with_no_image_says_so(client, db):
    """A large card with a hole in it looks broken; a small one does not. Sahayak's page has no
    photograph on it at all, so there is nothing honest to put here yet."""
    html = client.get('/sahayak').data.decode()
    assert meta(html, 'og:title'), 'it should still have a title and a description'
    assert meta(html, 'og:image') is None
    assert meta(html, 'twitter:card') == 'summary'


def test_the_companion_landing_still_has_its_own(client, db):
    """It is a standalone template with its own head, and its preview already worked."""
    html = client.get('/').data.decode()
    assert meta(html, 'og:image')
    assert meta(html, 'twitter:card') == 'summary_large_image'
