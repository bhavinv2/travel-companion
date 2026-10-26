"""Blog › Sidebars, a post's own thumbnail, and how a post's page uses the room beside it.
services/blog_sidebars.py, routes/admin_blog.py (blog_sidebar_*), routes/blog.py (blog_post, side_go),
pages/_blog_side.html, models.Blog.thumb_url / card_picture."""
from datetime import datetime, timedelta

from conftest import login, logout
from app import db as _db
from app.models import Blog, BlogPattern, BlogSideCard, BlogTerm, User
from app.services import blog_engine as be
from app.services import blog_sidebars as bs


def make(title, published=True, days_ago=1, cats=(), **kw):
    p = Blog(author_id=User.query.first().id, title=title, slug=be.unique_slug(title.lower().replace(' ', '-')),
             content=kw.pop('content', '<p>Words about %s.</p>' % title), is_published=published,
             published_at=datetime.utcnow() - timedelta(days=days_ago) if published else None, **kw)
    p.terms = list(cats)
    _db.session.add(p)
    _db.session.commit()
    return p


def cat(name):
    t = BlogTerm(kind='category', name=name, slug=name.lower().replace(' ', '-'))
    _db.session.add(t)
    _db.session.commit()
    return t


def card(**kw):
    kw.setdefault('name', kw.get('title') or 'A card')
    kw.setdefault('kind', 'flyer')
    kw.setdefault('side', 'right')
    if kw['kind'] == 'flyer':
        kw.setdefault('image_url', '/static/uploads/flyer.jpg')
    c = BlogSideCard(**kw)
    _db.session.add(c)
    _db.session.commit()
    return c


ARTICLE = '<h2>Why it matters</h2><p>One.</p><h3>A detail</h3><p>Two.</p><h2>What to do</h2><p>Three.</p>'


# ============================================================================== what a post shows beside it

def test_a_card_shows_on_every_post_some_categories_or_some_posts(app, admin_user):
    ins, visa = cat('Insurance'), cat('Visas')
    a = make('Cover for parents', cats=[ins])
    b = make('Visa queues', cats=[visa])
    every = card(title='Every post')
    only_ins = card(title='Insurance offer', show_on='cats', term_ids=[ins.id])
    only_b = card(title='Just one post', show_on='posts', post_ids=[b.id], side='left')
    with app.test_request_context():
        on_a, on_b = bs.for_post(a), bs.for_post(b)
    assert [c.id for c in on_a['right']] == [every.id, only_ins.id] and on_a['left'] == []
    assert [c.id for c in on_b['right']] == [every.id] and [c.id for c in on_b['left']] == [only_b.id]


def test_a_card_switched_off_not_started_ended_or_empty_shows_nowhere(app, admin_user):
    post = make('A story')
    now = datetime.utcnow()
    live = card(title='Live')
    card(title='Off', is_on=False)
    card(title='Later', starts_at=now + timedelta(days=2))
    card(title='Ended', ends_at=now - timedelta(minutes=1))
    card(title='No picture', image_url=None)                              # a flyer needs its picture
    card(title='Links without links', kind='links')
    card(title='Contents', kind='contents')                               # the post has no headings
    with app.test_request_context():
        got = bs.for_post(post)
    assert [c.id for c in got['right']] == [live.id]


def test_phones_get_the_cards_meant_for_them_under_the_post(app, admin_user):
    post = make('A story', content=ARTICLE)
    left = card(title='Left flyer', side='left', look={'phone': 'below'})
    card(title='On this page', kind='contents', side='left')               # not on phones, as it starts
    right = card(title='Right ad', kind='ad', body='Words', look={'phone': 'below'})
    card(title='Desktop only', look={'phone': 'hide'})
    with app.test_request_context():
        got = bs.for_post(post)
    assert [c.id for c in got['below']] == [left.id, right.id]
    assert len(got['left']) == 2 and len(got['right']) == 2


