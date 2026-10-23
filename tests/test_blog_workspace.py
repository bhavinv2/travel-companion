"""The blog as a workspace of its own, the way WordPress has it: a dashboard, All posts by status (Published,
Scheduled, Drafts, From Word, Trash) with filters and bulk actions, categories and tags, the media library,
saved versions, posts scheduled for later, "Replace from Word" in the full-screen editor -- and what readers
see of it: the featured post, category and tag pages, related posts. routes/admin_blog.py,
services/blog_posts.py, routes/blog.py."""
import io
from datetime import datetime, timedelta

from conftest import login
from app import db as _db
from app.models import Blog, BlogMedia, BlogRevision, BlogTerm, Notification, User
from app.services import blog_engine as be
from app.services import blog_posts as bp

BODY = ('<h2>Before the flight</h2><p>' + 'Carry every prescription and the medicines for the whole stay. ' * 40 +
        '</p><h2>At the airport</h2><p>Ask for the wheelchair when you book.</p>')


def picture(width=1400, height=900, color=(40, 120, 200)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (width, height), color).save(buf, 'JPEG')
    return buf.getvalue()


def form(**over):
    data = {'title': 'Travel insurance for parents visiting the USA', 'slug': '', 'slug_auto': '1',
            'summary': 'What travel insurance parents visiting the USA need: cover, the hospital bills it pays and '
                       'how to claim.',
            'content': BODY, 'cover_image_url': '', 'cover_alt': '', 'send_notification_shown': '1',
            'settings_shown': '1', 'action': 'save', 'tags': '', 'publish_at': ''}
    data.update(over)
    return data


def make(title, published=True, when=None, **kw):
    p = Blog(author_id=User.query.first().id, title=title, slug=be.unique_slug(title.lower().replace(' ', '-')),
             content=kw.pop('content', '<p>Words about %s.</p>' % title), is_published=published,
             published_at=when or (datetime.utcnow() - timedelta(days=1) if published else None), **kw)
    _db.session.add(p)
    _db.session.commit()
    return p


# ============================================================================== the workspace

def test_every_screen_is_the_blog_workspace_without_the_site_header(client, admin_user):
    login(client, 'admin@test.com')
    for url in ('/admin/blog/dashboard', '/admin/blog', '/admin/blog/categories', '/admin/blog/tags',
                '/admin/blog/media', '/admin/blog/import'):
        html = client.get(url).data.decode()
        assert 'class="wpb-body"' in html and 'id="wpbMenu"' in html, url
        for line in ('Dashboard', 'All posts', 'Add new post', 'Categories', 'Tags', 'Media', 'Import from Word',
                     'Admin portal'):
            assert line in html, (url, line)
    editor = client.get('/admin/blog/new').data.decode()
    assert 'ge-body' in editor and 'id="geSide"' in editor and 'id="wpbMenu"' not in editor
    for bit in ('data-stab="post"', 'data-stab="seo"', 'data-stab="checks"', 'name="publish_at"', 'name="tags"',
                'name="categories"' if BlogTerm.query.count() else 'No categories yet', 'name="seo_title"',
                'name="focus_keyword"', 'name="is_featured"', 'name="author_id"', 'id="gePrepub"', 'id="geLib"',
                'data-ge="word"', 'Are you ready to publish?', 'blog-admin.css'):
        assert bit in editor, bit


def test_dashboard_counts_and_quick_draft(client, admin_user):
    make('Live one')
    make('A draft', published=False)
    make('Later', when=datetime.utcnow() + timedelta(days=2))
    login(client, 'admin@test.com')
    html = client.get('/admin/blog/dashboard').data.decode()
    assert '1 published' in html and '1 scheduled' in html and '1 draft' in html
    r = client.post('/admin/blog/quick-draft', data={'title': 'Packing for Amma', 'content': 'Medicines first.\n\nThen the shawl.'})
    post = Blog.query.filter_by(title='Packing for Amma').one()
    assert r.headers['Location'].endswith('/admin/blog/%d/edit' % post.id)
    assert not post.is_published and post.content == '<p>Medicines first.</p><p>Then the shawl.</p>'
    assert post.revisions.count() == 1 and post.revisions.first().note == 'Quick draft'


