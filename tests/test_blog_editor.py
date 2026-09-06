"""Redesigned admin blog editor: cover image, rich HTML content, validation keep-values."""
from conftest import login
from app.models import Blog


def test_editor_page_renders(client, admin_user):
    login(client, 'admin@test.com')
    html = client.get('/admin/blog/new').data.decode()
    for bit in ('bfEditor', 'bfToolbar', 'cover_image_url', 'bfPreview', 'Publish immediately'):
        assert bit in html


def test_create_post_with_cover_and_rich_html(client, db, admin_user):
    login(client, 'admin@test.com')
    r = client.post('/admin/blog/new', data={
        'title': 'Travelling with Amma',
        'content': '<h2>The plan</h2><p>Some <strong>bold</strong> advice.</p>',
        'cover_image_url': 'https://example.com/cover.jpg',
        'is_published': 'on',
        'send_notification': '',
    })
    post = Blog.query.filter_by(title='Travelling with Amma').first()
    assert post and post.cover_image_url == 'https://example.com/cover.jpg' and post.is_published
    assert r.status_code == 302 and r.headers['Location'].endswith(f'/blog/{post.slug}')
    page = client.get(f'/blog/{post.slug}').data.decode()
    assert '<strong>bold</strong>' in page and 'https://example.com/cover.jpg' in page


def test_validation_keeps_typed_values(client, admin_user):
    login(client, 'admin@test.com')
    html = client.post('/admin/blog/new', data={'title': 'Only a title', 'content': ''}).data.decode()
    assert 'Only a title' in html                      # the form did not lose the input
