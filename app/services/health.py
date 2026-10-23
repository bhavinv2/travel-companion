"""Health (Overview › Health): the master screen -- how every part of the portal is doing, and what needs
somebody now.

    attention   every number below that needs somebody, worst first, each opening the screen that fixes it
    sales       open leads, not given to anyone, new, late follow-ups, customers waiting, won and lost; leads a
                day; where they came from, the product and how they came; open leads by stage and by owner
    users       accounts, new ones a day, signed in lately, the team and who is away
    companion   live posts, new ones, waiting for a claim, leaving soon, the match queue, enquiries, reviews
    insurance   quote requests and the ones that failed, by plan; enquiries
    sahayak     bookings waiting for somebody, given out, done, cancelled; applications and enquiries
    service     Service to-do: posts to chase (services/service_todo), general enquiries, your notifications
    system      WhatsApp, the half-hourly check, lead sources not set up, the blog, the scraper

A part is drawn only when the workspace has its area switched on and this person may open a screen in it; a
number opens its screen only for somebody who may open that screen. Counted fresh on each visit (grouped
queries, nothing saved). `days` (PERIODS) is the period for everything that came in; the rest is how things
stand now. A number's state: 'bad' (somebody should act now), 'warn' (waiting), 'ok' (nothing waiting), ''
(just a count).
"""
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app import db
from app.services import access

PERIODS = (7, 30, 90)
IST = timedelta(hours=5, minutes=30)
STAGE_ROLES = ('new', 'cold', 'prospect', 'pipeline', 'customer')
SEVERITY = {'bad': 0, 'warn': 1}


class _Read:
    """One visit: who is looking, the period, and the links they may follow."""

    def __init__(self, user, days, now):
        self.user, self.days, self.now = user, days, now
        self.since = now - timedelta(days=days)
        self.before = self.since - timedelta(days=days)
        self.today = (now + IST).date()
        self.on = set(access.enabled_modules(access.current_workspace(user)))
        self.attention = []

    def url(self, key, **args):
        """The screen `key` (a page) with `args`, or None when this person may not open it."""
        page = access.PAGES.get(key)
        if page is None or page['module'] not in self.on or not access.can(self.user, key):
            return None
        return access.page_url(page, **args)

    def has(self, module):
        return module in self.on and any(access.can(self.user, k) for k, p in access.PAGES.items()
                                         if p['module'] == module)

    def came_in(self):
        """The leads list's words for "came in during the period"."""
        if self.days in (7, 30):
            return {'dr': '%dd' % self.days}
        return {'dr': 'custom', 'd1': (self.today - timedelta(days=self.days - 1)).isoformat(),
                'd2': self.today.isoformat()}

    def tile(self, area, label, n, href=None, state='', note='', tip='', alert=None, icon=None):
        """A number. `alert`: the words for the attention list when its state is bad or warn."""
        t = {'label': label, 'n': n, 'href': href, 'state': state, 'note': note, 'tip': tip, 'icon': icon}
        if alert and state in SEVERITY:
            self.attention.append({'area': area, 'state': state, 'text': alert, 'href': href})
        return t


def _plural(n, one, many=None):
    return '%d %s' % (n, one if n == 1 else (many or one + 's'))


