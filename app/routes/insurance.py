"""Travel insurance: the public landing page and the enquiries it produces.

The page itself is a port of the standalone travel-insurance build (see
templates/insurance/landing.html). Everything on it that is not marketing copy comes from the
places staff already manage:

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
from app.services import help_center, insurance_page
from app.services.ratelimit import rate_limit

insurance_bp = Blueprint('insurance', __name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _faqs():
    """The insurance questions, in admin order. Falls back to every FAQ only if the category
    has not been created yet, so the section is never blank on a fresh install."""
    rows = [f for f in help_center.faqs() if f.get('category') == insurance_page.FAQ_CATEGORY]
    return rows


def _canonical():
    """The address this page is meant to be found at.

    It answers on two: its own top-level path (the one people are given) and the same route
    inside the app's prefix (what url_for builds for internal links). Same page either way, so
    search engines are told which one counts rather than left to guess.
    """
    aliases = current_app.config.get('APP_ALIAS_PATHS') or []
    if not aliases:
        return request.url
    return request.host_url.rstrip('/') + '/' + aliases[0].strip('/')


@insurance_bp.route('/travel-insurance')
def landing():
    # Sample testimonials are shown to staff so the section can be previewed, and withheld from
    # the public: three invented customers on an insurance page cost more trust than an absent
    # section does. Real ones are entered in Admin -> Insurance page.
    samples = insurance_page.is_using_samples()
    staff = current_user.is_authenticated and (current_user.is_admin or current_user.is_cs)
    return render_template('insurance/landing.html',
                           reviews=[] if (samples and not staff) else insurance_page.reviews(),
                           reviews_are_samples=samples,
                           price_from=insurance_page.price_from(),
                           assurances=insurance_page.assurances(),
                           faqs=_faqs(),
                           canonical_url=_canonical())


@insurance_bp.route('/travel-insurances')
def landing_plural():
    """The address briefly used before the singular one was settled on. A permanent redirect
    costs nothing and means a link shared in the meantime still lands."""
    return redirect(url_for('insurance.landing'), code=301)


@insurance_bp.route('/api/insurance-enquiry', methods=['POST'])
@rate_limit(12, 3600)
def enquiry():
    """"Discuss your travel cover with an expert" -- stored as a normal contact message.

    The page then offers to continue on WhatsApp; that is a convenience, not the record. The
    record is here, so an enquiry is never lost because somebody closed the tab.
    """
    data = request.get_json(silent=True) or request.form
    name = (data.get('name') or '').strip()[:120]
    email = (data.get('email') or '').strip().lower()[:255]
    phone = (data.get('phone') or '').strip()[:30]
    destination = (data.get('destination') or '').strip()[:120]

    errors = []
    if not name:
        errors.append('Please tell us your name.')
    if not email or not EMAIL_RE.match(email):
        errors.append('A valid e-mail address is required.')
    if not phone:
        errors.append('A phone number is required so we can reach you.')
    if errors:
        return jsonify({'success': False, 'error': ' '.join(errors)}), 400

    body = 'Travel insurance enquiry from the /travel-insurance page.'
    if destination:
        body += '\nDestination: %s' % destination

    msg = ContactMessage(
        user_id=current_user.id if current_user.is_authenticated else None,
        name=name, email=email, phone=phone, message=body, topic='insurance',
    )
    db.session.add(msg)
    db.session.commit()
    ActivityEvent.log('insurance_enquiry', actor=current_user if current_user.is_authenticated else None,
                      email=email, destination=destination or None)
    db.session.commit()
    return jsonify({'success': True}), 201
