"""Travel insurance: the public landing page and the enquiries it produces.

The page is the React app in frontend/insurance, built into static/insurance and mounted by
templates/insurance/landing.html. Everything on it that is not marketing copy comes from the
places staff already manage, injected as window.__INSURANCE__ so the bundle never has to fetch
it separately:

  * reviews       -> Feedback rows with site='insurance', once an admin approves them
                     (Admin -> Travel Insurance -> Feedback). The same pipeline the companion
                     app uses: somebody who bought cover writes one, a human reads it, it
                     appears. Nothing on the page is a testimonial we wrote.
  * FAQs          -> services/help_center.py, the travel-insurance questions
                     (Admin -> Travel Insurance -> Help & FAQ)
  * enquiries     -> ContactMessage with topic='insurance', so they land in the CS and admin
                     inboxes next to every other enquiry rather than in a second system
  * conversions   -> services/ads.py, which decides whether this request carries the Google Ads
                     tag at all and what the four conversion actions are called
"""
import re

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.models import ActivityEvent, ContactMessage, Feedback
from app.services import (ads, help_center, insurance_countries, insurance_page, org,
                          settings, urls)
from app.services.ratelimit import rate_limit

insurance_bp = Blueprint('insurance', __name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _faqs():
    """The insurance questions, in admin order, as {question, answer}.

    What the admin screen says and nothing else. There used to be a fallback list here for when
    nothing had been filed under the category, which meant the page could show answers that
    appeared on no screen anybody could edit. Those answers are shipped defaults in the help
    centre now, so they are visible and editable in Admin -> Travel Insurance -> Help & FAQ; if
    somebody deletes them all, the section goes away rather than being quietly refilled.
    """
    return [{'question': f['question'], 'answer': f['answer']}
            for f in help_center.faqs('insurance')]


# What the page says it is. These are the words search results show, so the page's own title
# and meta description are built from them too -- schema that describes a different page from
# the one it sits on is the thing that gets discounted.
PAGE_NAME = 'Buy Travel Insurance Online | Visitors Insurance for USA | NRI Parent Service'
PAGE_HEADLINE = 'Buy Travel & Visitor Insurance Online for USA'
PAGE_DESCRIPTION = ('Buy travel insurance online for parents, relatives and visitors travelling '
                    'to the USA. Compare travel and visitor insurance plans with expert guidance '
                    'from NRI Parent Service.')
SERVICE_DESCRIPTION = ('Travel and visitor insurance solutions for parents, relatives, families, '
                       'tourists, students, business travelers and NRIs travelling to the USA.')
AUDIENCE = ['NRIs', 'Parents', 'Tourists', 'International Students', 'Business Travelers',
            'Senior Travelers']


def _structured_data(faqs, phones, canonical):
    """What the page says, in the form a search engine reads.

    One block, one graph, joined by @id: the Organization here is the same entity the rest of the
    site names, and the WebPage hangs off the WebSite rather than floating on its own. A second
    <script> would have meant two Organizations with two identities, two WebPages for one URL and
    two FAQPages -- which is not extra coverage, it is a page that cannot say who it belongs to.

    Only things the page actually shows go in here. The questions are the rendered ones, the
    numbers are the published ones, and there is no aggregateRating: reviews come from the
    approved queue and inventing an average is both dishonest and a manual penalty waiting.
    """
    ids = org.identity()
    org_ref = {'@id': ids['org_id']}
    service_id = canonical + '#service'

    graph = [
        org.organization(phones),
        org.website(),
        {
            '@type': 'WebPage',
            '@id': canonical + '#webpage',
            'url': canonical,
            'name': PAGE_NAME,
            'headline': PAGE_HEADLINE,
            'description': PAGE_DESCRIPTION,
            'isPartOf': {'@id': ids['website_id']},
            'about': {'@id': service_id},
            'publisher': org_ref,
            'inLanguage': 'en-US',
        },
        {
            '@type': 'Service',
            '@id': service_id,
            'name': 'Travel Insurance',
            'serviceType': 'Travel and Visitor Insurance',
            'description': SERVICE_DESCRIPTION,
            'provider': org_ref,
            'url': canonical,
            'areaServed': [{'@type': 'Country', 'name': 'United States'},
                           {'@type': 'Country', 'name': 'India'}],
            'audience': {'@type': 'Audience', 'audienceType': AUDIENCE},
        },
    ]
    if faqs:
        # Generated from the questions the page renders, never a list of its own. A FAQPage
        # promising answers the page does not show is exactly what the penalties are for -- and
        # it is why these are edited in Admin -> Travel Insurance -> Help & FAQ and read back
        # from there, rather than written twice.
        graph.append({
            '@type': 'FAQPage',
            '@id': canonical + '#faq',
            'mainEntity': [{
                '@type': 'Question',
                'name': f['question'],
                'acceptedAnswer': {'@type': 'Answer', 'text': f['answer']},
            } for f in faqs],
        })
    return {'@context': 'https://schema.org', '@graph': graph}


def _reviews():
    """Approved travel-insurance reviews, newest first, shaped the way the bundle reads them.

    Real people who left a review on this product, passed by a human first -- the same pipeline
    and the same moderation queue the companion app has always used. The page showed three
    invented customers before this, which is worse than showing none: an insurance page trades
    on being believed.
    """
    rows = (Feedback.query.filter_by(is_approved=True, site='insurance')
            .order_by(Feedback.created_at.desc()).limit(12).all())
    out = []
    for fb in rows:
        user = fb.user
        # show_photo is the reviewer's own answer to "may my picture be shown". A review is a
        # more public place than the profile they set it on, so it is honoured here rather than
        # treated as being about one screen; the bundle draws an avatar when there is no photo.
        photo = (user.photo_url or '') if (user and user.show_photo) else ''
        out.append({
            'id': str(fb.id),
            'quote': (fb.comment or '').strip(),
            'name': (user.username if user else 'A traveller'),
            'place': '',                 # we do not ask a reviewer where they are
            'rating': fb.rating,
            'photo': photo,
            'tag': '',
        })
    # A star rating with no words says nothing on a page like this one.
    return [r for r in out if r['quote']]


def _canonical():
    """The address this page is meant to be found at.

    It answers on two: its own top-level path (the one people are given) and the same route
    inside the app's prefix (what url_for builds for internal links). Same page either way, so
    search engines are told which one counts rather than left to guess.
    """
    return urls.public_absolute('insurance.landing')


@insurance_bp.route('/travel-insurance')
def landing():
    # Both teams, each labelled, so the page can offer a caller the number in their own country
    # instead of one number and a long-distance charge. Unset numbers are left out rather than
    # shown: the rule everywhere else on the site is never to publish a line nobody answers.
    wa = (settings.whatsapp_numbers() or {})
    phones = [dict(label=label, **wa[key]) for key, label in (('in', 'India'), ('us', 'USA'))
              if wa.get(key)]
    faqs = _faqs()
    canonical = _canonical()
    # Reviews and questions are both lists that may legitimately be empty, and both sections
    # disappear when they are. An empty section is honest; a filled one that nobody wrote is not.
    return render_template('insurance/landing.html',
                           reviews=_reviews(),
                           # the reviews page lives inside the app, so url_for's prefix is
                           # the right one here -- it is not one of the alias front doors
                           reviews_url=url_for('main.reviews', site='insurance'),
                           faqs=faqs,
                           countries={name: code for code, name in insurance_countries.ALL},
                           whatsapp_number=phones[0]['digits'] if phones else '',
                           support_phones=phones,
                           # Claims about the business, blank until staff fill them in.
                           price_from=insurance_page.price_from(),
                           assurances=insurance_page.assurances(),
                           # Admin -> Insurance page overrides the site-wide address; empty falls
                           # back, so the field only has to be filled when it differs.
                           support_email=insurance_page.support_email(),
                           availability=insurance_page.availability(),
                           structured_data=_structured_data(faqs, phones, canonical),
                           canonical_url=canonical,
                           # empty on localhost and in tests, which removes the tag entirely
                           ads_account=ads.account_id() if ads.enabled() else '',
                           ads_conversions=ads.conversions(),
                           # the page's own title and description, so what the schema claims and
                           # what the page says are one decision rather than two
                           page_title=PAGE_NAME, page_description=PAGE_DESCRIPTION)


@insurance_bp.route('/travel-insurances')
def landing_plural():
    """The address briefly used before the singular one was settled on. A permanent redirect
    costs nothing and means a link shared in the meantime still lands.

    public_url, so the redirect lands on /travel-insurance rather than sending somebody who
    followed an old link into the prefixed copy of the same page.
    """
    return redirect(urls.public_url('insurance.landing'), code=301)


@insurance_bp.route('/api/insurance-enquiry', methods=['POST'])
@rate_limit(12, 3600)
def enquiry():
    """Everything the page collects about a person who wants to be contacted.

    Two forms arrive here. The lead forms ("discuss your cover with an expert", the welcome
    popup) send a name and a destination, then offer WhatsApp -- that hand-off is a convenience,
    this is the record, so an enquiry is never lost because somebody closed the tab. The Support
    popup sends the same contact details plus what they actually asked.

    Both become an ordinary ContactMessage tagged `insurance`, in the one inbox CS already works
    from. Nothing here needs a second place to check.
    """
    data = request.get_json(silent=True) or request.form
    support = (data.get('kind') or '').strip().lower() == 'support'
    name = (data.get('name') or '').strip()[:120]
    email = (data.get('email') or '').strip().lower()[:255]
    phone = (data.get('phone') or '').strip()[:30]
    destination = (data.get('destination') or '').strip()[:120]
    subject = (data.get('subject') or '').strip()[:120]
    preferred = (data.get('preferred') or '').strip()[:40]
    written = (data.get('message') or '').strip()[:3000]

    errors = []
    if not name:
        errors.append('Please tell us your name.')
    if not email or not EMAIL_RE.match(email):
        errors.append('A valid e-mail address is required.')
    if not phone:
        errors.append('A phone number is required so we can reach you.')
    # Only the support form has a message box, and a two-word one tells CS nothing they can act
    # on. The lead forms have no box at all, so the rule would be meaningless for them.
    if support and len(written) < 10:
        errors.append('Please write a little more so we can help (at least 10 characters).')
    if errors:
        return jsonify({'success': False, 'error': ' '.join(errors)}), 400

    if support:
        lines = ['Support request from the /travel-insurance page.']
        if subject:
            lines.append('About: %s' % subject)
        if preferred:
            lines.append('Preferred contact: %s' % preferred)
        lines.append('')
        lines.append(written)
        body = '\n'.join(lines)
    else:
        body = 'Travel insurance enquiry from the /travel-insurance page.'
        if destination:
            body += '\nDestination: %s' % destination

    msg = ContactMessage(
        user_id=current_user.id if current_user.is_authenticated else None,
        name=name, email=email, phone=phone, message=body[:4000], topic='insurance',
    )
    db.session.add(msg)
    db.session.commit()
    ActivityEvent.log('insurance_support' if support else 'insurance_enquiry',
                      actor=current_user if current_user.is_authenticated else None,
                      email=email, destination=destination or None)
    db.session.commit()
    return jsonify({'success': True}), 201
