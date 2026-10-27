"""The tour guide (2026-10-27): short guided walks through the staff console, a spotlight on one part of the screen at a
time with a few words on what it is for.

Where it lives
    The round "Tour guide" button at the bottom left of every staff page opens the guide: the tours made for this
    person's role first, the ones for everybody ("Common places"), and "Find a screen" -- every screen they may open,
    with what it does and where it sits in the menu, each one a short tour of its own. Ten seconds after somebody
    lands in the console the guide asks once whether to show them round (should_ask): "Yes, show me", "Not now"
    (asked again at their next sign-in) or "Don't ask again". Finishing a tour stops the question too.

What a tour is
    TOURS below: a key, a title, who it is for (`for`: profile keys of services/role_rights.PROFILES, or 'all') and
    its steps. A step is (page, spot, title, words): `page` a page key of services/access.PAGES (None: whatever
    screen is open), optionally 'page>endpoint' for one screen of that page; `spot` the CSS selectors of the part to
    light up, the first one on the screen wins (none on the screen: the words show in the middle). Steps on pages
    this person may not open are left out, and so is a tour with none left. Nothing here changes anything: a tour
    only opens screens and points.

Who gets which tours
    profiles(user): the profiles their roles were made from ("Start from a profile" on the Roles screen), else
    guessed from what they may open (a site admin is Admin, a workspace owner Owner). The guide puts those tours
    under "For you", the common ones under "Common places", and every other role's tour they can follow under "More
    tours" -- a lead who wants to see an agent's day can.
"""
from datetime import datetime

from flask import url_for

from app import db
from app.services import access

ASK_AFTER_SECONDS = 10

# the parts of every staff screen (base.html, _staff_nav.html, _page_head.html)
RAIL = ('[data-tour="rail"]', '.staff-nav')
FIND = ('[data-tour="find"]',)
PANEL = ('[data-tour="panel"]', '.staff-nav')
PLUS = ('#qcDD',)
STAR = ('#favDD',)
FAVS = ('[data-tour="favs"]', '.staff-nav')
HEAD = ('.ui-head', '.wpb-head', 'main h1', 'h1')
GUIDE = ('#tgBtn',)


def S(page, spot, title, words):
    return {'page': page, 'spot': tuple(spot) if spot else (), 'title': title, 'text': words}