def test_all_posts_views_filters_and_the_red_checks(client, admin_user):
    a = make('Alpha post about visas')
    make('Beta draft', published=False, content='')
    make('Gamma scheduled', when=datetime.utcnow() + timedelta(days=3))
    make('Delta from Word', published=False, source_file='delta.docx')
    gone = make('Epsilon trashed')
    gone.trashed_at = datetime.utcnow()
    visas = BlogTerm(kind='category', name='Visas', slug='visas')
    _db.session.add(visas)
    a.terms = [visas]
    _db.session.commit()
    login(client, 'admin@test.com')
    html = client.get('/admin/blog').data.decode()
    assert 'All <span>(4)</span>' in html and 'Trash <span>(1)</span>' in html and 'Epsilon' not in html
    assert '— Scheduled' in html and '— Draft' in html and 'delta.docx' in html
    assert 'wpb-dot bad' in html                                   # the empty draft has a red check
    assert 'Epsilon' in client.get('/admin/blog?status=trash').data.decode()
    word = client.get('/admin/blog?status=word').data.decode()
    assert 'Delta from Word' in word and 'Alpha' not in word
    cat = client.get('/admin/blog?category=%d' % visas.id).data.decode()
    assert 'Alpha post about visas' in cat and 'Beta draft' not in cat
    assert 'Gamma' in client.get('/admin/blog?q=gamma').data.decode()
    assert 'Gamma' not in client.get('/admin/blog?q=alpha').data.decode()


def test_trash_and_restore(client, admin_user):
    p = make('Going away')
    login(client, 'admin@test.com')
    assert client.get('/blog/%s' % p.slug).status_code == 200
    client.post('/admin/blog/%d/trash' % p.id)
    assert _db.session.get(Blog, p.id).status == 'trash'
    assert client.get('/blog/%s' % p.slug).status_code == 404
    client.post('/admin/blog/%d/restore' % p.id)
    p = _db.session.get(Blog, p.id)
    assert p.status == 'draft' and p.trashed_at is None              # back as a draft, like WordPress


def test_bulk_actions_and_a_red_check_is_never_published(client, admin_user):
    good = make('Good draft', published=False, content=BODY, summary='x' * 100)
    empty = make('Empty draft', published=False, content='')
    login(client, 'admin@test.com')
    r = client.post('/admin/blog/bulk', data={'action': 'publish', 'ids': [good.id, empty.id], 'next': '/admin/blog'},
                    follow_redirects=True)
    assert 'Not published (fix their red checks first): Empty draft' in r.data.decode()
    assert _db.session.get(Blog, good.id).status == 'published' and _db.session.get(Blog, empty.id).status == 'draft'
    client.post('/admin/blog/bulk', data={'action': 'trash', 'ids': [good.id, empty.id]})
    assert {_db.session.get(Blog, i).status for i in (good.id, empty.id)} == {'trash'}


def test_duplicate(client, admin_user):
    tag = BlogTerm(kind='tag', name='OCI', slug='oci')
    _db.session.add(tag)
    p = make('Original')
    p.terms = [tag]
    _db.session.commit()
    login(client, 'admin@test.com')
    r = client.post('/admin/blog/%d/duplicate' % p.id)
    copy = Blog.query.filter_by(title='Copy of Original').one()
    assert r.headers['Location'].endswith('/admin/blog/%d/edit' % copy.id)
    assert copy.status == 'draft' and copy.content == p.content and copy.slug != p.slug and copy.tags == [tag]


# ============================================================================== categories and tags

def test_categories_screen(client, admin_user):
    login(client, 'admin@test.com')
    client.post('/admin/blog/categories', data={'name': 'Flying with parents', 'description': 'Airports, seats, wheelchairs.'})
    t = BlogTerm.query.filter_by(kind='category').one()
    assert t.slug == 'flying-with-parents'
    r = client.post('/admin/blog/categories', data={'name': 'flying with PARENTS'}, follow_redirects=True)
    assert 'There is already a category called' in r.data.decode() and BlogTerm.query.count() == 1
    client.post('/admin/blog/categories', data={'id': t.id, 'name': 'Flying', 'slug': 'flying'})
    assert _db.session.get(BlogTerm, t.id).name == 'Flying'
    html = client.get('/admin/blog/categories?edit=%d' % t.id).data.decode()
    assert 'Edit category' in html and 'value="flying"' in html
    client.post('/admin/blog/terms/%d/delete' % t.id)
    assert BlogTerm.query.count() == 0


