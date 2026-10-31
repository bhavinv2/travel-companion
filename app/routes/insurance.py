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
from datetime import date, datetime

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.models import ActivityEvent, ContactMessage, Feedback
from app.services import (ads, canada_quotes, help_center, insurance_countries, insurance_page, offices,
                          org, phone, settings, urls)
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
PAGE_NAME = 'Buy Travel Insurance Online | Visitor Insurance for the USA | NRI Parent Service'
PAGE_HEADLINE = 'Buy Travel & Visitor Insurance Online for the USA'
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
    # Every line staff have published for this page, each labelled, so a caller is offered the
    # number in their own country instead of one number and a long-distance charge. This used to
    # read the two whatsapp_in / whatsapp_us fields directly, which meant a third country could
    # be added on the admin screen and still never appear here. Unset numbers are left out
    # rather than shown: the rule everywhere else on the site is never to publish a line nobody
    # answers.
    phones = offices.numbers('insurance')
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
                           whatsapp_number=offices.whatsapp('insurance'),
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
                           # the same dialling codes the rest of the site validates against,
                           # so the bundle's picker and services/phone cannot disagree
                           dial_codes=[{'name': n, 'iso': i, 'dial': d}
                                       for i, n, d in phone.COUNTRIES],
                           # the page's own title and description, so what the schema claims and
                           # what the page says are one decision rather than two
                           page_title=PAGE_NAME, page_description=PAGE_DESCRIPTION,
                           # the link preview on WhatsApp and the rest. A 1200x630 crop of the
                           # hero rather than the hero itself: the full file is 341KB, past the
                           # size WhatsApp's fetcher will take, and a skipped image is why this
                           # page previewed as a bare logo.
                           share_image=url_for('static',
                                               filename='img/share/travel-insurance.jpg',
                                               _external=True),
                           share_image_alt=('Senior Indian couple with their suitcases at the '
                                            'departure gate at sunset'))


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
    else:
        # Stored as E.164 like every other number on the site. All three popups send the
        # dialling code joined on ("+1 917 900 5094"), so a leading + settles the country; a
        # client that sends it separately can say so in phone_cc.
        from app.services import phone as phone_svc
        e164, bad_phone = phone_svc.normalise(
            phone, (data.get('phone_cc') or '').strip().upper() or phone_svc.DEFAULT_ISO)
        if bad_phone:
            errors.append(bad_phone)
        else:
            phone = e164
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
    from app.services import crm
    # the support form and the expert form are one item on the lead sources: "Request (WhatsApp / call)"
    crm.capture_safely('ti-expert', name=name, phone=phone, email=email,
                       product='TI', message=written or None, ref=('contact_messages', msg.id),
                       user_id=msg.user_id, consent=crm.ticked(data.get('wa_consent')),
                       consent_from='insurance form',
                       details={'destination': destination, 'about': subject, 'preferred_contact': preferred})
    return jsonify({'success': True}), 201


# --------------------------------------------------------------------------------------------------------------
# Canada: super visa and visitors to Canada, priced on our own quotes page.
#
# Step 1 (here, from any of the quote forms): the trip is checked, saved as an InsuranceQuote with its own
# unguessable address, made a lead (source ti-canada, the Travel insurance pipeline) and the quotes are
# e-mailed to the customer -- in the background, so the form answers at once. The prices themselves come
# live from Secure Travel's calculators every time (services/canada_quotes.py); nothing of theirs is stored.
# Step 2 is a call from our team, never a checkout: the customer picks what they want on the quotes page and
# asks for a call back; staff complete the purchase on Secure Travel's form with our tracking code.

CANADA_COVERS = {'super_visa': 'Super visa insurance', 'visitors': 'Visitors to Canada insurance'}
CALL_TIMES = ('Any time', 'Morning', 'Afternoon', 'Evening')
CALL_HOW = ('Phone call', 'WhatsApp')
MAX_PICKS = 6


def _canada_err(text, status=400):
    return jsonify({'success': False, 'error': text}), status


def _yes(value):
    return str(value or '').strip().lower() in ('y', 'yes', 'true', '1', 'on')