TOURS = (
    # ------------------------------------------------------------------------------------------------ for everybody
    {'key': 'basics', 'for': 'all', 'icon': 'fa-compass', 'title': 'Getting around',
     'says': 'The menu rail, finding anything, making something new, your notifications and your account.',
     'steps': (
         S(None, RAIL, 'Your work areas',
           'Down the left: Home, Inbox, Leads, Contacts, Tasks, Services, Reports, Content and Automate, then Help and '
           'the Set-up gear. You only see the areas your role includes.'),
         S(None, PANEL, 'The lines of one area',
           'Click an area to see its screens here. The numbers say how much is waiting on each one.'),
         S(None, FIND, 'Find anything',
           'Type a screen’s name to jump to it, or a name, a phone number or an e-mail to find a person, a trip, a '
           'quote or a booking.'),
         S(None, PLUS, 'Make something new',
           'The + makes a lead, a companion post, a blog post or an import from any screen. Shortcut: Ctrl+Shift+K.'),
         S(None, STAR, 'Keep a page close',
           'The star keeps this page, with its filters, in your favourites, and saves filters as a view your team '
           'can use.'),
         S(None, ('#tzDD',), 'Which clock',
           'Every time on every screen is shown in the zone you choose here: India, a US zone or UTC.'),
         S(None, ('.notif-wrapper',), 'Notifications',
           'What happened while you were away: new leads, replies, things handed to you.'),
         S(None, ('.user-menu-wrapper',), 'Your account',
           'Notification settings, your password, Sign-in & security (two-step sign-in), and “Working as” when you '
           'have more than one role.'),
         S(None, GUIDE, 'The tour guide',
           'Come back here any time: tours for your role, the common places, and every screen explained.'),
     )},
    {'key': 'favourites', 'for': 'all', 'icon': 'fa-star', 'title': 'Favourites & saved views',
     'says': 'Star any page, save its filters as a view, share a view with your team only.',
     'steps': (
         S(None, STAR, 'Star this page',
           'Click the star to keep the page you are on, with the filters it has now, in your favourites. Give it '
           'any name you like.'),
         S(None, STAR, 'Save the filters as a view',
           'On a list with filters set, “Save as a view” keeps them under a name. Choose who sees it: only you, or '
           'you and your team. Nobody outside your team ever sees it.'),
         S(None, FAVS, 'Your favourites',
           'Your starred pages and views are at the top of the menu, one click from any screen.'),
         S('crm_board', ('.vw-menu', '.lt-bar') + HEAD, 'Views on Leads and Contacts',
           'Leads and Contacts keep their views in their own Views menu, with the ready-made ones. The star beside '
           'a view adds it to your favourites.'),
         S('@favourites', HEAD, 'Favourites & views',
           'Rename, reorder and remove your favourites here, change who sees your views, and find the views your '
           'team shared with you.'),
     )},
    {'key': 'screens', 'for': 'all', 'icon': 'fa-window-maximize', 'title': 'How every screen works',
     'says': 'The heading, the ? help, ⋯ More and the switch at the top right.',
     'steps': (
         S(None, ('.ui-head .ui-title',) + HEAD, 'What this screen is',
           'Every screen starts the same way: its name and one line on what it is for.'),
         S(None, ('.ui-head .help-pop', '.help-pop'), 'How this works',
           'The ? beside that line opens a few lines on how the screen works.'),
         S(None, ('.ui-head .ui-switch', '.ui-switch'), 'Two screens, one line',
           'Where a menu line holds two screens (Sales results and Forecast), the switch at the top right swaps them.'),
         S(None, ('.ui-head .ui-more', '.ui-more'), 'More',
           'Things you do less often wait under ⋯ More, so the screen stays calm.'),
         S(None, ('.ui-look-only',), 'Only to look',
           'If your role may only look at a screen, a line under the heading says so, and nothing can be changed.'),
     )},

    # ---------------------------------------------------------------------------------------------- one per role
    {'key': 'sales_agent', 'for': ('sales_agent',), 'icon': 'fa-headset', 'title': 'A day in sales',
     'says': 'My day, the Inbox, Leads, the half-hourly check, the calendar and contacts.',
     'steps': (
         S('crm_today', HEAD, 'Start here: My day',
           'What to do today, from the top down: follow-ups due, new leads, people waiting on a reply. Each card has '
           'one button that does the job.'),
         S('crm_today', ('.step',) + HEAD, 'One job at a time',
           'Work the cards in order. When a card is done it says so; the ones still open stay at the top.'),
         S('crm_inbox', ('.ib-who',) + HEAD, 'All conversations',
           'Every chat, e-mail and form in one list, one row a person. “Waiting on us” are the ones to answer first.'),
         S('crm_board', ('.lt-bar',) + HEAD, 'Your leads',
           'Every enquiry by stage. Filter by who looks after it, stage, date or status; “More filters” has the rest.'),
         S('crm_board', ('.lsw',) + HEAD, 'Board, list, flow',
           'Drag cards on the Board, scan the List, or see the Flow of a pipeline. Open a lead to call, message, '
           'quote and move it on.'),
         S('crm_checks', ('.hc-now-head',) + HEAD, 'The half-hourly check',
           'Each half hour, look at every inbox and tick it. Missed ones show up in “Catch up”.'),
         S('crm_calendar', ('.cal-filters',) + HEAD, 'Your calendar',
           'Calls, meetings, tasks and follow-ups by day and week.'),
         S('crm_people', HEAD, 'Contacts',
           'Everybody you have talked to, with their family, their chats and their leads.'),
     )},
    {'key': 'service_agent', 'for': ('service_agent',), 'icon': 'fa-handshake-angle', 'title': 'The service desk',
     'says': 'Service to-do, the website forms, WhatsApp chats, companion posts, matches, insurance and Sahayak.',
     'steps': (
         S('home', ('.admin-card',) + HEAD, 'Service to-do',
           'What needs somebody now, across every product, the most urgent first.'),
         S('voices_contact', HEAD, 'The website forms',
           'Messages from the website’s forms, one list per form, under Inbox › Website forms.'),
         S('wa_inbox', HEAD, 'WhatsApp chats',
           'The business WhatsApp number’s chats. Reply here; the lead and the contact keep the history.'),
         S('posts', HEAD, 'Companion posts',
           'Every travel-companion post: check new ones, fix details, close the ones that are done.'),
         S('matches', HEAD, 'Match queue',
           'Travellers who could fly together, waiting for somebody to look and introduce them.'),
         S('insurance', HEAD, 'Insurance quotes',
           'Travel insurance enquiries and the quotes sent.'),
         S('sahayak', HEAD, 'Sahayak bookings',
           'Home-care bookings for parents in India.'),
         S('crm_inbox', HEAD, 'All conversations',
           'Chats, e-mails and forms of your own leads, one row a person.'),
     )},
    {'key': 'team_lead', 'for': ('team_lead',), 'icon': 'fa-user-tie', 'title': 'Leading a team',
     'says': 'Team today, Team analysis, Sales results, Forecast, the Report builder and Targets.',
     'steps': (
         S('crm_tracker', HEAD, 'Team today',
           'Who is doing what today: calls, replies, follow-ups late, the half-hourly checks.'),
         S('crm_team', HEAD, 'Team analysis',
           'Each person over a period, side by side: leads, replies, speed, won and lost.'),
         S('crm_insights', ('.ui-switch',) + HEAD, 'Sales results and Forecast',
           'What was sold and what is coming. The switch at the top right swaps the two.'),
         S('crm_report_builder', HEAD, 'Report builder',
           'Build a report of your own: what to count, grouped by what. Save it and share it.'),
         S('crm_targets', HEAD, 'Targets',
           'Monthly targets per person and product; Results measures against them.'),
         S('crm_board', ('.lt-bar',) + HEAD, 'Your team’s leads',
           'Leads shows your team’s leads. “Looked after by” narrows it to one person. Save it as a view for your team.'),
         S('wa_broadcasts', HEAD, 'Broadcasts',
           'One WhatsApp message to a list of contacts who said yes to offers.'),
     )},
    {'key': 'content_editor', 'for': ('content_editor',), 'icon': 'fa-pen-nib', 'title': 'Writing for the website',
     'says': 'Blog posts, the editor, importing from Word, sidebars beside posts, and the site’s pages.',
     'steps': (
         S('blog_list', ('.wpb-quick',) + HEAD, 'The blog',
           'Every post, its state and how it is doing. Quick links start a new post or an import.'),
         S('blog', HEAD, 'The editor',
           'Write the post with blocks: headings, pictures, columns, slideshows, videos, buttons. The checks on the '
           'right say what to fix before publishing.'),
         S('blog_import', HEAD, 'Write it in Word',
           'Download the template, write the post in Word or Google Docs, and import it here as a draft.'),
         S('blog_list>admin.blog_sidebars', ('.sbm-help',) + HEAD, 'Beside the post',
           'Flyers, ads and links in the left and right sidebars, for every post, some categories or some posts. '
           'Drag a card’s edge to resize it.'),
         S('landing', HEAD, 'The landing page',
           'The words and pictures of the website’s front page.'),
         S('insurance_page', HEAD, 'The insurance page',
           'The travel insurance page’s content.'),
     )},
    {'key': 'admin', 'for': ('admin', 'owner'), 'icon': 'fa-user-gear', 'title': 'Running the console',
     'says': 'Health, people, teams, roles, security, integrations and downloads.',
     'steps': (
         S('health', ('.hl-grid',) + HEAD, 'Health',
           'How everything is doing: what needs somebody first, then a part per product. Every number opens the '
           'list behind it.'),
         S('ws_members', HEAD, 'Team members',
           'Everybody in the workspace, their role, their teams and whether two-step sign-in is on.'),
         S('ws_teams', HEAD, 'Teams',
           'A team shares leads, and the saved views its people share are seen by that team only.'),
         S('ws_roles', HEAD, 'Roles',
           'What each role opens and may do. Start from a profile; make a page “only to look”; hide numbers.'),
         S('ws_security', HEAD, 'Security',
           'Two-step sign-in rules, who is signed in where, and the log of sign-ins and downloads.'),
         S('crm_integrations', HEAD, 'Integrations',
           'WhatsApp, website chat, lead forms and the websites allowed to send leads.'),
         S('crm_export', HEAD, 'Downloads',
           'Every download in one place. Each one asks why, and the answer is kept in the log.'),
         S('guide', HEAD, 'Help centre',
           'Each product’s help, and every screen: what it is for and where it is in the menu.'),
     )},
    {'key': 'owner', 'for': ('owner', 'admin'), 'icon': 'fa-crown', 'title': 'Your workspace',
     'says': 'The workspace, its menu, lead sources, pipelines, imports and the recycle bin.',
     'steps': (
         S('ws_settings', HEAD, 'The workspace',
           'Its name, its products switched on, its WhatsApp number.'),
         S('ws_menu', HEAD, 'Menu builder',
           'Arrange, rename or hide menu lines for everybody in the workspace. Reset brings the standard menu back.'),
         S('crm_sources', HEAD, 'Lead sources',
           'Where leads come from: each number, form and page, and which are on the half-hourly check.'),
         S('crm_pipelines', HEAD, 'Pipelines & products',
           'The stages a lead goes through, and what you sell.'),
         S('crm_data', HEAD, 'Import & export',
           'Bring a list in, or take one out.'),
     )},
)
TOUR_BY_KEY = {t['key']: t for t in TOURS}
SPECIAL_PAGES = {'@favourites': ('my.favourites', None)}        # screens of everybody's, not pages of a role


