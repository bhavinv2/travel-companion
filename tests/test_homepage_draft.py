"""The home page (/home): what the server hands the React bundle.

    content     approved reviews only (featured first), the Help centre's questions, the Sahayak and
                insurance "from" prices, the published numbers -- each empty when nothing is
                published, so its section does not show
    blog        the WordPress blog's newest posts (services/wp_blog), [] when it cannot be asked
    the bundle  built without the sample reviews, the placeholders or the ticker banner
"""
import json
import os
import re
from datetime import datetime, timedelta

import requests

from app import db as _db
from app.models import REVIEW_SITE_LABELS, Feedback
from app.services import insurance_page, sahayak, wp_blog

PAGE = '/home'
BUNDLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'app', 'static', 'homepage-draft', 'homepage-draft.js')


def data(client, path=PAGE):
    html = client.get(path).get_data(as_text=True)
    return json.loads(re.search(r'window\.__HOMEPAGE__ = (\{.*?\});\n', html, re.S).group(1))


def review(user, text, approved=True, featured=False, site='sahayak', days=0):
    fb = Feedback(user_id=user.id, rating=5, comment=text, site=site, is_approved=approved, is_featured=featured,
                  created_at=datetime.utcnow() - timedelta(days=days))
    _db.session.add(fb)
    _db.session.commit()
    return fb


def test_no_reviews_until_staff_approve_one(app, client, user):
    assert data(client)['reviews'] == []
    review(user, 'Not checked yet', approved=False)
    assert data(client)['reviews'] == []


def test_approved_reviews_featured_first(app, client, user):
    review(user, 'Older, picked for the home page', featured=True, days=9)
    review(user, 'Newest', site='insurance')
    review(user, '   ')                                        # a star rating with no words says nothing
    got = data(client)['reviews']
    assert [r['quote'] for r in got] == ['Older, picked for the home page', 'Newest']
    assert got[0]['service'] == REVIEW_SITE_LABELS['sahayak']
    assert got[1]['service'] == 'Travel insurance' and got[1]['name'] == user.username


def test_questions_prices_and_numbers_come_from_the_admin_screens(app, client):
    d = data(client)
    assert d['faqs'] and all(f['question'] and f['answer'] for f in d['faqs'])
    asked = [(f['service'], f['question']) for f in d['faqs']]
    assert ('Travel Companion', 'Can I request a companion for my parents?') in asked
    assert ('Travel Insurance', 'Are pre-existing conditions covered?') in asked
    assert not any(q == 'Is NRI Parent Service free?' for _s, q in asked)          # the community's, not ours
    assert len(asked) == 7                                                          # Sahayak ships with none
    cheapest = min(int(s['price']) for s in sahayak.services())
    assert d['prices']['sahayak'] == '₹%d' % cheapest           # the cheapest in the Sahayak catalogue
    assert d['prices']['insurance'] == ''                       # nobody has set it: not shown
    insurance_page.save_page('From $1.20 a day', [])
    _db.session.commit()
    assert data(client)['prices']['insurance'] == 'From $1.20 a day'
    assert d['helpUrl'].endswith('/help') and isinstance(d['phones'], list)
    assert d['posts'] == []                                     # WordPress is not asked in the tests


def test_the_about_page_carries_none_of_the_home_content(app, client, user):
    review(user, 'A review')
    d = data(client, '/about-us')
    assert d['page'] == 'about' and d['reviews'] == [] and d['faqs'] == [] and d['posts'] == []


WP = [{'date': '2026-10-09T05:03:43', 'link': 'https://nriparentservice.com/how-to-buy-travel-insurance/',
       'title': {'rendered': 'How to Buy Travel Insurance for Parents Visiting the USA?'},
       'excerpt': {'rendered': '<p>When parents travel from India to the United States, NRIs plan every part '
                               'of their journey &amp; more [&hellip;]</p>'},
       '_embedded': {'wp:featuredmedia': [{'source_url': 'https://nriparentservice.com/full.jpg',
                                           'media_details': {'sizes': {'medium_large': {
                                               'source_url': 'https://nriparentservice.com/768.jpg'}}}}]}},
      {'date': '2026-10-06T05:00:00', 'link': 'https://nriparentservice.com/parents-alone/',
       'title': {'rendered': 'Supporting Parents Living Alone'}, 'excerpt': {'rendered': ''}},
      {'link': 'javascript:alert(1)', 'title': {'rendered': 'Not a post'}}]


class Answer:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def test_the_newest_posts_are_read_from_wordpress_and_kept(app, monkeypatch):
    calls = []
    monkeypatch.setattr(wp_blog.requests, 'get', lambda url, **kw: calls.append((url, kw)) or Answer(WP))
    wp_blog._cache.clear()
    app.testing = False
    try:
        with app.app_context():
            posts = wp_blog.latest(4)
            assert wp_blog.latest(4) is posts and len(calls) == 1          # kept for the hour
    finally:
        app.testing = True
        wp_blog._cache.clear()
    assert calls[0][0] == 'https://nriparentservice.com/wp-json/wp/v2/posts'
    assert calls[0][1]['params']['per_page'] == 4 and calls[0][1]['timeout'] == wp_blog.TIMEOUT
    first, second = posts
    assert first == {'title': 'How to Buy Travel Insurance for Parents Visiting the USA?',
                     'url': 'https://nriparentservice.com/how-to-buy-travel-insurance/', 'date': 'October 9, 2026',
                     'img': 'https://nriparentservice.com/768.jpg', 'label': 'Travel Insurance',
                     'summary': 'When parents travel from India to the United States, NRIs plan every part of '
                                'their journey & more'}
    assert second['label'] == 'Parent Care' and second['img'] == '' and second['summary'] == ''
    assert len(posts) == 2                                                  # never a link that is not a web page


def test_a_wordpress_that_does_not_answer_is_asked_again_later(app, monkeypatch):
    def down(url, **kw):
        raise requests.ConnectionError('down')
    monkeypatch.setattr(wp_blog.requests, 'get', down)
    wp_blog._cache.clear()
    app.testing = False
    try:
        with app.app_context():
            assert wp_blog.latest(4) == []
        until, posts = wp_blog._cache[4]
        assert posts == [] and until - __import__('time').monotonic() <= wp_blog.KEEP_FAILURE_FOR
    finally:
        app.testing = True
        wp_blog._cache.clear()


def test_the_built_page_has_no_samples_placeholders_or_ticker():
    js = open(BUNDLE, encoding='utf-8').read()
    for gone in ('[Customer name]', '[YOUR HELPLINE]', '[PARENT NAME]', 'Every time zone',
                 'My father had a cataract surgery', 'tk-track'):
        assert gone not in js, gone
    assert 'Talk to a Care Advisor' in js and 'liveChat' in js


def test_each_service_reads_more_on_its_own_page(app, client):
    """Virtual Doctor, Gift Health and Fit2Fly are the group's pages (the Call-ON-Doc page, and the
    two the site menu lists); the others are this app's. None of them is the contact page."""
    d = data(client)
    assert d['doctorUrl'] == 'https://preventia360.com/call-on-doc/'
    assert d['giftUrl'] == 'https://preventia360.com/gift-health/'
    assert d['fitUrl'] == 'https://preventia360.com/fit2fly/'
    pages = [d[k] for k in ('companionUrl', 'insuranceUrl', 'doctorUrl', 'sahayakUrl', 'giftUrl', 'fitUrl')]
    assert len(set(pages)) == 6 and d['contactUrl'] not in pages
