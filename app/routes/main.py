from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from app import options
from flask_login import current_user, login_required
from app.models import CompanionRequest, Feedback, ConnectionRequest, TripLeg, TRIP_ROLES
from datetime import date
from app.services.ratelimit import rate_limit
import json, os, re

main_bp = Blueprint('main', __name__)


def _viewer_id():
    return current_user.id if current_user.is_authenticated else None


# Staff (CS / admin) work in their consoles only: the traveller screens redirect them there.
STAFF_REDIRECT_ENDPOINTS = {'main.index', 'main.all_trips', 'main.dashboard', 'main.connections_page', 'chat.inbox'}


def staff_home(user):
    """Where a staff account lands: admins on the admin panel, CS agents on the CS console."""
    from flask import url_for
    if user.is_admin:
        return url_for('admin.dashboard')
    if user.is_cs:
        return url_for('cs.home')
    return url_for('main.index')


def staff_view_active(user=None):
    """True while a CS/admin account uses the staff console (the default); multi-role accounts can switch.

    Safe outside a request (CLI jobs render e-mail templates, which runs the context processors)."""
    from flask import has_request_context
    if user is None:
        if not has_request_context():
            return False
        user = current_user
    if not getattr(user, 'is_authenticated', False):
        return False
    return bool(user.is_cs and session.get('view') != 'traveller')


@main_bp.before_app_request
def _staff_to_console():
    if request.endpoint in STAFF_REDIRECT_ENDPOINTS and staff_view_active():
        return redirect(staff_home(current_user))


@main_bp.app_context_processor
def _inject_staff_home():
    staff = staff_view_active()
    return {'staff_home': staff_home, 'is_staff': staff,
            'can_switch_view': bool(staff and current_user.is_traveller)}


@main_bp.route('/switch-view/<view>')
@login_required
def switch_view(view):
    """Accounts holding both a traveller role and a staff role flip between the two experiences."""
    if view == 'traveller':
        if not (current_user.is_cs and current_user.is_traveller):
            flash('This account has no traveller role.', 'danger')
            return redirect(staff_home(current_user))
        session['view'] = 'traveller'
        return redirect(url_for('main.dashboard'))
    session.pop('view', None)
    if view == 'cs' and current_user.is_cs:
        return redirect(url_for('cs.home'))
    if view == 'admin' and current_user.is_admin:
        return redirect(url_for('admin.dashboard'))
    return redirect(staff_home(current_user))


def _landing_structured_data(landing_faqs, review_stats):
    """JSON-LD for the public landing: WebSite + Organization + WebPage + Service (the standard
    brand-identity graph our SEO reviewer asked for), plus FAQPage (mirrors the on-page accordion
    exactly — Google requires that match) and AggregateRating only once there's enough real
    signal (same 'credible' threshold as the visible rating text, so the structured data can
    never claim more than the page itself does)."""
    from flask import current_app
    site = current_app.config['SITE_URL']
    page_title = 'Travel Companion | Find a Trusted Travel Buddy Online'
    page_description = ('Help your parents travel with confidence. Find a trusted travel companion '
                        'online for safe, caring and comfortable journeys, with support every step of the way.')
    graph = [
        {
            '@type': 'WebSite',
            '@id': f'{site}/#website',
            'url': f'{site}/',
            'name': 'Connecting Desis',
            'description': 'Find a trusted travel companion online for parents, senior citizens and solo travellers.',
            'publisher': {'@id': f'{site}/#organization'},
            'inLanguage': 'en',
        },
        {
            '@type': 'Organization',
            '@id': f'{site}/#organization',
            'name': 'Connecting Desis',
            'url': f'{site}/',
            'logo': f'{site}/static/img/logo-icon.png',
            'description': 'Connecting Desis helps parents, senior citizens and travellers find trusted '
                           'companions travelling on the same route.',
            'contactPoint': {'@type': 'ContactPoint', 'contactType': 'customer support',
                             'email': current_app.config['SUPPORT_EMAIL'], 'availableLanguage': 'English'},
        },
        {
            '@type': 'WebPage',
            '@id': f'{site}/#webpage',
            'url': f'{site}/',
            'name': page_title,
            'description': page_description,
            'isPartOf': {'@id': f'{site}/#website'},
            'about': {'@id': f'{site}/#service'},
            'inLanguage': 'en',
        },
        {
            '@type': 'Service',
            '@id': f'{site}/#service',
            'name': 'Travel Companion Service',
            'serviceType': 'Travel Companion Matching',
            'description': 'A trusted travel companion matching service that helps parents, senior citizens '
                           'and solo travellers find fellow travellers on the same route.',
            'provider': {'@id': f'{site}/#organization'},
            'areaServed': {'@type': 'Place', 'name': 'Worldwide'},
            'audience': {'@type': 'Audience',
                        'audienceType': 'Parents, Senior Citizens, Solo Travellers and Desi Travellers'},
            'url': f'{site}/',
        },
    ]
    service_node = graph[3]
    if review_stats.get('credible'):
        service_node['aggregateRating'] = {
            '@type': 'AggregateRating', 'ratingValue': review_stats['avg'],
            'reviewCount': review_stats['count'], 'bestRating': 5, 'worstRating': 1,
        }
    if landing_faqs:
        graph.append({
            '@type': 'FAQPage',
            'mainEntity': [{'@type': 'Question', 'name': f['question'],
                            'acceptedAnswer': {'@type': 'Answer', 'text': f['answer']}}
                          for f in landing_faqs],
        })
    return {'@context': 'https://schema.org', '@graph': graph}


