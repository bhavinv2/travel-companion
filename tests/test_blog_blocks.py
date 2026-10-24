"""The blocks of a blog post beyond text, and how readers get the blog: columns, a picture beside text, carousels
and sliders, YouTube and Vimeo that play in the post, an uploaded video, the post's own HTML / CSS / JS in a
sandboxed frame, space; each block's looks (space, padding, background, width, alignment), link looks, the
post's layout, and Order on the blog. services/blog_engine.py (sanitize, embed_of), services/blog_posts.py
(layout, order), routes/admin_blog.py (blog_video, blog_order), routes/blog.py."""
import io
import json
import re
from datetime import datetime, timedelta

from conftest import login, logout
from app import db as _db
from app.models import Blog, BlogPattern, User
from app.services import blog_engine as be
from app.services import blog_posts as bp

BLOCKS = ('<div class="blog-cols sp-t3 bg-soft evil" data-cols="2" onclick="x()"><div class="blog-col"><h3>A</h3>'
          '<p>One</p></div><div class="blog-col"><p>Two</p></div></div>'
          '<div class="blog-cols" data-cols="99"><div class="blog-col"><p>x</p></div></div>'
          '<figure class="blog-embed wd-wide" data-provider="youtube" data-vid="dQw4w9WgXcQ" data-start="42">'
          '<bs-live><img src="https://img.youtube.com/x.jpg"></bs-live><figcaption>Cap</figcaption></figure>'
          '<figure class="blog-embed" data-provider="youtube" data-vid="bad id!"></figure>'
          '<figure class="blog-video"><video src="/static/uploads/a.mp4" poster="javascript:alert(1)" autoplay></video></figure>'
          '<div class="blog-code" data-h="auto" data-title="Map"><pre>&lt;b id="x"&gt;hi&lt;/b&gt;&lt;script&gt;'
          'document.cookie&lt;/script&gt;</pre></div>'
          '<div class="blog-spacer" data-h="96"></div>'
          '<div class="blog-carousel" data-show="2" data-interval="5"><div class="blog-slide"><h3>C1</h3></div>'
          '<figure class="blog-slide"><img src="/static/uploads/p.jpg" alt="p"></figure></div>'
          '<div class="blog-mt" data-pos="right" data-ratio="40"><figure class="blog-mt-media">'
          '<img src="/static/uploads/p.jpg" alt="p"></figure><div class="blog-mt-body"><p>Beside</p></div></div>'
          '<p>A <a href="/x" class="lk-arrow evil" target="_blank">link</a> and '
          '<a href="javascript:alert(1)" class="lk-btn">bad</a></p>'
          '<script>alert(2)</script><p class="pd-2 ta-center sp-b9">Styled</p>')


def make(title, published=True, days_ago=1, **kw):
    p = Blog(author_id=User.query.first().id, title=title, slug=be.unique_slug(title.lower().replace(' ', '-')),
             content=kw.pop('content', '<p>Words about %s.</p>' % title), is_published=published,
             published_at=datetime.utcnow() - timedelta(days=days_ago) if published else None, **kw)
    _db.session.add(p)
    _db.session.commit()
    return p


# ============================================================================== the blocks, as saved

def test_youtube_and_vimeo_links_are_read_with_their_start():
    assert be.embed_of('https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1m30s') == ('youtube', 'dQw4w9WgXcQ', 90)
    assert be.embed_of('https://youtu.be/dQw4w9WgXcQ?t=42') == ('youtube', 'dQw4w9WgXcQ', 42)
    assert be.embed_of('https://youtube.com/shorts/abcdefghijk') == ('youtube', 'abcdefghijk', 0)
    assert be.embed_of('https://vimeo.com/76979871') == ('vimeo', '76979871', 0)
    assert be.embed_of('https://player.vimeo.com/video/76979871#t=2m') == ('vimeo', '76979871', 120)
    for no in ('https://example.com/watch?v=dQw4w9WgXcQ', 'javascript:alert(1)', '', None):
        assert be.embed_of(no) is None


