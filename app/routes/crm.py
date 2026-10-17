"""Sales CRM screens (/cs/crm/...) and its two public doors (/api/leads, the WhatsApp CRM webhook).

Built for people who are not technical: every setting is a dropdown, a checkbox or a line of
text, every action is one button, and nothing on these screens asks anyone to know an id, a
code or a URL pattern. The logic lives in services/crm.py; this file only reads forms and draws
pages.
"""
import json
import re
from datetime import datetime, timedelta
from functools import wraps

from urllib.parse import urlencode

from flask import (Blueprint, abort, current_app, flash, jsonify, make_response, redirect,
                   render_template, request, session, url_for)
from flask_login import current_user
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app import csrf, db
from app.models import (ActivityEvent, CrmAnswer, CrmIdentity, CrmLead, CrmPerson, CrmPipeline, CrmPlaybookStep, CrmSource,
                        CrmStage, CrmStageChange, CrmTask, CrmTouchpoint, User,
                        CRM_CALL_OUTCOMES, CRM_CHANNEL_LABELS, CRM_REPLIES,
                        CRM_SOURCE_KIND_LABELS, CRM_SOURCE_KINDS, CRM_SOURCE_STATUSES,
                        CRM_STAGE_KINDS, CRM_STEP_TRIGGERS, CRM_TEMPERATURES, CRM_LIKELIHOOD, CRM_VIA,
                        CRM_AUTO_KINDS, CRM_DATE_FIELDS, CRM_LEGACY_TRIGGERS, CRM_MEANS_LABELS,
                        CRM_STAGE_MEANS, CRM_STEP_CHANNELS, CRM_STEP_KINDS, ROLE_MEANS, CrmField)
from app.routes.cs import cs_required
from app.services import (crm, crm_answers, crm_defaults, crm_kpi, crm_people, crm_products, crm_reports, crm_timeline, meta, urls,
                          wa_templates, wacrm)
from app.services.ratelimit import rate_limit

crm_bp = Blueprint('crm', __name__)
crm_public_bp = Blueprint('crm_public', __name__)

# The same screens are mounted twice: /cs/crm inside the CS console (blueprint "crm") and
# /admin/crm inside the admin portal (blueprint "admin_crm", admins only). Links are built with
# crm_url() so whoever is in one portal stays in it.
CRM_BLUEPRINTS = ('crm', 'admin_crm')


# Set-up, reports and imports are management pages: they open in the admin portal. Quick replies
# is an agent page.
MANAGE = {'setup', 'pipelines', 'sources', 'connection', 'data', 'save_source', 'save_pipeline', 'save_step',
          'save_whatsapp', 'backfill', 'import_sheet', 'import_confirm', 'insights', 'insights_csv', 'tracker',
          'save_process', 'setup_templates', 'pipeline_new', 'pipeline_edit', 'pipeline_save', 'pipeline_active',
          'pipeline_tag_check', 'pipeline_tag', 'tag_check', 'save_product', 'product_offered', 'template_draft',
          'import_csv', 'import_csv_confirm', 'wa_contacts_import', 'wa_notes_import', 'save_inboxes',
          'save_activities', 'source_tag_check', 'export_leads', 'export_contacts', 'automatic', 'connection_checks',
          'connection_team', 'connection_retry', 'connection_settle', 'quick_replies_push', 'quick_replies_import'}


def _portal_bp():
    bp = request.blueprint or ''
    if bp in CRM_BLUEPRINTS:
        return bp
    # a link from another admin screen (the insurance leads, the voices...) stays in the admin portal
    return 'admin_crm' if bp.startswith('admin') and current_user.is_authenticated and current_user.is_admin else 'crm'


@crm_bp.app_template_global()
def crm_url(endpoint, **values):
    if endpoint in MANAGE and current_user.is_authenticated and current_user.is_admin:
        return url_for('admin_crm.%s' % endpoint, **values)
    return url_for('%s.%s' % (_portal_bp(), endpoint), **values)


@crm_bp.app_template_global('CRM_LEAD_FOR')
def crm_lead_for(ref_type, ref_id, phone=None, email=None):
    """The lead behind a record on another screen (an insurance quote, a booking, a post...), for
    the pipeline symbol next to it. Looked up once per kind per page."""
    from app.models import request_cache
    cache = request_cache('crm_refs')
    key = ('ref', ref_type)
    if key not in cache:
        cache[key] = {l.ref_id: l for l in CrmLead.query.filter_by(ref_type=ref_type)
                      .order_by(CrmLead.created_at).all()}
    lead = cache[key].get(ref_id)
    if lead is None and (phone or email):
        pkey = ('person', phone or '', (email or '').lower())
        if pkey not in cache:
            person = crm.find_person(phone if (phone or '').startswith('+') else None, email)
            cache[pkey] = (next((l for l in person.leads if l.status == 'open'), None)
                           or (person.leads[0] if person.leads else None)) if person else None
        lead = cache[pkey]
    return lead


@crm_bp.app_template_global('CRM_ROLE')
def crm_role(lead):
    return crm.stage_role(lead.stage) if lead is not None else None


@crm_bp.app_template_global('CRM_ROLE_OF')
def crm_role_of(stage):
    return crm.stage_role(stage)


@crm_bp.before_request
def _who_sees_what():
    if not current_user.is_authenticated:
        return None
    from app.services import access
    name = (request.endpoint or '').split('.', 1)[-1]
    if request.blueprint == 'admin_crm' and not current_user.is_admin:
        # somebody whose role gives them a management screen opens it where it lives
        if name in MANAGE and access.allowed(current_user, request.endpoint):
            return None
        # an agent who followed an admin link: the same screen, in their own console
        if name in MANAGE:
            return redirect(url_for('crm.today'))
        return redirect(url_for('crm.' + name, **(request.view_args or {}), **request.args.to_dict()))
    if request.blueprint == 'crm' and name in MANAGE:
        if access.allowed(current_user, 'admin_crm.' + name):
            # the management screens live in the admin portal; 307 keeps a form's method and fields
            return redirect(url_for('admin_crm.' + name, **(request.view_args or {}), **request.args.to_dict()),
                            code=307)
        flash('Your role does not include that part of the Sales CRM.', 'warning')
        return redirect(url_for('crm.today'))


def admin_only(f):
    """The set-up and management screens: whoever's role includes them (services/access.py)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        from app.services import access
        if not access.allowed(current_user, request.endpoint, fallback=lambda u: u.is_admin):
            if request.is_json or request.accept_mimetypes.best == 'application/json':
                return jsonify({'error': 'Only an admin can change the CRM set-up.'}), 403
            flash('Only an admin can change the CRM set-up.', 'danger')
            return redirect(crm_url('board'))
        return f(*args, **kwargs)
    return decorated


def _staff():
    from app.services import cs_access
    return cs_access.recipients('crm_board', limit=None)


def _common():
    return {'PRODUCTS': crm_products.labels(), 'TEMPS': CRM_TEMPERATURES, 'CHANNELS': CRM_CHANNEL_LABELS,
            'OUTCOMES': CRM_CALL_OUTCOMES, 'KINDS': CRM_SOURCE_KIND_LABELS,
            'IST_OFFSET': crm.IST, 'utcnow': datetime.utcnow(), 'wa_ready': crm.wa_can_send(),
            'LIKELIHOOD': CRM_LIKELIHOOD, 'wa_configured': wacrm.enabled(), 'REPLIES': CRM_REPLIES,
            'WROTE': crm.WROTE_CHANNELS, 'CHAT_STATUS': crm.CHAT_STATUS, 'MILESTONE': crm.MILESTONE_HINT,
            'ROLE_STEPS': crm.ROLE_STEPS, 'MILESTONE_ASK': crm.milestone_ask,
            'STEP_WHEN': crm.step_when, 'AUTO_TEXT': crm.auto_text,
            'STEP_SENTENCE': crm.step_sentence, 'AUTO_SENTENCE': crm.auto_sentence,
            'wa_mode': crm.wa_mode(), 'REPLY_LABELS': crm.REPLY_LABELS,
            'unrouted_count': CrmSource.query.filter_by(status='unrouted').count()}


@crm_bp.app_template_global('CRM_PRODUCT_ICON')
def crm_product_icon(code):
    return crm_products.icon(code)


@crm_bp.app_template_global('DETAIL_TEXT')
def crm_detail_text(field, value):
    return crm.detail_text(field, value)


def _sees_team():
    """Team leads and admins look at everybody's leads first; everyone else at their own."""
    from app.services import access
    return access.can(current_user, 'crm_tracker') or access.can(current_user, 'crm_insights')


def _lead_or_404(lead_id):
    lead = db.session.get(CrmLead, lead_id)
    if lead is None:
        abort(404)
    return lead


def _json():
    return request.get_json(silent=True) or {}


# ============================================================================================ board

BOARD_PREFS = 'crm_leads'          # session: the last pipeline, filters and view on Leads, remembered per person
CHAT_FILTERS = (('waiting', 'Waiting on us'), ('open', '24 h open'), ('nochat', 'No chat yet'))


def _stage_ids_hidden(prefs, pipe):
    """The stage ids this person hid in this pipeline (ones that still exist)."""
    if pipe is None:
        return []
    keep = {s.id for s in pipe.stages}
    return [i for i in (prefs.get('hide') or {}).get(pipe.key, []) if i in keep]


@crm_bp.route('/')
@cs_required
def board():
    """Leads: the board (a column per stage) or the list (pages of 50), with filters that are remembered
    per person for the session. Every number on a card or row comes from a fixed set of queries."""
    from app.services import access
    crm.ensure_defaults()
    a = request.args
    prefs = dict(session.get(BOARD_PREFS) or {})
    if a.get('reset'):
        session[BOARD_PREFS] = {'hide': prefs.get('hide') or {}}
        return redirect(crm_url('board'))
    counts = dict(db.session.query(CrmLead.pipeline_id, func.count(CrmLead.id))
                  .filter(CrmLead.status == 'open').group_by(CrmLead.pipeline_id).all())
    # a pipeline not taking new leads stays here while it still has open ones
    pipelines = [p for p in CrmPipeline.query.order_by(CrmPipeline.id).all() if p.is_active or counts.get(p.id)]
    key = a.get('p') or prefs.get('p')
    all_pipes = key == 'all'
    pipe = None if all_pipes else next((p for p in pipelines if p.key == key), None)
    if pipe is None and not all_pipes and pipelines:
        pipe = max(pipelines, key=lambda p: counts.get(p.id, 0))
    p_key = 'all' if all_pipes else (pipe.key if pipe else None)
    view = a.get('view') if a.get('view') in ('board', 'list') else (prefs.get('view') or 'board')
    if all_pipes:
        view = 'list'
    view_auto = 'view' not in a and 'view' not in prefs

    def stay(**drop):
        """The same page again, without the one-off words (hide, show)."""
        return redirect(crm_url('board', **{k: v for k, v in a.items() if k not in drop}))

    if pipe is not None and a.get('hide', type=int):
        sid = a.get('hide', type=int)
        if sid in {s.id for s in pipe.stages}:
            hide = dict(prefs.get('hide') or {})
            hide[pipe.key] = sorted(set(hide.get(pipe.key, [])) | {sid})
            prefs['hide'] = hide
            session[BOARD_PREFS] = prefs
        return stay(hide=1)
    if pipe is not None and a.get('show') == 'all':
        hide = dict(prefs.get('hide') or {})
        hide.pop(pipe.key, None)
        prefs['hide'] = hide
        session[BOARD_PREFS] = prefs
        return stay(show=1)

    staff = _staff()
    staff_ids = {u.id for u in staff}
    owner = a.get('owner') or prefs.get('owner') or ('all' if access.can(current_user, 'crm_insights') else 'mine')
    if not (owner in ('mine', 'all', 'none') or (owner.isdigit() and int(owner) in staff_ids)):
        owner = 'all' if access.can(current_user, 'crm_insights') else 'mine'
    owner_id = current_user.id if owner == 'mine' else ('none' if owner == 'none' else (int(owner) if owner.isdigit() else None))
    chat = a.get('chat', prefs.get('chat', ''))
    chat = chat if chat in {k for k, _ in CHAT_FILTERS} else ''
    win = a.get('win', prefs.get('win', '30'))
    win = win if win in ('30', 'all') else '30'
    closed_days = 30 if win == '30' else None
    stage_id = a.get('stage', type=int)
    q = (a.get('q') or '').strip()[:80]
    follow = 'late' if a.get('follow') == 'late' else None
    page = max(1, a.get('page', type=int) or 1)

    prefs.update(p=p_key, view=view, owner=owner, chat=chat, win=win)
    session[BOARD_PREFS] = prefs
    session['crm_back'] = urls.here()[:500]

    hidden = _stage_ids_hidden(prefs, pipe)
    can_broadcast = crm.wa_mode() != 'off' and access.can(current_user, 'wa_broadcasts')
    columns, cards, listing, reach = [], {}, None, {}
    with wa_templates.cache_only():
        if pipe is not None and view == 'board':
            data = crm.board(pipe, owner_id, q, chat, closed_days, hidden=hidden)
            columns, cards = data['columns'], data['cards']
            if can_broadcast:
                reach = crm.stage_reach(pipe, [c['stage'] for c in columns])
                for r in reach.values():
                    r['url'] = url_for('messaging.broadcasts',
                                       p='/broadcasts/new?' + urlencode([('tag', t) for t in r['tags']]))
        elif view == 'list' and (pipe is not None or all_pipes):
            listing = crm.lead_list(pipe, page, owner_id=owner_id, q=q, chat=chat, stage_id=stage_id,
                                    closed_days=closed_days, follow=follow)
            cards = listing['cards']
    unrouted_q = CrmLead.query.filter(CrmLead.pipeline_id.is_(None), CrmLead.status == 'open')
    unrouted = unrouted_q.order_by(CrmLead.created_at.desc()).limit(12).all()
    unrouted_total = unrouted_q.count() if unrouted else 0
    has_leads = pipe is None or db.session.query(CrmLead.id).filter_by(pipeline_id=pipe.id).first() is not None
    stages_json = [{'stage': s.id, 'name': s.name, 'kind': s.kind,
                    'milestone': s.button_code if s.button_label else '',
                    'ask': crm.milestone_ask(s)}
                   for s in (pipe.stages if pipe else [])]

    def link(**kw):
        """This page's address with some words changed (None drops one)."""
        vals = {'p': p_key, 'view': view, 'owner': owner, 'chat': chat, 'win': win, 'stage': stage_id, 'q': q}
        vals.update(kw)
        return crm_url('board', **{k: v for k, v in vals.items() if v not in (None, '')})

    defaults = (owner == ('all' if access.can(current_user, 'crm_insights') else 'mine') and not chat
                and win == '30' and not q and not stage_id)
    return render_template('cs/crm/board.html', pipelines=pipelines, pipe=pipe, p_key=p_key, counts=counts,
                           columns=columns, cards=cards, listing=listing, reach=reach, view=view,
                           view_auto=view_auto, owner=owner, chat=chat, win=win, q=q, stage_id=stage_id,
                           staff=staff, staff_json=[[0, crm.NOBODY]] + [[u.id, u.full_name] for u in staff],
                           hidden_n=len(hidden), link=link, filters_on=not defaults,
                           CHAT_FILTERS=CHAT_FILTERS, can_bulk=access.can(current_user, 'crm_tracker'),
                           can_broadcast=can_broadcast, can_export=access.can(current_user, 'crm_export'),
                           stages_json=stages_json, unrouted=unrouted,
                           unrouted_total=unrouted_total, has_leads=has_leads, **_common())