def test_the_editor_saves_categories_tags_seo_and_featured(client, admin_user):
    cat = BlogTerm(kind='category', name='Insurance', slug='insurance')
    old = BlogTerm(kind='tag', name='USA', slug='usa')
    _db.session.add_all([cat, old])
    _db.session.commit()
    login(client, 'admin@test.com')
    client.post('/admin/blog/new', data=form(categories=[str(cat.id)], tags='usa, Hospital bills, , hospital bills',
                                             seo_title='Parents visiting the USA: insurance', focus_keyword='travel insurance',
                                             is_featured='on'))
    p = Blog.query.one()
    assert p.categories == [cat] and sorted(t.name for t in p.tags) == ['Hospital bills', 'USA']
    assert p.seo_title == 'Parents visiting the USA: insurance' and p.focus_keyword == 'travel insurance' and p.is_featured
    page = client.get('/admin/blog/%d/edit' % p.id).data.decode()
    assert 'value="Hospital bills, USA"' in page or 'value="USA, Hospital bills"' in page
    # a check from a tab without the settings (an old one) leaves them as they are
    client.post('/admin/blog/%d/edit' % p.id, data={k: v for k, v in form().items() if k != 'settings_shown'})
    p = _db.session.get(Blog, p.id)
    assert p.categories == [cat] and len(p.tags) == 2 and p.is_featured


def test_adding_a_category_from_the_editor(client, admin_user):
    login(client, 'admin@test.com')
    d = client.post('/admin/blog/terms/add', data={'name': 'Visas', 'kind': 'category'}).get_json()
    again = client.post('/admin/blog/terms/add', data={'name': 'visas', 'kind': 'category'}).get_json()
    assert d['id'] == again['id'] and BlogTerm.query.count() == 1
    assert client.post('/admin/blog/terms/add', data={'name': ' ', 'kind': 'category'}).status_code == 400


def test_keyword_checks():
    found = be.keyword_checks('travel insurance', 'Travel insurance for parents', 'travel-insurance-for-parents',
                              'Which travel insurance to buy.', '<h2>Travel insurance basics</h2><p>Travel insurance pays.</p>')
    assert found[0]['level'] == 'ok'
    found = be.keyword_checks('travel insurance', 'Parents in the USA', 'parents-usa', '', '<p>Nothing about it.</p>')
    assert 'not in the title, the summary, the address, the first paragraph, a section heading' in found[0]['text']
    assert be.keyword_checks('', 'x', 'x', 'x', 'x') == []


# ============================================================================== scheduling

def test_a_post_scheduled_for_later_goes_live_and_is_told_then(client, admin_user, user):
    login(client, 'admin@test.com')
    later = datetime.utcnow() + timedelta(days=2)
    r = client.post('/admin/blog/new', data=form(action='publish', send_notification='on',
                                                 publish_at=bp.ist_input(later)), follow_redirects=True)
    p = Blog.query.one()
    assert 'Scheduled: on the site from' in r.data.decode()
    assert p.status == 'scheduled' and p.is_published and p.notified_at is None
    assert Notification.query.filter_by(type='blog').count() == 0
    assert client.get('/blog/%s' % p.slug).status_code == 404 and p.title not in client.get('/blog').data.decode()
    assert bp.run_scheduled() == {'blog_went_live': 0, 'blog_told': 0}
    assert bp.run_scheduled(now=later + timedelta(minutes=1)) == {'blog_went_live': 1, 'blog_told': 1}
    assert Notification.query.filter_by(type='blog', user_id=user.id).count() == 1
    assert bp.run_scheduled(now=later + timedelta(hours=1)) == {'blog_went_live': 0, 'blog_told': 0}   # once


def test_publishing_now_tells_everybody_once_and_updates_never_again(client, admin_user, user):
    login(client, 'admin@test.com')
    client.post('/admin/blog/new', data=form(action='publish', send_notification='on'))
    p = Blog.query.one()
    assert p.status == 'published' and p.notified_at is not None
    assert Notification.query.filter_by(type='blog', user_id=user.id).count() == 1
    client.post('/admin/blog/%d/edit' % p.id, data=form(title='Travel insurance for parents visiting America'))
    client.post('/admin/blog/%d/edit' % p.id, data=form(action='unpublish'))
    client.post('/admin/blog/%d/edit' % p.id, data=form(action='publish'))
    assert Notification.query.filter_by(type='blog', user_id=user.id).count() == 1


# ============================================================================== versions

