"""nriparentservice.com pointing at this app itself, with no Worker and no WordPress (deploy/DOMAIN_SWITCH.md).

    before      through the Worker (X-Forwarded-Prefix) everything is as it was: the home page is a
                draft inside the app, out of search results
    after       the domain's root is ours: it opens the home page, /home; About at /about-us, robots.txt
                and the sitemap at the root, www sent to the bare address
    old site    WordPress's addresses redirect to where the same thing lives now; its machinery is gone
    the app     an app address written without the prefix moves inside it: one address per page
    the posts   Blog › Import › From WordPress copies the old blog's posts, once
    legal       WordPress's privacy policy and terms, ours now, at the same addresses
"""
import io
import json
import re
from datetime import datetime, timedelta

import pytest

from app import create_app, db as _db
from app.models import Blog
from conftest import login, make_user

PREFIX = '/travel-companions'
SITE = 'https://nriparentservice.com'
WORKER = {'X-Forwarded-Prefix': PREFIX}


@pytest.fixture()
def dapp(tmp_path):
    """The app as Railway runs it in production: a prefix and the public host configured."""
    app = create_app({
        'TESTING': True,
        'WTF_CSRF_ENABLED': False,
        'SQLALCHEMY_DATABASE_URI': 'sqlite://',
        'UPLOAD_FOLDER': str(tmp_path / 'uploads'),
        'PRIVATE_UPLOAD_FOLDER': str(tmp_path / 'private'),
        'MAIL_PASSWORD': None,
        'APP_URL_PREFIX': PREFIX,
        'APP_PUBLIC_HOST': 'nriparentservice.com',
    })
    with app.app_context():
        _db.create_all()
        from app.services import settings as _settings
        _settings.clear_cache()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def dc(dapp):
    return dapp.test_client()


def get(c, path, site=SITE, **kw):
    return c.get(path, base_url=site, **kw)


def links(r):
    return json.loads(re.search(r'window\.__HOMEPAGE__ = (\{.*?\});\n', r.get_data(as_text=True), re.S).group(1))


def post(slug, live=True, title='A post'):
    author = make_user('writer-%s@test.com' % slug, 'writer-%s' % slug)
    p = Blog(author_id=author.id, title=title, slug=slug, content='<p>Words.</p>', is_published=live,
             published_at=datetime.utcnow() - timedelta(days=1))
    _db.session.add(p)
    _db.session.commit()
    return p


# ------------------------------------------------------------------------------------------- before

def test_through_the_worker_the_home_page_is_still_a_draft(dc):
    r = get(dc, '/home', headers=WORKER)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'noindex' in html and 'rel="canonical"' not in html
    assert links(r)['homeUrl'] == PREFIX + '/home'                    # / is still WordPress's
    assert links(r)['aboutUrl'] == PREFIX + '/about-us'


def test_the_railway_address_is_left_alone(dc):
    r = get(dc, '/', site='https://travel-companion-production-261c.up.railway.app')
    assert r.status_code == 200 and '__HOMEPAGE__' not in r.get_data(as_text=True)


# -------------------------------------------------------------------------------------------- after

def test_the_domain_opens_on_the_home_page_at_home(dc):
    r = get(dc, '/?utm_source=whatsapp')                                  # the first page anybody opens
    assert r.status_code == 301 and r.headers['Location'] == '/home?utm_source=whatsapp'
    r = get(dc, '/home')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'noindex' not in html and '<link rel="canonical" href="https://nriparentservice.com/home"/>' in html
    d = links(r)
    assert d['page'] == 'home' and d['homeUrl'] == '/home' and d['aboutUrl'] == '/about-us'
    assert d['insuranceUrl'] == '/travel-insurance' and d['companionUrl'] == PREFIX + '/'
    assert 'href="%s/static/' % PREFIX in html                         # its files still come from inside the app


def test_the_about_page_answers_at_its_own_address(dc):
    r = get(dc, '/about-us')
    assert r.status_code == 200 and links(r)['page'] == 'about' and 'noindex' not in r.get_data(as_text=True)
    r = get(dc, '/about-us/')                                           # WordPress's spelling
    assert r.status_code == 301 and r.headers['Location'] == '/about-us'


def test_their_addresses_inside_the_app_move_out(dc):
    r = get(dc, PREFIX + '/home?x=1')
    assert r.status_code == 301 and r.headers['Location'] == '/home?x=1'
    assert get(dc, PREFIX + '/about-us').headers['Location'] == '/about-us'