def _review_stats():
    """Honest rating summary computed straight from SQL. Below a handful of reviews, a specific
    average reads as invented, so callers show generic praise instead until there is enough
    real signal."""
    from sqlalchemy import func
    from app import db
    count, avg = db.session.query(func.count(Feedback.id), func.avg(Feedback.rating)) \
        .filter(Feedback.is_approved.is_(True)).one()
    return {'avg': round(avg, 1) if avg is not None else None, 'count': count or 0,
            'credible': (count or 0) >= 3}


@main_bp.route('/')
def index():
    # Featured reviews (hand-picked by CS/admin) show on the public face — now the landing.
    approved_feedback = (Feedback.query.filter_by(is_approved=True, is_featured=True)
                         .order_by(Feedback.created_at.desc()).limit(6).all())
    if not approved_feedback:   # nothing hand-picked yet: the newest approved keep the section alive
        approved_feedback = Feedback.query.filter_by(is_approved=True).order_by(Feedback.created_at.desc()).limit(6).all()
    review_stats = _review_stats()
    # The public marketing landing is the face of the app; the functional home (post form +
    # Desis on Move) is for signed-in travellers only. Admins can force a preview.
    preview = request.args.get('preview') == 'landing' and current_user.is_authenticated and current_user.is_admin
    if not current_user.is_authenticated or preview:
        from app.services import settings as _settings, help_center
        # Admin-managed FAQs (same content that backs /help) — flattened in category order so
        # the landing page's "before you travel" accordion is never a copy an admin can't edit.
        landing_faqs = [f for _cat, items in help_center.grouped() for f in items]
        return render_template('landing.html', feedbacks=approved_feedback, review_stats=review_stats,
                               landing_colors=_settings.landing_settings()['colors'],
                               country_meta=COUNTRY_META, landing_faqs=landing_faqs,
                               structured_data=_landing_structured_data(landing_faqs, review_stats),
                               **_landing_live_data())
    return render_template('index.html', feedbacks=approved_feedback, review_stats=review_stats,
                           **_home_status())


# Small display map for the countries a trip's destination airport resolves to: flag + full
# name for the codes we actually see traffic to. Anything else falls back to its raw code.
COUNTRY_META = {
    'IN': ('India', '\U0001F1EE\U0001F1F3'), 'US': ('United States', '\U0001F1FA\U0001F1F8'),
    'GB': ('United Kingdom', '\U0001F1EC\U0001F1E7'), 'CA': ('Canada', '\U0001F1E8\U0001F1E6'),
    'AU': ('Australia', '\U0001F1E6\U0001F1FA'), 'AE': ('United Arab Emirates', '\U0001F1E6\U0001F1EA'),
    'DE': ('Germany', '\U0001F1E9\U0001F1EA'), 'QA': ('Qatar', '\U0001F1F6\U0001F1E6'),
    'SG': ('Singapore', '\U0001F1F8\U0001F1EC'), 'FR': ('France', '\U0001F1EB\U0001F1F7'),
}