def test_every_save_keeps_a_version_to_compare_and_bring_back(client, admin_user):
    p = make('Old post', content='<p>The first words.</p>')               # saved before versions were kept
    login(client, 'admin@test.com')
    client.post('/admin/blog/%d/edit' % p.id, data=form(title='Old post', content='<p>The second words.</p>', slug=p.slug))
    revs = BlogRevision.query.filter_by(blog_id=p.id).order_by(BlogRevision.id).all()
    assert [r.note for r in revs] == ['As it was before versions were kept', 'Updated']
    html = client.get('/admin/blog/%d/revisions' % p.id).data.decode()
    assert 'This is the post as it is now' in html and '<del>first</del>' in html and '<ins>second</ins>' in html
    old = client.get('/admin/blog/%d/edit?revision=%d' % (p.id, revs[0].id)).data.decode()
    assert 'The first words.' in old and 'data-dirty="1"' in old and 'name="revision"' in old
    client.post('/admin/blog/%d/edit' % p.id, data=form(title='Old post', content='<p>The first words.</p>',
                                                         slug=p.slug, revision=str(revs[0].id)))
    assert _db.session.get(Blog, p.id).content == '<p>The first words.</p>'
    assert BlogRevision.query.filter_by(blog_id=p.id).order_by(BlogRevision.id.desc()).first().note == \
        'Brought back an earlier version'
    # saving without a change keeps no new version
    n = BlogRevision.query.filter_by(blog_id=p.id).count()
    client.post('/admin/blog/%d/edit' % p.id, data=form(title='Old post', content='<p>The first words.</p>', slug=p.slug))
    assert BlogRevision.query.filter_by(blog_id=p.id).count() == n


def test_compare_lines():
    old = Blog(title='A', summary='s', content='<p>One two three.</p><p>Same.</p><figure class="blog-img"><img src="/x.jpg" alt="Amma"></figure>')
    new = Blog(title='B', summary='s', content='<p>One four three.</p><p>Same.</p><p>Added line.</p>')
    d = bp.compare(old, new)
    kinds = [l['kind'] for l in d['lines']]
    assert 'changed' in kinds and d['title'] == '<del>A</del> <ins>B</ins>' and d['summary'] is None
    assert any('[Picture: Amma]' in l['html'] for l in d['lines'] if l['kind'] in ('removed', 'changed'))


# ============================================================================== media

def test_media_library_upload_describe_and_delete_only_what_no_post_uses(client, admin_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/blog/media/upload', data={'files': [(io.BytesIO(picture()), 'amma.jpg'),
                                                                (io.BytesIO(b'nope'), 'notes.txt')]},
                    content_type='multipart/form-data')
    d = r.get_json()
    assert d['uploaded'] == 1 and 'notes.txt' in d['errors'][0]
    m = BlogMedia.query.one()
    assert m.width == 1400 and m.uploaded_by_id == admin_user.id
    client.post('/admin/blog/media/%d' % m.id, data={'alt': 'Amma at the gate'})
    items = client.get('/admin/blog/media?format=json').get_json()['items']
    assert items[0]['alt'] == 'Amma at the gate'
    # a picture an older post shows is in the library too
    make('With an old picture', content='<figure class="blog-img"><img src="/static/uploads/old-pic.jpg" alt="x"></figure>')
    names = [i['name'] for i in client.get('/admin/blog/media?format=json').get_json()['items']]
    assert 'old-pic.jpg' in names
    used = make('Uses it', cover_image_url=m.url)
    r = client.post('/admin/blog/media/%d/delete' % m.id, follow_redirects=True)
    assert 'That picture is in a post' in r.data.decode() and BlogMedia.query.count() == 1
    used.cover_image_url = None
    _db.session.commit()
    client.post('/admin/blog/media/%d/delete' % m.id)
    assert BlogMedia.query.count() == 0


def test_pictures_uploaded_in_the_editor_go_in_the_library(client, admin_user):
    login(client, 'admin@test.com')
    up = client.post('/admin/blog/image', data={'file': (io.BytesIO(picture()), 'gate.jpg'), 'purpose': 'body'},
                     content_type='multipart/form-data').get_json()
    assert BlogMedia.query.filter_by(url=up['url']).count() == 1
    html = client.get('/admin/blog/media').data.decode()
    assert 'Not used' in html and 'gate.jpg' in html


# ============================================================================== Word

def doc(title='Five things to pack for parents', words='Carry the medicines.'):
    return be.build_docx([('details', [('Title', '', title), ('Summary', '', 'A packing list for parents visiting.'),
                                       ('Web address', '', '')]),
                          ('h2', 'Medicines'), ('p', words)])