def _canada_travellers(raw, default_pre):
    """[{'age': '66', 'pre': 'n'}, ...] from the form's travellers, or an error message."""
    out = []
    for t in (raw if isinstance(raw, list) else []):
        age = str((t.get('age') if isinstance(t, dict) else t) or '').strip()
        if not age:
            continue
        if not age.isdigit() or int(age) > 120:
            return None, 'Traveller ages must be whole numbers (years).'
        pre = t.get('pre') if isinstance(t, dict) and t.get('pre') not in (None, '') else default_pre
        out.append({'age': str(int(age)), 'pre': 'y' if _yes(pre) else 'n'})
    if not out:
        return None, "Enter at least one traveller's age."
    if len(out) > canada_quotes.MAX_TRAVELLERS:
        return None, 'We can quote up to %d travellers at a time.' % canada_quotes.MAX_TRAVELLERS
    return out, None


def _canada_url(quote, absolute=False):
    if absolute:
        return urls.site_link('insurance.canada_quotes', token=quote.token)
    return urls.public_url('insurance.canada_quotes', token=quote.token)


def _canada_ref(quote):
    return 'CQ-%d' % quote.id


def _canada_books(quote):
    """Both covers priced for this request, now: {'super_visa': book | {'error'}, 'visitors': ...}.

    The cover they chose is priced for their own dates; the other one is there to compare -- a year for a
    super visa, their trip's days for a visit (a year when they asked for a super visa)."""
    extra = quote.extra or {}
    days = {'super_visa': 365, 'visitors': int(extra.get('days') or 365)}
    if extra.get('cover') == 'super_visa':
        days['visitors'] = 365
    out = {}
    for product in ('super_visa', 'visitors'):
        try:
            table_days = days[product]
            book = canada_quotes.book(product, quote.travellers or [], table_days)
            out[product] = book
        except canada_quotes.Unavailable:
            out[product] = {'product': product, 'label': canada_quotes.PRODUCTS[product]['label'],
                            'error': 'Secure Travel’s prices could not be read just now.'}
    return out


def _lowest(book):
    """Per plan, the lowest total for everyone, and the lowest with no deductible: for the e-mail and the lead."""
    out = {}
    if not book or book.get('error'):
        return out
    pres = [p['pre'] for p in book['people']]
    for plan in book['plans']:
        best = zero = None
        for lim in book['limits'].get(plan['code'], ()):
            for ded in book['deductibles']:
                each = [p['prices'][pre][plan['code']][lim['code']][str(ded['value'])]
                        for p, pre in zip(book['people'], pres)]
                if any(x is None for x in each):
                    continue
                total = round(sum(each), 2)
                row = (total, lim['label'], ded['label'])
                if best is None or total < best[0]:
                    best = row
                if ded['value'] == 0 and (zero is None or total < zero[0]):
                    zero = row
        if best:
            out[plan['label']] = {'from': best, 'no_deductible': zero}
    return out


def _canada_summary(quote):
    extra = quote.extra or {}
    ages = [t['age'] for t in (quote.travellers or [])]
    pre = [i + 1 for i, t in enumerate(quote.travellers or []) if t.get('pre') == 'y']
    cover = CANADA_COVERS.get(extra.get('cover'), 'Canada insurance')
    when = '%s to %s' % (quote.start_date.strftime('%d %b %Y'), quote.end_date.strftime('%d %b %Y'))
    return {
        'cover': cover + (' · 1 year' if extra.get('cover') == 'super_visa'
                          else ' · %s day%s' % (extra.get('days'), '' if extra.get('days') == 1 else 's')),
        'dates': when,
        'travellers': ('1 traveller · age %s' % ages[0]) if len(ages) == 1
                      else '%d travellers · ages %s' % (len(ages), ', '.join(ages)),
        'pre_existing': ('No' if not pre else 'Yes, traveller %s' % ', '.join(map(str, pre))),
    }


def _pick_line(p):
    return '%s%s · %s · %s · %s%s' % (
        (p['traveller_label'] + ': ') if p.get('traveller_label') else '',
        canada_quotes.PRODUCTS.get(p['product'], {}).get('label', p['product']), p.get('plan_label', p['plan']),
        p.get('limit_label', p['limit']), p.get('deductible_label', '$%s deductible' % p['deductible']),
        (' · ' + canada_quotes.money(p['total'])) if p.get('total') is not None else '')


def _picks_summary(picks, travellers):
    """Under the picks: what one pick per traveller adds up to, and who has no pick yet ([] for one pick)."""
    mine = [p for p in picks if p.get('traveller') is not None]
    if not mine:
        return []
    out = ['Together: %s' % canada_quotes.money(round(sum(p['total'] for p in mine), 2))] if len(mine) > 1 else []
    picked = {p['traveller'] for p in mine}
    out += ['No pick yet for %s' % _traveller_label(travellers, i) for i in range(len(travellers)) if i not in picked]
    return out