def _home_status():
    """Lightweight numbers for the signed-in home's compact "welcome back" strip — a status
    summary, not marketing. Cheap on purpose: this runs on every home-page view."""
    from app import db
    from app.models import Match, ChatRoom, ChatMessage
    trip_ids = [r[0] for r in db.session.query(CompanionRequest.id)
                .filter_by(user_id=current_user.id).all()]
    trips_count = len(trip_ids)
    matches_count = 0
    if trip_ids:
        from sqlalchemy import or_
        matches_count = Match.query.filter(
            Match.status.in_(['suggested', 'connected']),
            or_(Match.trip_a_id.in_(trip_ids), Match.trip_b_id.in_(trip_ids))).count()
    unread_count = ChatMessage.query.join(ChatRoom).filter(
        ((ChatRoom.user1_id == current_user.id) | (ChatRoom.user2_id == current_user.id)),
        ChatMessage.sender_id != current_user.id,
        ChatMessage.is_read.is_(False)).count()
    return {'home_stats': {'trips': trips_count, 'matches': matches_count, 'unread': unread_count}}


def _landing_live_data():
    """Real, anonymity-safe data for the public landing so it is the same product as the
    signed-in app: a teaser of upcoming public trips, and honest headline numbers. Uses the
    same visibility rule as /trips and /api/search (open/matched, not yet departed)."""
    from datetime import date as _date
    from sqlalchemy import func
    from app import db, options
    from app.models import Airport
    today = _date.today()
    public = CompanionRequest.query.filter(
        CompanionRequest.status.in_(['open', 'matched']),
        (CompanionRequest.from_date == None) | (CompanionRequest.from_date >= today))  # noqa: E711
    # Newest posts first, so a trip someone just posted shows up on the landing right away.
    teaser = (public.filter(CompanionRequest.from_date.isnot(None))
              .order_by(CompanionRequest.created_at.desc()).limit(4).all())
    open_count = public.count()
    travellers = (db.session.query(func.count(func.distinct(CompanionRequest.user_id)))
                  .filter(CompanionRequest.status.in_(['open', 'matched']),
                          CompanionRequest.user_id.isnot(None)).scalar() or 0)
    dest_codes = [c for (c,) in public.with_entities(CompanionRequest.dest_iata).distinct() if c]
    countries = 0
    country_counts = {}
    if dest_codes:
        countries = (db.session.query(func.count(func.distinct(Airport.country)))
                     .filter(Airport.iata.in_(dest_codes), Airport.country.isnot(None)).scalar() or 0)
        rows = (db.session.query(Airport.country, func.count(CompanionRequest.id))
                .join(CompanionRequest, CompanionRequest.dest_iata == Airport.iata)
                .filter(CompanionRequest.status.in_(['open', 'matched']),
                        (CompanionRequest.from_date == None) | (CompanionRequest.from_date >= today),  # noqa: E711
                        Airport.country.isnot(None))
                .group_by(Airport.country).all())
        country_counts = {code: n for code, n in rows}
    return {
        'landing_trips': [t.to_dict() for t in teaser],
        'landing_stats': {'open': open_count, 'travellers': travellers,
                          'languages': len(options.LANGUAGES or []), 'countries': countries},
        'landing_country_counts': country_counts,
    }


@main_bp.route('/reviews')
def reviews():
    """Public reviews page: every approved review (not just the hand-picked few featured on the
    landing), and — for signed-in travellers — the same "leave a review" form as the home page.
    This is what the landing's "Read all reviews" and the app footer's "Reviews" link point to."""
    feedbacks = (Feedback.query.filter_by(is_approved=True)
                .order_by(Feedback.created_at.desc()).limit(60).all())
    return render_template('pages/reviews.html', feedbacks=feedbacks, review_stats=_review_stats())


@main_bp.route('/robots.txt')
def robots_txt():
    from flask import Response, current_app
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin/\n"
        "Disallow: /cs/\n"
        "Disallow: /api/\n"
        "Disallow: /dashboard\n"
        "Disallow: /connections\n"
        "Disallow: /settings/\n"
        f"Sitemap: {current_app.config['SITE_URL']}/sitemap.xml\n"
    )
    return Response(body, mimetype='text/plain')


