"""Help centre: admin-managed categories and FAQs for all three products.

Stored as one JSON blob in app_settings (key 'help_center'), the same way options.py and
messages.py keep admin-editable content — so an edit shows up on the public page within the
settings cache window, with no migration and no deploy.

Shape:
    {'categories': [{'key', 'title', 'icon', 'blurb', 'site'}],
     'faqs':       [{'id', 'category', 'question', 'answer'}]}

A category belongs to one SITE -- the travel-companion app, the travel-insurance page or
Sahayak -- and that is the only place its questions appear. A question does not carry a site of
its own: it inherits the one its category has, so the two can never disagree.

Each site has its own admin screen, and saving one leaves the others alone. That matters more
than it sounds: this is one settings blob, so a save that wrote only the rows on screen would
silently delete every question belonging to the other two.

The built-in defaults below started as the eight questions that used to be hard-coded in
templates/pages/help.html, plus a handful that used to live only in the landing page's own FAQ
accordion before that was wired to this same source (2026-09-13) — one list, everywhere. Nothing
is lost if an admin never touches the screen.
"""
import re
import uuid

SETTING_KEY = 'help_center'
KEY_RE = re.compile(r'^[a-z0-9_]{1,40}$')

# The products, in the order the admin panel lists them.
SITES = [
    ('companion', 'Travel Companion', 'fa-plane-departure'),
    ('insurance', 'Travel Insurance', 'fa-shield-heart'),
    ('sahayak', 'Sahayak', 'fa-house-medical'),
]
SITE_KEYS = [k for k, _, _ in SITES]
SITE_LABELS = {k: label for k, label, _ in SITES}
DEFAULT_SITE = 'companion'

# Categories saved before this was split by product have no `site`. Two of them were already
# being read by the other two pages under a known key, so those move to where they belong and
# everything else stays with the app it was written for.
LEGACY_SITE_BY_KEY = {'travel_insurance': 'insurance', 'sahayak': 'sahayak'}

# Icons an admin can choose from. A free-text Font Awesome class was too easy to get
# wrong (and browsers happily autofilled nonsense into it), so the admin screen offers
# this list and anything outside it falls back to the question mark.
ICON_CHOICES = [
    ('fa-circle-question', 'Question mark'), ('fa-rocket', 'Rocket / getting started'),
    ('fa-shield-halved', 'Shield / privacy'), ('fa-lock', 'Lock / security'),
    ('fa-handshake', 'Handshake / matches'), ('fa-user-group', 'People'),
    ('fa-user-gear', 'Account settings'), ('fa-id-card', 'Profile / identity'),
    ('fa-plane-departure', 'Departure'), ('fa-plane-arrival', 'Arrival'),
    ('fa-suitcase-rolling', 'Baggage'), ('fa-passport', 'Passport / documents'),
    ('fa-ticket', 'Tickets'), ('fa-calendar-days', 'Dates'),
    ('fa-location-dot', 'Places'), ('fa-route', 'Routes'),
    ('fa-comments', 'Chat / messages'), ('fa-envelope', 'E-mail'),
    ('fa-bell', 'Notifications'), ('fa-headset', 'Support'),
    ('fa-credit-card', 'Payments'), ('fa-receipt', 'Billing'),
    ('fa-wheelchair', 'Accessibility'), ('fa-hand-holding-heart', 'Help / care'),
    ('fa-language', 'Languages'), ('fa-globe', 'International'),
    ('fa-triangle-exclamation', 'Warnings'), ('fa-circle-info', 'Information'),
    ('fa-clock', 'Timing'), ('fa-star', 'Reviews'),
    ('fa-gavel', 'Terms / legal'), ('fa-trash', 'Deleting things'),
]
ICON_KEYS = {k for k, _ in ICON_CHOICES}