@crm_bp.route('/leads/bulk', methods=['POST'])
@cs_required
def bulk():
    """Give many leads to somebody, or move them to one stage -- from the list's tick boxes. Each owner
    change marks the person so their chat follows; nothing is sent to anyone."""
    from app.services import access
    if not access.can(current_user, 'crm_tracker'):
        return jsonify({'error': 'Only a team lead or an admin can change many leads at once.'}), 403
    data = _json()
    ids = [i for i in (data.get('lead_ids') or []) if isinstance(i, int) and i > 0][:200]
    if not ids:
        return jsonify({'error': 'Choose some leads first.'}), 400
    leads = CrmLead.query.options(*crm.lead_load()).filter(CrmLead.id.in_(ids)).all()
    action = data.get('action')
    if action == 'give':
        uid = int(data.get('owner_id') or 0) or None
        if uid and uid not in {u.id for u in _staff()}:
            return jsonify({'error': 'That person cannot own leads.'}), 400
        items = []
        for l in leads:
            changed, chat = crm.set_owner(l, uid, by=current_user, ring=False)
            if changed:
                items.append((l, chat))
        crm.tell_given(items, by=current_user)
        db.session.commit()
        who = db.session.get(User, uid).full_name if uid else crm.NOBODY
        n = len(items)
        return jsonify({'success': True, 'done': n, 'message': crm.BULK_GIVEN % (n, '' if n == 1 else 's', who)})
    if action == 'move':
        stage = db.session.get(CrmStage, int(data.get('stage_id') or 0))
        if stage is None:
            return jsonify({'error': 'Choose a stage.'}), 400
        reason = (data.get('reason') or '').strip()[:160] or None
        lost = stage.kind == 'lost'
        if lost and not reason:
            return jsonify({'error': 'Pick why these leads fell out.', 'need_reason': True,
                            'reasons': stage.pipeline.fallout_reasons or []}), 400
        moved = other = 0
        for l in leads:
            if l.pipeline_id != stage.pipeline_id:
                other += 1
            elif crm.move_stage(l, stage, user=current_user, reason=None if lost else reason,
                                fallout_reason=reason if lost else None):
                moved += 1
        db.session.commit()
        msg = crm.BULK_MOVED % (moved, '' if moved == 1 else 's', stage.name)
        if other:
            msg += crm.BULK_OTHER_PIPE % (other, 'was' if other == 1 else 'were')
        return jsonify({'success': True, 'done': moved, 'message': msg})
    return jsonify({'error': 'Unknown action.'}), 400


def _said(body):
    """The start of what they wrote, for a row on My day: the words, or what kind of message it was."""
    kind, label, rest = crm.wa_media(body)
    words = (label + (': ' + rest if rest else '')) if kind in ('media', 'template') else rest
    words = ' '.join((words or '').split())
    return words[:40] + ('…' if len(words) > 40 else '')


def _short_name(person):
    """"Priya S": the first name and the last name's initial -- on a list that may be shown over a shoulder."""
    parts = (person.name or '').split()
    return '%s %s' % (parts[0], parts[-1][0]) if len(parts) > 1 else person.display_name


@crm_bp.route('/today')
@cs_required
def today():
    """My day (E1): customers waiting, new leads, today's follow-ups, what is stuck, the half-hourly
    check, what is coming, and the end-of-day numbers. One batched query set; no call to WhatsApp."""
    from app.services import access, crm_metrics
    crm.ensure_defaults()
    team = _sees_team()
    who = 'all' if team and request.args.get('who') == 'all' else 'me'
    mine_f = [] if who == 'all' else [CrmLead.owner_id == current_user.id]
    now = datetime.utcnow()
    session['crm_back'] = urls.here()[:500]
    q = (CrmTask.query.options(joinedload(CrmTask.lead).joinedload(CrmLead.person).selectinload(CrmPerson.identities),
                               joinedload(CrmTask.lead).joinedload(CrmLead.owner),
                               joinedload(CrmTask.lead).joinedload(CrmLead.stage),
                               joinedload(CrmTask.lead).joinedload(CrmLead.pipeline),
                               joinedload(CrmTask.step), joinedload(CrmTask.owner))
         .filter(CrmTask.status == 'open', CrmTask.due_at <= now + timedelta(days=3)))
    if who == 'me':
        q = q.filter(CrmTask.owner_id == current_user.id)
    tasks = q.order_by(CrmTask.due_at).limit(300).all()
    end_of_day = (datetime.combine((now + crm.IST).date(), datetime.max.time()) - crm.IST)
    texts = {t.id: crm.fill(t.step.body, t.lead, current_user) if t.step and t.step.body else ''
             for t in tasks}
    due_now = [t for t in tasks if t.due_at <= end_of_day]
    # a lead's very first message: "welcome the new ones" comes before the other follow-ups
    welcome = [t for t in due_now if t.step is not None and t.step.position == 0 and t.lead.stage is not None
               and t.lead.pipeline is not None and t.lead.stage.id == t.lead.pipeline.first_stage.id]
    follow = [t for t in due_now if t not in welcome]
    later = [t for t in tasks if t.due_at > end_of_day]

    # customers waiting for us: their latest message on WhatsApp, Instagram or Facebook is theirs
    own = select(CrmLead.person_id).where(CrmLead.status == 'open', *mine_f)
    rows = {r.person_id: r for r in db.session.execute(crm_metrics.waiting_rows(CrmTouchpoint.person_id.in_(own)))}
    best = {}
    if rows:
        for l in (CrmLead.query.options(*crm.lead_load())
                  .filter(CrmLead.status == 'open', CrmLead.person_id.in_(list(rows)),
                          or_(CrmLead.snoozed_until.is_(None), CrmLead.snoozed_until <= now), *mine_f)):
            if l.person_id not in best or (l.last_activity_at or l.created_at, l.id) > \
                    (best[l.person_id].last_activity_at or best[l.person_id].created_at, best[l.person_id].id):
                best[l.person_id] = l
    waiting = sorted(({'lead': l, 'channel': rows[pid].channel, 'at': rows[pid].created_at,
                       'words': _said(rows[pid].body), 'short': _short_name(l.person)}
                      for pid, l in best.items()), key=lambda w: w['at'])[:100]

    stuck = []
    for l in (CrmLead.query.options(*crm.lead_load()).filter(crm.stuck_filter(now), *mine_f)
              .order_by(CrmLead.entered_stage_at).limit(50)):
        stuck.append({'lead': l, 'short': _short_name(l.person), 'text': crm.stuck_text(crm.stuck_for(l, now) or 0)})

    # the one button on each card: decided from what we already have, with nothing asked of WhatsApp
    touches = crm_metrics.last_touches({t.lead.person_id for t in tasks})
    with wa_templates.cache_only():
        plans = {t.id: crm.task_plan(t, texts[t.id], touches.get(t.lead.person_id), now) for t in tasks}

    start = datetime.combine((now + crm.IST).date(), datetime.min.time()) - crm.IST
    done_q = CrmTask.query.filter(CrmTask.status == 'done', CrmTask.done_at >= start)
    if who == 'me':
        done_q = done_q.filter(CrmTask.done_by_id == current_user.id)
    done_today = done_q.count()
    rows_ = crm.crm_settings()['check_rows']
    channels = [r['name'] for r in rows_ if not crm.check_ticks_itself(r)]
    ticks_itself = [r['name'] for r in rows_ if crm.check_ticks_itself(r)]
    checks_line = ('Look at: ' + ', '.join(channels[:6]) + ('…' if len(channels) > 6 else '')
                   + (' (%s ticks itself)' % ', '.join(ticks_itself) if ticks_itself else ''))
    day, slot = crm_reports.current()
    ticks = crm_reports.grid(day)

    # before you finish: one question per number only a person can count
    today_ist = (now + crm.IST).date()
    try:
        log_day = datetime.strptime(request.args.get('log_day') or '', '%Y-%m-%d').date()
    except ValueError:
        log_day = today_ist
    log_day = min(log_day, today_ist)
    kpi = [(k, crm_kpi.question(k, log_day, today_ist), crm_kpi.QUESTIONS[k][1]) for k in crm_kpi.MANUAL]
    se = CrmAnswer.query.filter_by(code='SE').first()
    signoff_on = crm.wa_writes_on()
    signoff_n = len(crm.signoff_leads(current_user, now)) if (signoff_on and who == 'me') else 0
    signoff_preview = crm.fill(se.body, CrmLead(person=CrmPerson(name='there')), current_user) if se else ''

    getting_started = None
    if current_user.is_admin:
        getting_started = _getting_started()
    inbox_waiting = (url_for('messaging.inbox', p='/inbox?mine=1&filter=waiting')
                     if access.can(current_user, 'wa_inbox') and crm.wa_mode() != 'off' else None)
    first = (('wait-%d' % waiting[0]['lead'].id, waiting[0]['short'], 'Reply') if waiting else
             next((('task-%d' % t.id, _short_name(t.lead.person), plans[t.id].get('label') or 'Open')
                   for t in welcome + follow), None))
    return render_template('cs/crm/today.html', texts=texts, plans=plans, who=who, team=team, waiting=waiting,
                           stuck=stuck, welcome=welcome, follow=follow, later=later, done_today=done_today,
                           slot=slot, slot_label=crm_reports.slot_label,
                           slot_done=sum(1 for c in channels if (slot, c) in ticks), channels=channels,
                           checks_line=checks_line, coverage=crm_reports.coverage(day, channels),
                           kpi=kpi, log_day=log_day, today=today_ist, my_log=crm_kpi.entries(log_day, current_user.id),
                           signoff_on=signoff_on, signoff_n=signoff_n, signoff_text=se.body if se else '',
                           signoff_preview=signoff_preview, getting_started=getting_started,
                           inbox_waiting=inbox_waiting, next_bar=first, **_common())


def _getting_started():
    """The admin's first-week list on My day: [(label, done, link)], or None once every item is done."""
    from app.models import WorkspaceMember
    from app.services import access
    ws = access.current_workspace(current_user)
    with wa_templates.cache_only():
        st = wa_templates.statuses()
        names = {s.wa_template for s in CrmPlaybookStep.query.filter(CrmPlaybookStep.channel == 'whatsapp',
                                                                    CrmPlaybookStep.wa_template.isnot(None))}
    approved = bool(st) and (all(st.get(n) == 'APPROVED' for n in names) if names
                             else 'APPROVED' in st.values())
    items = [
        ('Connect WhatsApp', crm.wa_mode() != 'off', crm_url('connection')),
        ('Check your templates are approved', approved,
         url_for('messaging.templates') if access.can(current_user, 'wa_templates')
         else crm_url('pipelines', show='templates')),
        ('Add your team', bool(ws) and WorkspaceMember.query.filter_by(workspace_id=ws.id).count() > 1,
         url_for('workspace.members')),
        ('Add your first lead', db.session.query(CrmLead.id).first() is not None, crm_url('add')),
    ]
    return None if all(done for _, done, _ in items) else items


@crm_bp.route('/lead/<int:lead_id>/snooze', methods=['POST'])
@cs_required
def snooze_lead(lead_id):
    """"Remind me in 1 hour" on a customer waiting for us: the row leaves My day and the waiting bell
    holds off for an hour. Their other leads with the same owner go with it. No number changes."""
    lead = _lead_or_404(lead_id)
    if not (current_user.is_admin or lead.owner_id == current_user.id):
        return jsonify({'error': 'Only an admin or the person looking after this lead can do that.'}), 403
    until = datetime.utcnow() + timedelta(hours=1)
    (CrmLead.query.filter(CrmLead.person_id == lead.person_id, CrmLead.status == 'open',
                          CrmLead.owner_id == lead.owner_id)
     .update({'snoozed_until': until}, synchronize_session=False))
    db.session.commit()
    return jsonify({'success': True})


