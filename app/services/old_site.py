"""The rest of nriparentservice.com, once the domain points at this app itself.

Until then the domain was a WordPress site, and a Cloudflare Worker sent only /travel-companions
and the front doors (/travel-insurance, /sahayak, /contact-us) here. After the switch
(deploy/DOMAIN_SWITCH.md) every address on the domain arrives here, and PrefixMiddleware marks the
ones outside the app as the "site" door. They are answered by this module:

  * WordPress's pages -- bookmarked, shared on WhatsApp and indexed by Google -- redirect,
    permanently, to where the same thing lives now: /privacy-policy/ to the privacy page, a blog
    post's /<slug>/ to that post on our blog, /blog/<slug> (Blog › Import › From WordPress brings
    them over).
  * WordPress's own machinery (/wp-admin, /wp-login.php, /xmlrpc.php ...) is gone for good: 410.
  * An address of this app written without its prefix (/login) redirects to the prefixed one, so
    the app keeps one address per page.
  * Anything else is the app's own 404.

The domain's root is the first page anybody opens: it sends them to the home page, /home. And the
domain's own pages and the blog have an address inside the app (/travel-companions/home,
/travel-companions/blog/<slug>) beside their address on the domain (/home, /blog/<slug>): the
inside one redirects out, so each has one address.

    answer()     the response for this request, or None to let the app answer it
    where(path)  the address an old WordPress path now lives at, GONE, or None
"""
from flask import Response, redirect, request

from app.services import urls

GONE = 'gone'

# The WordPress site's pages (its sitemaps, October 2026), each with the page that replaced it.
PAGES = {
    '/': 'homepage_draft.landing',                          # the root: the home page lives at /home
    '/home/': 'homepage_draft.landing',                     # WordPress's spelling, with the slash
    '/homepage-draft/': 'homepage_draft.landing',           # its address while it was a draft
    '/home-2/': 'homepage_draft.landing',
    '/elementor-hf/before-footer/': 'homepage_draft.landing',
    '/about-us/': 'homepage_draft.about',
    '/about-us-2/': 'homepage_draft.about',
    '/travel-insurance-2/': 'insurance.landing',
    '/form-travel-insurance/': 'insurance.landing',
    '/contactus/': 'main.contact_us',
    '/privacy-policy/': 'main.privacy_policy',
    '/terms-and-conditions/': 'main.terms_conditions',
    '/blog/': 'blog.blog_list',
    '/feed/': 'blog.blog_list',
}
# WordPress's archives: a list of posts, which is our blog's list now
ARCHIVES = ('author', 'page', 'feed', 'comments', 'date')
# WordPress itself, which nobody should be sent anywhere for
GONE_STARTS = ('/wp-', '/xmlrpc.php', '/wlwmanifest.xml', '/license.txt', '/readme.html')


def _query():
    return ('?' + request.query_string.decode('latin-1')) if request.query_string else ''


def where(path):
    from app.models import Blog, BlogTerm
    key = ('/' + path.strip('/') + '/').lower() if path.strip('/') else '/'
    if key.startswith(GONE_STARTS):
        return GONE
    if key.endswith('.xml/') and 'sitemap' in key:          # sitemap_index.xml, post-sitemap.xml ...
        return urls.public_url('main.sitemap_xml')
    if key in PAGES:
        return urls.public_url(PAGES[key])
    parts = [p for p in key.split('/') if p]
    if not parts:
        return None
    if parts[0] == 'blog' and len(parts) > 1:
        parts = parts[1:]                                    # /blog/<post>/, /blog/category/<x>/: the slash spelling
    if parts[0] in ('category', 'tag') and len(parts) > 1:
        term = BlogTerm.query.filter_by(kind='category' if parts[0] == 'category' else 'tag', slug=parts[1]).first()
        if term is not None and Blog.live().filter(Blog.terms.any(BlogTerm.id == term.id)).first():
            return urls.public_url('blog.blog_term', kind=term.kind, slug=term.slug)
        return urls.public_url('blog.blog_list')
    if parts[0] in ARCHIVES or parts[0].isdigit():
        return urls.public_url('blog.blog_list')
    if len(parts) == 1:
        post = Blog.live().filter(Blog.slug == parts[0]).first()
        if post is not None:
            return urls.public_url('blog.blog_post', slug=post.slug)
    return None


def answer():
    if not request.environ.get('app.direct'):
        return None
    entry = request.environ.get('app.entry')
    get = request.method in ('GET', 'HEAD')
    if entry == 'prefix':
        # the domain's own pages and /blog answer at their own address, not at their route inside the app
        if get:
            inside = request.script_root + request.path
            public = urls.to_site(inside)
            if public != inside:
                return redirect(public + _query(), 301)
        return None
    if entry == 'site-page' and request.url_rule is None and get:
        target = where(request.path)                        # /blog/ or /blog/<post>/ -- the slash spelling
        return redirect(target, 301) if target and target != GONE else None
    if entry != 'site':
        return None
    if get:
        target = where(request.path)
        if target == GONE:
            return Response('Gone.\n', status=410, mimetype='text/plain')
        if target:
            # the root is where ads and shared links land: their campaign tags (utm_*, gclid) go along
            return redirect(target + (_query() if request.path == '/' else ''), 301)
    if request.url_rule is not None:
        return redirect(request.script_root + request.path + _query(), 301 if get else 308)
    return None