DEFAULT_CATEGORIES = [
    {'site': 'companion', 'key': 'getting_started', 'icon': 'fa-rocket', 'title': 'Getting started',
     'blurb': 'Posting a trip and finding your first companion.'},
    {'site': 'companion', 'key': 'privacy', 'icon': 'fa-shield-halved', 'title': 'Privacy & contact details',
     'blurb': 'Who can see what, and when.'},
    {'site': 'companion', 'key': 'matches', 'icon': 'fa-handshake', 'title': 'Matches & connections',
     'blurb': 'How we pair travellers and introduce you.'},
    {'site': 'companion', 'key': 'account', 'icon': 'fa-user-gear', 'title': 'Account & listings',
     'blurb': 'Editing, closing and deleting things.'},

    # The travel-insurance page reads this one by key; renaming it would empty that page's
    # accordion, which is why the key is spelled out rather than derived from the title.
    {'site': 'insurance', 'key': 'travel_insurance', 'icon': 'fa-shield-halved',
     'title': 'Travel insurance', 'blurb': 'Cover, exclusions, claims and when to buy.'},

    # Ships empty on purpose: the Sahayak page hides its FAQ section until somebody files a
    # question, and we have nothing true to say about a service that is still being priced.
    {'site': 'sahayak', 'key': 'sahayak', 'icon': 'fa-hand-holding-heart',
     'title': 'Sahayak home visits', 'blurb': 'What a visit covers, and how to book one.'},
]

DEFAULT_FAQS = [
    {'id': 'faq_start_post', 'category': 'getting_started',
     'question': 'How do I post a trip?',
     'answer': 'Sign up or log in, then use the form on the home page. Say whether you need a companion or can '
               'help someone, fill in your route and dates, choose how a matched companion may reach you, and '
               'click "Connect Desis".'},
    {'id': 'faq_start_free', 'category': 'getting_started',
     'question': 'Is NRI Parent Service free?',
     'answer': 'Yes, the core features are completely free. We may introduce premium features in the future.'},
    {'id': 'faq_start_parents', 'category': 'getting_started',
     'question': 'Can I request a companion for my parents?',
     'answer': "Yes — that's our most common request. Upload their e-ticket or fill in the form yourself; your "
               "parents don't need to do anything technical, and our care team reviews every request."},
    {'id': 'faq_start_ticket', 'category': 'getting_started',
     'question': 'Can I upload my flight ticket instead of typing everything in?',
     'answer': 'Yes. Upload the PDF e-ticket and we read the route, dates, airline and flight number for you — '
               'you can still change anything afterwards. Typing it in yourself works just as well.'},
    {'id': 'faq_start_countries', 'category': 'getting_started',
     'question': 'Which countries do you serve?',
     'answer': 'India, the United States, Canada, the United Kingdom, Australia and the UAE are our most active '
               'routes today, and the list keeps growing. Other routes are welcome — post your trip and we will '
               'look for a match on any route.'},
    {'id': 'faq_privacy_contacts', 'category': 'privacy',
     'question': 'Who can see my contact details?',
     'answer': 'Only a travel companion we match you with — and only if you ticked the consent box for that trip. '
               'Everyone else sees just the type of contact you offer (for example an e-mail icon), never the '
               'value. You can skip contact details entirely and use in-app chat instead.'},
    {'id': 'faq_privacy_link', 'category': 'privacy',
     'question': 'I got a message from your team with a link. What is it?',
     'answer': 'If you asked for a travel companion on Facebook or another website, our team may offer to list '
               'your request here. The link lets you confirm the request and add the contact details you want to '
               'share. Nothing is published until you confirm.'},
    {'id': 'faq_match_how', 'category': 'matches',
     'question': 'How does matching work?',
     'answer': 'We compare route, dates, flight, language and needs, then rank the closest matches with a score '
               'and the reasons behind it. A care-team member reviews before anyone is introduced.'},
    {'id': 'faq_match_connect', 'category': 'matches',
     'question': 'How do I connect with another traveller?',
     'answer': 'Browse the listings and click "Connect" on any listing. The other person can accept or decline; '
               'once accepted you can chat in-app.'},
    {'id': 'faq_account_modify', 'category': 'account',
     'question': 'Can I modify my trip after posting?',
     'answer': 'In-place editing is coming soon. For now, close the trip from "My Trips" and post an updated one, '
               'or contact us and we will update it for you.'},
    {'id': 'faq_account_expiry', 'category': 'account',
     'question': 'What happens to my listing after my travel date?',
     'answer': 'Listings are automatically removed from search results after the departure date has passed.'},
    {'id': 'faq_account_delete', 'category': 'account',
     'question': 'How do I delete my account or a request?',
     'answer': 'Contact us and we will delete your account, your requests and all associated data within 48 hours.'},
]