@crm_bp.route('/today/signoff', methods=['POST'])
@cs_required
def signoff():
    """The shift-end message to the person's open chats (crm.send_signoff): only chats that are open,
    only people who have not opted out, each with their own first name, logged on the lead."""
    if not crm.wa_writes_on():
        return jsonify({'error': crm.WA_WRITES_OFF}), 409
    text = (_json().get('text') or '').strip()[:1000]
    if not text:
        se = CrmAnswer.query.filter_by(code='SE').first()
        text = se.body if se else ''
    if not text:
        return jsonify({'error': crm.WA_WRITE_FIRST}), 400
    out = crm.send_signoff(current_user, text)
    return jsonify({'success': True, 'sent': out['sent'], 'message': crm.signoff_said(out)})


@crm_bp.route('/tracker')
@cs_required
@admin_only
def tracker():
    """Team today: for any day, what each person had to do and what they did."""
    today_ = (datetime.utcnow() + crm.IST).date()
    try:
        day = datetime.strptime(request.args.get('day') or '', '%Y-%m-%d').date()
    except ValueError:
        day = today_
    day = min(day, today_)
    everyone = _staff()
    staff = crm_reports.visible_staff(current_user, everyone)
    sheet = crm_reports.day_sheet(day, staff)
    who = request.args.get('who', type=int)
    person = sheet.get(who) if who else None
    channels = crm.crm_settings()['check_channels']
    nums = crm_reports.team_numbers(day, staff)
    steps = crm_reports.step_ticks(day, None if len(staff) == len(everyone) else [u.id for u in staff])
    team_note = None
    if len(staff) != len(everyone):
        names = sorted({t.name for t in _my_teams()})
        team_note = ('You see your own teams: %s.' % ', '.join(names)) if names else \
            'You are not in a team yet, so only your own day shows.'
    return render_template('cs/crm/tracker.html', day=day, today=today_, sheet=sheet, staff=staff, person=person,
                           prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1), nums=nums,
                           steps=steps, team_note=team_note,
                           coverage=crm_reports.coverage(day, channels), slot_label=crm_reports.slot_label,
                           slots=crm_reports.slots(), MANUAL=dict((k, crm_kpi.METRICS[k][0]) for k in crm_kpi.MANUAL),
                           **_common())


def _my_teams():
    from app.services import access
    ws = access.current_workspace(current_user)
    member = next((m for m in access.memberships(current_user) if ws is not None and m.workspace_id == ws.id), None)
    return access.teams_of(member) if member is not None else []


# ============================================================================================ lead

def _timeline(lead):
    items = []
    for tp in lead.touchpoints:
        items.append({'at': tp.created_at, 'kind': 'touch', 'obj': tp})
    for ch in lead.stage_changes:
        items.append({'at': ch.created_at, 'kind': 'stage', 'obj': ch})
    for t in lead.tasks:
        if t.status != 'open' and t.done_at:
            items.append({'at': t.done_at, 'kind': 'task', 'obj': t})
    items.sort(key=lambda i: i['at'] or datetime.min, reverse=True)
    return items


def _ref_url(lead):
    """Where the record a lead came from can be opened, when it has a screen of its own."""
    try:
        if lead.ref_type == 'companion_requests' and lead.ref_id:
            return url_for('cs.post_detail', trip_id=lead.ref_id)
        return {'insurance_quotes': url_for('cs.insurance_quotes'),
                'sahayak_bookings': url_for('cs.sahayak_bookings'),
                'contact_messages': url_for('cs.voices')}.get(lead.ref_type)
    except Exception:      # noqa: BLE001 -- a screen that is not there must not break the lead page
        return None


def lead_card_context(lead, compact=False):
    """What the lead card needs (_lead_card.html): on the lead page, and beside the WhatsApp
    inbox (messaging.lead_panel, `compact`). The next step's words, filled in for them, and how
    WhatsApp will take it (crm.send_plan) -- decided here so the button says what will really
    happen. A person's own press of Send needs only "Keep contacts in step" (by_hand)."""
    task = lead.open_task
    step = task.step if task is not None else None
    next_text = crm.fill(step.body if step and step.body else (task.title if task else ''), lead, current_user) \
        if task else ''
    plan = crm.send_plan(lead, step, by_hand=True) if task is not None and task.channel == 'whatsapp' else None
    return dict(lead=lead, person=lead.person, task=task, next_text=next_text, plan=plan,
                sales_tags=crm_people.sales_tags(lead.person),
                social=crm.social_reply_channels(lead),
                events=crm.milestones(lead),
                waiting=crm.waiting_line(lead) if task is None else None,
                choices=crm.product_choices(lead),
                card_fields=crm.card_fields(lead), other_details=crm.other_details(lead),
                ends_used=bool(lead.ends_on) or crm.uses_date(lead.pipeline, 'ends_on'),
                ref_url=_ref_url(lead), timeline=_timeline(lead) if compact else [],
                others=[l for l in lead.person.leads if l.id != lead.id], staff=_staff(),
                no_answers=crm.no_answer_streak(lead), compact=compact,
                quick=crm.quick_replies_for(lead, current_user), wa_off=crm.wa_mode() == 'off')


def lead_page_context(lead, confirm=False):
    """Everything the lead page draws (lead.html and its live regions). Without `confirm` nothing is
    asked of the WhatsApp CRM: the strip comes from portal data and what it said in the last minute."""
    from app.routes.messaging import crm_role
    from app.services import wacrm_team
    person = lead.person
    ctx = lead_card_context(lead)
    wa = crm.wa_chat_state(lead, confirm=confirm)
    social_open = crm.social_windows(lead)
    admin_or_owner = bool(current_user.is_admin or lead.owner_id == current_user.id)
    chat_url = (url_for('messaging.lead_chat', lead_id=lead.id)
                if wacrm_team.enabled() and crm_role(current_user) and (person.phone or person.wacrm_conversation_id)
                else None)
    via = request.args.get('via')
    back = session.get('crm_back') or ''
    if back.startswith('/') and not back.startswith('//'):
        back_url = back
    else:
        back_url = crm_url('board', p=lead.pipeline.key if lead.pipeline else None)
    ctx.update(back_url=back_url, back_label='My day' if '/today' in back_url.split('?')[0] else 'Leads',
               pipelines=CrmPipeline.query.filter_by(is_active=True).order_by(CrmPipeline.id).all(),
               has_moves=any(ch.from_stage_id for ch in lead.stage_changes),
               can_remove=crm.can_remove(lead, current_user),
               wa=wa, wa_line=crm.wa_line(wa), box_note=crm.box_note(wa), social_open=social_open,
               social_notes={ch: '' if ok else crm.SOCIAL_CLOSED % ('Instagram' if ch == 'instagram' else 'Messenger')
                             for ch, ok in social_open.items()},
               sync=crm.wa_sync_state(person) if admin_or_owner else None,
               can_opt_in=bool(current_user.is_admin and wa['state'] in ('opted_out', 'opted_out_open')),
               chat_url=chat_url, stream=crm_timeline.build(lead), tpl=crm.box_templates(lead, current_user),
               via0=via if via in ('whatsapp', 'instagram', 'facebook') else '')
    return ctx


def _send_answer(result):
    """A send's outcome for crm.js: refused ones as an error it shows; the step stays where it is."""
    mode = result.get('mode')
    if mode in ('blocked', 'taken'):
        return jsonify({'error': result.get('reason'), 'mode': mode}), 409
    if mode in ('failed', 'down'):
        return jsonify({'error': 'WhatsApp did not send it: %s' % result.get('reason'), 'mode': mode}), 502
    return jsonify({'success': True, **result})


@crm_bp.route('/lead/<int:lead_id>')
@cs_required
def lead(lead_id):
    lead = _lead_or_404(lead_id)
    # drawing the page asks the WhatsApp CRM for nothing: the live endpoint (crm.js) fills in the rest
    with wa_templates.cache_only():
        return render_template('cs/crm/lead.html', **lead_page_context(lead), **_common())


@crm_bp.route('/lead/<int:lead_id>/live')
@cs_required
def live(lead_id):
    """The regions of the lead page that change by themselves (journey, timeline, card), for crm.js
    to swap in. The first call after the page opened also brings in their older WhatsApp messages."""
    lead = _lead_or_404(lead_id)
    if request.args.get('first') == '1':
        crm.wa_import_history(lead)
    with wacrm.short_timeouts():
        html = render_template('cs/crm/_lead_live.html', **lead_page_context(lead, confirm=True), **_common())
    resp = make_response(html)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@crm_bp.route('/lead/<int:lead_id>/move', methods=['POST'])
@cs_required
def move(lead_id):
    lead = _lead_or_404(lead_id)
    data = _json()
    stage = db.session.get(CrmStage, int(data.get('stage_id') or 0))
    if stage is None or stage.pipeline_id != lead.pipeline_id:
        return jsonify({'error': 'That stage is not in this lead\'s pipeline.'}), 400
    reason = (data.get('reason') or '').strip()[:160] or None
    if stage.kind == 'lost' and not reason:
        return jsonify({'error': 'Pick why this lead fell out.', 'need_reason': True,
                        'reasons': lead.pipeline.fallout_reasons or []}), 400
    moved = crm.move_stage(lead, stage, user=current_user,
                           reason=None if stage.kind == 'lost' else reason,
                           fallout_reason=reason if stage.kind == 'lost' else None)
    # "Did you send the quote? [Yes, log it]": the milestone button's line, only when they said yes
    code = stage.button_code if stage.button_label else None
    logged = bool(moved and data.get('log_milestone') is True and code and stage.kind == 'open')
    if logged:
        crm.log_touch(lead, 'system', 'none', body=stage.button_label, code=code, user=current_user)
    db.session.commit()
    return jsonify({'success': True, 'stage': stage.name, 'status': lead.status, 'logged': logged,
                    **({'logged_label': stage.button_label} if logged else {})})


@crm_bp.route('/lead/<int:lead_id>/route', methods=['POST'])
@cs_required
def route_lead(lead_id):
    lead = _lead_or_404(lead_id)
    pipe = CrmPipeline.query.filter_by(key=(request.form.get('pipeline') or _json().get('pipeline'))).first()
    if pipe is None:
        flash('Choose a pipeline.', 'danger')
        return redirect(crm_url('lead', lead_id=lead.id))
    crm.set_pipeline(lead, pipe, user=current_user)
    if not lead.owner_id:
        lead.owner = current_user if current_user.is_cs else None
        if lead.owner is not None:
            crm.mark_wa_due(lead.person, assign=True)
    db.session.commit()
    flash('Moved to %s.' % pipe.name, 'success')
    return redirect(crm_url('lead', lead_id=lead.id))


@crm_bp.route('/task/<int:task_id>/<action>', methods=['POST'])
@cs_required
def task_action(task_id, action):
    task = db.session.get(CrmTask, task_id)
    if task is None:
        abort(404)
    if action == 'done':
        crm.complete_task(task, user=current_user, note=_json().get('note'))
    elif action == 'skip':
        crm.complete_task(task, user=current_user, skipped=True, note=_json().get('note'))
    elif action == 'snooze':
        crm.snooze_task(task, hours=int(_json().get('hours') or 24))
    else:
        return jsonify({'error': 'Unknown action'}), 400
    db.session.commit()
    nxt = task.lead.open_task
    return jsonify({'success': True, 'next': ({'code': nxt.code, 'title': nxt.title,
                                               'due': nxt.due_at.isoformat()} if nxt else None)})


@crm_bp.route('/lead/<int:lead_id>/send', methods=['POST'])
@cs_required
def send(lead_id):
    lead = _lead_or_404(lead_id)
    data = _json()
    text = (data.get('text') or '').strip()
    via = data.get('via') or 'whatsapp'
    task = db.session.get(CrmTask, int(data['task_id'])) if data.get('task_id') else None
    if task is not None and task.lead_id != lead.id:
        task = None
    if task is not None and task.status != 'open':
        # sent a moment ago (another click, another tab, the jobs runner): nothing goes twice
        return jsonify({'error': crm.SEND_TAKEN if task.status == 'sending' else crm.STEP_DONE,
                        'mode': 'taken'}), 409
    if task is not None and via == 'whatsapp' and task.channel == 'whatsapp':
        # a step: its approved template, free text inside the 24 hours, or the agent's WhatsApp
        if not lead.person.phone:
            return jsonify({'error': 'This lead has no phone number to message.'}), 400
        return _send_answer(crm.send_step(lead, task, user=current_user, text=text or None))
    if not text:
        return jsonify({'error': 'Write the message first.'}), 400
    quick = db.session.get(CrmAnswer, int(data['answer_id'])) if str(data.get('answer_id') or '').isdigit() else None
    if quick is not None and quick.code:
        quick.use_count = (quick.use_count or 0) + 1
        data['code'] = quick.code
    if via in crm.SOCIAL_ID:
        try:
            result = crm.send_social(lead, via, text[:1900], user=current_user, task=task,
                                     code=data.get('code'))
        except meta.MetaError as exc:
            db.session.rollback()
            return jsonify({'error': str(exc)}), 400
        return jsonify({'success': True, **result})
    if not lead.person.phone:
        return jsonify({'error': 'This lead has no phone number to message.'}), 400
    return _send_answer(crm.send_whatsapp(lead, text[:4000], user=current_user,
                                          code=(task.code if task else data.get('code')), task=task))


