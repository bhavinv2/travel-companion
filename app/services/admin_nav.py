"""What the admin sidebar shows, grouped by the product it belongs to.

The panel grew one link at a time until it was sixteen in a flat list, mixing three separate
products with the settings that apply to all of them. Somebody who came in to answer a Sahayak
booking read past insurance testimonials and colour themes to find it.

So the menu is grouped, and the header carries a tab per product. Picking one narrows the sidebar
to that product's screens; the settings that genuinely apply site-wide live in their own tab
rather than being repeated in each.

Contact messages and feedback were reachable before this but never named in the menu: they are
three tabs inside one screen called "User voices", which tells you nothing about what is in it.
They are listed here by what they are, and the enquiry list is split by topic -- a travel-cover
enquiry belongs with the insurance screens, not filed under the companion app with everything
else. One screen, one URL, different slices of it. Sahayak's slice holds two things that are
read the same way: somebody applying to join the network, and somebody asking about a visit.

Two judgements worth stating, because they are the ones most likely to be wrong for you:

  * The Dashboard is not in any tab. It reports across all three, so burying it under one would
    be a lie about what it shows.
  * Help & FAQ appears under all three, because there are now three sets of questions: one
    screen, one URL, a `site` in the query string, and a save that touches only what is on it.
    It used to be a single list under Travel Companion that the other two pages read a category
    out of -- which is why nobody could find where the insurance questions were edited.
"""


def _item(key, endpoint, label, icon, **args):
    """One line in the sidebar. `args` are query parameters, for screens that are really one
    page showing different slices (the enquiry inbox, filtered by topic)."""
    return {'key': key, 'endpoint': endpoint, 'label': label, 'icon': icon, 'args': args}


SECTIONS = [
    {
        'key': 'companion',
        'label': 'Travel Companion',
        'icon': 'fa-plane-departure',
        'items': [
            _item('listings', 'admin.listings', 'Listings', 'fa-list'),
            _item('voices_contact', 'admin.voices', 'Contact us', 'fa-envelope',
                  tab='contact', topic='companion'),
            _item('voices_feedback', 'admin.voices', 'Feedback', 'fa-star', tab='feedback'),
            _item('voices_report', 'admin.voices', 'Reports', 'fa-flag-checkered', tab='report'),
            _item('landing', 'admin.landing_page', 'Landing page', 'fa-flag'),
            _item('blog', 'admin.new_blog', 'New blog post', 'fa-pen'),
            _item('help', 'admin.help_center_page', 'Help & FAQ', 'fa-circle-question'),
        ],
    },
    {
        'key': 'insurance',
        'label': 'Travel Insurance',
        'icon': 'fa-shield-heart',
        'items': [
            _item('insurance', 'admin.insurance_quotes', 'Quote leads', 'fa-shield-heart'),
            _item('voices_insurance', 'admin.voices', 'Enquiries', 'fa-envelope',
                  tab='contact', topic='insurance'),
            _item('insurance_page', 'admin.insurance_page_content', 'Page content', 'fa-quote-left'),
            _item('help_insurance', 'admin.help_center_page', 'Help & FAQ', 'fa-circle-question',
                  site='insurance'),
        ],
    },
    {
        'key': 'sahayak',
        'label': 'Sahayak',
        'icon': 'fa-house-medical',
        'items': [
            _item('sahayak', 'admin.sahayak_bookings', 'Bookings', 'fa-house-medical'),
            _item('voices_sahayak', 'admin.voices', 'Applications & enquiries', 'fa-user-plus',
                  tab='contact', topic='sahayak'),
            _item('sahayak_services', 'admin.sahayak_services', 'Services & prices', 'fa-list-check'),
            _item('help_sahayak', 'admin.help_center_page', 'Help & FAQ', 'fa-circle-question',
                  site='sahayak'),
        ],
    },
    {
        'key': 'site',
        'label': 'Site',
        'icon': 'fa-gear',
        'items': [
            _item('voices_general', 'admin.voices', 'Contact us (all services)', 'fa-inbox',
                  tab='contact', topic='general'),
            _item('users', 'admin.users', 'Users', 'fa-users'),
            _item('cs_agents', 'admin.cs_agents', 'CS agents & access', 'fa-user-lock'),
            _item('options', 'admin.options_page', 'Options & dropdowns', 'fa-sliders'),
            _item('messages', 'admin.messages_page', 'Messages & e-mails', 'fa-envelope-open-text'),
            _item('notiflog', 'admin.notification_log', 'Notifications', 'fa-bell'),
            _item('notifications', 'admin.notification_switches', 'Notification switches', 'fa-bell-slash'),
            _item('themes', 'admin.themes_page', 'Colour themes', 'fa-palette'),
        ],
    },
]