def test_a_word_imported_post_opens_in_the_editor_and_can_be_replaced_from_word(client, admin_user):
    login(client, 'admin@test.com')
    client.post('/admin/blog/import', data={'documents': [(io.BytesIO(doc()), 'pack.docx')]},
                content_type='multipart/form-data')
    p = Blog.query.one()
    assert p.source_file == 'pack.docx' and p.revisions.first().note == 'Imported from Word: pack.docx'
    page = client.get('/admin/blog/%d/edit' % p.id).data.decode()
    assert 'Imported from <b>pack.docx</b>' in page and 'Replace from a Word document' in page
    assert 'Carry the medicines.' in page
    d = client.post('/admin/blog/%d/word' % p.id, data={'document': (io.BytesIO(doc('Six things', 'Carry water too.')), 'v2.docx')},
                    content_type='multipart/form-data').get_json()
    assert d['title'] == 'Six things' and 'Carry water too.' in d['content'] and d['file'] == 'v2.docx'
    assert _db.session.get(Blog, p.id).title == 'Five things to pack for parents'     # nothing saved by reading
    bad = client.post('/admin/blog/%d/word' % p.id, data={'document': (io.BytesIO(b'x'), 'old.doc')},
                      content_type='multipart/form-data')
    assert bad.status_code == 400 and '.docx' in bad.get_json()['error']
    assert client.post('/admin/blog/new/word', data={'document': (io.BytesIO(doc()), 'a.docx')},
                       content_type='multipart/form-data').status_code == 200


# ============================================================================== what readers see

def test_the_blog_shows_the_featured_post_sections_and_tags(client, admin_user):
    cat = BlogTerm(kind='category', name='Visas', slug='visas', description='Visas for parents.')
    tag = BlogTerm(kind='tag', name='OCI', slug='oci')
    _db.session.add_all([cat, tag])
    hero = make('The big one', is_featured=True, seo_title='Big one for Google')
    a = make('Visa basics')
    a.terms = [cat, tag]
    hero.terms = [cat]
    make('Draft unseen', published=False)
    make('Scheduled unseen', when=datetime.utcnow() + timedelta(days=1))
    _db.session.commit()
    html = client.get('/blog').data.decode()
    assert 'blog-hero' in html and 'The big one' in html and 'Visa basics' in html
    assert 'Draft unseen' not in html and 'Scheduled unseen' not in html
    assert 'href="/blog/category/visas"' in html and '2</small>' in html
    page = client.get('/blog/category/visas').data.decode()
    assert 'Visas for parents.' in page and 'Visa basics' in page and 'blog-hero' not in page
    assert 'Visa basics' in client.get('/blog/tag/oci').data.decode()
    assert 'The big one' not in client.get('/blog/tag/oci').data.decode()
    assert client.get('/blog/category/nothing').status_code == 404
    post = client.get('/blog/%s' % a.slug).data.decode()
    assert '#OCI' in post and 'Read next' in post and 'The big one' in post and 'min read' in post
    assert '<title>Big one for Google – NRI Parent Service</title>' in client.get('/blog/%s' % hero.slug).data.decode()
    assert 'Visa basics' in client.get('/blog?q=basics').data.decode()
    assert '/blog/category/visas' in client.get('/sitemap.xml').data.decode()


def test_a_writer_without_the_lists_writes_but_does_not_manage(client, app, cs_user):
    from app.models import WorkspaceMember, WorkspaceRole
    from app.services import access
    ws = access.ensure_defaults()
    role = WorkspaceRole(workspace_id=ws.id, name='Writer', pages=['blog'])
    _db.session.add(role)
    _db.session.flush()
    m = WorkspaceMember.query.filter_by(workspace_id=ws.id, user_id=cs_user.id).first()
    if m is None:
        m = WorkspaceMember(workspace_id=ws.id, user_id=cs_user.id)
        _db.session.add(m)
    m.role_id = role.id
    _db.session.commit()
    login(client, 'cs@test.com')
    assert client.get('/admin/blog/new').status_code == 200
    assert client.get('/admin/blog/media').status_code == 200
    for url in ('/admin/blog', '/admin/blog/dashboard', '/admin/blog/categories'):
        assert client.get(url).status_code == 302, url
    html = client.get('/admin/blog/media').data.decode()
    assert 'Add new post' in html and 'All posts' not in html and 'Categories' not in html