# The travel-insurance answers. They used to live in services/insurance_page.py and were shown
# only when nothing had been filed under the category -- a fallback the admin screen could not
# see, let alone edit. They are shipped defaults now, like every other question here: the screen
# lists them, an admin can reword or delete any of them, and the page renders what the screen
# says and nothing else.
#
# Every answer is deliberately about travel insurance in general and defers to the policy
# wording for specifics. What a given plan covers, excludes or waits out differs by plan and by
# insurer, and that page sells 65+ of them -- a confident number here would be wrong for most.
_INSURANCE_QA = [
    ('What is travel insurance?',
     'A policy that can help cover eligible costs from unexpected events on a trip, such as '
     'medical emergencies, evacuation, delays or lost baggage. It pays towards what the policy '
     'lists, up to the limits you choose when you buy.'),
    ('What does travel insurance cover?',
     'It varies by plan. Common benefits are emergency medical treatment, hospitalisation, '
     'emergency evacuation, trip interruption and baggage. The amount each one pays, and the '
     'deductible you meet first, are set by the plan you pick. Always read the policy wording '
     'before you buy — that document, not this page, is the contract.'),
    ('What is not covered?',
     'Most travel medical plans exclude routine or planned treatment, check-ups, dental and '
     'vision beyond emergencies, pregnancy and childbirth in many cases, injuries from extreme '
     'sports, and anything arising while under the influence. Exclusions differ between plans, '
     'so compare them rather than assuming they match.'),
    ('Are pre-existing conditions covered?',
     'Sometimes, and it is the question worth asking before you buy. Plans differ: some exclude '
     'pre-existing conditions outright, some cover an acute onset of one, and some cover them '
     'after a look-back period during which you were stable. The look-back window and what '
     'counts as stable are defined in each policy. If somebody travelling has a known condition, '
     'tell us and we will point you at the plans that address it.'),
    ('Is there a waiting period?',
     'Many plans apply one, so cover for certain benefits starts a set number of days after the '
     'policy does. It is one of the things that differs most between plans, and one of the '
     'reasons to buy before departure rather than after a problem appears.'),
    ('When should I buy?',
     'Before the trip starts, and ideally as soon as it is booked. Cover cannot be bought for '
     'something that has already happened, and benefits that protect the cost of the trip only '
     'apply to bookings made before the policy was issued.'),
    ('Is travel insurance mandatory?',
     'For some destinations and visa types, yes — many Schengen visa applications require proof '
     'of minimum medical cover, and some countries ask for it on entry. Requirements change, so '
     'check the embassy or immigration source for your destination; they have the final word.'),
    ('What is visitor insurance?',
     'Travel medical cover for people visiting another country — most often parents staying with '
     'family abroad, or tourists. It covers emergencies that happen during the visit rather than '
     'ongoing care, and it is bought for the length of the stay.'),
    ('How do I make a claim?',
     'You claim with the insurer who issued the policy, not with us. Keep every medical report, '
     'bill and receipt, and tell the insurer as soon as you reasonably can — most set a deadline '
     'for notifying them. Their emergency line is on your policy document. If you are not sure '
     'where to start, contact us and we will walk you through it.'),
    ('Can I buy travel insurance online?',
     'Yes. Get a quote, compare 65+ A-rated plans side by side and buy online. Policy documents '
     'are sent to you by e-mail.'),
]