def _age(dt, now):
    """'3 days' / '5 hours' since `dt`."""
    if dt is None:
        return ''
    h = int((now - dt).total_seconds() // 3600)
    return _plural(h // 24, 'day') if h >= 48 else _plural(max(h, 1), 'hour')


def _delta(now_n, before_n):
    """The change on the period before, for a tile's note: '+12% on the 30 days before'."""
    if not before_n:
        return 'new' if now_n else ''
    pct = round((now_n - before_n) * 100 / before_n)
    return '%s%d%%' % ('+' if pct > 0 else '', pct)


def _nice(top):
    """A clean top for a chart's scale: 1, 2, 5 times a power of ten, at least `top`."""
    if top <= 4:
        return 4
    step = 10 ** (len(str(int(top))) - 1)
    for m in (1, 2, 5, 10):
        if m * step >= top:
            return int(m * step)
    return int(10 * step)


def columns(stamps, r):
    """Counts a day (India time) of `stamps` (UTC datetimes) over the period, for a column chart:
    {'points': [{'day', 'n', 'pct', 'label'}], 'top', 'ticks', 'total', 'peak', 'first', 'mid', 'last'}."""
    days = [r.today - timedelta(days=i) for i in range(r.days - 1, -1, -1)]
    count = Counter((s + IST).date() for s in stamps if s is not None)
    top = _nice(max([count[d] for d in days] or [0]))
    points = [{'day': d, 'n': count[d], 'pct': round(100 * count[d] / top, 2),
               'label': '%s %d %s' % (d.strftime('%a'), d.day, d.strftime('%b'))} for d in days]
    peak = max(points, key=lambda p: p['n'])
    return {'points': points, 'top': top, 'ticks': (top, top // 2, 0),
            'total': sum(p['n'] for p in points), 'peak': peak if peak['n'] else None,
            'first': points[0]['label'], 'mid': points[len(points) // 2]['label'], 'last': points[-1]['label']}


def _bars(rows):
    """[(label, n, href, extra...)] as bars: {'label', 'n', 'pct', 'href', 'share'} -- pct against the biggest,
    share of the whole."""
    top = max([r[1] for r in rows] or [0])
    total = sum(r[1] for r in rows)
    return [{'label': r[0], 'n': r[1], 'href': r[2], 'pct': round(100 * r[1] / top, 1) if top else 0,
             'share': round(100 * r[1] / total) if total else 0, 'key': r[3] if len(r) > 3 else None}
            for r in rows]


# ============================================================================================ the parts

def _sales(r):
    from app.models import CrmLead, CrmSource, CrmStage, CrmTask, CrmTouchpoint, User
    from app.services import crm, crm_metrics, crm_products, crm_sources
    L = CrmLead
    board = dict(view='list', p='all', owner='all')
    came = r.came_in()
    open_q = L.query.filter(L.status == 'open')
    n_open = open_q.count()
    n_none = open_q.filter(L.owner_id.is_(None)).count()
    oldest = db.session.query(func.min(L.created_at)).filter(L.status == 'open', L.owner_id.is_(None)).scalar()
    new_n = L.query.filter(L.created_at >= r.since).count()
    new_before = L.query.filter(L.created_at >= r.before, L.created_at < r.since).count()
    won = L.query.filter(L.status == 'won', L.closed_at >= r.since).count()
    lost = L.query.filter(L.status == 'lost', L.closed_at >= r.since).count()
    late = CrmTask.query.filter(CrmTask.status == 'open', CrmTask.due_at <= r.now).count()
    end_today = datetime.combine(r.today + timedelta(days=1), datetime.min.time()) - IST
    due_today = CrmTask.query.filter(CrmTask.status == 'open', CrmTask.due_at > r.now,
                                     CrmTask.due_at < end_today).count()
    owned = select(L.person_id).where(L.status == 'open')
    w = crm_metrics.waiting_rows(CrmTouchpoint.person_id.in_(owned)).subquery()
    waiting = db.session.execute(select(func.count()).select_from(w)).scalar() or 0

    area = 'Sales CRM'
    tiles = [
        r.tile(area, 'Open leads', n_open, r.url('crm_board', status='open', **board), icon='fa-table-columns'),
        r.tile(area, 'Not given to anyone', n_none,
               r.url('crm_board', view='list', p='all', owner='none', status='open'),
               state=('bad' if oldest and r.now - oldest > timedelta(hours=24) else 'warn') if n_none else 'ok',
               note=('oldest %s' % _age(oldest, r.now)) if n_none else 'every open lead has somebody',
               alert='%s not given to anyone (the oldest %s)' % (_plural(n_none, 'open lead'), _age(oldest, r.now)),
               icon='fa-user-slash'),
        r.tile(area, 'New in %d days' % r.days, new_n, r.url('crm_board', **dict(board, **came)),
               note=_delta(new_n, new_before) and '%s on the %d days before' % (_delta(new_n, new_before), r.days),
               icon='fa-inbox'),
        r.tile(area, 'Customers waiting for a reply', waiting,
               r.url('crm_board', chat='waiting', **board), state='bad' if waiting else 'ok',
               note='they wrote last' if waiting else 'nobody waiting',
               alert='%s waiting for a reply' % _plural(waiting, 'customer'), icon='fa-comment-dots'),
        r.tile(area, 'Follow-ups late', late, r.url('crm_board', follow='late', **board),
               state='warn' if late else 'ok', note='%d more due today' % due_today,
               alert='%s late' % _plural(late, 'follow-up'), icon='fa-clock'),
        r.tile(area, 'Won in %d days' % r.days, won, r.url('crm_insights', days=r.days),
               note='%d lost' % lost, icon='fa-trophy'),
    ]

    # leads a day
    stamps = [s for (s,) in db.session.query(L.created_at).filter(L.created_at >= r.since).all()]
    daily = columns(stamps, r)

    # where the leads of the period came from: the lead sources' groups
    rows = db.session.query(L.source_id, func.count(L.id)).filter(L.created_at >= r.since).group_by(L.source_id).all()
    src = {s.id: s for s in CrmSource.query.filter(CrmSource.id.in_([i for i, _ in rows if i])).all()} if rows else {}
    by_group = Counter()
    for sid, n in rows:
        by_group[crm_sources.group_of(src.get(sid)) if sid in src else crm_sources.UNSORTED[0]] += n
    order = [g for g, _n, _i, _items in crm_sources.GROUPS] + [crm_sources.UNSORTED[0]]
    groups = _bars([(crm_sources.GROUP_NAMES[g][0] if g in crm_sources.GROUP_NAMES else crm_sources.UNSORTED[1], by_group[g],
                     r.url('crm_board', src='g:%s' % g if g in crm_sources.GROUP_NAMES else 'none',
                           **dict(board, **came)))
                    for g in order if by_group[g]])

    # the product
    names = crm_products.labels()
    rows = (db.session.query(L.product, func.count(L.id)).filter(L.created_at >= r.since)
            .group_by(L.product).order_by(func.count(L.id).desc()).all())
    products = _bars([(names.get(code, code or 'Not known'), n, None) for code, n in rows])

    # how they came: by themselves, added by us, brought in from a list
    rows = (db.session.query(L.imported, L.created_by_id, func.count(L.id)).filter(L.created_at >= r.since)
            .group_by(L.imported, L.created_by_id).all())
    staff = crm_sources.staff_ids([u for _i, u, _n in rows])
    how = Counter()
    for imported, by, n in rows:
        how['imported' if imported else 'manual' if by in staff else 'organic'] += n
    origins = _bars([(word, how[k], r.url('crm_board', how=k, **dict(board, **came)), k)
                     for k, word, _says, _icon in crm_sources.ORIGINS])

    # open leads by stage (the kind of stage: cold, prospect, ...) and by who has them
    rows = db.session.query(L.stage_id, func.count(L.id)).filter(L.status == 'open').group_by(L.stage_id).all()
    stages = {s.id: s for s in CrmStage.query.filter(CrmStage.id.in_([i for i, _ in rows if i])).all()} if rows else {}
    by_role = Counter()
    for sid, n in rows:
        by_role[stages[sid].role if sid in stages else 'new'] += n
    roles = _bars([(crm.ROLE_LABELS.get(k, k), by_role[k], None, k) for k in STAGE_ROLES if by_role[k]])

    rows = (db.session.query(L.owner_id, func.count(L.id)).filter(L.status == 'open')
            .group_by(L.owner_id).order_by(func.count(L.id).desc()).all())
    people = {u.id: u for u in User.query.filter(User.id.in_([i for i, _ in rows if i])).all()} if rows else {}
    owners = _bars([('Not given to anyone' if oid is None else (people[oid].full_name if oid in people else '#%d' % oid),
                     n, r.url('crm_board', view='list', p='all', owner='none' if oid is None else str(oid), status='open'),
                     'none' if oid is None else 'person')
                    for oid, n in sorted(rows, key=lambda x: (x[0] is not None, -x[1]))])
    return {'tiles': tiles, 'daily': daily, 'groups': groups, 'products': products, 'origins': origins,
            'roles': roles, 'owners': owners, 'href': r.url('crm_board'), 'new_n': new_n}


def _users(r):
    from app.models import User, WorkspaceMember
    area = 'Users'
    total = User.query.count()
    new_n = User.query.filter(User.created_at >= r.since).count()
    new_before = User.query.filter(User.created_at >= r.before, User.created_at < r.since).count()
    verified = User.query.filter(User.is_verified.is_(True)).count()
    seen = User.query.filter(User.last_login >= r.now - timedelta(days=7)).count()
    ws = access.current_workspace(r.user)
    team = WorkspaceMember.query.filter_by(workspace_id=ws.id) if ws else None
    n_team = team.count() if team is not None else 0
    away = team.filter(WorkspaceMember.away_until > r.now).count() if team is not None else 0
    stamps = [s for (s,) in db.session.query(User.created_at).filter(User.created_at >= r.since).all()]
    tiles = [
        r.tile(area, 'Accounts', total, r.url('users'), icon='fa-users'),
        r.tile(area, 'New in %d days' % r.days, new_n, r.url('users'),
               note=_delta(new_n, new_before) and '%s on the %d days before' % (_delta(new_n, new_before), r.days),
               icon='fa-user-plus'),
        r.tile(area, 'E-mail checked', verified, r.url('users', verified='yes'),
               note='%d%% of accounts' % round(100 * verified / total) if total else '', icon='fa-envelope-circle-check'),
        r.tile(area, 'Signed in this week', seen, None, icon='fa-right-to-bracket'),
        r.tile(area, 'Team members', n_team, r.url('ws_members'),
               note=('%d away now' % away) if away else 'nobody away', icon='fa-people-group'),
    ]
    return {'tiles': tiles, 'daily': columns(stamps, r), 'new_n': new_n}


def _companion(r):
    from app.models import CompanionRequest, ContactMessage, Feedback, Match, MatchReport
    area, CR = 'Travel Companion', CompanionRequest
    live = CR.query.filter(CR.status.in_(['open', 'matched']))
    n_live = live.count()
    leaving = live.filter(CR.from_date >= r.today, CR.from_date <= r.today + timedelta(days=7)).count()
    new_n = CR.query.filter(CR.created_at >= r.since).count()
    unclaimed = CR.query.filter_by(status='unconfirmed').count()
    queue = Match.query.filter(Match.needs_cs_attention.is_(True), Match.status != 'dismissed').count()
    connected = Match.query.filter(Match.status == 'connected', Match.updated_at >= r.since).count()
    enquiries = ContactMessage.query.filter_by(topic='companion', status='new').count()
    reviews = Feedback.query.filter_by(is_approved=False).count()
    reports = MatchReport.query.filter_by(status='open').count()
    tiles = [
        r.tile(area, 'Live posts', n_live, r.url('posts'), note='%d leave in 7 days' % leaving, icon='fa-plane-departure'),
        r.tile(area, 'New posts in %d days' % r.days, new_n, r.url('posts'), icon='fa-plus'),
        r.tile(area, 'Waiting for a claim', unclaimed, r.url('posts', status='unconfirmed'),
               state='warn' if unclaimed else 'ok', note='the traveller has not claimed the post',
               alert='%s waiting for the traveller to claim' % _plural(unclaimed, 'post'), icon='fa-link'),
        r.tile(area, 'Match queue', queue, r.url('matches'), state='warn' if queue else 'ok',
               note='%d connected in %d days' % (connected, r.days),
               alert='%s waiting in the match queue' % _plural(queue, 'match', 'matches'), icon='fa-handshake'),
        r.tile(area, 'New enquiries', enquiries, r.url('voices_contact'), state='warn' if enquiries else 'ok',
               alert='%s about Travel Companion not answered' % _plural(enquiries, 'enquiry', 'enquiries'),
               icon='fa-envelope'),
        r.tile(area, 'Reviews to check', reviews, r.url('voices_feedback'), state='warn' if reviews else 'ok',
               alert='%s to approve or turn down' % _plural(reviews, 'review'), icon='fa-star'),
        r.tile(area, 'Reported matches', reports, r.url('voices_report'), state='bad' if reports else 'ok',
               alert='%s reported as a problem' % _plural(reports, 'match', 'matches'), icon='fa-flag'),
    ]
    rows = dict(db.session.query(CR.status, func.count(CR.id)).group_by(CR.status).all())
    words = (('unconfirmed', 'Waiting for a claim'), ('open', 'Open'), ('matched', 'Matched'), ('closed', 'Closed'))
    states = _bars([(w, rows.get(k, 0), r.url('posts', status=k), k) for k, w in words])
    return {'tiles': tiles, 'states': states}


def _insurance(r):
    from app.models import ContactMessage, InsuranceQuote
    area, Q = 'Travel Insurance', InsuranceQuote
    new_n = Q.query.filter(Q.created_at >= r.since).count()
    new_before = Q.query.filter(Q.created_at >= r.before, Q.created_at < r.since).count()
    failed = Q.query.filter(Q.created_at >= r.since, Q.status == 'failed').count()
    enquiries = ContactMessage.query.filter_by(topic='insurance', status='new').count()
    tiles = [
        r.tile(area, 'Quote requests in %d days' % r.days, new_n, r.url('insurance'),
               note=_delta(new_n, new_before) and '%s on the %d days before' % (_delta(new_n, new_before), r.days),
               icon='fa-shield-heart'),
        r.tile(area, 'Quotes that failed', failed, r.url('insurance', status='failed'), state='warn' if failed else 'ok',
               note='in %d days' % r.days, alert='%s failed in %d days' % (_plural(failed, 'insurance quote'), r.days),
               icon='fa-triangle-exclamation'),
        r.tile(area, 'New enquiries', enquiries, r.url('voices_insurance'), state='warn' if enquiries else 'ok',
               alert='%s about travel insurance not answered' % _plural(enquiries, 'enquiry', 'enquiries'),
               icon='fa-envelope'),
        r.tile(area, 'All quote requests', Q.query.count(), r.url('insurance'), icon='fa-list'),
    ]
    rows = (db.session.query(Q.insurance_type, func.count(Q.id)).filter(Q.created_at >= r.since)
            .group_by(Q.insurance_type).order_by(func.count(Q.id).desc()).all())
    plans = _bars([((k or 'Not known').replace('_', ' ').capitalize(), n, None) for k, n in rows])
    return {'tiles': tiles, 'plans': plans}


def _sahayak(r):
    from app.models import ContactMessage, SahayakBooking, SAHAYAK_STATUS_LABELS
    area, B = 'Sahayak', SahayakBooking
    waiting = B.query.filter_by(status='new')
    n_wait = waiting.count()
    oldest = db.session.query(func.min(B.created_at)).filter(B.status == 'new').scalar()
    done = B.query.filter(B.status == 'completed', B.completed_at >= r.since).count()
    new_n = B.query.filter(B.created_at >= r.since).count()
    upcoming = B.query.filter(B.status == 'assigned').count()
    enquiries = ContactMessage.query.filter_by(topic='sahayak', status='new').count()
    tiles = [
        r.tile(area, 'Waiting for somebody', n_wait, r.url('sahayak', status='new'),
               state=('bad' if oldest and r.now - oldest > timedelta(hours=24) else 'warn') if n_wait else 'ok',
               note=('oldest %s' % _age(oldest, r.now)) if n_wait else 'every request has somebody',
               alert='%s waiting for somebody (the oldest %s)' % (_plural(n_wait, 'Sahayak request'), _age(oldest, r.now)),
               icon='fa-house-medical'),
        r.tile(area, 'Given to somebody', upcoming, r.url('sahayak', status='assigned'), icon='fa-user-nurse'),
        r.tile(area, 'Requests in %d days' % r.days, new_n, r.url('sahayak'), note='%d done' % done, icon='fa-inbox'),
        r.tile(area, 'Applications & enquiries', enquiries, r.url('voices_sahayak'), state='warn' if enquiries else 'ok',
               alert='%s about Sahayak not answered' % _plural(enquiries, 'application or enquiry', 'applications or enquiries'),
               icon='fa-user-plus'),
    ]
    rows = dict(db.session.query(B.status, func.count(B.id)).group_by(B.status).all())
    states = _bars([(SAHAYAK_STATUS_LABELS.get(k, k), rows.get(k, 0), r.url('sahayak', status=k), k)
                    for k in ('new', 'assigned', 'completed', 'cancelled')])
    return {'tiles': tiles, 'states': states}


def _service(r):
    from app.models import ContactMessage, Notification
    from app.services import service_todo
    area = 'Service to-do'
    chase = len(service_todo.needs_action(r.today, r.now)) if 'companion' in r.on else 0
    general = ContactMessage.query.filter_by(topic='general', status='new').count()
    mine = Notification.query.filter_by(user_id=r.user.id, is_read=False).count()
    return {'tiles': [
        r.tile(area, 'Posts to chase', chase, r.url('home'), state='warn' if chase else 'ok',
               note='no answer to a claim link, or leaving soon with nobody to contact',
               alert='%s for customer service to chase' % _plural(chase, 'trip post'), icon='fa-list-check'),
        r.tile(area, 'General enquiries', general, r.url('voices_general'), state='warn' if general else 'ok',
               alert='%s (all services) not answered' % _plural(general, 'enquiry', 'enquiries'), icon='fa-inbox'),
        r.tile(area, 'Your notifications', mine, r.url('notifications'), note='not read yet', icon='fa-bell'),
    ]}


def _system(r):
    area, tiles = 'System', []
    if 'crm' in r.on:
        from app.models import CrmSource
        from app.services import crm, crm_connection, crm_reports
        mode = crm.wa_mode()
        stuck = crm_connection.needs_attention(limit=20)['count'] if mode != 'off' else 0
        tiles.append(r.tile(area, 'WhatsApp', crm.WA_MODES.get(mode, mode), r.url('crm_connection'),
                            state='bad' if stuck else ('ok' if mode != 'off' else ''),
                            note=('%s to look at' % _plural(stuck, 'message')) if stuck else
                            ('connected' if mode != 'off' else 'the portal does not use WhatsApp yet'),
                            alert='%s on WhatsApp need a look' % _plural(stuck, 'message'), icon='fa-brands fa-whatsapp'))
        checks = crm.crm_settings()['check_channels']
        done = crm_reports.current_slot_done(checks)
        tiles.append(r.tile(area, 'Half-hourly check', 'Ticked' if done else 'Not ticked', r.url('crm_checks'),
                            state='ok' if done else 'warn', note='this half hour (or outside working hours)'
                            if done else "this half hour's inboxes",
                            alert="This half hour's inboxes are not ticked", icon='fa-clipboard-check'))
        unrouted = CrmSource.query.filter_by(status='unrouted').count()
        tiles.append(r.tile(area, 'Lead sources not set up', unrouted, r.url('crm_sources'),
                            state='warn' if unrouted else 'ok',
                            alert='%s not set up yet' % _plural(unrouted, 'lead source'), icon='fa-door-open'))
    if 'companion' in r.on:
        from app.models import Blog, ScrapeRun
        live = Blog.live(r.now).count()
        drafts = Blog.query.filter(Blog.is_published.isnot(True), Blog.trashed_at.is_(None)).count()
        soon = Blog.query.filter(Blog.is_published.is_(True), Blog.trashed_at.is_(None), Blog.published_at > r.now).count()
        tiles.append(r.tile(area, 'Blog posts live', live, r.url('blog_list'),
                            note='%d drafts, %d scheduled' % (drafts, soon), icon='fa-newspaper'))
        failed = ScrapeRun.query.filter(ScrapeRun.kind == 'run', ScrapeRun.status == 'failed',
                                        ScrapeRun.created_at >= r.since).count()
        if failed or access.can(r.user, 'scraper'):
            tiles.append(r.tile(area, 'Scraper runs failed', failed, r.url('scraper'), state='warn' if failed else 'ok',
                                note='in %d days' % r.days,
                                alert='%s failed in %d days' % (_plural(failed, 'scraper run'), r.days), icon='fa-spider'))
    return {'tiles': tiles}


PARTS = (('sales', 'Sales CRM', 'fa-filter-circle-dollar', 'crm', _sales),
         ('users', 'Users & team', 'fa-users', None, _users),
         ('companion', 'Travel Companion', 'fa-plane-departure', 'companion', _companion),
         ('insurance', 'Travel Insurance', 'fa-shield-heart', 'insurance', _insurance),
         ('sahayak', 'Sahayak', 'fa-house-medical', 'sahayak', _sahayak),
         ('service', 'Service to-do', 'fa-inbox', 'console', _service),
         ('system', 'System', 'fa-gear', None, _system))


def build(user, days=30, now=None):
    """The whole screen: {'days', 'at', 'parts': [{'key', 'label', 'icon', ...the part's numbers}], 'attention',
    'state'} -- `state` the worst of the attention list ('bad', 'warn' or 'ok')."""
    now = now or datetime.utcnow()
    r = _Read(user, days if days in PERIODS else 30, now)
    parts = []
    for key, label, icon, module, fn in PARTS:
        if module and not r.has(module):
            continue
        if key == 'users' and not (r.user.is_admin or access.can(user, 'users') or access.can(user, 'ws_members')):
            continue
        part = fn(r)
        if part.get('tiles'):
            parts.append(dict(part, key=key, label=label, icon=icon))
    attention = sorted(r.attention, key=lambda a: SEVERITY[a['state']])
    state = attention[0]['state'] if attention else 'ok'
    return {'days': r.days, 'at': (now + IST).strftime('%d %b, %H:%M'), 'parts': parts, 'attention': attention,
            'state': state, 'periods': PERIODS}
