"""Blog studio: Word documents become draft posts; the editor checks them, previews them as the
public page and publishes them. services/blog_engine.py, routes/admin_blog.py.

Writers are not technical, so the main way is plain Word: a details box, pasted pictures, Heading
styles, and lines starting Tip: / Quote: / Button:. The older @label format with a zip of pictures
still works (the "advanced" tests)."""
import io
import os
import re
import zipfile
from html import unescape

from conftest import login
from app import db as _db
from app.models import Blog, Notification
from app.services import blog_engine as be


def picture(width=2000, height=1050, fmt='JPEG', color=(40, 120, 200), photo=False):
    """photo: grain like a real photo's, so a PNG of it is big (a flat colour compresses to nothing)."""
    from PIL import Image
    im = Image.frombytes('RGB', (width, height), os.urandom(width * height * 3)) if photo else Image.new('RGB', (width, height), color)
    buf = io.BytesIO()
    im.save(buf, fmt)
    return buf.getvalue()


def zipped(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def upload(client, docs, pictures=None):
    data = {'documents': [(io.BytesIO(d), n) for n, d in docs.items()]}
    if pictures is not None:
        data['pictures'] = [(io.BytesIO(pictures), 'pictures.zip')]
    return client.post('/admin/blog/import', data=data, content_type='multipart/form-data')


def writers_doc(cover=True):
    """What a writer hands in: the details box filled, pictures pasted with Word's alt text, an
    italic caption, the three plain words."""
    details = [('Title', '', 'Five things to pack for parents flying to the USA'),
               ('Summary', '', 'A short packing list for parents visiting the USA: medicines, documents, warm '
                               'clothes and a few comforts from home.'),
               ('Web address', '', '')]
    if cover:
        details.insert(2, ('Cover picture', '', {'data': picture(2400, 1260, color=(200, 90, 40)), 'alt': 'Parents at the airport'}))
    return be.build_docx([
        ('details', details),
        ('p', 'Packing for a long visit is different from packing for a holiday.'),
        ('h2', 'Medicines and prescriptions'),
        ('p', 'Carry enough medicine for the whole stay.'),
        ('picture', {'data': picture(900, 600, 'PNG', photo=True), 'alt': 'A pouch of labelled medicines\n\nDescription automatically generated'}),
        ('caption', 'Keep medicines in the cabin bag.'),
        ('p', [('Tip: ', {'b': True}), ('Keep a photo of every prescription on your phone.', {})]),
        ('p', 'Quote: Pack light, but never without the medicines.'),
        ('bullet', 'Passport'),
        ('bullet', 'Insurance card'),
        ('p', [('Button: ', {}), ('See travel insurance', {'link': 'rIdTi'})]),
    ], links={'rIdTi': 'https://nriparentservice.com/travel-insurance'})


def legacy_doc():
    """The older label format, pictures named for a zip."""
    return be.build_docx([
        ('note', '// a note for the writer'),
        ('p', '@title: How to Buy Travel Insurance for Parents Visiting the USA'),
        ('p', '@slug: travel-insurance-for-parents-visiting-usa'),
        ('p', '@summary: A step-by-step guide for NRIs choosing travel medical insurance for parents visiting the USA: '
              'what to compare and what to avoid.'),
        ('p', '@cover: parents-insurance-cover.jpg'),
        ('p', '@cover-alt: Indian parents with their suitcases at a US airport'),
        ('p', 'Healthcare in the United States is expensive.'),
        ('p', '@h2 Compare the plans'),
        ('p', '@image: parents-insurance-1.jpg | A doctor talking with an elderly patient | Care is costly.'),
        ('p', '@note: Check whether the policy can be extended.'),
        ('p', '@cta: Get a free travel insurance quote | /travel-insurance'),
    ])


LEGACY_PICTURES = {'Pictures/parents-insurance-cover.jpg': picture(), 'Pictures/parents-insurance-1.jpg': picture(900, 600)}


# ---------------------------------------------------------------------------- reading Word, the plain way

def test_the_template_reads_as_a_clean_post_and_leaves_its_samples_out():
    r = be.parse_docx(be.template_docx())
    assert r['title'] == 'How to Buy Travel Insurance for Parents Visiting the USA'
    assert r['slug'] == 'how-to-buy-travel-insurance-for-parents-visiting-the-usa'
    assert 70 <= len(r['summary']) <= 160 and r['cover_alt'].startswith('Indian parents')
    assert r['cover'] == '' and r['embedded'] == {}                     # the sample pictures are not the writer's
    assert any('sample picture' in n for n in r['notes'])
    h = r['html']
    assert 'HOW TO USE' not in h and 'POST DETAILS' not in h and 'Your caption goes here' not in h
    assert h.count('<h2>') == 3 and h.count('<h3>') == 1
    assert '<ul><li>Full name and date of birth</li>' in h and '<ol><li>Compare the policy maximum' in h
    assert '<aside class="blog-note">Check whether' in h and '<blockquote>The best plan' in h
    assert ('<a class="blog-cta" href="https://nriparentservice.com/travel-insurance">Get a free travel insurance quote</a>'
            in h)


def test_the_template_carries_the_whole_writing_guide_and_never_publishes_it():
    """The guide on the import page and the one at the end of the template are the same lists."""
    data = be.template_docx()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        text = unescape(re.sub(r'<[^>]+>', '', z.read('word/document.xml').decode()))
    for what, becomes in be.FORMAT_RULES + be.CHECK_RULES + be.ADVANCED_RULES:
        assert what in text and becomes in text, what
    for rule in be.IMAGE_RULES + be.ADVANCED_IMAGE_RULES:
        assert rule in text, rule
    assert 'The full writing guide is at the end of this document' in text
    html = be.parse_docx(data)['html']
    for guide_bit in ('WRITING GUIDE', 'On the website', '@title', 'Stops publishing', 'never published'):
        assert guide_bit not in html


def test_the_import_page_folds_the_guide_until_asked(client, admin_user):
    login(client, 'admin@test.com')
    page = client.get('/admin/blog/import').data.decode()
    assert '<details class="admin-card bs-guide" id="bs-guide">' in page        # closed: no "open"
    for part in ('id="bs-format"', 'id="bs-pictures"', 'id="bs-checks"', 'id="bs-advanced"'):
        assert part in page
    assert be.CHECK_RULES[1][1] in page and be.FORMAT_RULES[0][0] in page


def test_a_writers_document_with_pasted_pictures():
    r = be.parse_docx(writers_doc())
    assert r['title'] == 'Five things to pack for parents flying to the USA' and r['summary'].startswith('A short packing')
    assert r['cover'] == 'picture-1.jpg' and r['cover_alt'] == 'Parents at the airport'
    assert set(r['embedded']) == {'picture-1.jpg', 'picture-2.png'}
    h = r['html']
    assert ('<figure class="blog-img blog-img-missing" data-file="picture-2.png" data-alt="A pouch of labelled medicines">'
            '<figcaption>Keep medicines in the cabin bag.</figcaption></figure>') in h        # Word's guess-suffix dropped
    assert '<aside class="blog-note">Keep a photo' in h and '<blockquote>Pack light' in h
    assert '<a class="blog-cta" href="https://nriparentservice.com/travel-insurance">See travel insurance</a>' in h
    assert '<ul><li>Passport</li><li>Insurance card</li></ul>' in h and r['notes'] == []


def test_a_picture_above_the_post_is_the_cover_and_title_and_summary_lines_work():
    doc = be.build_docx([
        ('p', 'Title: Winter clothes for a December visit'),
        ('p', 'Summary: What parents arriving in December need, from thermals to a good coat.'),
        ('picture', {'data': picture(1600, 840), 'alt': 'Snow in New Jersey'}),
        ('p', 'December in the north-east is colder than most parents expect.'),
        ('p', 'Summary: later in the post this is just a sentence.'),
    ])
    r = be.parse_docx(doc)
    assert r['title'] == 'Winter clothes for a December visit' and r['summary'].startswith('What parents arriving')
    assert r['cover'] == 'picture-1.jpg' and r['cover_alt'] == 'Snow in New Jersey'
    assert '<p>Summary: later in the post this is just a sentence.</p>' in r['html']


def test_a_plain_document_imports_with_its_bold_lines_as_headings():
    """Like the real "Blog 6": no box, no labels, a bold first line, bold section lines, Word lists."""
    doc = be.build_docx([
        ('p', [('How to Pack for a Long Visit', {'b': True})]),
        ('p', 'Parents visiting for months need a different packing list.'),
        ('p', [('1. Medicines first', {'b': True})]),
        ('bullet', 'Prescriptions'),
        ('bullet', 'A doctor’s letter'),
        ('p', [('Your age + length of stay + health = the plan.', {'b': True})]),     # ends with a full stop: not a heading
        ('p', '@hashtag stays as text'),
        ('number', 'One'),
        ('number', 'Two'),
    ])
    r = be.parse_docx(doc)
    assert r['title'] == 'How to Pack for a Long Visit'
    h = r['html']
    assert '<h2>1. Medicines first</h2>' in h
    assert '<p><strong>Your age + length of stay + health = the plan.</strong></p>' in h
    assert '<ul><li>Prescriptions</li><li>A doctor’s letter</li></ul>' in h and '<ol><li>One</li><li>Two</li></ol>' in h
    assert '<p>@hashtag stays as text</p>' in h
    assert any('first line became the title' in n for n in r['notes'])
    assert any('1 short bold line became' in n for n in r['notes'])


def test_a_button_line_without_a_link_stays_text_and_says_why():
    r = be.parse_docx(be.build_docx([('p', 'Title: A post with a broken button'), ('p', 'Button: Click me')]))
    assert '<p>Button: Click me</p>' in r['html'] and any('Ctrl+K' in n for n in r['notes'])
    r = be.parse_docx(be.build_docx([('p', 'Title: A post with a typed link'), ('p', 'Button: Get a quote → /travel-insurance')]))
    assert '<a class="blog-cta" href="/travel-insurance">Get a quote</a>' in r['html']


def test_files_that_are_not_word_documents_are_explained(client, admin_user):
    login(client, 'admin@test.com')
    html = upload(client, {'old.doc': b'\xd0\xcf\x11\xe0rest', 'broken.docx': b'not a zip',
                           'notes.txt': b'hello'}).data.decode()
    assert 'save it as .docx' in html and 'This is not a Word document (.docx).' in html
    assert 'Only Word documents (.docx) can be imported.' in html
    assert Blog.query.count() == 0


# ---------------------------------------------------------------------------- importing

def test_a_writers_document_becomes_a_draft_with_its_pictures(client, app, admin_user):
    login(client, 'admin@test.com')
    r = upload(client, {'packing.docx': writers_doc()})                  # no zip: the pictures are inside
    assert r.status_code == 200 and b'Draft created' in r.data and b'2 pictures' in r.data
    post = Blog.query.one()
    assert not post.is_published and post.source_file == 'packing.docx'
    assert post.cover_image_url.startswith('/static/uploads/') and post.cover_alt == 'Parents at the airport'
    assert 'blog-img-missing' not in post.content and 'alt="A pouch of labelled medicines"' in post.content
    assert '<figcaption>Keep medicines in the cabin bag.</figcaption>' in post.content
    from PIL import Image
    folder = app.config['UPLOAD_FOLDER']
    cover = Image.open(os.path.join(folder, post.cover_image_url.rsplit('/', 1)[1]))
    assert cover.width == be.COVER_WIDTH                               # 2400 wide in, made web-sized
    body = [f for f in os.listdir(folder) if 'picture-2' in f]
    assert body and body[0].endswith('.jpg')                           # a big opaque PNG from Word goes JPG


def test_importing_again_updates_the_draft(client, admin_user):
    login(client, 'admin@test.com')
    upload(client, {'packing.docx': writers_doc()})
    first = Blog.query.one()
    html = upload(client, {'packing.docx': writers_doc()}).data.decode()
    assert 'Draft updated' in html and Blog.query.count() == 1 and Blog.query.one().id == first.id


def test_another_document_with_the_same_title_never_overwrites_a_draft(client, admin_user):
    """Blog 6 and the template's example share a title: the second must not replace the first."""
    login(client, 'admin@test.com')
    same = be.build_docx([('p', 'Title: Five things to pack for parents flying to the USA'), ('p', 'Different words.')])
    html = upload(client, {'packing.docx': writers_doc(), 'other.docx': same}).data.decode()
    assert html.count('Draft created') == 2 and 'Another draft already uses' in html
    posts = Blog.query.order_by(Blog.id).all()
    assert [p.slug for p in posts] == ['five-things-to-pack-for-parents-flying-to-the-usa',
                                       'five-things-to-pack-for-parents-flying-to-the-usa-2']
    assert 'Different words.' not in posts[0].content


def test_a_published_post_is_never_changed_by_an_import(client, admin_user):
    login(client, 'admin@test.com')
    upload(client, {'packing.docx': writers_doc()})
    live = Blog.query.one()
    live.is_published, live.title = True, 'Edited live title'
    _db.session.commit()
    html = upload(client, {'packing.docx': writers_doc()}).data.decode()
    assert 'new draft beside it' in html
    assert _db.session.get(Blog, live.id).title == 'Edited live title'
    assert Blog.query.filter_by(slug='five-things-to-pack-for-parents-flying-to-the-usa-2', is_published=False).one()


# ---------------------------------------------------------------------------- the advanced way: labels and a zip

def test_labels_and_a_zip_of_pictures_still_work(client, app, admin_user):
    login(client, 'admin@test.com')
    r = upload(client, {'legacy.docx': legacy_doc()}, zipped(LEGACY_PICTURES))
    assert b'Draft created' in r.data
    post = Blog.query.one()
    assert post.slug == 'travel-insurance-for-parents-visiting-usa' and post.cover_image_url
    assert 'alt="A doctor talking with an elderly patient"' in post.content and 'a note for the writer' not in post.content
    assert '<a href="/travel-insurance" class="blog-cta">' in post.content
    small = [f for f in os.listdir(app.config['UPLOAD_FOLDER']) if 'parents-insurance-1' in f]
    from PIL import Image
    assert small and Image.open(os.path.join(app.config['UPLOAD_FOLDER'], small[0])).width == 900   # already small: untouched
    # imported again without the zip, it keeps the pictures it has
    upload(client, {'legacy.docx': legacy_doc()})
    again = Blog.query.one()
    assert again.cover_image_url == post.cover_image_url and 'blog-img-missing' not in again.content


def test_several_documents_in_one_upload_share_the_zip(client, admin_user):
    login(client, 'admin@test.com')
    other = be.build_docx([('p', '@title: Second post about airports'), ('p', '@cover: parents-insurance-cover'),
                           ('p', 'Body text for the second post.')])
    upload(client, {'a.docx': legacy_doc(), 'b.docx': other}, zipped(LEGACY_PICTURES))
    posts = Blog.query.order_by(Blog.id).all()
    assert len(posts) == 2 and posts[1].cover_image_url        # found by its name without the extension


# ---------------------------------------------------------------------------- editing and publishing

def _fields(post, **over):
    data = {'title': post.title, 'slug': post.slug, 'summary': post.summary or '', 'content': post.content,
            'cover_image_url': post.cover_image_url or '', 'cover_alt': post.cover_alt or '',
            'send_notification_shown': '1', 'send_notification': 'on'}
    data.update(over)
    return data


def test_a_missing_picture_blocks_publishing_until_it_is_uploaded(client, admin_user, user):
    login(client, 'admin@test.com')
    upload(client, {'legacy.docx': legacy_doc()})                       # labels name pictures, no zip sent
    post = Blog.query.one()
    page = client.get('/admin/blog/%d/edit' % post.id).data.decode()
    assert 'blog-img-missing' in page and 'The picture parents-insurance-1.jpg is missing' in page

    r = client.post('/admin/blog/%d/edit' % post.id, data=_fields(post, action='publish'), follow_redirects=True)
    assert b'not published' in r.data and not _db.session.get(Blog, post.id).is_published

    up = client.post('/admin/blog/%d/image' % post.id, data={'file': (io.BytesIO(picture()), 'doctor.jpg'),
                                                              'purpose': 'body'}, content_type='multipart/form-data')
    url = up.get_json()['url']
    fixed = post.content.replace(
        '<figure class="blog-img blog-img-missing" data-file="parents-insurance-1.jpg" data-alt="A doctor talking with an elderly patient">',
        '<figure class="blog-img"><img src="%s" alt="A doctor" data-file="doctor.jpg">' % url)
    r = client.post('/admin/blog/%d/edit' % post.id, data=_fields(post, content=fixed, action='publish'))
    assert r.status_code == 302
    post = _db.session.get(Blog, post.id)
    assert post.is_published and post.published_at
    assert Notification.query.filter_by(user_id=user.id, type='blog').count() == 1      # told once, on first publish
    public = client.get('/blog/%s' % post.slug).data.decode()
    assert url in public and 'blog-cta' in public and 'name="description" content="A step-by-step guide' in public


def test_a_live_post_is_not_updated_while_a_red_check_is_left(client, admin_user):
    login(client, 'admin@test.com')
    upload(client, {'packing.docx': writers_doc()})
    post = Blog.query.one()
    client.post('/admin/blog/%d/edit' % post.id, data=_fields(post, action='publish'))
    assert _db.session.get(Blog, post.id).is_published
    r = client.post('/admin/blog/%d/edit' % post.id, data=_fields(post, content='', action='save'))
    assert r.status_code == 400 and b'The live post is unchanged' in r.data
    assert _db.session.get(Blog, post.id).content == post.content
    client.post('/admin/blog/%d/edit' % post.id, data=_fields(post, action='unpublish'))
    assert not _db.session.get(Blog, post.id).is_published


def test_an_address_another_post_uses_is_refused(client, admin_user):
    login(client, 'admin@test.com')
    a = Blog(author_id=admin_user.id, title='First post here', slug='taken', content='<p>x</p>')
    b = Blog(author_id=admin_user.id, title='Second post here', slug='free', content='<p>y</p>')
    _db.session.add_all([a, b])
    _db.session.commit()
    r = client.post('/admin/blog/%d/edit' % b.id, data=_fields(b, slug='Taken', action='save'))
    assert r.status_code == 400 and b'another post already uses that address' in r.data
    assert _db.session.get(Blog, b.id).slug == 'free'


def test_the_preview_shows_what_is_in_the_editor_not_what_is_saved(client, admin_user):
    login(client, 'admin@test.com')
    post = Blog(author_id=admin_user.id, title='Saved title here', slug='saved', content='<p>Saved words</p>')
    _db.session.add(post)
    _db.session.commit()
    r = client.post('/admin/blog/%d/preview' % post.id, data=_fields(post, title='Unsaved title here',
                                                                    content='<p>Unsaved words</p>'))
    html = r.data.decode()
    assert r.status_code == 200 and r.headers['X-Robots-Tag'] == 'noindex'
    assert 'Unsaved words' in html and 'Unsaved title here' in html and 'Preview' in html
    assert _db.session.get(Blog, post.id).title == 'Saved title here'


def test_the_checks_answer_for_the_editor(client, admin_user):
    login(client, 'admin@test.com')
    post = Blog(author_id=admin_user.id, title='T', slug='t', content='<p>x</p>')
    _db.session.add(post)
    _db.session.commit()
    d = client.post('/admin/blog/%d/check' % post.id, data=_fields(
        post, title='A title that is long enough to read well', summary='short',
        content='<h3>Sub first</h3><p>' + 'word ' * 130 + '</p><img src="/static/uploads/a.jpg">')).get_json()
    texts = ' | '.join(c['text'] for c in d['checks'])
    assert 'Title length is good' in texts and 'The summary is 5 characters' in texts
    assert 'start sections with an H2' in texts and 'longer than 120 words' in texts
    assert '1 picture in the post has no description' in texts and 'No cover picture' in texts
    assert d['words'] == 132 and not be.has_errors(d['checks'])


# ---------------------------------------------------------------------------- safety

def test_whatever_html_arrives_only_the_blog_allowlist_is_kept():
    dirty = ('<div onclick="steal()">Hi <b>there</b><script>alert(1)</script></div>'
             '<p style="color:red"><a href="javascript:alert(1)">bad</a> <a href="/trips" target="_blank">ok</a></p>'
             '<iframe src="https://evil.example"><p>inside</p></iframe><img src="data:image/png;base64,AAAA">'
             '<span><font>loose</font></span><h1>Big</h1><meta name="google-site-verification" content="x">')
    clean = be.sanitize(dirty)
    for gone in ('onclick', 'script', 'alert', 'style=', 'javascript', 'iframe', 'evil', 'inside', 'data:', 'meta', 'span', 'font'):
        assert gone not in clean, gone
    assert '<p>Hi <strong>there</strong></p>' in clean and '<h2>Big</h2>' in clean
    assert '<a href="/trips" target="_blank" rel="noopener noreferrer">ok</a>' in clean and 'bad' in clean


def test_the_public_page_keeps_links_and_pictures_inside_the_app(app):
    html = ('<p><a href="/trips">trips</a> <a href="/travel-insurance">insurance</a></p>'
            '<figure class="blog-img"><img src="/static/uploads/a.jpg" alt="A"></figure>'
            + be.missing_figure('never-uploaded.jpg', 'x'))
    with app.test_request_context('/', base_url='https://nriparentservice.com/travel-companions'):
        out = be.render(html)
    assert 'href="/travel-companions/trips"' in out and 'href="/travel-insurance"' in out
    assert 'src="/travel-companions/static/uploads/a.jpg"' in out
    assert 'never-uploaded' not in out                                  # a missing picture is never shown


def test_only_people_who_may_write_posts_reach_the_studio(client, cs_user, admin_user):
    login(client, cs_user.email)
    for path in ('/admin/blog/import', '/admin/blog/template.docx'):
        r = client.get(path)
        assert r.status_code in (302, 403) and b'PK' not in r.data[:2]
    client.post('/auth/logout')
    login(client, 'admin@test.com')
    r = client.get('/admin/blog/template.docx')
    assert r.status_code == 200 and r.mimetype == be.DOCX_MIME
    assert be.parse_docx(r.data)['title']
    page = client.get('/admin/blog/import').data.decode()
    assert 'Import blog posts' in page and 'Blog template (.docx)' in page and 'Tip:' in page