def test_the_blocks_keep_what_they_are_and_lose_anything_else(app):
    with app.test_request_context():
        html = be.for_editor(BLOCKS)
    # columns, with their looks; an unknown class, a handler and a wrong count are dropped
    assert '<div class="blog-cols sp-t3 bg-soft" data-cols="2"><div class="blog-col"><h3>A</h3>' in html
    assert 'evil' not in html and 'onclick' not in html and 'data-cols="99"' not in html
    # YouTube: the video and its start; the editor's preview is never kept; a wrong id is
    assert 'data-vid="dQw4w9WgXcQ" data-start="42"' in html and 'bs-live' not in html and 'img.youtube' not in html
    assert 'bad id' not in html
    # a video plays with the browser's controls, never by itself; no script for a poster
    assert '<video src="/static/uploads/a.mp4" controls="controls" playsinline="playsinline" preload="metadata">' in html
    assert 'autoplay' not in html and 'javascript' not in html
    # the post's own code is kept as text, to run apart from the site
    assert '<div class="blog-code" data-h="auto" data-title="Map"><pre>&lt;b id=&quot;x&quot;&gt;hi' in html \
        or '<div class="blog-code" data-h="auto" data-title="Map"><pre>&lt;b id="x"&gt;hi' in html
    assert 'data-h="96"' in html and 'data-show="2"' in html and 'data-interval="5"' in html
    assert '<div class="blog-mt" data-pos="right" data-ratio="40"><figure class="blog-mt-media">' in html
    # links: a look and a new tab (safely); a script link loses its address
    assert '<a href="/x" target="_blank" class="lk-arrow" rel="noopener noreferrer">link</a>' in html
    assert 'lk-btn' not in html and '>bad<' not in html
    # a script outside a code block is dropped; a look that is not one of ours is too
    assert 'alert(2)' not in html and '<p class="pd-2 ta-center">Styled</p>' in html


def test_readers_get_players_and_the_code_in_a_sandbox(app):
    with app.test_request_context():
        html = be.render(BLOCKS)
    yt = re.search(r'<iframe src="https://www\.youtube-nocookie\.com/embed/dQw4w9WgXcQ\?rel=0&amp;start=42"[^>]*>', html)
    assert yt and 'allowfullscreen' in yt.group(0) and 'loading="lazy"' in yt.group(0)
    assert ('<a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ&amp;t=42s" target="_blank" '
            'rel="noopener noreferrer">Watch on YouTube') in html
    frame = re.search(r'<iframe class="blog-code-frame" sandbox="([^"]*)" srcdoc="([^"]*)"', html)
    assert frame, html
    assert 'allow-scripts' in frame.group(1) and 'allow-same-origin' not in frame.group(1)
    assert '&lt;b id=&quot;x&quot;&gt;hi' in frame.group(2) and 'blogFrame' in frame.group(2)
    assert 'title="Map"' in html and 'data-auto="1"' in html
    # the words of a post are not its code
    with app.test_request_context():
        words = be.plain_text(be.for_editor(BLOCKS))
    assert 'cookie' not in words and 'Beside' in words


# ============================================================================== layout

def test_the_layout_keeps_only_what_differs_from_the_standard():
    assert bp.clean_layout({'layout_width': 'wide', 'layout_size': 'm', 'layout_spacing': 'airy'}) == \
        {'width': 'wide', 'spacing': 'airy'}
    assert bp.clean_layout({'layout_width': 'normal'}) is None
    assert bp.clean_layout({'layout_width': 'huge', 'layout_size': '<script>'}) is None
    assert bp.layout_classes({'width': 'wide', 'spacing': 'airy'}) == 'lay-w-wide lay-sp-airy'
    assert bp.layout_classes({'width': 'evil'}) == '' and bp.layout_classes(None) == ''