def test_the_post_page_has_the_sidebars_and_the_cards_under_it(client, admin_user):
    ins = cat('Insurance')
    post = make('Cover for parents', cats=[ins], content=ARTICLE)
    other = make('Another story', cats=[ins])
    pat = BlogPattern(name='Call us', content='<p class="ta-center">Call <b>us</b></p>')
    _db.session.add(pat)
    _db.session.commit()
    card(title='Insurance flyer', link_url='https://example.com/offer', new_tab=True, look={'height': 400, 'fit': 'fill'})
    card(title='Useful links', kind='links', side='left',
         links=[{'label': 'Get a quote', 'url': '/travel-insurance'}, {'label': 'Talk to us', 'url': 'tel:+911234'}])
    card(title='', kind='contents', side='left')
    card(title='', kind='more', look={'count': 3})
    card(name='Block', kind='block', pattern_id=pat.id)
    html = client.get('/blog/%s' % post.slug).data.decode()
    assert 'bj-shell has-left has-right' in html and 'bj-rail is-left' in html and 'bj-rail is-right' in html
    # a flyer: its picture, its own height, a tap counted on the way, a new tab for another site
    assert 'class="bsd bsd--flyer th-plain fit-fill has-h"' in html and '--h: 400px' in html
    assert '/blog/go/' in html and 'rel="nofollow noopener" target="_blank"' in html
    assert 'Get a quote' in html and 'data-toc' in html and 'On this page' in html
    assert 'More stories' in html and other.title in html
    assert 'Call <strong>us</strong>' in html
    # the cover shows whole, on a blurred copy of itself; the box under the post has room before the footer
    assert 'class="bj-cover-bg"' in html and 'class="bj-cover-img"' in html and 'bj-sharebox-ic' in html


def test_a_post_with_no_cards_is_one_column(client, admin_user):
    post = make('Quiet story')
    html = client.get('/blog/%s' % post.slug).data.decode()
    assert 'class="bj-shell"' in html and 'bj-rail' not in html and 'bj-below' not in html


def test_a_tap_is_counted_and_goes_where_staff_said(client, admin_user):
    c = card(title='Offer', link_url='https://example.com/offer')
    links = card(title='Links', kind='links', links=[{'label': 'A', 'url': '/travel-insurance'}, {'label': 'B', 'url': 'https://b.example'}])
    r = client.get('/blog/go/%d' % c.id)
    assert r.status_code == 302 and r.headers['Location'] == 'https://example.com/offer'
    assert r.headers.get('X-Robots-Tag') == 'noindex'
    assert client.get('/blog/go/%d?i=1' % links.id).headers['Location'] == 'https://b.example'
    assert client.get('/blog/go/%d?i=0' % links.id).headers['Location'].endswith('/travel-insurance')
    # nothing in the request chooses where a reader lands: a wrong number goes back to the blog
    assert client.get('/blog/go/%d?i=7' % links.id).headers['Location'].endswith('/blog')
    assert client.get('/blog/go/%d?i=x&next=https://evil.example' % links.id).headers['Location'].endswith('/blog')
    assert client.get('/blog/go/999999').status_code == 404
    _db.session.expire_all()
    assert _db.session.get(BlogSideCard, c.id).clicks == 1 and _db.session.get(BlogSideCard, links.id).clicks == 2


# ============================================================================== the Sidebars screen

def test_the_sidebars_screen_draws_both_sidebars_and_is_in_the_blog_menu(client, admin_user):
    ins = cat('Insurance')
    card(title='Right flyer')
    card(title='Insurance only', kind='ad', body='Cheap cover', side='left', show_on='cats', term_ids=[ins.id])
    login(client, 'admin@test.com')
    html = client.get('/admin/blog/sidebars').data.decode()
    assert 'Left sidebar' in html and 'Right sidebar' in html and 'data-hgrip' in html and 'data-wgrip' in html
    assert 'Right flyer' in html and 'Insurance only' in html and 'Every post' in html
    assert '>Sidebars</span>' in client.get('/admin/blog').data.decode()
    # for one category's posts: a card for every post is lit, one for another category is not
    other = cat('Visas')
    html = client.get('/admin/blog/sidebars?for=cat:%d' % other.id).data.decode()
    assert html.count('is-dim') == 1 and 'Not on Posts in Visas' in html