DEFAULT_FAQS += [{'id': 'faq_ins_%02d' % i, 'category': 'travel_insurance',
                  'question': q, 'answer': a}
                 for i, (q, a) in enumerate(_INSURANCE_QA, 1)]


def _stored():
    try:
        from app.services import settings
        return settings.get_setting(SETTING_KEY, {}) or {}
    except Exception:           # pragma: no cover - table not created yet
        return {}


def site_of(category):
    """Which product a category belongs to.

    Rows saved before the split have no `site`, so the two keys the other pages were already
    reading are recognised by name and everything else stays with the companion app -- which is
    what it was written for.
    """
    site = (category or {}).get('site')
    if site in SITE_KEYS:
        return site
    return LEGACY_SITE_BY_KEY.get((category or {}).get('key'), DEFAULT_SITE)


def clean_site(site):
    """A site key from a URL, or the default. Never trusted straight from the query string: it
    decides which rows a save replaces."""
    site = (site or '').strip().lower()
    return site if site in SITE_KEYS else DEFAULT_SITE


def categories(site=None):
    """Every category, or one product's. Site is normalised on the way out so callers never
    have to think about rows saved before the split."""
    stored = _stored().get('categories')
    rows = [dict(c) for c in (stored if stored is not None else DEFAULT_CATEGORIES)]
    for c in rows:
        c['site'] = site_of(c)
    return rows if site is None else [c for c in rows if c['site'] == site]


def faqs(site=None):
    """Every question, or one product's.

    A question has no site of its own -- it inherits its category's, which is the only way the
    two cannot contradict each other. One whose category was deleted counts as the default
    site's, so it stays visible somewhere rather than vanishing.
    """
    stored = _stored().get('faqs')
    rows = [dict(f) for f in (stored if stored is not None else DEFAULT_FAQS)]
    if site is None:
        return rows
    by_key = {c['key']: c['site'] for c in categories()}
    return [f for f in rows if by_key.get(f.get('category'), DEFAULT_SITE) == site]


def is_customised(site=None):
    """Whether anybody has edited this product's questions, so the admin screen can say the list
    is the shipped one. Compared against the defaults rather than "has the blob been written",
    because saving one product writes rows for all three."""
    if _stored().get('categories') is None and _stored().get('faqs') is None:
        return False
    if site is None:
        return True
    shipped_c = [c for c in DEFAULT_CATEGORIES if site_of(c) == site]
    shipped_keys = {c['key'] for c in shipped_c}
    shipped_f = [f for f in DEFAULT_FAQS if f.get('category') in shipped_keys]
    strip = lambda rows, fields: [{k: r.get(k) for k in fields} for r in rows]
    return (strip(categories(site), ('key', 'title', 'icon', 'blurb')) != strip(shipped_c, ('key', 'title', 'icon', 'blurb'))
            or strip(faqs(site), ('category', 'question', 'answer')) != strip(shipped_f, ('category', 'question', 'answer')))


def grouped(site=None):
    """[(category, [faq, ...])] in admin order. FAQs whose category was deleted are
    collected under a synthetic 'Other' group so an edit can never hide content."""
    cats = categories(site)
    by_key = {c['key']: [] for c in cats}
    orphans = []
    known = {c['key'] for c in categories()}
    for f in faqs(site):
        if f.get('category') in by_key:
            by_key[f['category']].append(f)
        elif f.get('category') not in known:
            orphans.append(f)           # its category is gone; show it rather than lose it
    out = [(c, by_key[c['key']]) for c in cats]
    if orphans:
        out.append(({'key': 'other', 'icon': 'fa-circle-question', 'title': 'Other',
                     'blurb': 'Questions not filed under a category yet.', 'site': DEFAULT_SITE}, orphans))
    return out


def _slug(text, fallback='category'):
    s = re.sub(r'[^a-z0-9]+', '_', str(text or '').lower()).strip('_')[:40]
    return s or fallback