def _traveller_label(travellers, i):
    return 'Traveller %d (age %s)' % (i + 1, travellers[i].get('age'))


def _in_background(fn, *args):
    """Run `fn(app, *args)` after the response, in its own app context (inline under tests)."""
    import threading
    app = current_app._get_current_object()
    if app.config.get('TESTING') or app.config.get('CANADA_MAIL_INLINE'):
        fn(app, *args)
        return
    threading.Thread(target=fn, args=(app, *args), daemon=True, name='canada-quote-mail').start()


def _mail_quote(app, quote_id, kind, link):
    """E-mail the customer: 'quote' (step 1, their prices and the link) or 'callback' (we will call you).

    `link` is built by the request that sends it: this runs on its own thread, where there is no request to
    build an address from."""
    from app.models import InsuranceQuote
    from app.services import clock, mailer
    with app.app_context():
        try:
            quote = db.session.get(InsuranceQuote, quote_id)
            if quote is None:
                return
            s = _canada_summary(quote)
            lines = ['Hello%s,' % ((' ' + (quote.name or '').split()[0]) if (quote.name or '').strip() else ''), '']
            if kind == 'quote':
                subject = 'Your Canada insurance quotes (%s)' % _canada_ref(quote)
                lines += ['Thank you for asking NRI Parent Service for Canada insurance quotes.', '',
                          'Cover:        %s' % s['cover'], 'Dates:        %s' % s['dates'],
                          'Travellers:   %s' % s['travellers'], 'Pre-existing: %s' % s['pre_existing'],
                          'Reference:    %s' % _canada_ref(quote), '']
                book = _canada_books(quote).get((quote.extra or {}).get('cover') or 'super_visa')
                low = _lowest(book)
                if low:
                    lines.append('Lowest prices for everyone together:')
                    for plan, row in low.items():
                        best = row['from']
                        lines.append('  %s plan: from %s (%s cover, %s deductible)'
                                     % (plan, canada_quotes.money(best[0]), best[1], best[2]))
                        if row['no_deductible'] and row['no_deductible'] != best:
                            z = row['no_deductible']
                            lines.append('    with no deductible: from %s (%s cover)' % (canada_quotes.money(z[0]), z[1]))
                    lines.append('')
                    lines.append('Prices are estimates from Secure Travel’s published rates, checked %s IST. The final '
                                 'premium is confirmed when the policy is issued.' % clock.fmt(datetime.utcnow(), zone='IST'))
                else:
                    lines.append('We could not read the prices just now. Open the link below in a little while, or '
                                 'reply to this e-mail and our team will call you with them.')
                lines += ['', 'See every option, compare the Standard and Enhanced plans, and pick the one you want:',
                          link, '', ('Pick one for each traveller' if len(quote.travellers or []) > 1 else 'Pick one') +
                          ' and press "Request a call back": our agent will call you and complete '
                          'the application with you.']
            else:
                cb = (quote.extra or {}).get('callback') or {}
                subject = 'We will call you about your Canada insurance (%s)' % _canada_ref(quote)
                lines += ['Your request is in progress. Our agent will contact you%s%s.'
                          % (' on WhatsApp' if cb.get('how') == 'WhatsApp' else ' by phone',
                             (' (' + cb['best_time'].lower() + ')') if cb.get('best_time') and cb['best_time'] != 'Any time' else ''),
                          '', 'What you picked:']
                picks = (quote.extra or {}).get('picks') or []
                for p in picks:
                    lines.append('  • ' + _pick_line(p))
                lines += ['  ' + x for x in _picks_summary(picks, quote.travellers or [])]
                lines += ['', 'Cover:      %s' % s['cover'], 'Dates:      %s' % s['dates'],
                          'Travellers: %s' % s['travellers'], 'Reference:  %s' % _canada_ref(quote), '',
                          'Your quotes stay here: ' + link]
            lines += ['', 'NRI Parent Service']
            ok = mailer.send(subject, [quote.email], '\n'.join(lines), category='cs', force=True,
                             from_name='NRI Parent Service · Travel insurance')
            extra = dict(quote.extra or {})
            extra['emailed'] = (extra.get('emailed') or []) + [{'kind': kind, 'ok': bool(ok), 'at': datetime.utcnow().isoformat()}]
            quote.extra = extra
            db.session.commit()
        except Exception:          # noqa: BLE001 -- a mail we could not send never undoes a quote
            db.session.rollback()
            current_app.logger.exception('Canada quote e-mail (%s) failed for quote %s', kind, quote_id)


