"""Homepage draft: the React rebuild of nri-parent-service-homepage.html, at /homepage-draft,
and its About page at /about-us (the path the live site uses).

Both are the one React app in frontend/homepage-draft, built into static/homepage-draft and
mounted by templates/homepage_draft/landing.html inside base.html, so they carry the site's own
navbar and footer, the same as the travel-insurance page. `page` tells the bundle which page to
draw. The links that point at other pages of this app are built here with url_for, so the
bundle never hard-codes a path that the URL prefix would break.

What the business publishes reaches the page from here too, never typed into the bundle:
reviews staff approved (featured ones first), each product's questions from the Help centre, the
"from" prices on the Sahayak and insurance pages, the published numbers and address, and the
newest posts on the WordPress blog. Each may be empty, and its section then does not show: an
empty section is honest, a filled one nobody wrote is not.

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


REVIEWS_SHOWN = 9
# The Help centre's questions a family asks before it starts, picked by id -- their words are edited
# in the Help centre like any other. None: that product's first few, as published (Sahayak ships
# with none, on purpose). The companion app's other questions are about using the app, and one --
# "Is NRI Parent Service free?" -- is true of the community and not of this page's services, so
# its picks never fall back to the rest.
HOME_FAQS = (('sahayak', None),
             ('companion', ('faq_start_parents', 'faq_match_how', 'faq_start_countries')),
             ('insurance', ('faq_ins_08', 'faq_ins_04', 'faq_ins_02', 'faq_ins_06')))
FAQS_FIRST = 3


def _reviews():
    """Approved reviews with words, the ones hand-picked for the home page first, newest first."""
    from app.models import REVIEW_SITE_LABELS, Feedback
    rows = (Feedback.query.filter(Feedback.is_approved.is_(True), Feedback.comment.isnot(None))
            .order_by(Feedback.is_featured.desc(), Feedback.created_at.desc()).limit(REVIEWS_SHOWN * 2).all())
    out = []
    for fb in rows:
        quote = (fb.comment or '').strip()
        if not quote:
            continue
        user = fb.user
        out.append({'quote': quote, 'rating': fb.rating, 'name': user.username if user else 'A customer',
                    'photo': (user.photo_url or '') if (user and user.show_photo) else '',
                    'service': REVIEW_SITE_LABELS.get(fb.site or 'companion', '')})
    return out[:REVIEWS_SHOWN]


def _faqs():
    """The questions in HOME_FAQS, each with the service it is about."""
    from app.services import help_center
    out = []
    for site, ids in HOME_FAQS:
        rows = help_center.faqs(site)
        if ids is None:
            picked = rows[:FAQS_FIRST]
        else:
            by_id = {f.get('id'): f for f in rows}
            picked = [by_id[i] for i in ids if i in by_id]
        out += [{'question': f['question'], 'answer': f['answer'], 'service': help_center.SITE_LABELS[site]}
                for f in picked]
    return out


def _prices():
    """{'sahayak': '₹149', 'insurance': 'From $1/day'}: the lowest Sahayak price from its catalogue
    (what the Sahayak page shows) and the insurance page's own "from" line; '' where unknown."""
    from app.services import insurance_page, sahayak
    try:
        amounts = [int(s['price']) for s in sahayak.services() if str(s.get('price') or '').isdigit()]
    except Exception:          # noqa: BLE001 -- the catalogue is somebody else's API: no price, no page error
        amounts = []
    return {'sahayak': '₹%d' % min(amounts) if amounts else '', 'insurance': insurance_page.price_from()}


def _contacts():
    from app.services import offices
    return {'phones': [{'label': p['label'], 'display': p['display'], 'digits': p['digits']}
                       for p in offices.numbers()],
            'email': offices.email()}


def _render(page):
    from app.services import nri_services, wp_blog
    home = page == 'home'
    return render_template('homepage_draft/landing.html', meta=PAGES[page], links={
        'chrome': False,
        'page': page,
        'reviews': _reviews() if home else [],
        'faqs': _faqs() if home else [],
        'prices': _prices() if home else {},
        'posts': wp_blog.latest(4) if home else [],
        'helpUrl': urls.public_url('main.help_page'),
        **_contacts(),
        'homeUrl': urls.public_url('homepage_draft.landing'),
        'aboutUrl': urls.public_url('homepage_draft.about'),
        'contactUrl': urls.public_url('main.contact_us'),
        'insuranceUrl': urls.public_url('insurance.landing'),
        'sahayakUrl': urls.public_url('sahayak.landing'),
        'companionUrl': urls.public_url('main.index'),
        'blogUrl': urls.public_url('blog.blog_list'),
        # the services the group runs on its other site: each one's own page
        'doctorUrl': nri_services.CALL_ON_DOC_URL,
        'giftUrl': nri_services.page_of('Gift Health'),
        'fitUrl': nri_services.page_of('Fit2Fly'),
    })


@homepage_draft_bp.route('/homepage-draft')
def landing():
    return _render('home')


@homepage_draft_bp.route('/about-us')
def about():
    return _render('about')