@main_bp.route('/sitemap.xml')
def sitemap_xml():
    """Every public, indexable page. Blog posts are included dynamically so a new post is
    discoverable without a code change."""
    from flask import Response, current_app
    from app.models import Blog
    site = current_app.config['SITE_URL']
    today = date.today().isoformat()
    urls = [
        (f'{site}/', 'daily', '1.0', today),
        (f'{site}/trips', 'hourly', '0.9', today),
        (f'{site}/blog', 'daily', '0.7', today),
        (f'{site}/reviews', 'daily', '0.6', today),
        (f'{site}/about', 'monthly', '0.5', today),
        (f'{site}/contact', 'monthly', '0.5', today),
        (f'{site}/help', 'monthly', '0.5', today),
        (f'{site}/terms', 'yearly', '0.2', today),
        (f'{site}/privacy', 'yearly', '0.2', today),
    ]
    posts = Blog.query.filter_by(is_published=True).order_by(Blog.published_at.desc()).limit(500).all()
    for p in posts:
        lastmod = (p.updated_at or p.published_at or p.created_at)
        urls.append((f'{site}/blog/{p.slug}', 'monthly', '0.6',
                    lastmod.date().isoformat() if lastmod else today))
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, freq, prio, lastmod in urls:
        xml.append(f'<url><loc>{loc}</loc><lastmod>{lastmod}</lastmod>'
                   f'<changefreq>{freq}</changefreq><priority>{prio}</priority></url>')
    xml.append('</urlset>')
    return Response('\n'.join(xml), mimetype='application/xml')


@main_bp.route('/about')
def about():
    return render_template('pages/about.html')


@main_bp.route('/terms')
def terms():
    return render_template('pages/terms.html')


@main_bp.route('/privacy')
def privacy():
    return render_template('pages/privacy.html')


def _validate_contact(form):
    """Shared by the /contact page and the home-page widget. Returns a list of errors."""
    from app.routes.auth import EMAIL_RE
    errors = []
    if not form['name']:
        errors.append('Please tell us your name.')
    if not EMAIL_RE.match(form['email'] or ''):
        errors.append('Please enter an e-mail address we can reply to.')
    if form['phone'] and not re.fullmatch(r'[\d\s()+-]{7,20}', form['phone']):
        errors.append('That phone number does not look right - digits, spaces, + and - only.')
    if len(form['message']) < 10:
        errors.append('Please write a little more so we can help (at least 10 characters).')
    return errors


def _save_contact(form):
    """Store the enquiry and let the CS team know. Returns the ContactMessage."""
    from app import db
    from app.models import ContactMessage, ActivityEvent, User
    from app.services import notify
    msg = ContactMessage(
        name=form['name'][:120], email=form['email'].lower()[:255],
        phone=form['phone'][:30] or None, message=form['message'][:4000],
        user_id=current_user.id if current_user.is_authenticated else None)
    db.session.add(msg)
    db.session.flush()
    ActivityEvent.log('contact_message_received',
                      actor=(current_user if current_user.is_authenticated else None),
                      contact_id=msg.id, email=msg.email)
    for agent in User.query.filter(User.role.in_(['cs', 'admin']), User.is_active.is_(True)).limit(20).all():
        notify.push(agent.id, 'cs_escalation', title='New contact message',
                    body=f'{msg.name} <{msg.email}>: {msg.message[:90]}', link='/cs/contact')
    db.session.commit()
    return msg


def _contact_fields(src):
    return {k: (src.get(k) or '').strip() for k in ('name', 'email', 'phone', 'message')}


@main_bp.route('/contact', methods=['GET', 'POST'])
@rate_limit(6, 3600)
def contact():
    """Contact us. Works signed-out on purpose - someone who cannot log in most needs it."""
    form = {}
    if request.method == 'POST':
        form = _contact_fields(request.form)
        errors = _validate_contact(form)
        if not errors:
            msg = _save_contact(form)
            flash('Thanks - we have your message and will reply to ' + msg.email + '.', 'success')
            return redirect(url_for('main.contact'))
        for e in errors:
            flash(e, 'danger')
    return render_template('pages/contact.html', form=form)


@main_bp.route('/api/contact', methods=['POST'])
@rate_limit(6, 3600)
def api_contact():
    """Same thing from the home-page widget, without leaving the page."""
    form = _contact_fields(request.get_json(silent=True) or request.form)
    errors = _validate_contact(form)
    if errors:
        return jsonify({'success': False, 'error': ' '.join(errors)}), 400
    msg = _save_contact(form)
    return jsonify({'success': True,
                    'message': f'Thanks — we have your message and will reply to {msg.email}.'})


@main_bp.route('/api/landing-contact', methods=['POST'])
@rate_limit(6, 3600)
def api_landing_contact():
    """The landing 'Request a call back' form: store it as a CS message (as usual) and, when an
    admin has enabled it, also e-mail the configured address. That e-mail is the only mail toggle
    the admin controls here — nothing else."""
    form = _contact_fields(request.get_json(silent=True) or request.form)
    errors = _validate_contact(form)
    if errors:
        return jsonify({'success': False, 'error': ' '.join(errors)}), 400
    msg = _save_contact(form)
    from app.services import settings as _settings, mailer
    ls = _settings.landing_settings()
    if ls['contact_email_enabled'] and ls['contact_email']:
        body = (f"New enquiry from the Connecting Desis landing page.\n\n"
                f"Name: {msg.name}\nEmail: {msg.email}\nPhone: {msg.phone or '—'}\n\n"
                f"Message:\n{msg.message}\n")
        mailer.send(f'Landing enquiry from {msg.name}', ls['contact_email'], body,
                    reply_to=msg.email, force=True)
    return jsonify({'success': True,
                    'message': f'Thanks — we have your message and will reply to {msg.email}.'})


