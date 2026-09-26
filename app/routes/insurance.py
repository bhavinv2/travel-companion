"""Travel insurance: the public landing page and the enquiries it produces.

The page is the React app in frontend/insurance, built into static/insurance and mounted by
templates/insurance/landing.html. Everything on it that is not marketing copy comes from the
places staff already manage, injected as window.__INSURANCE__ so the bundle never has to fetch
it separately:

  * testimonials  -> services/insurance_page.py  (Admin -> Insurance page)
  * FAQs          -> services/help_center.py, the 'travel_insurance' category
                     (Admin -> Help & FAQ, the same screen the rest of the site uses)
  * enquiries     -> ContactMessage with topic='insurance', so they land in the CS and admin
                     inboxes next to every other enquiry rather than in a second system
"""
import re

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.models import ActivityEvent, ContactMessage
from app.services import help_center, insurance_countries, insurance_page, settings, urls
from app.services.ratelimit import rate_limit

insurance_bp = Blueprint('insurance', __name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _faqs():
    """The insurance questions, in admin order, as {question, answer}.

    Falls back to the default set in insurance_page when nothing has been filed under the
    category. The fallback is resolved here rather than inside the bundle so that the page and
    its JSON-LD always declare the same questions -- schema that promises an answer the page does
    not show is the kind of thing search engines penalise.
    """
    rows = [f for f in help_center.faqs() if f.get('category') == insurance_page.FAQ_CATEGORY]
    if rows:
        return [{'question': f['question'], 'answer': f['answer']} for f in rows]
    return [{'question': q, 'answer': a} for q, a in insurance_page.DEFAULT_FAQS]


def _structured_data(faqs, phones, canonical):
    """What the page says, in the form a search engine reads.

    Only things the page actually shows go in here. The questions are the rendered ones, the
    numbers are the published ones, and there is no aggregateRating: we have no verified reviews,
    and inventing one is both dishonest and a manual penalty waiting to happen.
    """
    site = current_app.config.get('SITE_URL', '').rstrip('/') or request.host_url.rstrip('/')
    org = {
        '@type': 'Organization',
        'name': 'NRI Parent Service',
        'url': site,
        'email': current_app.config.get('SUPPORT_EMAIL', ''),
    }
    if phones:
        org['contactPoint'] = [{
            '@type': 'ContactPoint',
            'contactType': 'customer service',
            'telephone': '+' + p['digits'],
            'areaServed': 'IN' if p['label'] == 'India' else 'US',
            'availableLanguage': ['en', 'hi'],
        } for p in phones]
    return {
        '@context': 'https://schema.org',
        '@graph': [
            org,
            {
                '@type': 'WebPage',
                '@id': canonical,
                'url': canonical,
                'name': 'Travel Insurance for Every Journey',
                'isPartOf': {'@type': 'WebSite', 'name': 'NRI Parent Service', 'url': site},
            },
            {
                '@type': 'Service',
                'name': 'Travel and visitor insurance',
                'serviceType': 'Travel insurance comparison and purchase',
                'provider': org,
                'areaServed': 'Worldwide',
                'description': ('Quote and compare 65+ A-rated travel and visitor insurance plans '
                                'covering emergency medical treatment, hospitalisation, '
                                'evacuation and trip disruption.'),
            },
            {
                '@type': 'FAQPage',
                'mainEntity': [{
                    '@type': 'Question',
                    'name': f['question'],
                    'acceptedAnswer': {'@type': 'Answer', 'text': f['answer']},
                } for f in faqs],
            },
        ],
    }


def _canonical():
    """The address this page is meant to be found at.

    It answers on two: its own top-level path (the one people are given) and the same route
    inside the app's prefix (what url_for builds for internal links). Same page either way, so
    search engines are told which one counts rather than left to guess.
    """
    return urls.public_absolute('insurance.landing')


@insurance_bp.route('/travel-insurance')
def landing():
    # Sample testimonials are shown to staff so the section can be previewed, and withheld from
    # the public: three invented customers on an insurance page cost more trust than an absent
    # section does. Real ones are entered in Admin -> Insurance page.
    samples = insurance_page.is_using_samples()
    staff = current_user.is_authenticated and (current_user.is_admin or current_user.is_cs)
    # Both teams, each labelled, so the page can offer a caller the number in their own country
    # instead of one number and a long-distance charge. Unset numbers are left out rather than
    # shown: the rule everywhere else on the site is never to publish a line nobody answers.
    wa = (settings.whatsapp_numbers() or {})
    phones = [dict(label=label, **wa[key]) for key, label in (('in', 'India'), ('us', 'USA'))
              if wa.get(key)]
    faqs = _faqs()
    canonical = _canonical()
    return render_template('insurance/landing.html',
                           reviews=[] if (samples and not staff) else insurance_page.reviews(),
                           reviews_are_samples=samples,
                           faqs=faqs,
                           countries={name: code for code, name in insurance_countries.ALL},
                           whatsapp_number=phones[0]['digits'] if phones else '',
                           support_phones=phones,
                           # Claims about the business, blank until staff fill them in.
                           price_from=insurance_page.price_from(),
                           assurances=insurance_page.assurances(),
                           structured_data=_structured_data(faqs, phones, canonical),
                           canonical_url=canonical)


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