def _message_answer(result):
    """What crm.send_by_hand answered, for crm.js: refusals as an error it shows."""
    mode = result.get('mode')
    if mode in ('failed', 'down'):
        return jsonify({'error': 'WhatsApp did not send it: %s' % result.get('reason'), 'mode': mode}), 502
    if mode in ('sent', 'unsure'):
        return jsonify({'success': True, **result})
    return jsonify({'error': result.get('reason'), 'mode': mode}), 409


@crm_bp.route('/lead/<int:lead_id>/message', methods=['POST'])
@cs_required
def message(lead_id):
    """The lead page's message box (and the panel's Send): free text inside the 24 hours, or an
    approved template -- crm.send_by_hand, the one safe path."""
    lead = _lead_or_404(lead_id)
    data = _json()
    kind = data.get('kind')
    if kind not in ('text', 'template'):
        return jsonify({'error': 'Choose what to send.'}), 400
    params = data.get('params')
    if params is not None and not isinstance(params, list):
        return jsonify({'error': 'The fill-ins did not come through.'}), 400
    task = db.session.get(CrmTask, int(data['task_id'])) if str(data.get('task_id') or '').isdigit() else None
    if task is not None and task.lead_id != lead.id:
        task = None
    answer = db.session.get(CrmAnswer, int(data['answer_id'])) if str(data.get('answer_id') or '').isdigit() else None
    template = (data.get('template') or '').strip()[:80] or None
    return _message_answer(crm.send_by_hand(lead, current_user, kind, text=data.get('text'), template=template,
                                            params=params, task=task, answer=answer))


@crm_bp.route('/lead/<int:lead_id>/opt-in', methods=['POST'])
@cs_required
def opt_in(lead_id):
    lead = _lead_or_404(lead_id)
    if not current_user.is_admin:
        return jsonify({'error': 'Only an admin can opt them back in.'}), 403
    if not crm.wa_opt_in(lead.person, lead, current_user):
        return jsonify({'error': 'They have not opted out.'}), 400
    db.session.commit()
    return jsonify({'success': True, 'message': crm.OPTED_IN_SAID if crm.wa_writes_on() else crm.OPTED_IN_LATER})


@crm_bp.route('/lead/<int:lead_id>/wa-retry', methods=['POST'])
@cs_required
def wa_retry(lead_id):
    lead = _lead_or_404(lead_id)
    if not (current_user.is_admin or lead.owner_id == current_user.id):
        return jsonify({'error': 'Only an admin or the person looking after this lead can do that.'}), 403
    if not crm.mark_wa_due(lead.person):
        return jsonify({'error': crm.WA_WRITES_OFF}), 409
    db.session.commit()
    return jsonify({'success': True})


@crm_bp.route('/lead/<int:lead_id>/call', methods=['POST'])
@cs_required
def call(lead_id):
    lead = _lead_or_404(lead_id)
    data = _json()
    outcome = data.get('outcome')
    if outcome not in CRM_CALL_OUTCOMES:
        return jsonify({'error': 'Pick how the call went.'}), 400
    task = db.session.get(CrmTask, int(data['task_id'])) if data.get('task_id') else None
    if task is not None and (task.lead_id != lead.id or task.status != 'open'):
        task = None
    due = None
    if outcome == 'call_back':
        due = crm.call_back_at(data.get('when') or 'morning', data.get('at'))
        if due is None:
            return jsonify({'error': 'Pick a time later than now.'}), 400
    streak = crm.log_call(lead, outcome, note=(data.get('note') or '').strip()[:1000] or None,
                          user=current_user, task=task, call_back_at=due)
    when = None
    if due is not None and lead.status == 'open':
        d = due + crm.IST
        when = '%s %d %s, %s' % (d.strftime('%a'), d.day, d.strftime('%b'), d.strftime('%H:%M'))
    return jsonify({'success': True, 'no_answers': streak, 'call_back': when,
                    'suggest_fallout': streak >= crm.NO_ANSWER_LIMIT})


@crm_bp.route('/lead/<int:lead_id>/note', methods=['POST'])
@cs_required
def note(lead_id):
    lead = _lead_or_404(lead_id)
    data = _json()
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'Write something first.'}), 400
    channel = data.get('channel') if data.get('channel') in CRM_CHANNEL_LABELS else 'note'
    direction = 'in' if data.get('from_them') else ('none' if channel == 'note' else 'out')
    if direction == 'in':
        # what they wrote on another channel, typed in by the agent: it counts as a reply
        crm.record_reply(lead, text, channel=channel)
    else:
        crm.log_touch(lead, channel, direction, body=text[:4000], user=current_user)
    db.session.commit()
    return jsonify({'success': True})


@crm_bp.route('/lead/<int:lead_id>/update', methods=['POST'])
@cs_required
def update(lead_id):
    lead = _lead_or_404(lead_id)
    data = _json()
    # "details.visit_date": one detail edited on the lead card
    dotted = {k[8:]: v for k, v in data.items() if isinstance(k, str) and k.startswith('details.')}
    if dotted:
        data['details'] = {**(data.get('details') if isinstance(data.get('details'), dict) else {}), **dotted}
    owner_changed = details_changed = False
    new_phone = None
    dates = set()                      # the dates that changed: follow-ups counting from them are re-planned
    said, moved = None, False
    if 'owner_id' in data:
        uid = int(data['owner_id'] or 0)
        if uid and uid not in {u.id for u in _staff()}:
            return jsonify({'error': 'That person cannot own leads.'}), 400
        owner_changed = (uid or None) != lead.owner_id
        if owner_changed:
            crm.log_touch(lead, 'system', 'none', body=crm.owner_line(lead.owner, db.session.get(User, uid) if uid else None),
                          user=current_user, activity=False)
        lead.owner_id = uid or None
        for t in lead.tasks:
            if t.status == 'open':
                t.owner_id = lead.owner_id
    if 'temperature' in data:
        t = data['temperature'] or None
        if t and t not in CRM_TEMPERATURES:
            return jsonify({'error': 'Unknown status.'}), 400
        lead.temperature = t
    if 'likelihood' in data:
        v = data['likelihood'] or None
        if v and v not in CRM_LIKELIHOOD:
            return jsonify({'error': 'Unknown choice.'}), 400
        lead.likelihood = v
    for col in ('departure_date', 'ends_on'):
        if col in data:
            raw = (data[col] or '').strip()
            try:
                new = datetime.strptime(raw, '%Y-%m-%d').date() if raw else None
            except ValueError:
                return jsonify({'error': 'Use a real date.'}), 400
            if new != getattr(lead, col):
                dates.add(col)
            setattr(lead, col, new)
    if isinstance(data.get('details'), dict):
        asked = {f.key: f for f in crm.lead_fields(lead.pipeline)}
        merged = dict(lead.details or {})
        if len(data['details']) > 20:
            return jsonify({'error': 'Too many details at once.'}), 400
        for k, v in data['details'].items():
            field = asked.get(k)
            if field is None:
                return jsonify({'error': 'That detail is not asked in this pipeline.'}), 400
            v, why = crm.clean_detail(field, v)
            if why:
                return jsonify({'error': why}), 400
            if field.type == 'date' and (merged.get(k) or '') != (v or ''):
                dates.add(k)
            if v in ('', None):
                merged.pop(k, None)
            else:
                merged[k] = v
        lead.details = merged
        details_changed = True
    if 'product' in data:
        if lead.status != 'open':
            return jsonify({'error': 'This lead is closed. Choose Work on it again under More first.'}), 400
        try:
            said, moved = crm.set_product(lead, (data['product'] or '').strip().upper(), user=current_user)
        except ValueError:
            return jsonify({'error': 'Choose one of the products shown.'}), 400
    if 'name' in data and (data['name'] or '').strip():
        name = data['name'].strip()[:120]
        details_changed = details_changed or name != lead.person.name
        lead.person.name = name
    if 'email' in data:
        e = (data['email'] or '').strip().lower()
        if e and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', e):
            return jsonify({'error': 'That e-mail address does not look right.'}), 400
        details_changed = details_changed or (e or None) != lead.person.email
        lead.person.email = e or None
    if (data.get('phone') or '').strip():
        e164 = crm.normalise_phone(data['phone'], data.get('phone_cc'))
        if not e164:
            return jsonify({'error': 'That phone number does not look right -- start it with + and the country code.'}), 400
        other = CrmPerson.query.filter(CrmPerson.phone == e164, CrmPerson.id != lead.person_id).first()
        if other:
            return jsonify({'error': 'That number belongs to another lead already.'}), 400
        new_phone = e164
    for kind in ('instagram', 'facebook'):
        if (data.get(kind) or '').strip():
            v = crm.clean_identity(kind, data[kind])
            if not v:
                return jsonify({'error': 'That %s handle does not look right.' % kind.capitalize()}), 400
            if not lead.person.identity(kind) and not CrmIdentity.query.filter_by(kind=kind, value=v).first():
                lead.person.identities.append(CrmIdentity(kind=kind, value=v))
    if new_phone:
        crm.change_phone(lead.person, new_phone)     # the WhatsApp CRM ids were the old number's
    if dates:
        said = said or crm.replan_dates(lead, dates)
    wa = False
    if owner_changed or details_changed:
        # the WhatsApp CRM follows after the save: a new owner gets the chat too
        wa = crm.mark_wa_due(lead.person, assign=owner_changed)
    # the chat follows the owner of their most recently active open lead (crm._wa_main_lead), which
    # may be another of their leads: "it goes to them too" only when that is this lead's new owner
    follows = crm.chat_follows(lead, wa) if owner_changed else False
    if owner_changed and lead.owner_id and lead.owner_id != current_user.id:
        crm.tell_new_owner(lead, chat=follows)          # "Meera's lead is yours now"
    db.session.commit()
    out = {'success': True, 'whatsapp': follows}
    if said:
        out['message'] = said
    if moved:
        out['moved'] = True
    return jsonify(out)


@crm_bp.route('/suggest')
@cs_required
def suggest():
    text = (request.args.get('q') or '')[:1000]
    lead = db.session.get(CrmLead, int(request.args.get('lead') or 0)) if request.args.get('lead') else None
    out = crm_answers.suggest(text, lead.product if lead else request.args.get('product'), limit=4)
    if lead:
        for s in out:
            s['body'] = crm.fill(s['body'], lead, current_user)
    return jsonify({'suggestions': out})


@crm_bp.route('/answer/<rid>/used', methods=['POST'])
@cs_required
def answer_used(rid):
    if rid.startswith('a') and rid[1:].isdigit():
        a = db.session.get(CrmAnswer, int(rid[1:]))
        if a:
            a.use_count = (a.use_count or 0) + 1
            db.session.commit()
    return jsonify({'success': True})


# ============================================================================================ add

def _add_prefill():
    """What Add a lead starts with: ?person=<id> fills it from that contact; else ?name, ?phone, ?email ... as given."""
    a = request.args
    form = {k: (a.get(k) or '')[:200] for k in ('name', 'phone', 'phone_cc', 'email', 'instagram', 'facebook',
                                                 'product', 'source') if a.get(k)}
    pid = a.get('person', type=int)
    person = db.session.get(CrmPerson, pid) if pid else None
    if person is not None:
        from app.services import phone as phone_svc
        form.update(name=person.name or '', phone=person.phone or '', email=person.email or '',
                    phone_cc=(phone_svc.iso_for(person.phone) if person.phone else '') or '',
                    instagram=person.identity('instagram') or '', facebook=person.identity('facebook') or '',
                    person_id=str(person.id))
    return form