def test_the_draft_address_and_the_slash_spelling_reach_home(dc):
    for old in (PREFIX + '/homepage-draft', '/homepage-draft', '/home/'):
        r = get(dc, old)
        assert r.status_code == 301 and r.headers['Location'] == '/home', old
    r = get(dc, '/homepage-draft', headers=WORKER)                        # before the switch: inside the app
    assert r.status_code == 301 and r.headers['Location'] == PREFIX + '/home'


def test_the_logo_goes_home(dc):
    html = get(dc, '/about-us').get_data(as_text=True)
    assert re.search(r'<a href="/home" class="nav-logo">', html)
    html = get(dc, '/about', headers=WORKER).get_data(as_text=True)      # before the switch: the app's first page
    assert re.search(r'<a href="%s/" class="nav-logo">' % PREFIX, html)
    html = get(dc, PREFIX + '/').get_data(as_text=True)                  # the companion page's own header
    assert '<a class="logo" href="/home" aria-label="NRI Parent Service home">' in html
    html = get(dc, '/', headers=WORKER).get_data(as_text=True)
    assert '<a class="logo" href="#top" aria-label="NRI Parent Service home">' in html


def test_www_goes_to_the_bare_address(dc):
    r = get(dc, '/travel-insurance?utm_source=x', site='https://www.nriparentservice.com')
    assert r.status_code == 301
    assert r.headers['Location'] == 'https://nriparentservice.com/travel-insurance?utm_source=x'


def test_the_tidying_the_worker_did(dc):
    assert get(dc, PREFIX).headers['Location'] == PREFIX + '/'
    r = get(dc, '/travel-insurance/')
    assert r.status_code == 301 and r.headers['Location'] == '/travel-insurance'
    assert get(dc, '/travel-insurance').status_code == 200
    assert get(dc, PREFIX + '/auth/login').status_code == 200


def test_a_forged_prefix_header_is_not_believed(dc):
    r = get(dc, '/home', headers={'X-Forwarded-Prefix': '/elsewhere'})
    assert r.status_code == 200 and '/elsewhere' not in r.get_data(as_text=True)


def test_robots_and_the_sitemap_at_the_root(dc):
    body = get(dc, '/robots.txt').get_data(as_text=True)
    assert 'Disallow: %s/admin/' % PREFIX in body and 'Disallow: /admin/' not in body
    assert 'Sitemap: https://nriparentservice.com/sitemap.xml' in body
    xml = get(dc, '/sitemap.xml').get_data(as_text=True)
    assert '<loc>https://nriparentservice.com/home</loc>' in xml
    assert '<loc>https://nriparentservice.com/about-us</loc>' in xml
    assert '<loc>https://nriparentservice.com/travel-insurance</loc>' in xml
    assert 'about-us' not in get(dc, '/sitemap.xml', headers=WORKER).get_data(as_text=True)


def test_the_home_page_shows_our_newest_posts(dc):
    post('older')
    newest = post('parents-alone', title='Supporting parents living alone')
    newest.summary = 'What helps most when parents live alone in India.'
    _db.session.commit()
    cards = links(get(dc, '/home'))['posts']
    assert [c['url'] for c in cards] == ['/blog/parents-alone', '/blog/older']
    assert cards[0]['summary'] == 'What helps most when parents live alone in India.'


# --------------------------------------------------------------------------------------------- blog

def test_the_blog_lives_at_blog_and_nowhere_else(dc):
    p = post('parents-alone', title='Supporting parents living alone')
    from app.models import BlogTerm
    term = BlogTerm(kind='category', name='Care at home', slug='care-at-home')
    _db.session.add(term)
    p.terms.append(term)
    _db.session.commit()
    for path in ('/blog', '/blog/parents-alone', '/blog/category/care-at-home'):
        assert get(dc, path).status_code == 200, path
    html = get(dc, '/blog').get_data(as_text=True)
    assert 'href="/blog/parents-alone"' in html and PREFIX + '/blog' not in html
    html = get(dc, '/blog/parents-alone').get_data(as_text=True)
    assert '<link rel="canonical" href="https://nriparentservice.com/blog/parents-alone"/>' in html
    assert '<meta property="og:url" content="https://nriparentservice.com/blog/parents-alone"/>' in html
    assert PREFIX + '/blog' not in html
    xml = get(dc, '/sitemap.xml').get_data(as_text=True)
    assert '<loc>https://nriparentservice.com/blog</loc>' in xml
    assert '<loc>https://nriparentservice.com/blog/parents-alone</loc>' in xml
    assert '<loc>https://nriparentservice.com/blog/category/care-at-home</loc>' in xml
    assert PREFIX + '/blog' not in xml
    assert links(get(dc, '/home'))['blogUrl'] == '/blog'