# The travel-insurance partner whose embeddable "Visitors Insurance for USA" widget we were given.
# Its quote form POSTs this JSON shape to this endpoint and opens the returned results page.
INSURANCE_PARTNER = 'https://preventia360.brokersnexus.com'


@main_bp.route('/api/insurance-quote', methods=['POST'])
@rate_limit(12, 3600)
def api_insurance_quote():
    """Landing 'Travel insurance' drawer: our own fields in our own styling, priced by the
    partner's widget API (the exact request its iframe makes). We validate, relay, and return
    the partner's quote-results URL. Nothing is stored on our side."""
    import json as _json
    import urllib.request
    import urllib.error
    from datetime import datetime, date as _date
    data = request.get_json(silent=True) or {}

    def _day(key):
        try:
            return datetime.strptime(str(data.get(key, '') or '').strip(), '%Y-%m-%d').date()
        except ValueError:
            return None

    start, end = _day('start_date'), _day('end_date')
    if not start or start < _date.today():
        return jsonify({'success': False, 'error': 'Pick a coverage start date from today onwards.'}), 400
    if not end or end < start:
        return jsonify({'success': False, 'error': 'The coverage end date must be on or after the start date.'}), 400
    ages = []
    for key in ('age1', 'age2'):
        raw = str(data.get(key, '') or '').strip()
        if not raw and key == 'age2':
            continue
        if not raw.isdigit() or int(raw) > 120:
            return jsonify({'success': False, 'error': 'Traveller ages must be whole numbers (years).'}), 400
        ages.append(str(int(raw)))
    citizenship = str(data.get('citizenship', '') or '').strip().upper()
    if not re.fullmatch(r'[A-Z]{3}', citizenship):
        return jsonify({'success': False, 'error': 'Please choose the country of citizenship.'}), 400

    payload = {
        'travelerInfos': [{'age': a, 'dependentChild': False, 'tripCost': None, 'bdate': None} for a in ages],
        'numChildren': '', 'startDate': start.strftime('%m/%d/%Y'), 'endDate': end.strftime('%m/%d/%Y'),
        'citizenshipCountry': citizenship, 'policyMaximum': -1, 'primaryDestination': 'USA',
        'coverageArea': '5', 'arrivalInUSA': '0', 'mailingState': 'OutsideUSA',
        'physicalPresenceState': '', 'homeCountry': '', 'section': 'visitorUSA',
    }
    req = urllib.request.Request(
        INSURANCE_PARTNER + '/api/compare/travel-medical', data=_json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                 'User-Agent': 'ConnectingDesis/1.0 (+landing insurance drawer)',
                 'Referer': INSURANCE_PARTNER + '/widget1/visitors-insurance/'},
        method='POST')
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = _json.loads(resp.read().decode('utf-8', 'ignore'))
    except (urllib.error.URLError, ValueError, OSError):
        return jsonify({'success': False, 'error': 'Our insurance partner is not responding right now. '
                        'Please try again in a moment, or use their form below.'}), 502
    info = body.get('data') or {}
    if body.get('status') == 'success' and info.get('redirectToBN'):
        path = str(info['redirectToBN'])
        return jsonify({'success': True, 'url': path if path.startswith('http') else INSURANCE_PARTNER + path})
    msgs = info.get('allErrorMessages') or info.get('globalErrors') or []
    text = ' '.join((m.get('message', '') if isinstance(m, dict) else str(m)) for m in msgs).strip()
    if not text:
        text = 'No plans found for these details.' if info.get('noPlansFound') else 'Our partner could not price this trip.'
    return jsonify({'success': False, 'error': text}), 400


@main_bp.route('/help')
def help_page():
    """Topic index. Each category links to its own page rather than filtering in place."""
    from app.services import help_center
    grouped = help_center.grouped()
    # flat index so the topic page can search every answer and link straight to its page
    index = [{'q': f['question'], 'a': f['answer'], 'id': f['id'], 'cat': cat['title'],
              'url': url_for('main.help_category', category=cat['key'])}
             for cat, items in grouped for f in items]
    return render_template('pages/help.html', grouped=grouped, faq_index=index,
                           faq_total=len(index))