def test_a_card_is_made_from_the_form_and_wrong_answers_are_said(client, admin_user):
    ins = cat('Insurance')
    login(client, 'admin@test.com')
    assert 'What is it?' in client.get('/admin/blog/sidebars/new?kind=ad&side=left').data.decode()
    form = {'kind': 'ad', 'side': 'left', 'title': 'Diwali offer', 'body': 'Cover from ₹999', 'link_url': 'javascript:alert(1)',
            'theme': 'navy', 'height_mode': 'auto', 'on_phone': 'below', 'show_on': 'cats', 'is_on': 'on', 'name': ''}
    r = client.post('/admin/blog/sidebars/new', data=form)
    page = r.data.decode()
    assert r.status_code == 400 and 'The link must start with' in page and 'Pick at least one category' in page
    assert 'Diwali offer' in page and BlogSideCard.query.count() == 0           # what was typed, nothing kept
    form.update(link_url='/travel-insurance', terms=[str(ins.id)], height_mode='fixed', height='5000',
                starts_at='2026-11-01T09:00', ends_at='2026-11-15T21:00')
    r = client.post('/admin/blog/sidebars/new', data=form, follow_redirects=True)
    assert r.status_code == 200 and 'Saved: “Diwali offer”' in r.data.decode()
    c = BlogSideCard.query.one()
    assert (c.kind, c.side, c.term_ids, c.link_url, c.name) == ('ad', 'left', [ins.id], '/travel-insurance', 'Diwali offer')
    assert bs.look(c)['theme'] == 'navy' and bs.look(c)['height'] == bs.HEIGHT_MAX         # 5000 px is 1200 at most
    assert c.starts_at < c.ends_at and bs.status(c, datetime(2026, 10, 30)) == 'later'
    # the end before the start is refused
    form.update(ends_at='2026-10-01T09:00')
    r = client.post('/admin/blog/sidebars/%d' % c.id, data=form)
    assert r.status_code == 400 and 'It must end after it starts' in r.data.decode()
    _db.session.expire_all()
    assert _db.session.get(BlogSideCard, c.id).ends_at > c.starts_at


def test_links_and_a_reusable_block_from_the_form(client, admin_user):
    pat = BlogPattern(name='Call us', content='<p>Call</p>')
    _db.session.add(pat)
    _db.session.commit()
    login(client, 'admin@test.com')
    client.post('/admin/blog/sidebars/new', data={
        'kind': 'links', 'side': 'right', 'title': 'Useful', 'show_on': 'all', 'is_on': 'on', 'height_mode': 'auto',
        'link_label_n': ['Quote', '', 'Bad'], 'link_url_n': ['/travel-insurance', '', 'https://ok.example']})
    c = BlogSideCard.query.one()
    assert c.links == [{'label': 'Quote', 'url': '/travel-insurance'}, {'label': 'Bad', 'url': 'https://ok.example'}]
    r = client.post('/admin/blog/sidebars/new', data={'kind': 'block', 'side': 'right', 'show_on': 'all', 'is_on': 'on',
                                                      'height_mode': 'auto', 'pattern_id': str(pat.id)}, follow_redirects=True)
    assert r.status_code == 200 and BlogSideCard.query.filter_by(kind='block').one().pattern_id == pat.id


def test_the_preview_draws_the_card_and_keeps_nothing(client, admin_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/blog/sidebars/preview', data={'kind': 'ad', 'side': 'right', 'title': 'Hello there', 'body': 'Words',
                                                          'theme': 'coral', 'show_on': 'all', 'height_mode': 'auto'})
    html = r.data.decode()
    assert r.status_code == 200 and 'bsd--ad th-coral' in html and 'Hello there' in html
    assert BlogSideCard.query.count() == 0
    # a flyer before its picture is up: nothing drawn (never an <img src="None">)
    html = client.post('/admin/blog/sidebars/preview', data={'kind': 'flyer', 'side': 'right', 'show_on': 'all',
                                                             'height_mode': 'auto'}).data.decode()
    assert 'Fill in the card' in html and '<img' not in html