def test_the_long_blog_addresses_move_to_blog(dc):
    post('parents-alone')
    for old, new in ((PREFIX + '/blog', '/blog'), (PREFIX + '/blog/parents-alone?utm_source=x', '/blog/parents-alone?utm_source=x'),
                     ('/blog/parents-alone/', '/blog/parents-alone'), (PREFIX + '/blog?page=2', '/blog?page=2')):
        r = get(dc, old)
        assert r.status_code == 301 and r.headers['Location'] == new, old


def test_before_the_switch_the_blog_stays_inside_the_app(dc):
    post('parents-alone')
    r = get(dc, '/blog', headers=WORKER)
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and 'href="%s/blog/parents-alone"' % PREFIX in html   # /blog is WordPress's until then
    r = get(dc, '/blog', site='https://travel-companion-production-261c.up.railway.app')
    assert r.status_code == 200 and 'href="/blog/parents-alone"' in r.get_data(as_text=True)


def test_the_new_post_mail_and_bell_say_blog(dc):
    from app.models import Notification
    from app.services import mailer
    p = post('parents-alone')
    fan = make_user('fan@test.com', 'fan')
    fan.marketing_consent = True
    _db.session.commit()
    mailer.OUTBOX.clear()
    dc.application.config['SENDGRID_API_KEY'] = 'SG.test'          # announcements go out through SendGrid only
    with dc.application.test_request_context('/', base_url=SITE):
        from flask import request
        request.environ['app.direct'] = True
        from app.routes.admin import _notify_all_blog
        _notify_all_blog(p)
    sent = [m for m in mailer.OUTBOX if m['recipients'] == ['fan@test.com']]
    assert sent and 'blog/parents-alone' in sent[0]['body'] and PREFIX + '/blog' not in sent[0]['body']
    n = Notification.query.filter_by(user_id=fan.id, type='blog').first()
    assert n.link == '/blog/parents-alone'


# -------------------------------------------------------------------------------------------- legal

def test_the_privacy_policy_and_terms_answer_at_their_wordpress_addresses(dc):
    r = get(dc, '/privacy-policy')
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and '2. Information We Collect' in html and '15. Contact Us' in html
    assert '<link rel="canonical" href="https://nriparentservice.com/privacy-policy"/>' in html and 'noindex' not in html
    assert 'href="%s/privacy"' % PREFIX in html                             # the community's own notice
    r = get(dc, '/terms-and-conditions')
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and '8. Travel Companion Services' in html and '24. Acceptance of Terms' in html
    assert '<a href="/privacy-policy">Privacy Policy</a>' in html
    assert get(dc, PREFIX + '/privacy-policy').headers['Location'] == '/privacy-policy'


def test_their_contact_section_is_what_admin_publishes(dc):
    from app.services import offices
    html = get(dc, '/privacy-policy').get_data(as_text=True)
    assert '+91 80191 11360' in html and '2512 Carpenter Rd' in html
    offices.save_numbers([{'label': 'India', 'iso': 'IN', 'number': '+91 90000 00001', 'sites': ['contact']}])
    _db.session.commit()
    html = get(dc, '/terms-and-conditions').get_data(as_text=True)
    assert '+91 90000 00001' in html and '+91 80191 11360' not in html


def test_through_the_worker_they_are_copies_out_of_search(dc):
    html = get(dc, '/privacy-policy', headers=WORKER).get_data(as_text=True)
    assert 'noindex' in html and 'rel="canonical"' not in html


def test_every_page_links_to_them(dc):
    html = get(dc, PREFIX + '/about').get_data(as_text=True)                       # the shared footer
    assert 'href="/privacy-policy"' in html and 'href="/terms-and-conditions"' in html
    html = get(dc, '/about', headers=WORKER).get_data(as_text=True)                 # before the switch
    assert 'href="%s/privacy-policy"' % PREFIX in html
    data = get(dc, '/travel-insurance').get_data(as_text=True)                      # the quote form's consent
    assert '"privacyUrl": "/privacy-policy"' in data and '"termsUrl": "/terms-and-conditions"' in data
    xml = get(dc, '/sitemap.xml').get_data(as_text=True)
    assert '<loc>https://nriparentservice.com/privacy-policy</loc>' in xml