@crm_bp.route('/add', methods=['GET', 'POST'])
@cs_required
def add():
    from app.services import crm_people
    crm.ensure_defaults()
    manual = (CrmSource.query.filter(CrmSource.kind.in_(['manual', 'chat']), CrmSource.status != 'unrouted')
              .order_by(CrmSource.name).all())
    tiles = crm_products.tiles()
    add_fields = crm.add_fields(tiles)          # {'TI': [CrmField...], ..., '': [...]}: asked when adding a lead
    staff = _staff()
    if request.method == 'POST':
        f = request.form
        src = CrmSource.query.filter_by(key=f.get('source')).first()
        chosen_product = crm_products.by_code(f.get('product'))
        product = chosen_product.code if chosen_product is not None and chosen_product.offered else None
        dep = None
        if f.get('departure_date'):
            try:
                dep = datetime.strptime(f['departure_date'], '%Y-%m-%d').date()
            except ValueError:
                dep = None
        errors = []
        details = {}
        group = product or ''
        for fld in add_fields.get(group, []):
            raw = f.get('detail__%s__%s' % (group or 'none', fld.key))
            v, why = crm.clean_detail(fld, raw)
            if why:
                errors.append('%s: %s' % (fld.label, why))
            elif v in ('', None):
                if fld.required:
                    errors.append('Fill in “%s”.' % fld.label)
            else:
                details[fld.key] = v
        idents = [(k, f.get(k)) for k in ('instagram', 'facebook') if (f.get(k) or '').strip()]
        if not src:
            errors.append('Choose where the lead came from.')
        if not (f.get('phone') or '').strip() and not (f.get('email') or '').strip() and not idents:
            errors.append('A phone number, an e-mail or an Instagram / Facebook handle is needed to follow up.')
        e164 = crm.normalise_phone(f.get('phone'), f.get('phone_cc'))
        if (f.get('phone') or '').strip() and not e164:
            errors.append('That phone number does not look right for the country chosen.')
        for k, v in idents:
            if not crm.clean_identity(k, v):
                errors.append('That %s handle does not look right.' % k.capitalize())
        owner_choice = f.get('owner') if f.get('owner') in ('me', 'auto', 'pick') else 'auto'
        pick_id = f.get('owner_id', type=int)
        if owner_choice == 'pick' and pick_id not in {u.id for u in staff}:
            errors.append('Choose who looks after them.')

        def again(ask=None):
            return render_template('cs/crm/add.html', sources=manual, form=f, tiles=tiles, add_fields=add_fields,
                                   chosen=f.get('product') or '', mode='new', staff=staff, ask=ask, **_common())
        if errors:
            for e in errors:
                flash(e, 'danger')
            return again()
        email_clean = (f.get('email') or '').strip().lower() or None
        if email_clean and '@' not in email_clean:
            email_clean = None
        # asks first: somebody erased at their request, then somebody who is already a contact
        hits = crm_people.dnc_find(e164, email_clean)
        if hits and f.get('dnc') != 'ok':
            return again({'kind': 'dnc', 'text': crm_people.DNC_ASK % crm_people.dnc_since(hits),
                          'yes': crm_people.DNC_YES})
        clean_idents = [(k, crm.clean_identity(k, v)) for k, v in idents]
        existing = crm.find_person(e164, email_clean, clean_idents)
        dup = f.get('dup')
        if existing is not None and dup not in ('same', 'new') and str(existing.id) != (f.get('person_id') or ''):
            first = (existing.display_name.split() or [existing.display_name])[0]
            return again({'kind': 'dup', 'text': crm_people.DUP_ASK % (existing.display_name,
                                                                        crm_people.short_reach(existing)),
                          'add': crm_people.DUP_ADD % first, 'other': crm_people.DUP_OTHER,
                          'person_id': existing.id})
        person = None
        if existing is not None and dup == 'new':
            first = (existing.display_name.split() or [existing.display_name])[0]
            if e164 and existing.phone == e164:
                flash(crm_people.DUP_SAME_PHONE % (existing.display_name, first), 'danger')
                return again()
            held = next((k for k, v in clean_idents if v and CrmIdentity.query.filter_by(kind=k, value=v).first()),
                        None)
            if held:
                flash(crm_people.DUP_SAME_HANDLE % (existing.display_name, held.capitalize(), first), 'danger')
                return again()
            # the same e-mail only: a different person
            person = CrmPerson(phone=e164, email=email_clean, name=(f.get('name') or '').strip()[:120] or None)
            db.session.add(person)
            db.session.flush()
            for k, v in clean_idents:
                if v and not CrmIdentity.query.filter_by(kind=k, value=v).first():
                    person.identities.append(CrmIdentity(kind=k, value=v))
            db.session.flush()
        # a lead for a known product starts in that product's pipeline: capture() passes it on from a
        # catch-all source
        mine = owner_choice == 'me'
        lead = crm.capture(src.key, name=f.get('name'), phone=e164, email=f.get('email'), identities=idents,
                           product=product, message=(f.get('note') or '').strip() or None, details=details,
                           departure_date=dep, utm={}, channel='chat' if src.kind == 'chat' else 'note',
                           created_by_id=current_user.id, start_stage=None,
                           notify=owner_choice == 'auto', person=person)
        if lead is None:
            flash('Could not add that lead.', 'danger')
            return redirect(crm_url('add'))
        session['crm_add_product'] = (product or '')
        # whoever added it takes it, unless they chose to share it out
        if mine:
            lead.owner_id = current_user.id
            for t in lead.tasks:
                if t.status == 'open':
                    t.owner_id = current_user.id
            crm.mark_wa_due(lead.person, assign=True)     # their WhatsApp chat comes to them too
            db.session.commit()
        elif owner_choice == 'pick':
            crm.set_owner(lead, pick_id, by=current_user)
            db.session.commit()
        flash('Lead added.', 'success')
        return redirect(crm_url('lead', lead_id=lead.id))
    q = (request.args.get('q') or '').strip()
    found = crm.search_records(q) if request.args.get('from') == 'existing' else []
    form = _add_prefill()
    if not form.get('source') and any(s.key == 'call' for s in manual):
        form['source'] = 'call'                      # most leads added by hand are a phone call
    return render_template('cs/crm/add.html', sources=manual, form=form, q=q, found=found,
                           tiles=tiles, add_fields=add_fields,
                           chosen=form.get('product') or session.get('crm_add_product') or '',
                           mode='existing' if request.args.get('from') == 'existing' else 'new',
                           staff=staff, ask=None, **_common())


@crm_bp.route('/add/record', methods=['POST'])
@cs_required
def add_from_record():
    """Make a lead of something the site already has: from "Add a lead -> From existing data",
    or the "Add to Sales CRM" button beside a quote, a booking, a message or a post."""
    kind, rid = request.form.get('kind'), request.form.get('id', type=int)
    if kind not in crm.RECORD_KINDS or not rid:
        abort(400)
    from app.services import crm_people
    try:
        lead, created = crm.lead_from_record(kind, rid, user=current_user)
    except crm.DoNotContact:
        db.session.rollback()
        flash(crm_people.DNC_RECORD, 'warning')
        return redirect(request.referrer or crm_url('add', **{'from': 'existing'}))
    if lead is None:
        flash('That record has no phone number or e-mail to follow up, so it cannot become a lead.', 'danger')
        return redirect(request.referrer or crm_url('add', **{'from': 'existing'}))
    if created and request.form.get('mine') != '0':
        lead.owner_id = current_user.id
        for t in lead.tasks:
            if t.status == 'open':
                t.owner_id = current_user.id
        crm.mark_wa_due(lead.person, assign=True)         # their WhatsApp chat comes to them too
        db.session.commit()
    flash(('Added to the Sales CRM: %s.' if created else '%s is already in the Sales CRM.') % lead.person.display_name,
          'success' if created else 'info')
    nxt = request.form.get('next') or ''
    if nxt.startswith('/') and not nxt.startswith('//'):
        return redirect(nxt)
    return redirect(crm_url('lead', lead_id=lead.id))


# ============================================================================================ undo, reopen, remove

@crm_bp.route('/lead/<int:lead_id>/undo', methods=['POST'])
@cs_required
def undo(lead_id):
    lead = _lead_or_404(lead_id)
    back = crm.undo_last_move(lead, user=current_user)
    if back is None:
        return jsonify({'error': 'There is no move to undo.'}), 400
    return jsonify({'success': True, 'stage': back.name})


@crm_bp.route('/lead/<int:lead_id>/reopen', methods=['POST'])
@cs_required
def reopen(lead_id):
    lead = _lead_or_404(lead_id)
    back = crm.reopen(lead, user=current_user)
    if back is None:
        return jsonify({'error': 'This lead is already open.'}), 400
    return jsonify({'success': True, 'stage': back.name})


@crm_bp.route('/lead/<int:lead_id>/remove', methods=['POST'])
@cs_required
def remove(lead_id):
    lead = _lead_or_404(lead_id)
    if not crm.can_remove(lead, current_user):
        return jsonify({'error': 'Only the person who added or looks after this lead, or an admin, can remove it.'}), 403
    name = crm.remove_lead(lead, user=current_user)
    flash('Removed this lead. %s stays in Contacts.' % name, 'success')
    return jsonify({'success': True, 'next': crm_url('board', owner='all')})


# ============================================================================================ insights

@crm_bp.route('/insights')
@cs_required
@admin_only
def insights():
    """Reports -> Results (E17): how sales are going for 7, 30 or 90 days, one pipeline and one person; every
    number has its definition (crm_metrics.DEFINITIONS). The site owner's start page."""
    from app.services import crm_metrics, crm_results
    days = request.args.get('days', type=int) or 30
    days = days if days in (7, 30, 90) else 30
    staff = crm_reports.visible_staff(current_user, _staff())
    person = next((u for u in staff if u.id == request.args.get('who', type=int)), None)
    pipelines = CrmPipeline.query.order_by(CrmPipeline.id).all()
    pipe = next((p for p in pipelines if p.id == request.args.get('pipeline', type=int)), None)
    today = (datetime.utcnow() + crm.IST).date()
    first = today - timedelta(days=days - 1)
    since, until = crm_kpi.utc_bounds(first, today)
    psince, puntil = crm_kpi.utc_bounds(first - timedelta(days=days), first - timedelta(days=1))
    pid, oid = (pipe.id if pipe else None), (person.id if person else None)
    day_list, groups = crm_kpi.table(first, today, oid)
    return render_template('cs/crm/insights.html', days=days, staff=staff, person=person, pipelines=pipelines,
                           pipe=pipe, cards=crm_results.cards(since, until, pid, oid),
                           before=crm_results.counts(psince, puntil, pid, oid),
                           funnel=crm_results.funnel(since, until, pipe, oid),
                           sources=crm_results.sources(since, until, pid, oid),
                           senders=crm_results.by_sender(since, until, pid, oid),
                           milestones=crm_results.milestones(since, until, pid, oid),
                           reasons=crm_results.lost_reasons(since, until, pid, oid),
                           day_list=day_list, groups=groups, DEFS=crm_metrics.DEFINITIONS, **_common())


@crm_bp.route('/insights/log', methods=['POST'])
@cs_required
def log_work():
    """Log the day's work: the few numbers the CRM cannot count by itself (the form is on My day)."""
    try:
        day = datetime.strptime(request.form.get('day') or '', '%Y-%m-%d').date()
    except ValueError:
        day = (datetime.utcnow() + crm.IST).date()
    for key in crm_kpi.MANUAL:
        raw = (request.form.get(key) or '').strip()
        if raw == '':
            continue
        try:
            crm_kpi.set_entry(day, current_user.id, key, max(0.0, float(raw)))
        except ValueError:
            flash('"%s" needs a number.' % crm_kpi.METRICS[key][0], 'danger')
    flash('Saved your numbers for %s.' % day.strftime('%d %b'), 'success')
    return redirect(crm_url('today') + '#finish')


# ============================================================================================ the sales process

@crm_bp.route('/process')
@cs_required
def process():
    """The Sales Process tab, drawn from the live CRM: lead channels, the way in, every pipeline
    with today's counts and its messages, and the fallouts."""
    from app.services import crm_defaults
    crm.ensure_defaults()
    settings_ = crm.crm_settings_raw()
    channels = settings_.get('channels') or [list(c) for c in crm_defaults.CHANNELS]
    pipelines = CrmPipeline.query.filter_by(is_active=True).order_by(CrmPipeline.id).all()
    open_counts = dict(db.session.query(CrmLead.stage_id, func.count(CrmLead.id))
                       .filter(CrmLead.status == 'open').group_by(CrmLead.stage_id).all())
    since = datetime.utcnow() - timedelta(days=30)
    closed_counts = dict(db.session.query(CrmLead.stage_id, func.count(CrmLead.id))
                         .filter(CrmLead.status != 'open', CrmLead.closed_at >= since)
                         .group_by(CrmLead.stage_id).all())
    inlets = (db.session.query(CrmSource, func.count(CrmLead.id))
              .outerjoin(CrmLead, (CrmLead.source_id == CrmSource.id) & (CrmLead.created_at >= since))
              .filter(CrmSource.status != 'paused').group_by(CrmSource.id)
              .order_by(func.count(CrmLead.id).desc(), CrmSource.name).all())
    return render_template('cs/crm/process.html', channels=channels, pipelines=pipelines,
                           open_counts=open_counts, closed_counts=closed_counts, inlets=inlets,
                           **_common())


@crm_bp.route('/process', methods=['POST'])
@cs_required
@admin_only
def save_process():
    f = request.form
    if f.get('what') == 'channels':
        rows = []
        for line in (f.get('channels') or '').splitlines():
            parts = [x.strip() for x in line.split('|')]
            if parts and parts[0]:
                rows.append((parts + ['', '', '', ''])[:4])
        crm.save_settings(current_user, channels=rows[:80])
    flash('Saved.', 'success')
    return redirect(crm_url('sources', tab='activities'))


# ============================================================================================ lead extras

@crm_bp.route('/lead/<int:lead_id>/event', methods=['POST'])
@cs_required
def event(lead_id):
    """I sent the quote / I sent the payment link: a system line under Q / PLS, and the lead moves
    forward. Nothing is sent to the customer."""
    lead = _lead_or_404(lead_id)
    code = (_json().get('code') or '').upper()
    if crm.milestone_stage(lead.pipeline, code) is None:
        return jsonify({'error': 'Unknown action.'}), 400
    moved = crm.mark_event(lead, code, user=current_user, note=(_json().get('note') or '').strip()[:500] or None)
    return jsonify({'success': True, 'stage': moved.name if moved else None})