@main_bp.route('/help/<category>')
def help_category(category):
    """One category's questions, with a way back to the index."""
    from flask import abort
    from app.services import help_center
    grouped = help_center.grouped()
    match = next(((c, items) for c, items in grouped if c['key'] == category), None)
    if match is None:
        abort(404)
    cat, items = match
    keys = [c['key'] for c, _ in grouped]
    i = keys.index(category)
    return render_template('pages/help_category.html', cat=cat, items=items,
                           prev_cat=(grouped[i - 1][0] if i > 0 else None),
                           next_cat=(grouped[i + 1][0] if i + 1 < len(grouped) else None),
                           total_cats=len(grouped))


@main_bp.route('/api/airports')
def airport_search():
    q = request.args.get('q', '').strip().lower()
    if len(q) < 2:
        return jsonify([])
    from app.services import locations
    # Rank by how well each airport matches, so "del" surfaces Delhi (DEL) before Adelaide
    # or "Ciudad del Este". Lower score = better; we sort then take the top 8. Without this
    # the list was in file order and cut off at 8, hiding the airport people actually meant.
    scored = []
    for a in locations.all_airports():
        iata = (a.get('iata') or '').lower()
        city = (a.get('city') or '').lower()
        name = (a.get('name') or '').lower()
        if iata == q:
            rank = 0
        elif iata.startswith(q):
            rank = 1
        elif city.startswith(q):
            rank = 2
        elif name.startswith(q):
            rank = 3
        elif q in city or q in iata:
            rank = 4
        elif q in name:
            rank = 5
        else:
            continue
        scored.append((rank, len(city), city, a))
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    results = [{'iata': a.get('iata'), 'name': a.get('name'), 'city': a.get('city'), 'country': a.get('country')}
               for _, _, _, a in scored[:8]]
    return jsonify(results)


@main_bp.route('/api/airlines')
def airline_search():
    q = request.args.get('q', '').strip().lower()
    if len(q) < 2:
        return jsonify([])
    results = []
    from app.services import airlines as airlines_svc
    for a in airlines_svc.all_airlines():
        name = a['name'].lower()
        iata = a['iata'].lower()
        if name.startswith(q) or iata.startswith(q) or q in name:
            results.append(a)
            if len(results) == 8:
                break
    return jsonify(results)


@main_bp.route('/trips')
def all_trips():
    return render_template('trips/all_trips.html')