def test_drag_resize_reorder_switch_copy_and_delete(client, admin_user):
    a, b = card(title='A', sort_order=1), card(title='B', sort_order=2)
    c = card(title='C', side='left', sort_order=1)
    login(client, 'admin@test.com')
    # a card's height, dragged; back to as tall as it needs
    d = client.post('/admin/blog/sidebars/%d/quick' % a.id, data={'height': '333'}).get_json()
    assert d['height'] == 333 and bs.look(_db.session.get(BlogSideCard, a.id))['height'] == 333
    assert client.post('/admin/blog/sidebars/%d/quick' % a.id, data={'height': ''}).get_json()['height'] is None
    # off and on again
    assert client.post('/admin/blog/sidebars/%d/quick' % b.id, data={'is_on': '0'}).get_json()['status'] == 'off'
    # the order dragged: B to the top of the left, A stays right
    client.post('/admin/blog/sidebars/order', data={'left': '%d,%d' % (b.id, c.id), 'right': '%d,abc' % a.id})
    _db.session.expire_all()
    got = {x.title: (x.side, x.sort_order) for x in BlogSideCard.query}
    assert got == {'A': ('right', 1), 'B': ('left', 1), 'C': ('left', 2)}
    # a sidebar's width, dragged (kept within its limits), and its last card staying in view
    assert client.post('/admin/blog/sidebars/rail', data={'side': 'left', 'width': '999'}).get_json()['width'] == bs.WIDTH_MAX
    assert client.post('/admin/blog/sidebars/rail', data={'side': 'right', 'sticky': '0'}).get_json()['sticky'] is False
    assert client.post('/admin/blog/sidebars/rail', data={'side': 'middle', 'width': '300'}).status_code == 400
    assert bs.rails()['left']['width'] == bs.WIDTH_MAX and bs.rails()['right']['sticky'] is False
    # a copy waits, switched off; a delete is gone from every post
    r = client.post('/admin/blog/sidebars/%d/copy' % a.id, follow_redirects=True)
    assert 'Copy of A' in r.data.decode() and BlogSideCard.query.filter_by(name='Copy of A').one().is_on is False
    client.post('/admin/blog/sidebars/%d/delete' % a.id)
    assert _db.session.get(BlogSideCard, a.id) is None


def test_only_staff_with_the_blog_lists_manage_sidebars(client, admin_user):
    c = card(title='A')
    for url in ('/admin/blog/sidebars', '/admin/blog/sidebars/new', '/admin/blog/sidebars/%d' % c.id):
        r = client.get(url)
        assert r.status_code in (302, 401, 403) and 'Left sidebar' not in r.data.decode()
    assert client.post('/admin/blog/sidebars/%d/quick' % c.id, data={'is_on': '0'}).status_code in (302, 401, 403)
    assert _db.session.get(BlogSideCard, c.id).is_on is True


def test_a_sidebar_picture_counts_as_used_in_media(client, admin_user):
    from app.services import blog_posts as bp
    c = card(title='Poster', image_url='/static/uploads/blog-poster_abc.jpg')
    with client.application.test_request_context():
        used = bp.usage()
    assert used['blog-poster_abc.jpg'][0].edit_url.endswith('/admin/blog/sidebars/%d' % c.id)


# ============================================================================== a post's own thumbnail

def test_the_thumbnail_is_the_card_picture_and_the_cover_tops_the_post(client, admin_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/blog/new', data={
        'title': 'Thumb story', 'slug': '', 'slug_auto': '1', 'send_notification_shown': '1', 'action': 'publish',
        'summary': 'What we learnt flying with Amma from Hyderabad to Chicago: documents, medicines and the layover.',
        'content': '<h2>The plan</h2><p>Some <strong>bold</strong> advice.</p>',
        'cover_image_url': '/static/uploads/cover.jpg', 'cover_alt': 'Cover', 'thumb_url': '/static/uploads/thumb.jpg'},
        follow_redirects=True)
    assert r.status_code == 200
    post = Blog.query.filter_by(title='Thumb story').one()
    assert post.thumb_url == '/static/uploads/thumb.jpg' and post.card_picture == post.thumb_url
    assert 'name="thumb_url" value="/static/uploads/thumb.jpg"' in client.get('/admin/blog/%d/edit' % post.id).data.decode()
    logout(client)
    listing = client.get('/blog').data.decode()
    assert '/static/uploads/thumb.jpg' in listing and 'data-fit' in listing
    page = client.get('/blog/%s' % post.slug).data.decode()
    assert 'class="bj-cover-img" src="/static/uploads/cover.jpg"' in page
    # no thumbnail: the cover is the card's picture; a copy keeps the thumbnail
    post.thumb_url = None
    _db.session.commit()
    assert post.card_picture == '/static/uploads/cover.jpg'
    assert post.pictures(1) == [('/static/uploads/cover.jpg', 'Cover')]


def test_the_editor_has_a_thumbnail_slot_and_says_the_sizes(client, admin_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/blog/new').data.decode()
    assert 'id="bsThumb"' in html and '800 × 450 px' in html and '1200 × 630 px' in html
