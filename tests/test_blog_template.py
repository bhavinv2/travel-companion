"""The writer's Word template (blog_engine.template_docx) and the Word rules it shows: the Post details box's
thumbnail, category, tags, focus keyword and Google title; Video:, Slideshow:, a picture beside words, dividers and
the button looks. The template is a promise -- everything it shows, the import understands -- and its samples
(pictures and the video) never reach a post."""
import io
import os
import zipfile
from html import unescape

from conftest import login
from app import db as _db
from app.models import Blog, BlogTerm
from app.services import blog_engine as be

REAL_VIDEO = 'https://youtu.be/dQw4w9WgXcQ?t=42'


def picture(width=1200, height=675, color=(40, 120, 200), fmt='JPEG'):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (width, height), color).save(buf, fmt)
    return buf.getvalue()


def swapped(doc, video=REAL_VIDEO):
    """The template as a writer hands it in: every sample picture changed for one of theirs (same size), the sample
    video for a real link."""
    from PIL import Image
    samples = set(be.sample_pictures().values())
    src, out = zipfile.ZipFile(io.BytesIO(doc)), io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, info in enumerate(src.infolist()):
            data = src.read(info)
            if info.filename.startswith('word/media/') and data in samples:
                data = picture(*Image.open(io.BytesIO(data)).size, color=((n * 37) % 256, (n * 91) % 256, 160))
            if info.filename == 'word/document.xml':
                data = data.replace(be.SAMPLE_VIDEO.encode(), video.encode())
            z.writestr(info, data)
    return out.getvalue()


def upload(client, docs, pictures=None):
    data = {'documents': [(io.BytesIO(d), n) for n, d in docs.items()]}
    if pictures is not None:
        data['pictures'] = [(io.BytesIO(pictures), 'pictures.zip')]
    return client.post('/admin/blog/import', data=data, content_type='multipart/form-data')


def html_of(items, **kw):
    return be.parse_docx(be.build_docx([('p', 'Title: A post to try the Word rules on')] + items, **kw))


# ---------------------------------------------------------------------------- the template itself

def test_the_template_with_the_writers_pictures_gives_every_block():
    r = be.parse_docx(swapped(be.template_docx()))
    assert r['notes'] == []
    assert r['cover'] and r['thumb'] and r['cover'] != r['thumb']
    assert r['categories'] == ['Travel insurance'] and r['tags'] == ['parents', 'health insurance', 'USA visit']
    assert r['keyword'] == 'travel insurance for parents'
    assert r['seo_title'] == 'Travel Insurance for Parents Visiting the USA: 2026 Guide'
    h = r['html']
    assert '<figure class="blog-img blog-img-missing"' in h and 'Your caption goes here' in h
    assert '<div class="blog-mt" data-pos="left" data-ratio="50"><figure class="blog-mt-media blog-img-missing"' in h
    assert '<div class="blog-mt-body"><h3>Pre-existing conditions</h3><p>Many plans' in h
    assert '<figure class="blog-embed" data-provider="youtube" data-vid="dQw4w9WgXcQ" data-start="42"></figure>' in h
    assert '<h3>A day at the airport</h3>\n<div class="blog-carousel" data-show="1" data-interval="5">' in h
    assert h.count('<figure class="blog-slide blog-img-missing"') == 3
    assert '<figcaption>Security: medicines go in the cabin bag.</figcaption>' in h
    assert '<hr/>' in h and '<a class="blog-cta cta-outline" href="https://nriparentservice.com/travel-companions">' in h
    assert len(r['embedded']) == 7                       # cover, thumbnail, body, beside, three slides


def test_the_template_is_valid_word_with_its_header_and_page_numbers():
    with zipfile.ZipFile(io.BytesIO(be.template_docx())) as z:
        names = set(z.namelist())
        assert {'word/header1.xml', 'word/footer1.xml', 'docProps/core.xml'} <= names
        from xml.etree import ElementTree as ET
        for n in names:
            if n.endswith(('.xml', '.rels')):
                ET.fromstring(z.read(n))                 # every part is well-formed XML
        types = z.read('[Content_Types].xml').decode()
        assert 'header+xml' in types and 'footer+xml' in types
        assert 'w:headerReference' in z.read('word/document.xml').decode()
        assert 'PAGE' in z.read('word/footer1.xml').decode()


