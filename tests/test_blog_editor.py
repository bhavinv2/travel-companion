"""Writing a post in the admin portal: "New blog post" is the blog studio editor itself (blocks,
pictures, cover, summary, checks, preview), the same page that edits a saved post. The first Save
draft or Publish makes the post. routes/admin_blog.py, static/js/blog-studio.js."""
import io

from conftest import login
from app.models import Blog, Notification
from app.services import blog_engine as be


def picture():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (1600, 900), (40, 120, 200)).save(buf, 'JPEG')
    return buf.getvalue()


def post_form(**over):
    data = {'title': 'Travelling with Amma: what we learnt', 'slug': '', 'slug_auto': '1',
            'summary': 'What we learnt flying with Amma from Hyderabad to Chicago: documents, medicines, the long '
                       'layover and the wheelchair.',
            'content': '<h2>The plan</h2><p>Some <strong>bold</strong> advice.</p>',
            'cover_image_url': '', 'cover_alt': '', 'send_notification_shown': '1', 'action': 'save'}
    data.update(over)
    return data


def test_new_blog_post_is_the_full_editor(client, admin_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/blog/new').data.decode()
    for bit in ('id="bsEditor"', 'id="bsToolbar"', 'Add block', 'id="bsMenu"', 'id="bsBlockBar"', 'name="summary"',
                'name="cover_image_url"', 'name="slug"', 'name="slug_auto"', 'Save draft', 'Publish', 'Preview',
                'blog-studio.js', 'Not saved yet', 'The checks appear here as you write'):
        assert bit in html, bit
    assert 'action="/admin/blog/new"' in html
    assert 'data-check-url="/admin/blog/new/check"' in html and 'data-image-url="/admin/blog/image"' in html
    assert 'bs-c-error' not in html                       # a blank page is not a list of red mistakes


def test_save_draft_makes_the_post_and_opens_it_in_the_editor(client, admin_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/blog/new', data=post_form())
    post = Blog.query.filter_by(title='Travelling with Amma: what we learnt').one()
    assert r.status_code == 302 and r.headers['Location'].endswith('/admin/blog/%d/edit' % post.id)
    assert not post.is_published and post.slug == 'travelling-with-amma-what-we-learnt'
    assert post.author_id == admin_user.id and post.summary.startswith('What we learnt')
    page = client.get('/admin/blog/%d/edit' % post.id).data.decode()
    assert 'Edit blog post' in page and '<strong>bold</strong>' in page and 'Draft saved.' in page


def test_publishing_a_new_post_puts_it_live_and_tells_everybody(client, admin_user, user):
    login(client, 'admin@test.com')
    body = '<h2>The plan</h2>' + '<p>%s</p>' % ' '.join(['word'] * 320)
    r = client.post('/admin/blog/new', data=post_form(content=body, action='publish', send_notification='on',
                                                       cover_image_url='https://example.com/cover.jpg',
                                                       cover_alt='Amma at the airport'))
    post = Blog.query.one()
    assert r.status_code == 302 and post.is_published and post.published_at
    assert post.cover_image_url == 'https://example.com/cover.jpg'
    assert Notification.query.filter_by(user_id=user.id, type='blog').count() == 1
    page = client.get('/blog/%s' % post.slug).data.decode()
    assert '<h2>The plan</h2>' in page and 'https://example.com/cover.jpg' in page


def test_publish_with_a_red_check_keeps_a_draft(client, admin_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/blog/new', data=post_form(content='', action='publish'), follow_redirects=True)
    post = Blog.query.one()
    assert not post.is_published
    assert 'Saved as a draft, not published' in r.data.decode()


def test_no_title_keeps_what_was_typed(client, admin_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/blog/new', data=post_form(title='', summary='Only a summary here'))
    html = r.data.decode()
    assert r.status_code == 400 and 'Not saved: add a title.' in html
    assert 'Only a summary here' in html and '<strong>bold</strong>' in html
    assert Blog.query.count() == 0


def test_an_address_made_from_the_title_never_clashes(client, admin_user):
    login(client, 'admin@test.com')
    client.post('/admin/blog/new', data=post_form())
    client.post('/admin/blog/new', data=post_form())
    assert sorted(b.slug for b in Blog.query.all()) == ['travelling-with-amma-what-we-learnt',
                                                       'travelling-with-amma-what-we-learnt-2']
    # one typed by hand is the writer's choice: a clash is said, not changed
    r = client.post('/admin/blog/new', data=post_form(slug='travelling-with-amma-what-we-learnt', slug_auto='0'))
    assert r.status_code == 400 and 'another post already uses that address' in r.data.decode()


def test_checks_preview_and_pictures_answer_before_the_post_exists(client, admin_user):
    login(client, 'admin@test.com')
    d = client.post('/admin/blog/new/check', data=post_form()).get_json()
    assert d['slug'] == 'travelling-with-amma-what-we-learnt' and d['words'] == 5
    assert any(c['text'].startswith('Only 5 words') for c in d['checks'])
    r = client.post('/admin/blog/new/preview', data=post_form(title='Not saved yet but previewed'))
    assert r.status_code == 200 and 'Not saved yet but previewed' in r.data.decode() and 'Preview' in r.data.decode()
    up = client.post('/admin/blog/image', data={'file': (io.BytesIO(picture()), 'amma.jpg'), 'purpose': 'body'},
                     content_type='multipart/form-data').get_json()
    assert up['url'] and up['src'] and up['name'] == 'amma.jpg'
    assert Blog.query.count() == 0


def test_whatever_the_editor_sends_is_cleaned(client, admin_user):
    login(client, 'admin@test.com')
    client.post('/admin/blog/new', data=post_form(
        content='<p class="bs-ph" contenteditable="false">Hi<script>alert(1)</script></p>'
                '<table><thead><tr><th>Plan</th></tr></thead><tbody><tr><td>Gold</td></tr></tbody></table>'
                '<p class="blog-cta-wrap"><a class="blog-cta" href="/travel-insurance">Get a quote</a></p>'))
    html = Blog.query.one().content
    assert 'script' not in html and 'bs-ph' not in html and 'contenteditable' not in html
    assert '<th>Plan</th>' in html and '<a href="/travel-insurance" class="blog-cta">Get a quote</a>' in html


def test_the_posts_list_and_the_import_page_lead_to_the_editor(client, admin_user):
    login(client, 'admin@test.com')
    assert 'href="/admin/blog/new"' in client.get('/admin/blog').data.decode()
    assert 'Write one here instead' in client.get('/admin/blog/import').data.decode()
    assert be.CHECK_RULES[0][0] == 'Stops publishing'