@crm_bp.route('/insights.csv')
@cs_required
@admin_only
def insights_csv():
    """The per-person numbers, day by day, for a spreadsheet -- the old KPI tabs."""
    import csv
    import io
    days = request.args.get('days', type=int) or 30
    days = days if days in (7, 30, 90) else 30
    _, daily = crm_reports.kpis(datetime.utcnow() - timedelta(days=days))
    names = {u.id: u.full_name for u in User.query.filter(User.id.in_(list(daily) or [0])).all()}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['Date', 'Person'] + [label for _, label in crm_reports.METRICS])
    for uid, by_day in daily.items():
        for day in sorted(by_day):
            w.writerow([day.isoformat(), names.get(uid, uid)] + [by_day[day].get(k, 0) for k, _ in crm_reports.METRICS])
    ActivityEvent.log('crm_export', actor=current_user, kind='numbers', days=days)
    db.session.commit()
    resp = make_response('\ufeff' + buf.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename=sales-numbers-%dd.csv' % days
    return resp


# ============================================================================================ setup

@crm_bp.route('/setup')
@cs_required
def setup():
    """Moved: Set-up is five pages now. Old links and bookmarks land on the right one."""
    a, tab = request.args, request.args.get('tab') or 'pipelines'
    if tab == 'templates':
        return redirect(crm_url('pipelines', show='templates'))
    if tab == 'sources':
        return redirect(crm_url('sources', edit=a.get('edit') or None))
    if tab == 'answers':
        return redirect(crm_url('quick_replies', edit=a.get('edit') or None))
    if tab == 'connect':
        return redirect(crm_url('connection'))
    if tab == 'import':
        return redirect(crm_url('data'))
    return redirect(crm_url('pipelines', p=a.get('p') or None))      # no tab, pipelines, messages, anything else


def _sources_context(**extra):
    """What Where leads come from draws, for the list and for the editor shown again with its errors."""
    from app.services import access, crm_editor, crm_people
    crm.ensure_defaults()
    tab = request.args.get('tab') if request.args.get('tab') in ('inboxes', 'activities') else 'sources'
    rows = CrmSource.query.all()
    order = {'unrouted': 0, 'live': 1, 'paused': 2}
    rows.sort(key=lambda s: (order.get(s.status, 3), s.name.lower()))
    staff = _staff()
    ws = access.current_workspace(current_user)
    teams = list(ws.teams) if ws is not None else []
    staff_by_id, teams_by_id = {u.id: u for u in staff}, {t.id: t for t in teams}
    since = datetime.utcnow() - timedelta(days=30)
    counts30 = dict(db.session.query(CrmLead.source_id, func.count(CrmLead.id))
                    .filter(CrmLead.created_at >= since).group_by(CrmLead.source_id).all())
    really = {s.id: crm_people.really_goes(s) for s in rows}
    edit = extra.pop('edit', None)
    if edit is None:
        arg = request.args.get('edit')
        edit = (CrmSource() if arg == 'new' else db.session.get(CrmSource, int(arg)) if arg and arg.isdigit() else None)
    is_new = extra.pop('is_new', request.args.get('edit') == 'new')
    snippet_url = url_for('static', filename='js/lead-capture.js', _external=True)
    ctx = dict(tab=tab, sources=rows, edit=edit, is_new=is_new, pipelines=CrmPipeline.query.order_by(CrmPipeline.id).all(),
               staff=staff, teams=teams, STATUSES=CRM_SOURCE_STATUSES,
               goes={s.id: crm_people.goes_to(s, staff_by_id, teams_by_id) for s in rows},
               really=really, counts30=counts30,
               tag_names=sorted({str(t).lower() for s in rows for t in s.crm_tags or []}),
               intake_url=_public_url('crm_public.intake'), snippet_url=snippet_url, snippet=None,
               check_rows=crm.crm_settings()['check_rows'], wa_key=current_app.config.get('WACRM_SOURCE_KEY', 'wa-india'),
               replies_linked=crm.wa_replies_linked(), source_keys=[(s.key, s.name) for s in rows],
               activities=crm.crm_settings_raw().get('channels') or [list(c) for c in crm_defaults.CHANNELS],
               form={}, errors={}, clash=None, take_over=set())
    if edit is not None and edit.key:
        ctx['snippet'] = crm_editor.form_snippet(edit.key, edit.product, snippet_url)
    ctx.update(extra)
    return {**_common(), **ctx}


@crm_bp.route('/sources')
@cs_required
@admin_only
def sources():
    """Set-up -> Where leads come from (E20): tabs Sources (?edit=<id> or new opens one), Inboxes to check,
    Marketing activities."""
    return render_template('cs/crm/sources.html', **_sources_context())


def _data_context(**extra):
    """What Bring in & download draws (the sheet's preview and the CSV's plan come in as `preview` / `csv`)."""
    from app.services import access, crm_people, wacrm_team
    ctx = dict(preview=None, csv=None, pipelines=CrmPipeline.query.order_by(CrmPipeline.id).all(), staff=_staff(),
               sources=CrmSource.query.order_by(CrmSource.name).all(), tiles=crm_products.tiles(),
               dnc_n=crm_people.dnc_count(), wa_enabled=wacrm_team.enabled(),
               feed_missing=bool(crm.crm_settings_raw().get('wa_feed_missing')),
               can_export=access.can(current_user, 'crm_export'), crm_people=crm_people)
    ctx.update(extra)
    return {**_common(), **ctx}


@crm_bp.route('/data')
@cs_required
@admin_only
def data():
    """Set-up -> Bring in & download (E23): import a list, the sales sheet, old website enquiries, downloads
    and the one-off imports from WhatsApp."""
    return render_template('cs/crm/data.html', **_data_context())


@crm_bp.route('/setup/templates/<action>', methods=['GET', 'POST'])
@cs_required
@admin_only
def setup_templates(action):
    """WhatsApp templates for the messages: download the list, or put the missing ones into the
    WhatsApp CRM as drafts (a person then submits each to Meta there). Only while the portal may
    write to WhatsApp (crm.wa_writes_on). Quick replies have their own page now."""
    from app.services import wa_templates, wacrm_team
    if action == 'csv':
        resp = make_response(wa_templates.csv_text())
        resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
        resp.headers['Content-Disposition'] = 'attachment; filename=whatsapp-templates.csv'
        return resp
    if request.method != 'POST':
        abort(405)
    if action != 'drafts':
        abort(404)
    back = crm_url('pipelines', show='templates')
    if not crm.wa_writes_on():
        flash(crm.WA_WRITES_OFF, 'warning')           # the switch is Off: nothing goes to WhatsApp
        return redirect(back)
    try:
        out = wa_templates.push_drafts()
        flash('%d template(s) added to WhatsApp as drafts%s. Open WhatsApp templates to send them for approval.'
              % (out['created'], ('; %d left out (see the list)' % len(out['skipped'])) if out['skipped'] else ''),
              'success')
    except wacrm_team.TeamError as exc:
        flash('The WhatsApp CRM said: %s' % exc, 'danger')
    return redirect(back)


def _slug(text):
    s = re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')
    return s[:58] or 'source'


@crm_bp.route('/setup/source', methods=['POST'])
@cs_required
@admin_only
def save_source():
    f = request.form
    sid = f.get('id')
    src = db.session.get(CrmSource, int(sid)) if sid and sid.isdigit() else None
    old_tags = {t.lower() for t in (src.crm_tags or [])} if src is not None else set()
    old_name = src.name if src is not None else None
    name = (f.get('name') or '').strip()[:100]
    if not name:
        flash('Give the source a name people will recognise.', 'danger')
        return redirect(crm_url('sources', edit=sid or 'new'))
    from app.services import access, crm_people
    staff_ids = {u.id for u in _staff()}
    ws = access.current_workspace(current_user)
    team_ids = {t.id for t in ws.teams} if ws is not None else set()
    team, team_error = crm_people.parse_routing(f, staff_ids, team_ids)
    new_tag_list = [t.strip().lower()[:30] for t in (f.get('crm_tags') or '').split(',') if t.strip()][:8]
    errors, clash = {}, None
    if team_error:
        errors['team'] = team_error
    take_over = set(f.getlist('take_over'))
    for t in dict.fromkeys(new_tag_list):
        if t in old_tags:
            continue
        problem = crm_people.source_tag_problem(t, take_over=take_over)
        if problem:
            errors['tags'] = problem['error']
            clash = problem.get('clash')
            break
    if errors:
        for e in errors.values():
            flash(e, 'danger')
        shown = src if src is not None else CrmSource()
        return render_template('cs/crm/sources.html', **_sources_context(edit=shown, is_new=src is None, form=f,
                                                                           errors=errors, clash=clash,
                                                                           take_over=take_over)), 400
    is_new = src is None
    if src is None:
        key = _slug(f.get('key') or name)
        base, n = key, 2
        while CrmSource.query.filter_by(key=key).first():
            key = '%s-%d' % (base[:55], n)
            n += 1
        src = CrmSource(key=key)
        db.session.add(src)
    src.name = name
    src.kind = f.get('kind') if f.get('kind') in CRM_SOURCE_KINDS else 'form'
    chosen = crm_products.by_code(f.get('product'))
    src.product = chosen.code if chosen is not None else crm_products.general_code()
    pipe = CrmPipeline.query.filter_by(key=f.get('pipeline')).first()
    src.pipeline = pipe
    status = f.get('status') if f.get('status') in ('live', 'paused') else 'live'
    src.status = status if pipe else 'unrouted'
    src.team = team
    src.crm_tags = new_tag_list or None
    src.pages = [p.strip()[:200] for p in (f.get('pages') or '').split(',') if p.strip()][:10] or None
    try:
        src.dedupe_days = max(0, min(365, int(f.get('dedupe_days') or 30)))
    except ValueError:
        src.dedupe_days = 30
    src.updated_by_id = current_user.id
    db.session.flush()
    new_tags = {t.lower() for t in (src.crm_tags or [])}
    if new_tags != old_tags:
        # the tags it no longer adds stay the portal's, so the sync takes them off; saved now --
        # it commits -- before anybody is marked, so the first sync after this save knows them
        crm.wa_retire_tags(old_tags - new_tags, actor=current_user)
    # leads that waited while this source was unrouted start their pipeline now
    crm.start_waiting_leads(src, user=current_user)
    if new_tags != old_tags:
        crm.wa_mark_source(src)        # its people's tags follow, quietly, through the jobs runner
    ActivityEvent.log('crm_source_saved', actor=current_user, source=src.key, new=is_new,
                      tags_changed=new_tags != old_tags)
    db.session.commit()
    if new_tags != old_tags or (src.crm_tags and old_name != src.name):
        crm.wa_tag_rule_changed()      # the WhatsApp CRM learns which tags are the Sales CRM's
    if isinstance(team, dict):
        members = {x.id for t in (ws.teams if ws is not None else []) if t.id == team['team_id'] for x in t.users}
        if not members & staff_ids:
            flash('Nobody in that team can take leads yet, so they go to anyone in sales.', 'warning')
    flash('Saved "%s".' % src.name, 'success')
    return redirect(crm_url('sources'))


@crm_bp.route('/setup/pipeline', methods=['GET', 'POST'])
@cs_required
@admin_only
def save_pipeline():
    """The Set-up form from before U6, kept for one release: old open tabs (and tests) still post here."""
    if request.method == 'GET':
        return redirect(crm_url('pipelines'))
    f = request.form
    action = f.get('action')
    if action == 'new':
        name = (f.get('name') or '').strip()[:80]
        if not name:
            flash('Name the new pipeline.', 'danger')
            return redirect(crm_url('pipeline_new'))
        key = _slug(name)[:40]
        base, n = key, 2
        while CrmPipeline.query.filter_by(key=key).first():
            key = '%s-%d' % (base[:36], n)
            n += 1
        chosen = crm_products.by_code(f.get('product'))
        product = chosen.code if chosen is not None else crm_products.general_code()
        p = CrmPipeline(key=key, name=name, product=product,
                        fallout_reasons=list(crm_defaults.SIMPLE_REASONS))
        for pos, (skey, sname, means, on_reply) in enumerate(crm_defaults.SIMPLE_PATH):
            p.stages.append(CrmStage(key=skey, name=sname, means=means, on_reply=on_reply, position=pos))
        db.session.add(p)
        ActivityEvent.log('crm_pipeline_created', actor=current_user, pipeline=key, product=product, via='old form')
        db.session.commit()
        crm.wa_tag_rule_changed()
        flash('Pipeline "%s" created. Add its stages and messages.' % name, 'success')
        return redirect(crm_url('pipeline_edit', pid=p.id))

    pipe = CrmPipeline.query.filter_by(key=f.get('pipeline')).first_or_404()
    if action == 'reasons':
        pipe.fallout_reasons = [r.strip()[:80] for r in (f.get('reasons') or '').splitlines() if r.strip()][:20]
        pipe.name = (f.get('name') or pipe.name).strip()[:80] or pipe.name
        pipe.is_active = f.get('is_active') == 'on'
        ActivityEvent.log('crm_pipeline_saved', actor=current_user, pipeline=pipe.key, via='old form')
        db.session.commit()
        if pipe.tag_mode == 'own':
            crm.wa_tag_rule_changed()      # the label's text in the WhatsApp CRM is the pipeline's name
        flash('Saved.', 'success')
        return redirect(crm_url('pipeline_edit', pid=pipe.id))
    if action == 'stage':
        sid = f.get('stage_id')
        st = db.session.get(CrmStage, int(sid)) if sid and sid.isdigit() else None
        op = f.get('op')
        if st is None or st.pipeline_id != pipe.id:
            if op == 'add':
                name = (f.get('name') or '').strip()[:60]
                if not name:
                    flash('Name the stage.', 'danger')
                    return redirect(crm_url('pipeline_edit', pid=pipe.id))
                key = _slug(name)[:40].replace('-', '_')
                base, n = key, 2
                while any(s.key == key for s in pipe.stages):
                    key = '%s_%d' % (base[:36], n)
                    n += 1
                means = f.get('means') if f.get('means') in CRM_STAGE_MEANS else (
                    f.get('kind') if f.get('kind') in ('won', 'lost') else None)
                kind = 'won' if means == 'won' else 'lost' if means == 'lost' else 'open'
                # a new open stage goes after the last open one, before the finish lines
                pos = max([s.position for s in pipe.stages if s.kind == 'open'] or [-1]) + 1
                for s in pipe.stages:
                    if s.position >= pos:
                        s.position += 1
                new_stage = CrmStage(key=key, name=name, kind=kind, means=means,
                                     position=pos if kind == 'open'
                                     else max([s.position for s in pipe.stages] or [0]) + 1)
                pipe.stages.append(new_stage)
                if means is None:
                    new_stage.means = crm.derive_means(new_stage)
                db.session.commit()
                crm.wa_tag_rule_changed()
                flash('Stage added.', 'success')
            return redirect(crm_url('pipeline_edit', pid=pipe.id))
        if op == 'save':
            old_name = st.name
            st.name = (f.get('name') or st.name).strip()[:60] or st.name
            st.on_reply = f.get('on_reply') == 'on'
            if st.on_reply:
                for s in pipe.stages:
                    if s.id != st.id:
                        s.on_reply = False
            # "This stage means" decides open / won / lost; the old form's "kind" still works
            if f.get('means') in CRM_STAGE_MEANS:
                st.means = f.get('means')
            elif f.get('kind') in ('won', 'lost'):
                st.means = f.get('kind')
            elif f.get('kind') == 'open' and st.means in ('won', 'lost', None):
                st.means = (crm.derive_means(st) if st.means is None else 'talking' if st.on_reply else 'quoted')
            sla = (f.get('sla_hours') or '').strip()
            st.sla_hours = int(sla) if sla.isdigit() else None
            kind = f.get('auto_kind') if f.get('auto_kind') in CRM_AUTO_KINDS else None
            field = None
            if f.get('auto_kind') == 'departed':               # the old form's word for it
                kind, field = 'after_date', 'departure_date'
            to = db.session.get(CrmStage, int(f.get('auto_to') or 0)) if (f.get('auto_to') or '').isdigit() else None
            days = (f.get('auto_days') or '').strip()
            if kind and to is not None and to.pipeline_id == pipe.id and to.id != st.id:
                st.auto_kind, st.auto_to, st.auto_days = kind, to, int(days) if days.isdigit() else 0
                st.auto_reason = (f.get('auto_reason') or '').strip()[:80] or None
                if kind == 'after_date':
                    field = field or f.get('auto_field')
                    st.auto_field = field if field in dict(crm.date_fields(pipe)) else 'departure_date'
                else:
                    st.auto_field = None
            else:
                st.auto_kind = st.auto_to = st.auto_days = st.auto_reason = st.auto_field = None
            if st.name != old_name:
                crm.stage_renamed(st, old_name)    # "TI: <new name>" on their WhatsApp contacts, after the save
        elif op in ('up', 'down'):
            ordered = list(pipe.stages)
            i = ordered.index(st)
            j = i - 1 if op == 'up' else i + 1
            if 0 <= j < len(ordered):
                ordered[i].position, ordered[j].position = ordered[j].position, ordered[i].position
        elif op == 'delete':
            in_use = CrmLead.query.filter_by(stage_id=st.id).count()
            if in_use or len(pipe.stages) <= 2:
                flash('That stage still has leads in it, or the pipeline would be too short.', 'danger')
                return redirect(crm_url('pipeline_edit', pid=pipe.id))
            CrmStageChange.query.filter((CrmStageChange.to_stage_id == st.id) |
                                        (CrmStageChange.from_stage_id == st.id)).delete(synchronize_session=False)
            db.session.delete(st)
        ActivityEvent.log('crm_pipeline_saved', actor=current_user, pipeline=pipe.key, via='old form')
        db.session.commit()
        if op in ('save', 'delete'):
            crm.wa_tag_rule_changed()
        flash('Saved.', 'success')
        return redirect(crm_url('pipeline_edit', pid=pipe.id))
    abort(400)


@crm_bp.route('/setup/step', methods=['GET', 'POST'])
@cs_required
@admin_only
def save_step():
    """The Set-up form from before U6, kept for one release: old open tabs (and tests) still post here."""
    if request.method == 'GET':
        return redirect(crm_url('pipelines'))
    f = request.form
    stage = db.session.get(CrmStage, int(f.get('stage_id') or 0))
    if stage is None:
        abort(404)
    sid = f.get('id')
    step = db.session.get(CrmPlaybookStep, int(sid)) if sid and sid.isdigit() else None
    if f.get('op') == 'delete' and step:
        CrmTask.query.filter_by(step_id=step.id, status='open').update(
            {'status': 'skipped', 'note': 'Step deleted'}, synchronize_session=False)
        CrmTask.query.filter_by(step_id=step.id).update({'step_id': None}, synchronize_session=False)
        db.session.delete(step)
        db.session.commit()
        flash('Step removed.', 'success')
        return redirect(crm_url('pipeline_edit', pid=stage.pipeline_id))
    if step is None:
        step = CrmPlaybookStep(stage=stage, position=max([s.position for s in stage.steps] or [-1]) + 1,
                                code='STEP', title='STEP')       # filled in below (queries here may flush)
        db.session.add(step)
    step.channel = f.get('channel') if f.get('channel') in CRM_STEP_CHANNELS else 'whatsapp'
    trig, unit = f.get('trigger'), f.get('unit') or 'hours'
    try:
        val = int(f.get('value') or 0)
    except ValueError:
        val = 0
    if trig in CRM_LEGACY_TRIGGERS:            # the old form: "(days) before they travel / ... ends"
        step.trigger, step.trigger_field, step.trigger_value = 'date_offset', CRM_LEGACY_TRIGGERS[trig], -abs(val)
    elif trig == 'date_offset':
        step.trigger, step.trigger_value = 'date_offset', max(-365, min(365, val))
        field = f.get('trigger_field')
        step.trigger_field = field if field in dict(crm.date_fields(stage.pipeline)) else 'departure_date'
    else:
        step.trigger, step.trigger_field = 'after_hours', None
        val = max(0, val)
        step.trigger_value = val * 24 if unit == 'days' else val
    step.kind = f.get('kind') if f.get('kind') in CRM_STEP_KINDS else (
        step.kind or crm_defaults.step_kind(f.get('code') or '', set(crm_products.codes())))
    step.code = (f.get('code') or '').strip()[:20] or crm.next_step_code(stage.pipeline, step.kind)
    step.title = (f.get('title') or '').strip()[:160] or step.code
    step.auto = f.get('auto') == 'on' and step.channel == 'whatsapp'
    step.body = (f.get('body') or '').strip()[:4000] or None
    step.wa_template = (f.get('wa_template') or '').strip()[:80] or None
    ActivityEvent.log('crm_pipeline_saved', actor=current_user, pipeline=stage.pipeline.key, via='old form')
    db.session.commit()
    flash('Saved %s.' % step.code, 'success')
    return redirect(crm_url('pipeline_edit', pid=stage.pipeline_id))


# ============================================================================================ inbox check

@crm_bp.route('/checks')
@cs_required
def checks():
    """The sales sheet's Checker: each inbox, every half hour, ticked by whoever looked."""
    today, now_slot = crm_reports.current()
    day = today
    if request.args.get('day'):
        try:
            day = datetime.strptime(request.args['day'], '%Y-%m-%d').date()
        except ValueError:
            day = today
    channels = crm.crm_settings()['check_channels']
    from app.services import crm_people
    auto = crm_people.check_auto(crm.crm_settings()['check_rows'])
    for item in auto:
        for w in item['waiting']:
            w['short'] = _short_name(w['lead'].person)
            w['url'] = crm_url('lead', lead_id=w['lead'].id)
    return render_template('cs/crm/checks.html', day=day, today=today, now_slot=now_slot, auto=auto,
                           channels=channels, ticks=crm_reports.grid(day), slots=crm_reports.slots(),
                           label=crm_reports.slot_label, cov=crm_reports.coverage(day, channels),
                           editable=(day == today), can_tick=crm_reports.can_tick,
                           week=[(today - timedelta(days=i), crm_reports.coverage(today - timedelta(days=i), channels))
                                 for i in range(1, 8)],
                           timedelta=timedelta, **_common())


@crm_bp.route('/checks/tick', methods=['POST'])
@cs_required
def check_tick():
    data = _json()
    day, now_slot = crm_reports.current()
    channels = crm.crm_settings()['check_channels']
    slot = data.get('slot')
    slot = now_slot if slot in (None, '') else int(slot)
    if slot is None or not crm_reports.can_tick(day, slot):
        return jsonify({'error': 'Only the current half hour, or an earlier one today, can be ticked.'}), 400
    if data.get('all'):
        crm_reports.tick_all(day, slot, current_user, channels)
        return jsonify({'success': True, 'all': True})
    ch = data.get('channel')
    if ch not in channels:
        return jsonify({'error': 'Unknown inbox.'}), 400
    return jsonify({'success': True, 'ticked': crm_reports.toggle(day, slot, ch, current_user)})


# ============================================================================================ connect & import

def _public_url(endpoint):
    from app.services import urls
    try:
        return urls.public_absolute(endpoint)
    except Exception:          # noqa: BLE001
        return url_for(endpoint, _external=True)


IMPORT_DIR = 'crm-imports'


def _import_path(token):
    import os
    folder = os.path.join(current_app.config['PRIVATE_UPLOAD_FOLDER'], IMPORT_DIR)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, '%s.xlsx' % token)