# Shown above the tabs, because they report on all of them.
DASHBOARD = {'key': 'dashboard', 'endpoint': 'admin.dashboard', 'label': 'Dashboard',
             'icon': 'fa-gauge', 'args': {}}
# The promotion team's read-only view. Here rather than under a product for the same reason as
# the dashboard: it counts all three. Admins reach it from the menu; the influencer role reaches
# it from the account menu in base.html, having no admin panel to find it in.
PROMOTION = {'key': 'promotion', 'endpoint': 'main.promo_dashboard', 'label': 'Promotion',
             'icon': 'fa-chart-line', 'args': {}}
TOP = [DASHBOARD, PROMOTION]

# Screens reached from another one rather than from the menu.
ALIASES = {'feedback': 'voices_feedback'}


def current_key(active, args=None):
    """Which sidebar line this request corresponds to.

    Four of them share one endpoint -- the enquiry inbox, feedback and reports are tabs of the
    same screen, and the inbox is split again by topic -- so the route's `active` alone cannot
    say which line is the current one. The query string finishes the job.
    """
    args = args or {}
    if active == 'voices':
        tab = args.get('tab') or 'contact'
        if tab == 'feedback':
            return 'voices_feedback'
        if tab == 'report':
            return 'voices_report'
        topic = args.get('topic')
        if topic == 'insurance':
            return 'voices_insurance'
        if topic == 'sahayak':
            return 'voices_sahayak'
        if topic == 'general':
            return 'voices_general'
        return 'voices_contact'
    return ALIASES.get(active, active)


def section_for(active, args=None):
    """Which tab the given page belongs to. Defaults to the first, so an unknown key still
    renders a sane menu rather than an empty one."""
    key = current_key(active, args)
    for section in SECTIONS:
        if any(i['key'] == key for i in section['items']):
            return section['key']
    return SECTIONS[0]['key']


# Screens reached from another screen rather than from the menu. They have no line of their own,
# but the header switcher still has to say which product you are in -- without this it falls back
# to "All screens", which reads as though the menu were showing everything.
SIDE_SCREENS = {
    'admin.cs_screen_access': 'site',
    'admin.new_user': 'site',
    'admin.translations_list': 'site',
    'admin.feedback': 'companion',
    'admin.contact_messages': 'companion',
}

# endpoint -> section, so a control that renders before the sidebar (the header switcher) can
# still tell where it is. Built once.
_SECTION_BY_ENDPOINT = {i['endpoint']: sec['key'] for sec in SECTIONS for i in sec['items']}
_SECTION_BY_ENDPOINT.update(SIDE_SCREENS)


def section_for_endpoint(endpoint, args=None):
    """Which tab an endpoint belongs to. Two screens answer for more than one product -- the
    enquiry inbox and the help centre -- so for those the query string settles it, the same rule
    current_key follows."""
    args = args or {}
    if endpoint == 'admin.voices':
        if (args.get('tab') or 'contact') == 'contact':
            if args.get('topic') == 'insurance':
                return 'insurance'
            if args.get('topic') == 'sahayak':
                return 'sahayak'
            if args.get('topic') == 'general':
                return 'site'
        return 'companion'
    if endpoint == 'admin.help_center_page':
        site = args.get('site')
        return site if site in ('insurance', 'sahayak') else 'companion'
    return _SECTION_BY_ENDPOINT.get(endpoint or '')


def is_dashboard(active):
    return active == DASHBOARD['key']