# --------------------------------------------------------------------------------------------- who is this person

def profiles(user):
    """The profile keys that describe `user`, most specific first (module note)."""
    from app.services import role_rights
    act = access.acting_role(user)
    if user.is_admin and (act is None or act.system_key == 'admin'):
        return ['admin', 'owner']
    keys = []
    ws = access.current_workspace(user)
    member = next((m for m in access.memberships(user) if ws is not None and m.workspace_id == ws.id), None)
    if act is None and member is not None and member.is_owner:
        keys.append('owner')
    roles = [act] if act is not None else (
        ([member.role] if member is not None and member.role is not None else [])
        + ([t.role for t in access._teams(member) if t.role is not None] if member is not None else []))
    for r in roles:
        prof = (r.rights or {}).get('profile') if isinstance(r.rights, dict) else None
        if r.system_key == 'admin':
            prof = 'admin'
        if prof in role_rights.PROFILE_BY_KEY and prof not in keys:
            keys.append(prof)
    if keys:
        return keys
    pages = access.pages_for(user)
    if pages & access.TEAM_LEAD_EXTRA:
        keys.append('team_lead')
    if pages & {'crm_board', 'crm_today'}:
        keys.append('sales_agent')
    if pages & {'home', 'posts', 'matches'}:
        keys.append('service_agent')
    if pages & {'blog_list', 'blog', 'landing'}:
        keys.append('content_editor')
    return keys