@crm_bp.route('/setup/backfill', methods=['POST'])
@cs_required
@admin_only
def backfill():
    from app.services import crm_import
    days = request.form.get('days', type=int) or 180
    out = crm_import.backfill(days=max(1, min(days, 730)))
    got = sum(v for k, v in out.items() if k not in ('already', 'unreachable', 'do not contact'))
    flash('Brought in %d past enquir%s%s.%s' % (
        got, 'y' if got == 1 else 'ies', ' (%d were already here)' % out['already'] if out.get('already') else '',
        ' %d skipped (on the do-not-contact list).' % out['do not contact'] if out.get('do not contact') else ''),
        'success')
    return redirect(crm_url('data'))


@crm_bp.route('/setup/import', methods=['POST'])
@cs_required
@admin_only
def import_sheet():
    """Step 1: upload the workbook and see what is in it. Nothing is stored yet."""
    import secrets
    from app.services import crm_import
    f = request.files.get('sheet')
    if not f or not (f.filename or '').lower().endswith('.xlsx'):
        flash('Choose the Sales Process workbook (.xlsx).', 'danger')
        return redirect(crm_url('data'))
    token = secrets.token_hex(12)
    path = _import_path(token)
    f.save(path)
    try:
        rows, stats, kpi = crm_import.read_sheet(path)
    except Exception:          # noqa: BLE001 -- not a workbook, or not this one
        current_app.logger.exception('Sales sheet unreadable')
        flash('That file could not be read as an Excel workbook.', 'danger')
        return redirect(crm_url('data'))
    staff = _staff()

    def guess(tab):
        # "HB KPI" -> the person whose initials are HB
        ini = tab.split()[0].upper()
        for u in staff:
            parts = [x for x in (u.full_name or '').split() if x]
            if len(parts) >= 2 and (parts[0][0] + parts[-1][0]).upper() == ini:
                return u.id
        return None
    kpi_tabs = [{'tab': t, 'days': len({d for d, _, _ in rows_}), 'team': t == 'KPI',
                 'guess': None if t == 'KPI' else guess(t)} for t, rows_ in kpi.items() if rows_]
    preview = {'token': token, 'stats': stats, 'total': len(rows), 'name': f.filename, 'kpi': kpi_tabs,
               'products': dict(__import__('collections').Counter(r['product'] for r in rows))}
    return render_template('cs/crm/data.html', **_data_context(preview=preview))


@crm_bp.route('/setup/import/confirm', methods=['POST'])
@cs_required
@admin_only
def import_confirm():
    """Step 2: store what step 1 showed, then forget the file."""
    import os
    from app.services import crm_import
    token = request.form.get('token') or ''
    if not re.fullmatch(r'[0-9a-f]{24}', token) or not os.path.exists(_import_path(token)):
        flash('That upload has expired -- choose the file again.', 'danger')
        return redirect(crm_url('data'))
    owner = request.form.get('owner', type=int)
    owner = owner if owner in {u.id for u in _staff()} else None
    path = _import_path(token)
    try:
        rows, _, kpi = crm_import.read_sheet(path)
        staff_ids = {u.id for u in _staff()}
        kpi_users = {}
        for tab in kpi:
            choice = request.form.get('kpi_' + tab.replace(' ', '_'))
            if tab == 'KPI' and choice == 'team':
                kpi_users[tab] = None
            elif choice and choice.isdigit() and int(choice) in staff_ids:
                kpi_users[tab] = int(choice)
        out = crm_import.import_sheet(rows, owner_id=owner, kpi=kpi, kpi_users=kpi_users)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    got = sum(v for k, v in out.items() if k not in ('already', 'unreachable', 'do not contact')
              and not k.startswith('KPI'))
    flash('Imported %d lead%s from the sales sheet%s.%s' % (
        got, '' if got == 1 else 's', ' (%d were already here)' % out['already'] if out.get('already') else '',
        ' %d skipped (on the do-not-contact list).' % out['do not contact'] if out.get('do not contact') else ''),
        'success')
    return redirect(crm_url('board', owner='all'))


# ============================================================================================ public

INTAKE_FIELDS = 30