# ----------------------------------------------------------------------------------------- old site

@pytest.mark.parametrize('old, new', [
    ('/privacy-policy/', '/privacy-policy'),
    ('/terms-and-conditions/', '/terms-and-conditions'),
    ('/contactus/', '/contact-us'),
    ('/form-travel-insurance/', '/travel-insurance'),
    ('/travel-insurance-2/', '/travel-insurance'),
    ('/home-2/', '/home'),
    ('/about-us-2/', '/about-us'),
    ('/blog/', '/blog'),
    ('/category/blog/', '/blog'),
    ('/feed/', '/blog'),
    ('/2026/10/', '/blog'),
    ('/sitemap_index.xml', '/sitemap.xml'),
    ('/post-sitemap.xml', '/sitemap.xml'),
])
def test_wordpress_pages_redirect_to_their_new_homes(dc, old, new):
    r = get(dc, old)
    assert r.status_code == 301, old
    assert r.headers['Location'] == new


def test_a_wordpress_post_redirects_to_it_on_our_blog(dc):
    post('parents-alone')
    post('not-yet', live=False)
    r = get(dc, '/parents-alone/?utm_source=whatsapp')
    assert r.status_code == 301 and r.headers['Location'] == '/blog/parents-alone'
    assert get(dc, '/not-yet/').status_code == 404                      # a draft is nobody's address yet
    assert get(dc, '/never-was/').status_code == 404


def test_a_wordpress_post_copied_here_under_another_slug_redirects_to_that(dc):
    """Five posts were copied by hand before the switch and got a different slug (…-2, here-s …):
    old_site.OLD_POSTS pairs each old address with ours."""
    old, ours = 'how-to-buy-travel-insurance-for-parents-visiting-the-usa', 'how-to-buy-travel-insurance-for-parents-visiting-the-usa-2'
    assert get(dc, '/%s/' % old).status_code == 404                     # nothing here yet
    post(ours)
    for path in ('/%s/' % old, '/%s' % old, '/blog/%s/' % old):
        r = get(dc, path)
        assert r.status_code == 301 and r.headers['Location'] == '/blog/' + ours, path
    post(old)                                                          # the same slug goes live here: it wins
    assert get(dc, '/%s/' % old).headers['Location'] == '/blog/' + old


@pytest.mark.parametrize('path', ['/wp-login.php', '/wp-admin/', '/wp-content/uploads/2026/10/a.jpg',
                                  '/xmlrpc.php', '/wp-json/wp/v2/posts'])
def test_wordpress_itself_is_gone(dc, path):
    assert get(dc, path).status_code == 410


def test_an_app_address_without_its_prefix_moves_inside(dc):
    r = get(dc, '/auth/login?next=/x')
    assert r.status_code == 301 and r.headers['Location'] == PREFIX + '/auth/login?next=/x'
    r = dc.post('/auth/login', base_url=SITE, data={'email': 'a@b.c'})
    assert r.status_code == 308 and r.headers['Location'] == PREFIX + '/auth/login'


def test_nothing_changes_through_the_worker(dc):
    """Until the switch, / through the Worker is the companion app's own landing, as it always was."""
    r = get(dc, '/', headers=WORKER)
    assert r.status_code == 200 and '__HOMEPAGE__' not in r.get_data(as_text=True)
    assert get(dc, '/privacy-policy/', headers=WORKER).status_code == 404


# ---------------------------------------------------------------------------------------- the posts

def _png():
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (40, 30), (200, 80, 40)).save(out, 'PNG')
    return out.getvalue()


WP_POSTS = [
    {'id': 7313, 'slug': 'how-to-buy-travel-insurance', 'date': '2026-10-09T10:33:43', 'date_gmt': '2026-10-09T05:03:43',
     'title': {'rendered': 'How to Buy Travel Insurance for Parents &#8211; USA'},
     'content': {'rendered': '<h2>Why</h2><p>Words <a href="https://nriparentservice.com/travel-insurance">here</a>.</p>'
                             '<p><img loading="lazy" src="https://nriparentservice.com/wp-content/uploads/body.png" '
                             'srcset="https://nriparentservice.com/wp-content/uploads/body-300.png 300w" alt="A chart"/></p>'
                             '<script>alert(1)</script>'},
     'excerpt': {'rendered': '<p>The excerpt [&hellip;]</p>'},
     'yoast_head_json': {'description': 'What Google showed for it.'},
     '_embedded': {'wp:featuredmedia': [{'source_url': 'https://nriparentservice.com/wp-content/uploads/cover.png',
                                         'alt_text': 'Parents at an airport'}],
                   'wp:term': [[{'taxonomy': 'category', 'name': 'Blog'}], [{'taxonomy': 'post_tag', 'name': 'USA'}]]}},
    {'id': 7302, 'slug': 'parents-living-alone', 'date_gmt': '2026-10-06T08:15:42',
     'title': {'rendered': 'Supporting Parents Living Alone'}, 'content': {'rendered': '<p>Hello.</p>'},
     'excerpt': {'rendered': '<p>Short.</p>'}},
]