def test_the_template_as_it_is_imports_without_its_samples(client, admin_user):
    login(client, 'admin@test.com')
    html = unescape(upload(client, {'template.docx': be.template_docx()}).data.decode())
    assert 'Draft created' in html and 'sample video' in html and 'sample picture' in html
    post = Blog.query.one()
    assert not post.cover_image_url and not post.thumb_url
    assert 'blog-embed' not in post.content and 'blog-carousel' not in post.content and '<img' not in post.content
    assert '<h3>Pre-existing conditions</h3>' in post.content          # the words beside the sample picture stay


def test_an_imported_template_brings_its_pictures_blocks_and_details(client, app, admin_user):
    cat = BlogTerm(kind='category', name='Travel Insurance', slug='travel-insurance')
    tag = BlogTerm(kind='tag', name='Parents', slug='parents')
    _db.session.add_all([cat, tag])
    _db.session.commit()
    terms = BlogTerm.query.count()
    login(client, 'admin@test.com')
    html = unescape(upload(client, {'mine.docx': swapped(be.template_docx())}).data.decode())
    assert 'Draft created' in html and '"health insurance", "USA visit" are not on the blog yet' in html
    post = Blog.query.one()
    assert BlogTerm.query.count() == terms                             # a document never makes a category or tag
    assert [t.name for t in post.categories] == ['Travel Insurance'] and [t.name for t in post.tags] == ['Parents']
    assert post.focus_keyword == 'travel insurance for parents' and post.seo_title.endswith('2026 Guide')
    assert post.cover_image_url and post.thumb_url and post.thumb_url != post.cover_image_url
    from PIL import Image
    folder = app.config['UPLOAD_FOLDER']
    assert Image.open(os.path.join(folder, post.thumb_url.rsplit('/', 1)[1])).width <= be.THUMB_WIDTH
    c = post.content
    assert 'blog-img-missing' not in c
    assert '<div class="blog-mt" data-pos="left" data-ratio="50"><figure class="blog-mt-media"><img src=' in c
    assert c.count('<figure class="blog-slide"><img src=') == 3 and 'data-vid="dQw4w9WgXcQ"' in c
    assert 'class="blog-cta cta-outline"' in c and '<hr/>' in c
    with app.test_request_context():
        public = be.render(c)
    assert 'youtube-nocookie.com/embed/dQw4w9WgXcQ' in public and 'blog-carousel' in public


def test_replace_from_word_brings_the_details_box_too(client, admin_user):
    cat = BlogTerm(kind='category', name='Travel insurance', slug='travel-insurance')
    _db.session.add(cat)
    _db.session.commit()
    login(client, 'admin@test.com')
    d = client.post('/admin/blog/new/word', data={'document': (io.BytesIO(swapped(be.template_docx())), 't.docx')},
                    content_type='multipart/form-data').get_json()
    assert d['thumb'] and d['thumb_src'] and d['cover'] and d['categories'] == [cat.id] and d['tags'] == ''
    assert d['keyword'] == 'travel insurance for parents' and d['seo_title'].startswith('Travel Insurance for Parents')
    assert any('are not on the blog yet' in n for n in d['notes'])
    assert 'blog-carousel' in d['content'] and 'blog-mt' in d['content']


def test_the_import_page_shows_the_details_box_and_the_editor_rules(client, admin_user):
    login(client, 'admin@test.com')
    page = client.get('/admin/blog/import').data.decode()
    assert 'id="bs-details"' in page and 'id="bs-editor"' in page
    assert be.DETAIL_RULES[5][1] in page and be.EDITOR_RULES[6][1] in page


# ---------------------------------------------------------------------------- the Word rules, one by one