def test_the_editor_saves_the_layout_and_readers_get_it(client, admin_user):
    login(client, 'admin@test.com')
    p = make('Layout post', content='<p>Some words for the layout.</p>')
    html = client.get('/admin/blog/%d/edit' % p.id).data.decode()
    assert 'name="layout_width"' in html and 'data-lay="spacing"' in html
    data = {'title': p.title, 'slug': p.slug, 'summary': 'A post to try the layout of the blog on, with enough words.',
            'content': p.content, 'cover_image_url': '', 'cover_alt': '', 'send_notification_shown': '1',
            'settings_shown': '1', 'action': 'save', 'tags': '', 'publish_at': '',
            'layout_width': 'wide', 'layout_size': 'l', 'layout_spacing': 'normal'}
    client.post('/admin/blog/%d/edit' % p.id, data=data)
    _db.session.refresh(p)
    assert p.layout == {'width': 'wide', 'size': 'l'}
    page = client.get('/blog/' + p.slug).data.decode()
    assert 'lay-w-wide lay-s-l' in page and 'blog-blocks.css' in page
    # back to the standard: nothing kept
    client.post('/admin/blog/%d/edit' % p.id, data=dict(data, layout_width='normal', layout_size='m'))
    _db.session.refresh(p)
    assert p.layout is None


# ============================================================================== video

def test_a_video_is_uploaded_only_when_it_is_one(client, admin_user, app):
    login(client, 'admin@test.com')

    def up(name, body):
        return client.post('/admin/blog/video', data={'file': (io.BytesIO(body), name)}, content_type='multipart/form-data')
    r = up('notes.txt', b'hello')
    assert r.status_code == 400 and 'MP4 or WebM' in r.get_json()['error']
    r = up('fake.mp4', b'this is not a video at all')
    assert r.status_code == 400 and 'not a video' in r.get_json()['error']
    mp4 = b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom' + b'\x00' * 64
    d = up('Trip clip.mp4', mp4).get_json()
    assert d['url'].startswith('/static/uploads/blog-trip-clip') and d['url'].endswith('.mp4')
    webm = b'\x1a\x45\xdf\xa3' + b'\x00' * 64
    assert up('clip.webm', webm).get_json()['url'].endswith('.webm')
    logout(client)
    assert up('clip.webm', webm).status_code in (302, 401, 403)


# ============================================================================== order on the blog

def test_order_on_the_blog_puts_the_picked_posts_first(client, admin_user):
    old = make('Oldest story', days_ago=30)
    mid = make('Middle story', days_ago=10)
    new = make('Newest story', days_ago=1)
    make('A draft', published=False)
    login(client, 'admin@test.com')
    html = client.get('/admin/blog/order').data.decode()
    assert 'data-order-placed' in html and 'Nothing pinned' in html and 'A draft' not in html
    assert html.index('Newest story') < html.index('Middle story') < html.index('Oldest story')
    # a post gone since the screen was opened, a draft, a repeat and nonsense are skipped; the places have no gaps
    draft = Blog.query.filter_by(title='A draft').one()
    ids = '999999,%d,%d,%d,%d,abc' % (draft.id, old.id, mid.id, old.id)
    r = client.post('/admin/blog/order', data={'ids': ids}, follow_redirects=True)
    assert 'Saved: 2 posts first' in r.data.decode() and draft.sort_order is None
    assert (old.sort_order, mid.sort_order, new.sort_order) == (1, 2, None)
    slugs = re.findall(r'<article class="bp[^"]*" data-slug="([^"]+)"', client.get('/blog').data.decode())
    assert slugs[:3] == [old.slug, mid.slug, new.slug]
    assert [p.id for p in bp.in_blog_order(Blog.live()).all()][:3] == [old.id, mid.id, new.id]
    # unpin all: newest first again
    client.post('/admin/blog/order', data={'ids': ''})
    assert Blog.query.filter(Blog.sort_order.isnot(None)).count() == 0
    slugs = re.findall(r'<article class="bp[^"]*" data-slug="([^"]+)"', client.get('/blog').data.decode())
    assert slugs[:3] == [new.slug, mid.slug, old.slug]


