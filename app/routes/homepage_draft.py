"""Homepage draft: the React rebuild of nri-parent-service-homepage.html, at /homepage-draft,
and its About page at /about-us (the path the live site uses).

Both are the one React app in frontend/homepage-draft, built into static/homepage-draft and
mounted by templates/homepage_draft/landing.html inside base.html, so they carry the site's own
navbar and footer, the same as the travel-insurance page. `page` tells the bundle which page to
draw. The links that point at other pages of this app are built here with url_for, so the
bundle never hard-codes a path that the URL prefix would break.

They are drafts: the template asks search engines not to index them.
"""
from flask import Blueprint, render_template

from app.services import urls

homepage_draft_bp = Blueprint('homepage_draft', __name__)

PAGES = {
    'home': {
        'title': 'NRI Parent Service | Trusted Parent Care Services for NRIs in India',
        'description': ('Trusted parent care for NRIs whose parents live in India: Sahayak support, '
                        'travel companions, travel insurance, virtual doctor consultations, Gift '
                        'Health and Fit2Fly.'),
    },
    'about': {
        'title': 'About Us | NRI Parent Service',
        'description': ('Dedicated support for parents in India while families stay connected '
                        'worldwide: our mission, our story and the advisors behind NRI Parent Service.'),
    },
}


def _render(page):
    return render_template('homepage_draft/landing.html', meta=PAGES[page], links={
        'chrome': False,
        'page': page,
        'homeUrl': urls.public_url('homepage_draft.landing'),
        'aboutUrl': urls.public_url('homepage_draft.about'),
        'contactUrl': urls.public_url('main.contact_us'),
        'insuranceUrl': urls.public_url('insurance.landing'),
        'sahayakUrl': urls.public_url('sahayak.landing'),
        'companionUrl': urls.public_url('main.index'),
        'blogUrl': urls.public_url('blog.blog_list'),
    })


@homepage_draft_bp.route('/homepage-draft')
def landing():
    return _render('home')


@homepage_draft_bp.route('/about-us')
def about():
    return _render('about')