def test_details_rows_and_lines_at_the_top():
    r = be.parse_docx(be.build_docx([
        ('details', [('Title', '', 'Winter clothes for a December visit'),
                     ('Thumbnail', '', {'data': picture(800, 450), 'alt': 'A warm coat'}),
                     ('Categories', '', 'Packing; Winter'), ('Focus keyword', '', 'winter clothes')]),
        ('p', 'Tags: coats, thermals'),
        ('p', 'Google title: Winter Clothes for Parents'),
        ('p', 'December is colder than most parents expect.'),
        ('p', 'Tags: later in the post this is just a sentence.'),
    ]))
    assert r['thumb'] == 'picture-1.jpg' and r['cover'] == ''
    assert r['categories'] == ['Packing', 'Winter'] and r['tags'] == ['coats', 'thermals']
    assert r['keyword'] == 'winter clothes' and r['seo_title'] == 'Winter Clothes for Parents'
    assert '<p>Tags: later in the post this is just a sentence.</p>' in r['html']


def test_video_lines():
    r = html_of([('p', 'Video: https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1m30s'),
                 ('p', [('Video: ', {}), ('our clinic tour', {'link': 'rV'})]),
                 ('p', 'https://vimeo.com/76979871'),
                 ('p', 'Video: the one we made last year'),
                 ('p', 'Watch https://youtu.be/dQw4w9WgXcQ in a sentence.')],
                links={'rV': 'https://youtu.be/abcdefghijk'})
    h = r['html']
    assert '<figure class="blog-embed" data-provider="youtube" data-vid="dQw4w9WgXcQ" data-start="90"></figure>' in h
    assert '<figure class="blog-embed" data-provider="youtube" data-vid="abcdefghijk"></figure>' in h
    assert '<figure class="blog-embed" data-provider="vimeo" data-vid="76979871"></figure>' in h
    assert '<p>Video: the one we made last year</p>' in h and any('YouTube or Vimeo link' in n for n in r['notes'])
    assert '<p>Watch https://youtu.be/dQw4w9WgXcQ in a sentence.</p>' in h
    assert '<iframe' in be.render(be.sanitize(h))


def test_dividers():
    doc = be.build_docx([('p', 'Title: Lines across the page'), ('p', 'One.'), ('p', '---'), ('p', 'Two.'),
                         ('p', 'Divider'), ('p', 'Three.'), ('rule', None), ('p', 'Four.'), ('p', '———'),
                         ('p', 'Five.'), ('p', 'HR_HERE'), ('p', '--- not a line, a sentence')])
    with zipfile.ZipFile(io.BytesIO(doc)) as src:            # Insert -> Horizontal line: a VML rect with o:hr
        parts = {n: src.read(n) for n in src.namelist()}
    xml = parts['word/document.xml'].decode()
    xml = xml.replace('<w:document ', '<w:document xmlns:v="urn:schemas-microsoft-com:vml" '
                                      'xmlns:o="urn:schemas-microsoft-com:office:office" ', 1)
    xml = xml.replace('<w:r><w:t xml:space="preserve">HR_HERE</w:t></w:r>',
                      '<w:r><w:pict><v:rect o:hr="t" o:hrstd="t" o:hralign="center"/></w:pict></w:r>')
    parts['word/document.xml'] = xml.encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for n, data in parts.items():
            z.writestr(n, data)
    h = be.parse_docx(out.getvalue())['html']
    assert h.count('<hr/>') == 5 and '<p>--- not a line, a sentence</p>' in h
    boxed = be.build_docx([('p', 'Title: A box is not a line'), ('p', 'Inside a box.'), ('rule', None)])
    with zipfile.ZipFile(io.BytesIO(boxed)) as src:            # Borders -> Outside borders: sides as well
        parts = {n: src.read(n) for n in src.namelist()}
    parts['word/document.xml'] = parts['word/document.xml'].replace(
        b'<w:pBdr><w:bottom', b'<w:pBdr><w:left w:val="single" w:sz="4" w:space="4" w:color="auto"/><w:bottom')
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for n, data in parts.items():
            z.writestr(n, data)
    assert '<hr/>' not in be.parse_docx(out.getvalue())['html']


