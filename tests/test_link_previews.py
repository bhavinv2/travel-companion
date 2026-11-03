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

PUBLIC = {'/home': 'home.jpg', '/about-us': 'about.jpg', '/contact-us': 'home.jpg', '/privacy-policy': 'home.jpg',
          '/terms-and-conditions': 'home.jpg', '/sahayak': 'sahayak.jpg', '/blog': 'blog.jpg',
          '/reviews': 'companion.jpg', '/about': 'companion.jpg', '/help': 'home.jpg'}


def test_every_public_page_offers_its_sections_picture(client, db):
    """The home page previewed as a bare logo: it named no picture, and WhatsApp then shows the site's icon. Every
    public page now names one -- its own, or its section's (services/share_pics.py)."""
    for path, picture in PUBLIC.items():
        r = client.get(path, follow_redirects=True)
        assert r.status_code == 200, path
        html = r.data.decode()
        assert re.match(r'https?://', meta(html, 'og:image') or ''), path
        assert 'img/share/' + picture in meta(html, 'og:image'), (path, meta(html, 'og:image'))
        assert meta(html, 'twitter:card') == 'summary_large_image', path
        assert meta(html, 'twitter:image') == meta(html, 'og:image'), path


def test_every_share_picture_is_fetchable_and_the_declared_size(client, db):
    pytest.importorskip('PIL')
    from PIL import Image
    from app.services import share_pics
    for rel in share_pics.PICTURES.values():
        path = os.path.join(ROOT, 'app', 'static', rel)
        assert os.path.getsize(path) // 1024 <= BUDGET_KB, rel
        with Image.open(path) as im:
            assert im.size == (1200, 630), rel
            assert im.format == 'JPEG', rel                              # base.html says image/jpeg


def test_staff_pages_send_none(client, db, cs_user):
    from conftest import login
    login(client, cs_user.email)
    html = client.get('/cs/crm/today').data.decode()
    assert meta(html, 'og:image') is None


def test_a_post_whose_picture_is_gone_shows_the_blogs(app, client, db, admin_user):
    """Uploads on the server's own disk are lost on a deploy: every post on the live site pointed its preview at a
    picture that answered 404. A missing or too big picture gives way to the blog's own; one that is there is used."""
    from datetime import datetime, timedelta
    from app.models import Blog
    then = datetime.utcnow() - timedelta(hours=1)
    folder = os.path.abspath(app.config['UPLOAD_FOLDER'])
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, 'share-test-small.jpg'), 'wb') as f:
        f.write(b'\xff\xd8' + b'0' * 2000)
    gone = Blog(author_id=admin_user.id, title='Gone picture', slug='gone-picture', content='<p>Hi</p>', is_published=True,
                published_at=then, cover_image_url='/static/uploads/not-here.jpg')
    there = Blog(author_id=admin_user.id, title='Has picture', slug='has-picture', content='<p>Hi</p>', is_published=True,
                 published_at=then, cover_image_url='/static/uploads/not-here.jpg',
                 thumb_url='/static/uploads/share-test-small.jpg')
    db.session.add_all([gone, there])
    db.session.commit()
    html = client.get('/blog/gone-picture').data.decode()
    assert 'img/share/blog.jpg' in meta(html, 'og:image')
    html = client.get('/blog/has-picture').data.decode()
    assert meta(html, 'og:image').split('?')[0].endswith('/static/uploads/share-test-small.jpg')


def test_the_companion_landing_still_has_its_own(client, db):
    """It is a standalone template with its own head, and its preview already worked."""
    html = client.get('/').data.decode()
    assert meta(html, 'og:image')
    assert meta(html, 'twitter:card') == 'summary_large_image'