class Answer:
    def __init__(self, status=200, body=None, content=b'', url=''):
        self.status_code, self.body, self.content, self.url = status, body, content, url
        self.headers = {'X-WP-TotalPages': '1'}

    def json(self):
        if self.body is None:
            raise ValueError('not json')
        return self.body


def _wordpress(monkeypatch, posts=WP_POSTS, status=200):
    from app.services import wp_import
    asked = []

    def fake(url, **kw):
        asked.append(url)
        if '/wp-json/' in url:
            return Answer(status, posts if status == 200 else None)
        return Answer(content=_png(), url=url)
    monkeypatch.setattr(wp_import.requests, 'get', fake)
    return asked


def test_the_wordpress_posts_are_brought_over_once(app, client, admin_user, monkeypatch):
    asked = _wordpress(monkeypatch)
    login(client, 'admin@test.com')
    r = client.post('/admin/blog/import/wordpress')
    assert r.status_code == 302
    p = Blog.query.filter_by(slug='how-to-buy-travel-insurance').one()
    assert p.title == 'How to Buy Travel Insurance for Parents – USA'
    assert p in Blog.live().all() and p.published_at == datetime(2026, 10, 9, 5, 3, 43)
    assert p.summary == 'What Google showed for it.' and p.cover_alt == 'Parents at an airport'
    assert p.cover_image_url and 'nriparentservice.com' not in p.cover_image_url      # a copy, not a link
    assert 'wp-content' not in p.content and 'srcset' not in p.content and '<script' not in p.content
    assert '<img' in p.content and 'alt="A chart"' in p.content
    assert [t.name for t in p.tags] == ['USA'] and p.categories == []                 # no "Blog" section here
    assert p.notified_at is not None and not p.send_notification                       # nobody told: old posts
    assert p.revisions.count() == 1
    assert Blog.query.filter_by(slug='parents-living-alone').one().summary == 'Short.'
    assert asked[0] == 'https://nriparentservice.com/wp-json/wp/v2/posts'

    client.post('/admin/blog/import/wordpress')                                        # twice: nothing twice
    assert Blog.query.count() == 2


def test_posts_already_here_under_another_address_are_not_brought_over(app, client, admin_user, monkeypatch):
    """The posts copied by hand before the switch: a different slug, the same title, or a slug in OLD_POSTS."""
    from app.services import old_site
    here = Blog(author_id=admin_user.id, title='Supporting  parents living alone', slug='parents-alone-here',
                content='<p>Here.</p>', is_published=True, published_at=datetime.utcnow())
    _db.session.add(here)
    _db.session.commit()
    renamed = dict(WP_POSTS[0], slug=next(iter(old_site.OLD_POSTS)))                  # known under another slug
    _wordpress(monkeypatch, [renamed, WP_POSTS[1]])                                    # [1]: the same title as `here`
    login(client, 'admin@test.com')
    r = client.post('/admin/blog/import/wordpress', follow_redirects=True)
    assert '0 posts brought over from WordPress and published. 2 already here, left alone.' in r.get_data(as_text=True)
    assert Blog.query.count() == 1


def test_nothing_is_brought_over_when_wordpress_is_gone(app, client, admin_user, monkeypatch):
    _wordpress(monkeypatch, status=410)
    login(client, 'admin@test.com')
    r = client.post('/admin/blog/import/wordpress', follow_redirects=True)
    assert 'Nothing was brought over' in r.get_data(as_text=True)
    assert Blog.query.count() == 0


def test_only_an_administrator_brings_them_over(app, client, cs_user, monkeypatch):
    _wordpress(monkeypatch)
    login(client, 'cs@test.com')
    client.post('/admin/blog/import/wordpress')
    assert Blog.query.count() == 0