@main_bp.route('/api/search', methods=['POST'])
def search():
    data = request.get_json(silent=True) or request.form
    sort = data.get('sort', 'newest')
    q = (data.get('q') or '').strip()
    try:
        limit = int(data.get('limit', 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))

    query = CompanionRequest.query.filter(
        CompanionRequest.status.in_(['open', 'matched']),
        CompanionRequest.travel_type == 'air',
    )

    # Hide departed trips
    today = date.today()
    query = query.filter(
        (CompanionRequest.from_date == None) | (CompanionRequest.from_date >= today)  # noqa: E711
    )

    # Optional field filters. Route terms are checked against every leg as well as the
    # post's overall origin and destination, so a search for Dubai finds an itinerary that
    # merely passes through it -- the same legs the matcher pairs on.
    if data.get('flying_from'):
        pat = f"%{data['flying_from']}%"
        query = query.filter(
            CompanionRequest.flying_from.ilike(pat) | CompanionRequest.origin_iata.ilike(pat)
            | CompanionRequest.leg_rows.any(
                TripLeg.origin_text.ilike(pat) | TripLeg.origin_iata.ilike(pat)))
    if data.get('destination'):
        pat = f"%{data['destination']}%"
        query = query.filter(
            CompanionRequest.destination.ilike(pat) | CompanionRequest.dest_iata.ilike(pat)
            | CompanionRequest.leg_rows.any(
                TripLeg.dest_text.ilike(pat) | TripLeg.dest_iata.ilike(pat)))
    if data.get('dest_country'):
        # Landing "Popular destinations" cards: every airport in that country (ISO-2 code),
        # the same join the landing's per-country counts use.
        from app import db
        from app.models import Airport
        code = str(data['dest_country']).strip().upper()[:2]
        in_country = db.session.query(Airport.iata).filter(Airport.country == code)
        query = query.filter(CompanionRequest.dest_iata.in_(in_country))
    if data.get('role') in TRIP_ROLES:
        # An explicit browse filter: "show me posts with this role" (the dashboard's
        # Seeking / Offering dropdown).
        query = query.filter(CompanionRequest.role == data['role'])
    elif data.get('for_role') in TRIP_ROLES:
        # ...and this is the other question: "I am this role -- who suits me?" The home
        # page sends the role from the post form, and someone who needs a companion needs
        # to see people offering help, not the other 30 people who also need one.
        want = {'seeking_help': ['offering_help', 'open'],
                'offering_help': ['seeking_help', 'open']}.get(data['for_role'])
        if want:
            query = query.filter(CompanionRequest.role.in_(want))
    if data.get('language'):
        from sqlalchemy import cast, String
        query = query.filter(cast(CompanionRequest.preferred_languages, String).ilike(f"%{data['language']}%"))
    if data.get('days'):
        try:
            from datetime import timedelta as _td2
            query = query.filter(CompanionRequest.from_date <= today + _td2(days=int(data['days'])))
        except (TypeError, ValueError):
            pass
    if data.get('from_date'):
        try:
            from datetime import datetime as _dt, timedelta as _td
            d = _dt.strptime(data['from_date'], '%Y-%m-%d').date()
            # The filter panel sends an explicit +/- window (0 = that day only); without
            # one, keep the historical default of 3 days, or 7 when marked flexible.
            try:
                window = max(0, min(int(data.get('flex_days')), 30))
            except (TypeError, ValueError):
                window = 7 if data.get('from_date_flexible') in ('on', 'true', True) else 3
            query = query.filter(CompanionRequest.from_date >= d - _td(days=window),
                                 CompanionRequest.from_date <= d + _td(days=window))
        except ValueError:
            pass

    # Filter-panel fields (all optional; absent means "don't filter on this")
    truthy = (True, 'true', 'on', '1', 1)
    if data.get('booking') in ('booked', 'planned'):
        if data['booking'] == 'booked':
            query = query.filter(CompanionRequest.ticket_booked.is_(True))
        else:
            query = query.filter((CompanionRequest.ticket_booked.is_(False))
                                 | (CompanionRequest.ticket_booked.is_(None)))
    trip_types = data.get('trip_types')
    if isinstance(trip_types, str):
        trip_types = [t.strip() for t in trip_types.split(',') if t.strip()]
    trip_types = [t for t in (trip_types or []) if t in ('one_way', 'round_trip', 'multi_destination')]
    if trip_types:
        clause = CompanionRequest.trip_type.in_(trip_types)
        if 'one_way' in trip_types:   # legacy/blank trip_type counts as a one-way
            clause = clause | (CompanionRequest.trip_type.is_(None))
        query = query.filter(clause)
    genders = data.get('genders')
    if isinstance(genders, str):
        genders = [g.strip() for g in genders.split(',') if g.strip()]
    if genders:
        query = query.filter(CompanionRequest.traveler_gender.in_(genders))
    if data.get('verified_only') in truthy:
        from app.models import User
        query = query.join(User, CompanionRequest.user_id == User.id).filter(User.is_verified.is_(True))

    # Free-text search across route fields
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            CompanionRequest.flying_from.ilike(pattern) |
            CompanionRequest.destination.ilike(pattern) |
            CompanionRequest.origin_iata.ilike(pattern) |
            CompanionRequest.dest_iata.ilike(pattern) |
            CompanionRequest.airline.ilike(pattern) |
            CompanionRequest.flight_number.ilike(pattern)
        )

    if sort == 'date':
        query = query.order_by(CompanionRequest.from_date.asc())
    elif sort == 'destination':
        query = query.order_by(CompanionRequest.destination.asc())
    else:
        query = query.order_by(CompanionRequest.created_at.desc())

    try:
        offset = max(int(data.get('offset', 0)), 0)
    except (TypeError, ValueError):
        offset = 0
    total = query.count()
    results = query.offset(offset).limit(limit).all()
    vid = _viewer_id()
    # Flag the posts that already match something the viewer posted, so they stand out while
    # browsing everyone's trips.
    mine_map = {}
    if current_user.is_authenticated:
        from app.services import matching
        mine_map = matching.matches_for_user(current_user)
    out = []
    for r in results:
        d = r.to_dict(viewer_id=vid)
        mm = mine_map.get(r.id)
        if mm and not d['is_own']:
            d['match_to_me'] = mm
        out.append(d)
    return jsonify({'results': out, 'count': len(out), 'total': total, 'offset': offset})