def _canada_trip(data):
    """The trip from a form: ({'cover', 'start', 'end', 'days', 'travellers'}, None) or (None, what is wrong).
    Step 1 and "Change the trip" on the quotes page check it the same way."""
    from datetime import date as _date, datetime as _dt, timedelta

    def _day(key):
        try:
            return _dt.strptime(str(data.get(key, '') or '').strip(), '%Y-%m-%d').date()
        except ValueError:
            return None

    cover = str(data.get('cover') or '').strip().lower().replace('-', '_')
    if cover not in CANADA_COVERS:
        cover = 'super_visa'
    start = _day('start_date')
    if not start or start < _date.today():
        return None, 'Pick a coverage start date from today onwards.'
    if cover == 'super_visa':
        end = start + timedelta(days=364)          # a super visa policy is one full year, both ends counted
    else:
        end = _day('end_date')
        if not end or end < start:
            return None, 'The coverage end date must be on or after the start date.'
    days = canada_quotes.cover_days(cover, start, end)
    if days > canada_quotes.MAX_DAYS:
        return None, 'A visitor policy covers up to a year. For longer, choose Super visa or ask our team.'
    travellers, bad = _canada_travellers(data.get('travellers'), data.get('pre_existing'))
    if bad:
        return None, bad
    return {'cover': cover, 'start': start, 'end': end, 'days': days, 'travellers': travellers}, None


def canada_start(data):
    """Step 1 for Canada, from POST /api/insurance-quote with insurance_type 'canada' (main.api_insurance_quote)."""
    import secrets
    from app.models import InsuranceQuote
    from app.services import crm

    trip, bad = _canada_trip(data)
    if bad:
        return _canada_err(bad)
    cover, start, end, days, travellers = trip['cover'], trip['start'], trip['end'], trip['days'], trip['travellers']
    citizenship = str(data.get('citizenship', '') or '').strip().upper()
    if citizenship and not re.fullmatch(r'[A-Z]{3}', citizenship):
        citizenship = ''
    email = str(data.get('email', '') or '').strip().lower()
    if not EMAIL_RE.match(email):
        return _canada_err('Please enter a valid email address.')
    raw_phone = str(data.get('phone', '') or '').strip()
    if not raw_phone:
        return _canada_err('Please enter a phone number.')
    e164, bad_phone = phone.normalise(raw_phone, str(data.get('phone_cc', '') or '').strip().upper() or phone.DEFAULT_ISO)
    if bad_phone:
        return _canada_err(bad_phone)

    name = str(data.get('name') or '').strip()[:120]          # the popup asks for it; the other forms do not

    quote = InsuranceQuote(
        user_id=current_user.id if current_user.is_authenticated else None, email=email[:255], phone=e164[:30],
        name=name or None, insurance_type='canada', citizenship=citizenship, destination='CAN', start_date=start,
        end_date=end, travellers=travellers, token=secrets.token_urlsafe(16)[:22],
        extra={'cover': cover, 'days': days})
    # priced once now: their page must be readable for the quotes to show, and the lead says so either way
    book = _canada_books_for(cover, travellers, days)
    low = _lowest(book)
    quote.status = 'quoted' if low else 'failed'
    db.session.add(quote)
    db.session.commit()
    quote.quote_url = _canada_url(quote)
    db.session.commit()

    s = _canada_summary(quote)
    crm.capture_safely(
        'ti-canada', name=name or None, phone=quote.phone, email=quote.email, product='TI', user_id=quote.user_id,
        departure_date=start, ends_on=end, ref=('insurance_quotes', quote.id),
        consent=crm.ticked(data.get('wa_consent')), consent_from='Canada quote form',
        details={'plan': 'Canada · ' + s['cover'], 'travellers_ages': ', '.join(t['age'] for t in travellers),
                 'pre_existing': s['pre_existing'], 'cover': s['dates'], 'citizenship': citizenship,
                 'quote': ('; '.join('%s from %s' % (k, canada_quotes.money(v['from'][0])) for k, v in low.items())
                           if low else 'Secure Travel prices could not be read'),
                 'quotes_page': _canada_url(quote, absolute=True), 'reference': _canada_ref(quote)})
    _in_background(_mail_quote, quote.id, 'quote', _canada_url(quote, absolute=True))
    return jsonify({'success': True, 'url': quote.quote_url, 'ref': _canada_ref(quote)})