def _cors(resp):
    origins = [o.strip().rstrip('/') for o in (current_app.config.get('CRM_INTAKE_ORIGINS') or '').split(',')
               if o.strip()]
    origin = (request.headers.get('Origin') or '').rstrip('/')
    if origin and origin in origins:
        resp.headers['Access-Control-Allow-Origin'] = origin
        resp.headers['Vary'] = 'Origin'
        resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp


@crm_public_bp.route('/api/leads', methods=['POST', 'OPTIONS'])
@csrf.exempt
@rate_limit(20, 3600)
def intake():
    """The one door every landing page can use: {source, name, phone, phone_cc, email, message,
    product, fields{...}}. A source nobody set up yet is accepted and shows up as unrouted."""
    if request.method == 'OPTIONS':
        return _cors(make_response('', 204))
    data = request.get_json(silent=True) or request.form.to_dict()
    if (data.get('website') or '').strip():
        # the hidden field only a bot fills in; answer as if it worked
        return _cors(make_response(jsonify({'success': True}), 201))
    key = (data.get('source') or '').strip().lower()
    if not crm.SOURCE_KEY_RE.match(key):
        return _cors(make_response(jsonify({'success': False, 'error': 'Unknown form.'}), 400))
    phone, email = (data.get('phone') or '').strip()[:30], (data.get('email') or '').strip()[:255]
    if not phone and not email:
        return _cors(make_response(jsonify({'success': False,
                                            'error': 'Please give a phone number or an e-mail.'}), 400))
    if phone and not crm.normalise_phone(phone, data.get('phone_cc')):
        return _cors(make_response(jsonify({'success': False,
                                            'error': 'That phone number does not look right.'}), 400))
    if email and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return _cors(make_response(jsonify({'success': False,
                                            'error': 'That e-mail address does not look right.'}), 400))
    fields = data.get('fields') if isinstance(data.get('fields'), dict) else {}
    fields = {str(k)[:40]: str(v)[:300] for k, v in list(fields.items())[:INTAKE_FIELDS]
              if v not in (None, '')}
    utm = crm.utm_from_request()
    for k in crm.UTM_KEYS:
        if data.get(k):
            utm[k] = str(data[k])[:200]
    lead = crm.capture_safely(key, name=(data.get('name') or '')[:120], phone=phone,
                              phone_cc=data.get('phone_cc'), email=email,
                              product=data.get('product'), message=(data.get('message') or '')[:2000] or None,
                              details=fields, utm=utm,
                              consent=bool(data.get('consent')) or crm.ticked(data.get('wa_consent')),
                              consent_from='lead form')
    if lead is None:
        return _cors(make_response(jsonify({'success': False,
                                            'error': 'Sorry, that did not go through. Please try again.'}), 500))
    return _cors(make_response(jsonify({'success': True}), 201))


@crm_public_bp.route('/api/crm/wacrm-webhook', methods=['POST'])
@csrf.exempt
def wacrm_webhook():
    """Replies from the WhatsApp CRM. Signed by it; anything unsigned is refused.

    Nothing here calls the WhatsApp CRM back (it waits five seconds and switches us off after 15
    failures in a row): what it should learn is marked and told after the save. An event that
    breaks is logged and answered 200 {"ok": false}, so one bad event cannot cost every reply
    after it; the jobs runner catches up (crm.wa_catch_up)."""
    raw = request.get_data()
    if not wacrm.verify_signature(request.headers.get('X-Wacrm-Signature', ''), raw):
        return jsonify({'error': 'Bad signature.'}), 401
    try:
        body = json.loads(raw.decode('utf-8') or '{}')
    except ValueError:
        return jsonify({'error': 'Not JSON.'}), 400
    if not isinstance(body, dict):
        return jsonify({'ok': True})
    event, data = body.get('event'), body.get('data') or {}
    handler = WACRM_EVENTS.get(event)
    if handler is None:
        return jsonify({'ok': True})
    try:
        return handler(data if isinstance(data, dict) else {})
    except Exception:          # noqa: BLE001 -- answered, logged, caught up by the jobs runner
        db.session.rollback()
        current_app.logger.exception('WhatsApp CRM %s event not stored', event)
        return jsonify({'ok': False})


# what the webhook answers for each way a message from them was recorded (crm.record_whatsapp_in)
WACRM_RECEIVED = {'logged': {}, 'duplicate': {'duplicate': True}, 'created': {'created': True},
                  'new_lead': {'created': True}, 'closed': {'closed': True}, 'opted_out': {'opted_out': True},
                  'ignored': {'ignored': True}}
WA_SENT_BY = {'automation': 'automation', 'flow': 'chatbot flow', 'ai': 'AI reply', 'broadcast': 'broadcast'}


def _wacrm_received(data):
    """Somebody wrote to us on WhatsApp: on the lead we last wrote to, or a new lead (see
    crm.record_whatsapp_in). Their number and name come with the event; nothing is asked back.
    interactive_reply_id is not needed: the reply's text carries the button's words."""
    result = crm.record_whatsapp_in(contact_id=data.get('contact_id'), conversation_id=data.get('conversation_id'),
                                    phone=data.get('contact_phone'), name=data.get('contact_name'),
                                    wamid=data.get('whatsapp_message_id'), text=data.get('text'),
                                    content_type=data.get('content_type'))
    if result == 'failed':
        return jsonify({'ok': False, 'created': False})
    return jsonify({'ok': True, **WACRM_RECEIVED.get(result, {})})


def _wa_event_person(data):
    """The person a WhatsApp CRM event is about (crm.wa_person), with what it says about them kept
    (crm.wa_link), or None."""
    cid = data.get('contact_id')
    person = crm.wa_person(cid, data.get('contact_phone'))
    if person is not None:
        crm.wa_link(person, cid, data.get('conversation_id'), data.get('contact_phone'))
    return person


def _staff_by_email(email):
    if not email:
        return None
    u = User.query.filter(db.func.lower(User.email) == str(email).lower(), User.is_active.is_(True)).first()
    return u if u is not None and (u.is_cs or u.is_admin) else None


def _wacrm_sent(data):
    """Somebody (or an automation, a flow, the AI) wrote to them from the WhatsApp CRM. It counts
    like a message sent from here: on the lead's history and in the numbers. A template that a
    lead's open step uses ticks that step, whoever sent it; when an agent wrote from the inbox,
    the WhatsApp step that was due is done too."""
    wamid = data.get('whatsapp_message_id')
    if wamid and CrmTouchpoint.query.filter_by(external_id=wamid).first():
        return jsonify({'ok': True, 'duplicate': True})
    person = _wa_event_person(data)
    template = (data.get('template_name') or '').strip() or None
    lead = (crm.wa_lead_for(person, template) or (person.leads[0] if person.leads else None)) \
        if person is not None else None
    if lead is None:
        db.session.commit()
        return jsonify({'ok': True, 'ignored': True})
    source = str(data.get('source') or 'inbox')
    agent = _staff_by_email(data.get('sent_by_email')) if source == 'inbox' else None
    text = data.get('text') or ('[template %s]' % template if template
                                else crm.wa_body(None, data.get('content_type')))
    if data.get('text') and not template:
        text = crm.wa_body(data.get('text'), data.get('content_type'))
    task = lead.open_task
    code = None
    if template and task is not None and task.channel == 'whatsapp' and task.step is not None \
            and task.step.wa_template == template:
        code = task.code
        crm.complete_task(task, user=agent, note='Sent from the WhatsApp inbox' if source == 'inbox'
                          else 'Sent from WhatsApp (%s)' % WA_SENT_BY.get(source, source))
    elif source == 'inbox':
        code = crm.ready_message_code(lead, data.get('text'), agent)
        if code is None and task is not None and task.channel == 'whatsapp' \
                and task.due_at <= datetime.utcnow() + timedelta(hours=12):
            code = task.code
            crm.complete_task(task, user=agent, note='Sent from the WhatsApp inbox')
    via = 'person' if source == 'inbox' else (source if source in CRM_VIA else None)
    crm.log_touch(lead, 'whatsapp', 'out', body=text, code=code, user=agent, status='sent', external_id=wamid,
                  via=via)
    if source != 'inbox':
        tp = CrmTouchpoint.query.filter_by(external_id=wamid).first() if wamid else None
        if tp is not None:
            tp.body = '%s (%s)' % (tp.body, WA_SENT_BY.get(source, source))
    db.session.commit()
    return jsonify({'ok': True})


WA_INBOX_ORIGINS = frozenset({'inbox', 'crm', ''})          # 'crm': an older WhatsApp CRM's word for the inbox
WA_BOT_ORIGINS = frozenset({'automation', 'flow', 'ai'})


def _wacrm_assigned(data):
    """The conversation was given to somebody in the WhatsApp CRM (contract 26). From the inbox: they
    look after the lead that holds the chat now (crm._wa_main_lead) and are rung. From a reply rule, the
    chatbot or the AI: the lead keeps its owner, and the chat goes back to them after the save. Our own
    change (origin "portal") is only the echo of ours."""
    origin = str(data.get('origin') or '')
    if origin == 'portal':
        return jsonify({'ok': True, 'echo': True})
    person = _wa_event_person(data)
    lead = None
    if person is not None:
        lead = crm._wa_main_lead(person) or (person.leads[0] if person.leads else None)
    if origin in WA_BOT_ORIGINS:
        owner = lead.owner if lead is not None else None
        if owner is not None and (owner.email or '').lower() != str(data.get('assignee_email') or '').lower():
            crm.mark_wa_due(person, assign=True)          # the chat goes back to whoever looks after the lead
            db.session.commit()
            return jsonify({'ok': True, 'kept': owner.email})
        db.session.commit()
        return jsonify({'ok': True, 'ignored': True})
    if origin not in WA_INBOX_ORIGINS:
        db.session.commit()
        return jsonify({'ok': True, 'ignored': True})
    user = _staff_by_email(data.get('assignee_email'))
    if lead is None or user is None or lead.owner_id == user.id:
        db.session.commit()
        return jsonify({'ok': True, 'ignored': True})
    crm.set_owner(lead, user.id, by=None, mark=False, chat=True)     # the chat is theirs in WhatsApp already
    db.session.commit()
    return jsonify({'ok': True, 'owner': user.email})


def _error_code(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _wacrm_status(data):
    """A message we sent moved on (sent, delivered, read, failed). A failure tells whoever sent it,
    in Meta's own words (crm.wa_failure_text); WhatsApp saying they stopped marketing messages
    from us (131050) opts them out."""
    wamid = data.get('whatsapp_message_id')
    tp = CrmTouchpoint.query.filter_by(external_id=wamid).first() if wamid else None
    status = str(data.get('status') or '')[:12]
    code = _error_code(data.get('error_code'))
    if status == 'failed' and code == crm.WA_OPT_OUT_CODE:
        person = db.session.get(CrmPerson, tp.person_id) if tp else crm.wa_person_by_chat(data.get('conversation_id'))
        if person is not None:
            lead = ((tp.lead if tp else None) or crm.wa_lead_for(person)
                    or (person.leads[0] if person.leads else None))
            crm.wa_opt_out(person, lead, crm.META_OPT_OUT_NOTE)
    if tp and status and tp.status != status and tp.status != 'imported':
        # deliveries can repeat and arrive out of order: never step back from read / failed
        order = {'sending': 0, 'opened': 0, 'sent': 1, 'delivered': 2, 'read': 3, 'failed': 4}
        if order.get(status, 0) >= order.get(tp.status or '', 0):
            tp.status = status
            if status == 'failed':
                person = db.session.get(CrmPerson, tp.person_id)
                why = crm.wa_failure_text(code, data.get('error_title'), person)
                tp.fail_reason = why[:300]
                if tp.agent_id and tp.lead:
                    from app.services import notify
                    notify.push(tp.agent_id, 'crm_failed',
                                title='WhatsApp message not delivered: %s' % tp.lead.person.display_name,
                                body=why, link=crm._lead_link(tp.lead))
    db.session.commit()
    return jsonify({'ok': True})


WACRM_EVENTS = {'message.received': _wacrm_received, 'message.sent': _wacrm_sent,
                'conversation.assigned': _wacrm_assigned, 'message.status_updated': _wacrm_status}


@crm_public_bp.route('/api/crm/meta-webhook', methods=['GET', 'POST'])
@csrf.exempt
def meta_webhook():
    """Instagram and Facebook messages and comments. GET is Meta checking the address once
    (it must echo hub.challenge back); POST deliveries are signed with the app secret."""
    if request.method == 'GET':
        if (request.args.get('hub.mode') == 'subscribe' and meta.verify_token()
                and request.args.get('hub.verify_token') == meta.verify_token()):
            return make_response(request.args.get('hub.challenge', ''), 200)
        return jsonify({'error': 'Verification failed.'}), 403
    raw = request.get_data()
    if not meta.verify_signature(request.headers.get('X-Hub-Signature-256', ''), raw):
        return jsonify({'error': 'Bad signature.'}), 401
    try:
        payload = json.loads(raw.decode('utf-8') or '{}')
    except ValueError:
        return jsonify({'error': 'Not JSON.'}), 400
    stored = 0
    for ev in meta.parse_events(payload):
        try:
            if crm.record_social(ev) is not None:
                stored += 1
        except Exception:      # noqa: BLE001 -- Meta retries the whole delivery on an error; keep the rest
            db.session.rollback()
            current_app.logger.exception('Meta event not stored')
    # always 200 once verified: anything else makes Meta resend, and in time switch us off
    return jsonify({'ok': True, 'stored': stored})