def test_the_order_screen_is_in_the_blog_menu(client, admin_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/blog').data.decode()
    assert 'Order on the blog' in html and '/admin/blog/order' in html


# ============================================================================== the editor

def test_the_editor_has_the_new_blocks_the_block_tab_and_the_structure(client, admin_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/blog/new').data.decode()
    for bit in ('blog-blocks.js', 'blog-blocks.css', 'data-stab="block"', 'id="geBlockPane"', 'data-bb="settings"',
                'data-k="look"', 'data-k="tab"', 'data-video-url=',
                # the structure on the left: find, all blocks or headings, fold every section
                'aria-label="Structure of the post"', 'id="geStFind"', 'data-st-mode="heads"', 'data-st-fold',
                'id="geStStats"', 'id="geBlocks"'):
        assert bit in html, bit
    assert 'data-dtab' not in html and 'id="bsOutline"' not in html
    # Add a block is a sidebar (with the reusable blocks), not a popup; the bar's insert buttons are gone
    for bit in ('id="geIns"', 'data-ge="inserter"', 'id="geInsFind"', 'data-ins-tab="reuse"',
                'class="bs-bb-grip" draggable="true"', 'data-bb="reuse"', 'id="geReuse"', 'name="pattern_edits"',
                'data-patterns-url=', 'data-pattern-save-url='):
        assert bit in html, bit
    for gone in ('data-do="menu"', 'data-do="insert"', 'data-do="library"'):
        assert gone not in html, gone


# ============================================================================== reusable blocks

def _post_form(p, content, **over):
    d = {'title': p.title, 'slug': p.slug, 'summary': 'A post to try reusable blocks on, with enough words in it.',
         'content': content, 'cover_image_url': '', 'cover_alt': '', 'send_notification_shown': '1',
         'settings_shown': '1', 'action': 'save', 'tags': '', 'publish_at': ''}
    d.update(over)
    return d


def _pattern(pid):
    _db.session.expire_all()
    return _db.session.get(BlogPattern, pid)


def test_a_reusable_block_is_kept_as_a_wrapper_with_its_blocks(app):
    html = ('<p>A</p><div class="blog-ref evil" data-ref="7" data-x="1"><h2>Call us</h2><p>Any time.</p></div>'
            '<div class="blog-ref" data-ref="0x1"><p>B</p></div>')
    with app.test_request_context():
        got = be.sanitize(html)
        assert '<div class="blog-ref" data-ref="7"><h2>Call us</h2><p>Any time.</p></div>' in got
        assert 'evil' not in got and 'data-x' not in got and '0x1' not in got
        assert be.refs_in(got) == {7: '<h2>Call us</h2><p>Any time.</p>'}
        assert be.with_refs(got, {7: '<p>New</p>'}).startswith('<p>A</p><div class="blog-ref" data-ref="7"><p>New</p></div>')
        assert be.with_refs(got, {7: None}).startswith('<p>A</p><h2>Call us</h2><p>Any time.</p>')
        assert '<h2>Call us</h2>' in be.render(got)          # on the site: its blocks (blog-blocks.css shows only them)


def test_reusable_blocks_are_made_listed_and_renamed(client, admin_user):
    login(client, 'admin@test.com')
    j = {'Accept': 'application/json'}
    d = client.post('/admin/blog/patterns/save', headers=j, data={
        'name': '  Talk to us  ', 'synced': '1', 'content': '<h2>Talk to us</h2><p>Call <script>x()</script>any time.</p>'}).get_json()
    assert d['name'] == 'Talk to us' and d['synced'] and '<script' not in d['content'] and 'Call' in d['content']
    assert _pattern(d['id']).created_by_id == admin_user.id
    # no name; nothing in it
    assert client.post('/admin/blog/patterns/save', data={'name': '', 'content': '<p>x</p>'}, headers=j).status_code == 400
    assert client.post('/admin/blog/patterns/save', data={'name': 'Empty', 'content': '<script>x</script>'}, headers=j).status_code == 400
    # a reusable block never holds another: one inside is made its own blocks
    d2 = client.post('/admin/blog/patterns/save', headers=j, data={
        'name': 'Copy', 'synced': '0', 'content': '<div class="blog-ref" data-ref="%d"><p>Inside</p></div>' % d['id']}).get_json()
    assert d2['content'] == '<p>Inside</p>' and not d2['synced']
    items = client.get('/admin/blog/patterns?format=json').get_json()['items']
    assert [i['name'] for i in items] == ['Copy', 'Talk to us']
    html = client.get('/admin/blog/patterns').data.decode()
    assert 'Reusable blocks' in html and 'Talk to us' in html and 'Not synced' in html
    client.post('/admin/blog/patterns/save', data={'id': d['id'], 'name': 'Talk to our team'})
    assert _pattern(d['id']).name == 'Talk to our team'
    assert 'Reusable blocks' in client.get('/admin/blog').data.decode()       # in the blog menu


def test_a_synced_block_changed_in_one_post_changes_in_every_post(client, admin_user):
    login(client, 'admin@test.com')
    pat = BlogPattern(name='Talk to us', content='<h2>Talk to us</h2><p>Call any time.</p>', synced=True)
    _db.session.add(pat)
    _db.session.commit()
    pid = pat.id
    ref = '<div class="blog-ref" data-ref="%d">%%s</div>' % pid
    one = make('Post one', content='<p>First.</p>' + ref % pat.content)
    two = make('Post two', content=ref % pat.content + '<p>Second.</p>')
    one_id, two_id, two_slug = one.id, two.id, two.slug
    # the editor shows the block as it is now, even where a post holds an older copy
    pat.content = '<h2>Talk to us</h2><p>Call us, any day.</p>'
    _db.session.commit()
    assert 'any day' in client.get('/admin/blog/%d/edit' % one_id).data.decode()
    # changed in post one (and the editor says so): saved, and copied into post two
    new = '<p>First.</p>' + ref % '<h2>Talk to our team</h2><p>WhatsApp or call, 24/7.</p>'
    client.post('/admin/blog/%d/edit' % one_id, data=_post_form(one, new, pattern_edits=str(pid)))
    assert 'WhatsApp or call' in _pattern(pid).content
    assert 'WhatsApp or call' in _db.session.get(Blog, two_id).content and '<p>Second.</p>' in _db.session.get(Blog, two_id).content
    assert 'WhatsApp or call' in client.get('/blog/' + two_slug).data.decode()
    # a post that holds an old copy, saved without changing the block (an old tab): it stays as it is everywhere
    client.post('/admin/blog/%d/edit' % one_id, data=_post_form(_db.session.get(Blog, one_id), '<p>First.</p>' + ref % '<p>Old.</p>'))
    _db.session.expire_all()
    c = _db.session.get(Blog, one_id).content
    assert '<p>Old.</p>' not in c and 'WhatsApp or call' in c
    # deleted: every post keeps the blocks, as its own
    r = client.post('/admin/blog/patterns/%d/delete' % pid, follow_redirects=True)
    assert 'keep its blocks as their own' in r.data.decode()
    assert _pattern(pid) is None
    for i in (one_id, two_id):
        c = _db.session.get(Blog, i).content
        assert 'blog-ref' not in c and 'WhatsApp or call' in c


def test_a_block_that_is_not_synced_is_the_posts_own(client, admin_user):
    login(client, 'admin@test.com')
    pat = BlogPattern(name='Starter', content='<p>Start here.</p>', synced=False)
    _db.session.add(pat)
    _db.session.commit()
    pid = pat.id
    p = make('Post three', content='<p>x</p>')
    pi = p.id
    # a wrapper pointing at it (an old copy pasted in) is unwrapped: the post's own blocks; the block is unchanged
    client.post('/admin/blog/%d/edit' % pi, data=_post_form(p, '<div class="blog-ref" data-ref="%d"><p>Mine now.</p></div>' % pid,
                                                            pattern_edits=str(pid)))
    _db.session.expire_all()
    assert _db.session.get(Blog, pi).content == '<p>Mine now.</p>'
    assert _pattern(pid).content == '<p>Start here.</p>'