def _canada_books_for(cover, travellers, days):
    try:
        return canada_quotes.book(cover, travellers, days)
    except canada_quotes.Unavailable:
        return None


def _canada_quote_or_404(token):
    from flask import abort
    from app.models import InsuranceQuote
    quote = InsuranceQuote.query.filter_by(token=token, insurance_type='canada').first() if token else None
    if quote is None:
        abort(404)
    return quote


@insurance_bp.route('/travel-insurance/canada/quotes/<token>', endpoint='canada_quotes')
def canada_quotes_page(token):
    """The quotes page: every option, Standard on the left and Enhanced on the right, filters in the middle."""
    quote = _canada_quote_or_404(token)
    books = _canada_books(quote)
    extra = quote.extra or {}
    sv, vi = books.get('super_visa'), books.get('visitors')
    page = {
        'ref': _canada_ref(quote), 'cover': extra.get('cover') or 'super_visa',
        'start': quote.start_date.isoformat(), 'end': quote.end_date.isoformat(),
        'summary': _canada_summary(quote), 'books': books,
        'travellers': quote.travellers or [],
        'picks': extra.get('picks') or [], 'callback': extra.get('callback'),
        'callbackUrl': url_for('insurance.canada_callback', token=quote.token),
        'tripUrl': url_for('insurance.canada_trip', token=quote.token),
        'today': date.today().isoformat(),
        'editUrl': urls.public_url('insurance.landing') + '#canada',
        'callTimes': list(CALL_TIMES), 'callHow': list(CALL_HOW),
        'phone': phone.pretty(quote.phone, quote.phone) if quote.phone else '', 'email': quote.email,
        'source': {k: v['url'] for k, v in canada_quotes.PRODUCTS.items()},
    }
    return render_template('insurance/canada_quotes.html', quote=quote, page=page,
                           check_ok=all(not b.get('error') for b in books.values()))


@insurance_bp.route('/travel-insurance/canada/quotes/<token>/trip', methods=['POST'])
@rate_limit(30, 3600)
def canada_trip(token):
    """"Change the trip" on the quotes page: new cover, dates or travellers for the same request, priced again
    on the same page. The lead hears about it, so an agent who already has the request calls about the new trip."""
    from app.services import crm
    quote = _canada_quote_or_404(token)
    trip, bad = _canada_trip(request.get_json(silent=True) or {})
    if bad:
        return _canada_err(bad)
    before = _canada_summary(quote)
    quote.start_date, quote.end_date, quote.travellers = trip['start'], trip['end'], trip['travellers']
    extra = dict(quote.extra or {})
    extra.update({'cover': trip['cover'], 'days': trip['days'],
                  'changes': (extra.get('changes') or []) + [{'at': datetime.utcnow().isoformat(), 'before': before}]})
    quote.extra = extra
    low = _lowest(_canada_books_for(trip['cover'], trip['travellers'], trip['days']))
    if quote.status != 'callback':
        quote.status = 'quoted' if low else 'failed'
    db.session.commit()
    s = _canada_summary(quote)
    crm.capture_safely(
        'ti-canada', name=quote.name, phone=quote.phone, email=quote.email, product='TI', user_id=quote.user_id,
        departure_date=quote.start_date, ends_on=quote.end_date, ref=('insurance_quotes', quote.id),
        message='Changed the trip on their quotes page %s: %s, %s, %s (was %s, %s, %s).' % (
            _canada_ref(quote), s['cover'], s['dates'], s['travellers'], before['cover'], before['dates'], before['travellers']),
        details={'plan': 'Canada · ' + s['cover'], 'travellers_ages': ', '.join(t['age'] for t in quote.travellers),
                 'pre_existing': s['pre_existing'], 'cover': s['dates'],
                 'quote': ('; '.join('%s from %s' % (k, canada_quotes.money(v['from'][0])) for k, v in low.items())
                           if low else 'Secure Travel prices could not be read')})
    return jsonify({'success': True})