def clean_categories(rows, site=DEFAULT_SITE):
    """Validate admin input for one product. Returns (categories, errors)."""
    out, errors, seen = [], [], set()
    for row in rows or []:
        title = str(row.get('title') or '').strip()
        if not title:
            continue                                    # blank row = deleted
        key = str(row.get('key') or '').strip() or _slug(title)
        if not KEY_RE.match(key):
            key = _slug(title)
        base, n = key, 2
        while key in seen:
            key, n = f'{base}_{n}', n + 1
        seen.add(key)
        # only known icons are stored; anything else (a typo, a browser autofill) would
        # render as a blank box on the public page, so fall back to the question mark
        icon = str(row.get('icon') or '').strip()[:40]
        if icon not in ICON_KEYS:
            icon = 'fa-circle-question'
        out.append({'site': site, 'key': key, 'title': title[:80], 'icon': icon,
                    'blurb': str(row.get('blurb') or '').strip()[:200]})
    if not out:
        errors.append('Keep at least one category — every question is filed under one.')
    return out, errors


def clean_faqs(rows, valid_keys):
    """Validate admin input. Returns (faqs, errors)."""
    out, errors, seen = [], [], set()
    for row in rows or []:
        q = str(row.get('question') or '').strip()
        a = str(row.get('answer') or '').strip()
        if not q and not a:
            continue                                    # blank row = deleted
        if not q or not a:
            errors.append(f'"{(q or a)[:48]}" needs both a question and an answer.')
            continue
        fid = str(row.get('id') or '').strip() or 'faq_' + uuid.uuid4().hex[:10]
        while fid in seen:
            fid = 'faq_' + uuid.uuid4().hex[:10]
        seen.add(fid)
        cat = str(row.get('category') or '').strip()
        if cat not in valid_keys:
            cat = valid_keys[0] if valid_keys else 'other'
        out.append({'id': fid, 'category': cat, 'question': q[:300], 'answer': a[:4000]})
    return out, errors


def save(cat_rows, faq_rows, actor=None, site=DEFAULT_SITE):
    """Persist one product's categories and questions together. Returns (ok, errors).

    Both lists go in one submit because a question may not reference a category the same submit
    deleted. The other products' rows are read back from the current state and written out
    unchanged -- this is a single settings blob, so writing only what was on screen would delete
    them. Their rows keep their relative order and this product's are appended after, which is
    all the ordering that means anything: each screen only ever shows one product.
    """
    from app.services import settings
    site = clean_site(site)
    cats, errors = clean_categories(cat_rows, site)
    if errors:
        return False, errors
    fqs, ferrors = clean_faqs(faq_rows, [c['key'] for c in cats])
    if ferrors:
        return False, ferrors

    keep_cats = [c for c in categories() if c['site'] != site]
    kept_keys = {c['key'] for c in keep_cats}
    keep_faqs = [f for f in faqs() if f.get('category') in kept_keys]
    settings.set_setting(SETTING_KEY, {'categories': keep_cats + cats,
                                       'faqs': keep_faqs + fqs}, actor)
    settings.clear_cache()
    return True, []


def reset(actor=None, site=None):
    """Drop the admin's version and go back to the shipped questions -- for one product, or for
    all three when no site is given."""
    from app.services import settings
    if site is None:
        settings.set_setting(SETTING_KEY, {}, actor)
        settings.clear_cache()
        return
    site = clean_site(site)
    keep_cats = [c for c in categories() if c['site'] != site]
    kept_keys = {c['key'] for c in keep_cats}
    keep_faqs = [f for f in faqs() if f.get('category') in kept_keys]
    shipped_c = [dict(c, site=site) for c in DEFAULT_CATEGORIES if site_of(c) == site]
    shipped_keys = {c['key'] for c in shipped_c}
    shipped_f = [dict(f) for f in DEFAULT_FAQS if f.get('category') in shipped_keys]
    settings.set_setting(SETTING_KEY, {'categories': keep_cats + shipped_c,
                                       'faqs': keep_faqs + shipped_f}, actor)
    settings.clear_cache()