def test_button_looks():
    h = html_of([('p', [('Big button: ', {}), ('Get a quote', {'link': 'rQ'})]),
                 ('p', 'Outline button: Talk to us | /contact'),
                 ('p', 'Big button: no link here')], links={'rQ': 'https://nriparentservice.com/travel-insurance'})
    assert '<a class="blog-cta cta-big" href="https://nriparentservice.com/travel-insurance">Get a quote</a>' in h['html']
    assert '<a class="blog-cta cta-outline" href="/contact">Talk to us</a>' in h['html']
    assert '<p>Big button: no link here</p>' in h['html'] and any('"Big button:" line needs a link' in n for n in h['notes'])
    assert 'class="blog-cta cta-big"' in be.sanitize(h['html'])


def test_slideshows():
    r = html_of([('p', 'Slideshow:'), ('picture', {'data': picture(color=(1, 2, 3)), 'alt': 'Gate'}),
                 ('caption', 'At the gate.'), ('picture', {'data': picture(color=(9, 8, 7)), 'alt': 'Plane'}),
                 ('h2', 'After the slideshow'), ('caption', 'An italic line here is just a line.')])
    h = r['html']
    assert h.startswith('<div class="blog-carousel" data-show="1" data-interval="5">')
    assert '<figure class="blog-slide blog-img-missing" data-file="picture-1.jpg" data-alt="Gate"><figcaption>At the gate.' in h
    assert '<figure class="blog-slide blog-img-missing" data-file="picture-2.jpg" data-alt="Plane"></figure></div>\n<h2>' in h
    one = html_of([('p', 'Slideshow: Just one'), ('picture', {'data': picture(), 'alt': 'Alone'}), ('p', 'Words.')])
    assert '<h3>Just one</h3>\n<figure class="blog-img blog-img-missing" data-file="picture-1.jpg"' in one['html']
    assert any('two pictures or more' in n for n in one['notes'])
    none = html_of([('p', 'Slideshow: Nothing under it'), ('p', 'Words.')])
    assert 'Nothing under it' not in none['html'] and any('no pictures under it' in n for n in none['notes'])


def test_a_picture_beside_words_and_the_tables_that_are_not():
    r = html_of([('beside', {'picture': {'data': picture(), 'alt': 'A nurse'}, 'side': 'right',
                             'text': [('h2', 'Care at home'), ('p', 'Tip: ask about home visits.')]})])
    h = r['html']
    assert ('<div class="blog-mt" data-pos="right" data-ratio="50"><figure class="blog-mt-media blog-img-missing" '
            'data-file="picture-1.jpg" data-alt="A nurse"></figure><div class="blog-mt-body"><h3>Care at home</h3>'
            '<aside class="blog-note">ask about home visits.</aside></div></div>') in h
    two = html_of([('beside', {'picture': {'data': picture(), 'alt': ''}, 'side': 'left', 'text': [('p', 'Words.')]})])
    assert 'data-pos="left"' in two['html']
    plain = html_of([('table', [['Plan', 'Price'], ['Basic', '$90']])])
    assert '<table><thead><tr><th>Plan</th><th>Price</th></tr></thead>' in plain['html']
    stored = be.sanitize(h.replace('blog-mt-media blog-img-missing', 'blog-mt-media'))
    assert '<div class="blog-mt" data-pos="right" data-ratio="50">' in stored


def test_labels_name_the_thumbnail_category_and_video(client, admin_user):
    _db.session.add(BlogTerm(kind='category', name='Insurance', slug='insurance'))
    _db.session.commit()
    doc = be.build_docx([('p', '@title: Labels for the new parts'), ('p', '@cover: cover.jpg'),
                         ('p', '@thumbnail: card.jpg'), ('p', '@category: Insurance, Visas'),
                         ('p', '@google-title: Labels on Google'), ('p', 'Words in the post.'),
                         ('p', '@video: https://youtu.be/dQw4w9WgXcQ')])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('cover.jpg', picture(1600, 840))
        z.writestr('card.jpg', picture(1000, 563, color=(200, 20, 20)))
    login(client, 'admin@test.com')
    html = unescape(upload(client, {'labels.docx': doc}, buf.getvalue()).data.decode())
    assert 'The category "Visas" is not on the blog' in html
    post = Blog.query.one()
    assert post.cover_image_url and post.thumb_url and [t.name for t in post.categories] == ['Insurance']
    assert post.seo_title == 'Labels on Google' and 'data-vid="dQw4w9WgXcQ"' in post.content