def profile_label(keys):
    from app.services import role_rights
    names = [role_rights.PROFILE_BY_KEY[k]['label'] for k in keys if k in role_rights.PROFILE_BY_KEY]
    return names[0] if names else None


# ------------------------------------------------------------------------------------------------ the tours, for one

def _step_url(page, user):
    """The address a step opens for `user`, '' for "whatever screen is open", None when they may not open it."""
    if page is None:
        return ''
    if page in SPECIAL_PAGES:
        return url_for(SPECIAL_PAGES[page][0])
    key, _, endpoint = page.partition('>')
    if key not in access.PAGES or not access.can(user, key):
        return None
    if endpoint:
        try:
            return url_for(endpoint)
        except Exception:          # noqa: BLE001 -- a screen switched off
            return None
    return access.page_url(access.PAGES[key], _console(user))


def _console(user):
    """The console a site admin works in is /admin, everybody else's /cs -- whatever screen asked (the guide's own
    address is neither)."""
    from app.services import page_address
    return page_address.console_of(user)


def _for(tour, user):
    steps = []
    for s in tour['steps']:
        url = _step_url(s['page'], user)
        if url is None:
            continue
        steps.append({'url': url or None, 'spot': list(s['spot']), 'title': s['title'], 'text': s['text']})
    return steps