@main_bp.route('/dashboard')
@login_required
def dashboard():
    from app.services import matching
    my_posts = (CompanionRequest.query.filter_by(user_id=current_user.id)
                .order_by(CompanionRequest.created_at.desc()).all())
    match_rows = []
    for t in my_posts:
        if not t.is_public:
            continue
        for m in matching.ranked_matches_for(t):
            other = m.other_trip(t.id)
            match_rows.append({'trip': t, 'match': m, 'other': other,
                               'my_leg': m.leg_for(t.id), 'their_leg': m.other_leg(t.id),
                               'mine': m.party_for(t.id), 'theirs': m.party_for(other.id)})
    match_rows.sort(key=lambda r: (r['match'].status == 'connected', -r['match'].score))
    return render_template('dashboard.html', my_posts=my_posts, match_rows=match_rows)


@main_bp.route('/settings/notifications', methods=['GET', 'POST'])
@login_required
def notification_settings():
    """Per-user notification preferences: mute all, no e-mail, or mute individual kinds."""
    from flask import redirect, url_for, flash
    from app import db
    from app.models import USER_PREF_CATEGORIES, NOTIFY_CATEGORY_LABELS
    from app.services import notify, settings as app_settings
    if request.method == 'POST':
        prefs = {'muted': request.form.get('muted') == 'on', 'email': request.form.get('email') == 'on'}
        for c in USER_PREF_CATEGORIES:
            prefs[c] = request.form.get(f'cat_{c}') == 'on'
        current_user.notify_prefs = prefs
        db.session.commit()
        flash('Notification settings saved.', 'success')
        return redirect(url_for('main.notification_settings'))
    return render_template('settings_notifications.html', prefs=notify.user_prefs(current_user),
                           categories=USER_PREF_CATEGORIES, labels=NOTIFY_CATEGORY_LABELS,
                           global_sw=app_settings.notification_switches())


@main_bp.route('/api/language', methods=['POST'])
def set_language():
    """Persist the visitor's language choice: a cookie for everyone, the profile column when signed in."""
    data = request.get_json(silent=True) or {}
    lang = str(data.get('lang') or 'en').split('-')[0].lower()[:8]
    if not lang.isalpha() or not 2 <= len(lang) <= 3:
        lang = 'en'
    if current_user.is_authenticated:
        from app import db
        current_user.language_preference = lang
        db.session.commit()
    resp = jsonify({'success': True, 'lang': lang})
    if lang == 'en':
        resp.delete_cookie('lang')
    else:
        resp.set_cookie('lang', lang, max_age=31536000, samesite='Lax')
    return resp


@main_bp.route('/connections')
@login_required
def connections_page():
    return render_template('connections.html')


@main_bp.route('/api/my-connections')
@login_required
def my_connections():
    # Requests I sent
    sent = ConnectionRequest.query.filter_by(requester_id=current_user.id).order_by(
        ConnectionRequest.created_at.desc()
    ).all()

    # Requests I received (on my trips)
    my_trip_ids = [t.id for t in CompanionRequest.query.filter_by(user_id=current_user.id).all()]
    received = ConnectionRequest.query.filter(
        ConnectionRequest.trip_id.in_(my_trip_ids)
    ).order_by(ConnectionRequest.created_at.desc()).all() if my_trip_ids else []

    def serialize(conn, role):
        trip = conn.trip
        travel_date = (trip.from_date or trip.road_from_date)
        if role == 'sent':
            if not conn.recipient_anonymous and trip.author:
                other_user = {'username': trip.author.username,
                              'photo_url': trip.author.photo_url if trip.author.show_photo else None}
            elif not conn.recipient_anonymous and not trip.author:
                other_user = {'username': trip.display_name, 'photo_url': None}
            else:
                other_user = {'username': 'Anonymous', 'photo_url': None}
        else:
            if not conn.requester_anonymous and conn.requester:
                other_user = {'username': conn.requester.username,
                              'photo_url': conn.requester.photo_url if conn.requester.show_photo else None}
            else:
                other_user = {'username': 'Anonymous', 'photo_url': None}

        return {
            'id': conn.id,
            'trip_id': trip.id,
            'route': trip.route_display,
            'travel_type': trip.travel_type,
            'travel_date': travel_date.isoformat() if travel_date else None,
            'status': conn.status,
            'role': role,
            'other_user': other_user,
            'created_at': conn.created_at.isoformat() if conn.created_at else None,
        }

    return jsonify({
        'sent': [serialize(c, 'sent') for c in sent],
        'received': [serialize(c, 'received') for c in received],
    })
