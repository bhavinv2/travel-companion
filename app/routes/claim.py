"""Claim flow: a person invited by CS confirms their post and adds contact details (with consent)."""
import re
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import current_user, login_user

from app import db
from app.models import ClaimToken, ContactPoint, ActivityEvent, Notification, User
from app.services.contacts import parse_contact_rows
from app.services.ratelimit import rate_limit

claim_bp = Blueprint('claim', __name__)


def _unique_username(base):
    base = re.sub(r'[^a-z0-9]', '', (base or '').lower())[:30] or 'traveller'
    if len(base) < 3:
        base = (base + 'user')[:30]
    username, n = base, 1
    while User.query.filter_by(username=username).first():
        n += 1
        username = f'{base}{n}'
    return username


@claim_bp.route('/claim/<token>', methods=['GET', 'POST'])
@rate_limit(20, 600)
def claim_page(token):
    tok = ClaimToken.query.filter_by(token=token).first()
    if tok is None:
        return render_template('claim/invalid.html', reason='not_found'), 404
    trip = tok.trip
    if tok.used_at is not None or trip.claimed_at is not None:
        return render_template('claim/done.html', trip=trip, already=True)
    if not tok.is_valid:
        return render_template('claim/invalid.html', reason='expired'), 410
    if trip.status == 'closed':
        return render_template('claim/invalid.html', reason='closed'), 410

    show_route = current_app.config.get('CLAIM_SHOW_ROUTE', True)

    if request.method == 'POST':
        form = request.form
        name = (form.get('name') or '').strip()[:120]
        rows, errors = parse_contact_rows(form)
        consent = form.get('consent') == 'on'
        create_account = form.get('create_account') == 'on'
        password = form.get('password') or ''

        if not name:
            errors.append('Please tell us your name.')
        if not rows:
            errors.append('Add at least one way for a matched companion to reach you.')
        if not consent:
            errors.append('We need your consent to share your contact details with matched companions.')

        user = current_user if current_user.is_authenticated else None
        account_email = next((r['value'] for r in rows if r['type'] == 'email'), None)
        if user is None and create_account:
            if not account_email:
                errors.append('Add an e-mail contact to create an account.')
            elif User.query.filter_by(email=account_email).first():
                errors.append('An account with that e-mail already exists — please log in first, then open this link again.')
            elif len(password) < 8:
                errors.append('Password must be at least 8 characters.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('claim/claim.html', trip=trip, token=tok, show_route=show_route,
                                   form=form, contact_rows=rows)

        if user is None and create_account:
            first, _, last = name.partition(' ')
            user = User(email=account_email, username=_unique_username(first + last or first),
                        first_name=first, last_name=last, is_verified=False)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            login_user(user)
            from app.routes.auth import send_verification_email
            send_verification_email(user)

        # Consent given on this page applies to every contact point entered here.
        for r in rows:
            db.session.add(ContactPoint(trip=trip, user_id=user.id if user else None, type=r['type'],
                                        value=r['value'], label=r['label'] or None,
                                        consent_to_share=True, added_by='owner'))
        trip.poster_name = name
        if user is not None:
            trip.user_id = user.id
        trip.claimed_at = datetime.utcnow()
        trip.set_status('open')
        tok.used_at = datetime.utcnow()
        ActivityEvent.log('post_claimed', trip, actor=user, token_id=tok.id,
                          contact_types=sorted({r['type'] for r in rows}))
        if trip.created_by_id:
            db.session.add(Notification(user_id=trip.created_by_id, type='post_claimed',
                                        title='Post confirmed',
                                        body=f'{name} confirmed post #{trip.id} ({trip.route_display}).',
                                        link=f'/cs/posts/{trip.id}'))
        db.session.commit()
        from app.services import matching
        matching.compute_matches_for(trip, actor=user)
        flash('Thank you — your request is now live.', 'success')
        return render_template('claim/done.html', trip=trip, already=False)

    return render_template('claim/claim.html', trip=trip, token=tok, show_route=show_route,
                           form=None, contact_rows=[])