@insurance_bp.route('/travel-insurance/canada/quotes/<token>/call-back', methods=['POST'])
@rate_limit(20, 3600)
def canada_callback(token):
    """Step 2 starts here: the options they picked, priced again now, and when to call them."""
    from app.services import crm
    quote = _canada_quote_or_404(token)
    data = request.get_json(silent=True) or {}
    name = str(data.get('name') or '').strip()[:120]
    if not name:
        return _canada_err('Please tell us your name, so our agent knows who to ask for.')
    best_time = data.get('best_time') if data.get('best_time') in CALL_TIMES else CALL_TIMES[0]
    how = data.get('how') if data.get('how') in CALL_HOW else CALL_HOW[0]
    note = str(data.get('note') or '').strip()[:1000]

    # their answers to "pre-existing condition?" may have changed on the page, one person at a time
    pres = data.get('pre') if isinstance(data.get('pre'), list) else []
    travellers = [dict(t, pre=('y' if _yes(pres[i]) else 'n') if i < len(pres) else t.get('pre', 'n'))
                  for i, t in enumerate(quote.travellers or [])]
    extra = dict(quote.extra or {})
    raw = data.get('picks') if isinstance(data.get('picks'), list) else []
    # one pick per traveller (one parent may want Standard, the other Enhanced), each priced for that traveller
    # alone; a pick that names no traveller is for everybody together, as the page made them before
    picks, seen = [], set()
    for p in raw[:max(MAX_PICKS, len(travellers))]:
        if not isinstance(p, dict) or p.get('product') not in canada_quotes.PRODUCTS:
            continue
        who = p.get('traveller')
        if who is not None:
            try:
                who = int(who)
            except (TypeError, ValueError):
                continue
            if not 0 <= who < len(travellers) or who in seen:
                continue
        product = p['product']
        days = 365 if product == 'super_visa' or extra.get('cover') == 'super_visa' else int(extra.get('days') or 365)
        try:
            priced = canada_quotes.price_pick(product, travellers if who is None else [travellers[who]], days,
                                              str(p.get('plan')), str(p.get('limit')), int(p.get('deductible') or 0))
        except (canada_quotes.Unavailable, ValueError, TypeError):
            priced = None
        if priced is None:
            continue
        total, each, table = priced
        monthly = p.get('pay') == 'monthly' and table.monthly_ok(days, str(p.get('limit')))
        if who is not None:
            seen.add(who)
        picks.append({**({'traveller': who, 'traveller_label': _traveller_label(travellers, who)} if who is not None else {}),
                      'product': product, 'plan': str(p['plan']), 'plan_label': table.plan_label(str(p['plan'])),
                      'limit': str(p['limit']), 'limit_label': table.limit_label(str(p['plan']), str(p['limit'])),
                      'deductible': int(p.get('deductible') or 0),
                      'deductible_label': '%s deductible' % dict(table.deductibles).get(int(p.get('deductible') or 0), ''),
                      'days': days, 'total': total, 'each': each, 'pay': 'monthly' if monthly else 'once',
                      'monthly': (round(total / table.monthly.get('months', 12), 2) if monthly else None),
                      'monthly_fee': table.monthly.get('fee') if monthly else None,
                      'fingerprint': table.fingerprint, 'priced_at': datetime.utcnow().isoformat()})
    if raw and not picks:
        return _canada_err('Those options could not be priced just now. Please try again, or ask for a call without a pick.')
    picks.sort(key=lambda p: -1 if p.get('traveller') is None else p['traveller'])

    extra.update({'picks': picks, 'callback': {'at': datetime.utcnow().isoformat(), 'name': name, 'best_time': best_time,
                                               'how': how, 'note': note}})
    quote.extra = extra
    quote.travellers = travellers
    quote.name = name
    quote.status = 'callback'
    db.session.commit()

    lines = ['Asked for a call back (%s, %s) about their Canada quotes %s.' % (how, best_time.lower(), _canada_ref(quote))]
    lines += ['Picked: ' + _pick_line(p) + (' (monthly)' if p['pay'] == 'monthly' else '') for p in picks] or \
             ['No option picked: wants to talk it through.']
    lines += _picks_summary(picks, travellers)
    if note:
        lines.append('Their note: ' + note)
    crm.capture_safely('ti-canada', name=name, phone=quote.phone, email=quote.email, product='TI',
                       user_id=quote.user_id, departure_date=quote.start_date, ends_on=quote.end_date,
                       ref=('insurance_quotes', quote.id), message='\n'.join(lines),
                       consent=crm.ticked(data.get('wa_consent')), consent_from='Canada quotes page',
                       details={'picked': '; '.join(_pick_line(p) for p in picks) or 'nothing yet',
                                'call_back': '%s · %s' % (how, best_time), 'reference': _canada_ref(quote)})
    _in_background(_mail_quote, quote.id, 'callback', _canada_url(quote, absolute=True))
    return jsonify({'success': True, 'ref': _canada_ref(quote), 'picks': picks})