def for_user(user):
    """What the guide shows: {'profile', 'tours': [...], 'screens': [...], 'ask', 'recommended'}."""
    mine = profiles(user)
    done = set(state(user).get('done') or ())
    out = []
    for t in TOURS:
        steps = _for(t, user)
        if not steps:
            continue
        if t['for'] == 'all':
            group = 'common'
        elif set(t['for']) & set(mine):
            group = 'you'
        elif len([s for s in steps if s['url']]) >= 2:
            group = 'more'
        else:
            continue
        out.append({'key': t['key'], 'title': t['title'], 'icon': t['icon'], 'says': t['says'], 'group': group,
                    'steps': steps, 'done': t['key'] in done})
    yours = [t['key'] for t in out if t['group'] == 'you']
    return {'profile': profile_label(mine), 'tours': out, 'screens': screens(user),
            'ask': state(user).get('ask') != 'never',
            'recommended': yours[0] if yours else 'basics'}


def screens(user):
    """Every screen this person may open, by area, for "Find a screen": [{'label', 'icon', 'pages': [{'label', 'icon',
    'says', 'where', 'url'}]}] -- the Help centre's screen guide, only the ones they can open."""
    out, console = [], _console(user)
    for area in access.screen_guide(user):
        pages = [{'label': p['label'], 'icon': p['icon'], 'says': p['says'], 'where': p['where'],
                  'url': access.page_url(access.PAGES[p['key']], console) or p['url']}
                 for p in area['pages'] if p['url']]
        if pages:
            out.append({'label': area['label'], 'icon': area['icon'], 'pages': pages})
    return out


# --------------------------------------------------------------------------------------------------- the question

def state(user):
    return dict(user.tour_state or {}) if isinstance(user.tour_state, dict) else {}


def _when(text):
    try:
        return datetime.fromisoformat(text) if text else None
    except (TypeError, ValueError):
        return None


def should_ask(user):
    """Ask "Would you like a tour?" on this visit? Not after "Don't ask again", not once a tour was finished, and
    once a sign-in: again only after signing in since the last time it was shown."""
    st = state(user)
    if st.get('ask') == 'never' or st.get('done'):
        return False
    asked = _when(st.get('asked_at'))
    return asked is None or bool(user.last_login and user.last_login > asked)


ANSWERS = ('shown', 'yes', 'later', 'never', 'again')


def answer(user, what):
    """The question was shown, or answered: 'yes' / 'later' (ask at the next sign-in) / 'never'; 'again' undoes
    "never" (the guide's "Ask me when I sign in")."""
    if what not in ANSWERS:
        return False
    st = state(user)
    if what == 'never':
        st['ask'] = 'never'
    elif what == 'again':
        st.pop('ask', None)
        st.pop('asked_at', None)
    else:
        st['asked_at'] = datetime.utcnow().isoformat()
    user.tour_state = st
    db.session.commit()
    return True


def finished(user, key):
    if key not in TOUR_BY_KEY and not key.startswith('screen:'):
        return False
    st = state(user)
    done = [k for k in (st.get('done') or []) if k in TOUR_BY_KEY]
    if key in TOUR_BY_KEY and key not in done:
        done.append(key)
    st['done'] = done
    if key.startswith('screen:') and not done:
        st['asked_at'] = datetime.utcnow().isoformat()
    user.tour_state = st
    db.session.commit()
    return True
