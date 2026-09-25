"""Sahayak home healthcare: the public page and the booking requests it produces.

This phase is deliberately a request desk, not a dispatch system. Somebody asks for a visit, it
lands in the CS queue, an agent phones them and assigns a Sahayak by name. No worker app, no
automated matching, no card payment -- and nothing clinical is stored here yet, so a booking
holds only what is needed to turn up at the right door at the right time.
"""
import re
from datetime import datetime

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import current_user

from app import db
from app.models import ActivityEvent, SahayakBooking, SAHAYAK_WHEN
from app.services import help_center, sahayak
from app.services.ratelimit import rate_limit

sahayak_bp = Blueprint('sahayak', __name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
PHONE_RE = re.compile(r'[0-9]')


def _faqs():
    return [f for f in help_center.faqs() if f.get('category') == sahayak.FAQ_CATEGORY]


def _canonical():
    aliases = [a for a in (current_app.config.get('APP_ALIAS_PATHS') or []) if 'sahayak' in a]
    if not aliases:
        return request.url
    return request.host_url.rstrip('/') + '/' + aliases[0].strip('/')


@sahayak_bp.route('/sahayak')
def landing():
    return render_template('sahayak/landing.html',
                           services=sahayak.services(),
                           faqs=_faqs(),
                           canonical_url=_canonical())


@sahayak_bp.route('/api/sahayak-booking', methods=['POST'])
@rate_limit(10, 3600)
def book():
    """Take a request for a visit.

    Signing in is not required: the person booking is often an NRI arranging care for a parent,
    and sometimes the parent themselves. Making them register first would lose the booking.
    """
    data = request.get_json(silent=True) or request.form

    def get(key, limit=200):
        return (data.get(key) or '').strip()[:limit]

    service = sahayak.by_key(get('service', 40))
    patient_name = get('patient_name', 120)
    phone = get('phone', 30)
    email = get('email', 255).lower()
    address = get('address', 600)
    when_type = get('when_type', 12) or 'asap'
    scheduled_raw = get('scheduled_for', 32)

    errors = []
    if not service:
        errors.append('Choose which service you need.')
    if not patient_name:
        errors.append('Tell us who the visit is for.')
    if not phone or not PHONE_RE.search(phone):
        errors.append('A phone number is required — the team calls to confirm.')
    if email and not EMAIL_RE.match(email):
        errors.append('That e-mail address does not look right.')
    if not address:
        errors.append('We need the address to send somebody to.')
    if when_type not in SAHAYAK_WHEN:
        when_type = 'asap'

    scheduled_for = None
    if when_type == 'scheduled':
        try:
            scheduled_for = datetime.strptime(scheduled_raw, '%Y-%m-%dT%H:%M')
        except ValueError:
            errors.append('Pick a date and time for the visit.')
        else:
            if scheduled_for < datetime.now():
                errors.append('That time has already passed.')

    if errors:
        return jsonify({'success': False, 'error': ' '.join(errors)}), 400

    age = get('patient_age', 3)
    booking = SahayakBooking(
        user_id=current_user.id if current_user.is_authenticated else None,
        service_key=service['key'], service_name=service['name'], quoted_price=service.get('price'),
        patient_name=patient_name,
        patient_age=int(age) if age.isdigit() and 0 < int(age) < 130 else None,
        contact_name=get('contact_name', 120) or None,
        phone=phone, email=email or None,
        address=address, landmark=get('landmark', 200) or None,
        pincode=get('pincode', 12) or None, access_notes=get('access_notes', 300) or None,
        when_type=when_type, scheduled_for=scheduled_for,
        notes=get('notes', 2000) or None,
    )
    db.session.add(booking)
    db.session.commit()
    ActivityEvent.log('sahayak_booking', actor=current_user if current_user.is_authenticated else None,
                      booking_id=booking.id, service=service['key'], when=when_type)
    db.session.commit()
    return jsonify({'success': True, 'booking_id': booking.id,
                    'message': 'Request received. Our team will call %s to confirm.' % phone}), 201
