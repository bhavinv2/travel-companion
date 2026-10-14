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

from flask import (Blueprint, abort, current_app, flash, jsonify, make_response, redirect,
                   render_template, request, url_for)
from flask_login import current_user
from sqlalchemy import func

from app import csrf, db
from app.models import (CrmAnswer, CrmIdentity, CrmLead, CrmPerson, CrmPipeline, CrmPlaybookStep, CrmSource,
                        CrmStage, CrmStageChange, CrmTask, CrmTouchpoint, User,
                        CRM_CALL_OUTCOMES, CRM_CHANNEL_LABELS, CRM_PRODUCT_LABELS, CRM_PRODUCTS,
                        CRM_SOURCE_KIND_LABELS, CRM_SOURCE_KINDS, CRM_SOURCE_STATUSES,
                        CRM_STAGE_KINDS, CRM_STEP_TRIGGERS, CRM_TEMPERATURES, CRM_LIKELIHOOD,
                        CRM_AUTO_KINDS)
from app.routes.cs import cs_required
from app.services import crm, crm_answers, crm_kpi, crm_reports, meta, wacrm
from app.services.ratelimit import rate_limit

crm_bp = Blueprint('crm', __name__)
crm_public_bp = Blueprint('crm_public', __name__)

# The same screens are mounted twice: /cs/crm inside the CS console (blueprint "crm") and
# /admin/crm inside the admin portal (blueprint "admin_crm", admins only). Links are built with
# crm_url() so whoever is in one portal stays in it.
CRM_BLUEPRINTS = ('crm', 'admin_crm')


# Set-up, imports, the dashboard and the daily tracker are the admin's: one-time or management
# work. Customer service sees only the day's work, in the CS console.
MANAGE = {'setup', 'save_source', 'save_pipeline', 'save_step', 'save_answer', 'save_whatsapp', 'backfill',
          'import_sheet', 'import_confirm', 'insights', 'insights_csv', 'tracker', 'save_process', 'setup_templates'}


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
    return {'PRODUCTS': CRM_PRODUCT_LABELS, 'TEMPS': CRM_TEMPERATURES, 'CHANNELS': CRM_CHANNEL_LABELS,
            'OUTCOMES': CRM_CALL_OUTCOMES, 'KINDS': CRM_SOURCE_KIND_LABELS,
            'IST_OFFSET': crm.IST, 'utcnow': datetime.utcnow(), 'wa_ready': crm.wa_can_send(),
            'LIKELIHOOD': CRM_LIKELIHOOD, 'wa_configured': wacrm.enabled(),
            'check_due': not crm_reports.current_slot_done(crm.crm_settings()['check_channels']),
            'unrouted_count': CrmSource.query.filter_by(status='unrouted').count(),
            'my_due': CrmTask.query.filter(CrmTask.status == 'open', CrmTask.owner_id == current_user.id,
                                           CrmTask.due_at <= datetime.utcnow()).count()}


def _lead_or_404(lead_id):
    lead = db.session.get(CrmLead, lead_id)
    if lead is None:
        abort(404)
    return lead


def _json():
    return request.get_json(silent=True) or {}


# ============================================================================================ board

@crm_bp.route('/')
@cs_required
def board():
    crm.ensure_defaults()
    pipelines = CrmPipeline.query.filter_by(is_active=True).order_by(CrmPipeline.id).all()
    counts = dict(db.session.query(CrmLead.pipeline_id, func.count(CrmLead.id))
                  .filter(CrmLead.status == 'open').group_by(CrmLead.pipeline_id).all())
    key = request.args.get('p')
    pipe = next((p for p in pipelines if p.key == key), None)
    if pipe is None:
        pipe = max(pipelines, key=lambda p: counts.get(p.id, 0)) if pipelines else None
    owner = request.args.get('owner') or ('all' if current_user.is_admin else 'mine')
    owner_id = current_user.id if owner == 'mine' else ('none' if owner == 'none' else None)
    q = (request.args.get('q') or '').strip()
    columns = crm.board(pipe, owner_id=owner_id, q=q) if pipe else []
    unrouted = (CrmLead.query.filter(CrmLead.pipeline_id.is_(None), CrmLead.status == 'open')
                .order_by(CrmLead.created_at.desc()).limit(50).all())
    return render_template('cs/crm/board.html', pipelines=pipelines, pipe=pipe, counts=counts,
                           columns=columns, owner=owner, q=q, unrouted=unrouted, **_common())


@crm_bp.route('/today')
@cs_required
def today():
    crm.ensure_defaults()
    who = request.args.get('who') or 'me'
    now = datetime.utcnow()
    q = CrmTask.query.filter(CrmTask.status == 'open', CrmTask.due_at <= now + timedelta(days=3))
    if who == 'me':
        q = q.filter(CrmTask.owner_id == current_user.id)
    tasks = q.order_by(CrmTask.due_at).limit(300).all()
    end_of_day = (datetime.combine((now + crm.IST).date(), datetime.max.time()) - crm.IST)
    groups = [('Overdue', [t for t in tasks if t.due_at < now]),
              ('Today', [t for t in tasks if now <= t.due_at <= end_of_day]),
              ('Next few days', [t for t in tasks if t.due_at > end_of_day])]
    texts = {t.id: crm.fill(t.step.body, t.lead, current_user) if t.step and t.step.body else ''
             for t in tasks}
    sq = (CrmLead.query.join(CrmStage, CrmLead.stage_id == CrmStage.id)
          .filter(CrmLead.status == 'open', CrmStage.sla_hours > 0))
    if who == 'me':
        sq = sq.filter(CrmLead.owner_id == current_user.id)
    stuck = [l for l in sq.order_by(CrmLead.entered_stage_at).limit(200).all() if l.stuck_hours]
    due_now = [t for t in tasks if t.due_at <= end_of_day]
    # a lead's very first message: "welcome the new ones" comes before the other follow-ups
    welcome = [t for t in due_now if t.step is not None and t.step.position == 0 and t.lead.stage is not None
               and t.lead.pipeline is not None and t.lead.stage.id == t.lead.pipeline.first_stage.id]
    follow = [t for t in due_now if t not in welcome]
    later = [t for t in tasks if t.due_at > end_of_day]
    start = datetime.combine((now + crm.IST).date(), datetime.min.time()) - crm.IST
    done_q = CrmTask.query.filter(CrmTask.status == 'done', CrmTask.done_at >= start)
    if who == 'me':
        done_q = done_q.filter(CrmTask.done_by_id == current_user.id)
    done_today = done_q.count()
    channels = crm.crm_settings()['check_channels']
    day, slot = crm_reports.current()
    ticks = crm_reports.grid(day)
    se = CrmAnswer.query.filter_by(code='SE').first()
    return render_template('cs/crm/today.html', groups=groups, texts=texts, who=who, total=len(tasks),
                           stuck=stuck, welcome=welcome, follow=follow, later=later, done_today=done_today,
                           slot=slot, slot_label=crm_reports.slot_label, slot_done=sum(1 for c in channels if (slot, c) in ticks),
                           channels=channels, coverage=crm_reports.coverage(day, channels),
                           shift_end=crm.fill(se.body, CrmLead(person=CrmPerson(name='there')), current_user) if se else '',
                           MANUAL=[(k, crm_kpi.METRICS[k][0]) for k in crm_kpi.MANUAL],
                           my_log=crm_kpi.entries((now + crm.IST).date(), current_user.id), **_common())


@crm_bp.route('/tracker')
@cs_required
@admin_only
def tracker():
    """The daily tracker: for any day, what each person had to do and what they did."""
    today_ = (datetime.utcnow() + crm.IST).date()
    try:
        day = datetime.strptime(request.args.get('day') or '', '%Y-%m-%d').date()
    except ValueError:
        day = today_
    day = min(day, today_)
    staff = _staff()
    sheet = crm_reports.day_sheet(day, staff)
    who = request.args.get('who', type=int)
    person = sheet.get(who) if who else None
    channels = crm.crm_settings()['check_channels']
    return render_template('cs/crm/tracker.html', day=day, today=today_, sheet=sheet, staff=staff, person=person,
                           prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1),
                           coverage=crm_reports.coverage(day, channels), slot_label=crm_reports.slot_label,
                           slots=crm_reports.slots(), MANUAL=dict((k, crm_kpi.METRICS[k][0]) for k in crm_kpi.MANUAL),
                           **_common())


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


def lead_card_context(lead):
    """What the lead card needs (_lead_card.html): on the lead page, and beside the WhatsApp
    inbox (messaging.lead_panel). The next step's words, filled in for them, and how WhatsApp
    will take it (crm.send_plan) -- decided here so the button says what will really happen."""
    task = lead.open_task
    step = task.step if task is not None else None
    next_text = crm.fill(step.body if step and step.body else (task.title if task else ''), lead, current_user) \
        if task else ''
    plan = crm.send_plan(lead, step) if task is not None and task.channel == 'whatsapp' else None
    return dict(lead=lead, person=lead.person, task=task, next_text=next_text, plan=plan,
                social=crm.social_reply_channels(lead),
                events=[(code, label) for code, (label, key) in crm.EVENTS.items()
                        if lead.pipeline and any(s.key == key for s in lead.pipeline.stages)],
                ref_url=_ref_url(lead), timeline=_timeline(lead),
                others=[l for l in lead.person.leads if l.id != lead.id], staff=_staff(),
                no_answers=crm.no_answer_streak(lead))


@crm_bp.route('/lead/<int:lead_id>')
@cs_required
def lead(lead_id):
    lead = _lead_or_404(lead_id)
    pipelines = CrmPipeline.query.filter_by(is_active=True).order_by(CrmPipeline.id).all()
    # The real WhatsApp conversation, as the WhatsApp CRM shows it, when it is connected to the
    # portal and this person's role includes WhatsApp.
    from app.services import wacrm_team
    from app.routes.messaging import crm_role
    wa_embed = bool(wacrm_team.enabled() and lead.person.phone and crm_role(current_user))
    return render_template('cs/crm/lead.html', wa_embed=wa_embed, pipelines=pipelines,
                           has_moves=any(ch.from_stage_id for ch in lead.stage_changes),
                           can_remove=crm.can_remove(lead, current_user),
                           **lead_card_context(lead), **_common())


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
    crm.move_stage(lead, stage, user=current_user,
                   reason=None if stage.kind == 'lost' else reason,
                   fallout_reason=reason if stage.kind == 'lost' else None)
    db.session.commit()
    return jsonify({'success': True, 'stage': stage.name, 'status': lead.status})


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
    if task is not None and (task.lead_id != lead.id or task.status != 'open'):
        task = None
    if task is not None and via == 'whatsapp' and task.channel == 'whatsapp':
        # a step: its approved template, free text inside the 24 hours, or the agent's WhatsApp
        if not lead.person.phone:
            return jsonify({'error': 'This lead has no phone number to message.'}), 400
        return jsonify({'success': True, **crm.send_step(lead, task, user=current_user, text=text or None)})
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
    result = crm.send_whatsapp(lead, text[:4000], user=current_user,
                               code=(task.code if task else data.get('code')), task=task)
    return jsonify({'success': True, **result})


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
    streak = crm.log_call(lead, outcome, note=(data.get('note') or '').strip()[:1000] or None,
                          user=current_user, task=task)
    return jsonify({'success': True, 'no_answers': streak,
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
    if 'owner_id' in data:
        uid = int(data['owner_id'] or 0)
        if uid and uid not in {u.id for u in _staff()}:
            return jsonify({'error': 'That person cannot own leads.'}), 400
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
    if 'departure_date' in data:
        raw = (data['departure_date'] or '').strip()
        try:
            lead.departure_date = datetime.strptime(raw, '%Y-%m-%d').date() if raw else None
        except ValueError:
            return jsonify({'error': 'Use a real date.'}), 400
    if 'name' in data and (data['name'] or '').strip():
        lead.person.name = data['name'].strip()[:120]
    if 'email' in data:
        e = (data['email'] or '').strip().lower()
        if e and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', e):
            return jsonify({'error': 'That e-mail address does not look right.'}), 400
        lead.person.email = e or None
    if (data.get('phone') or '').strip():
        e164 = crm.normalise_phone(data['phone'], data.get('phone_cc'))
        if not e164:
            return jsonify({'error': 'That phone number does not look right -- start it with + and the country code.'}), 400
        other = CrmPerson.query.filter(CrmPerson.phone == e164, CrmPerson.id != lead.person_id).first()
        if other:
            return jsonify({'error': 'That number belongs to another lead already.'}), 400
        lead.person.phone = e164
    for kind in ('instagram', 'facebook'):
        if (data.get(kind) or '').strip():
            v = crm.clean_identity(kind, data[kind])
            if not v:
                return jsonify({'error': 'That %s handle does not look right.' % kind.capitalize()}), 400
            if not lead.person.identity(kind) and not CrmIdentity.query.filter_by(kind=kind, value=v).first():
                lead.person.identities.append(CrmIdentity(kind=kind, value=v))
    db.session.commit()
    return jsonify({'success': True})


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

@crm_bp.route('/add', methods=['GET', 'POST'])
@cs_required
def add():
    crm.ensure_defaults()
    manual = (CrmSource.query.filter(CrmSource.kind.in_(['manual', 'chat']), CrmSource.status != 'unrouted')
              .order_by(CrmSource.name).all())
    if request.method == 'POST':
        f = request.form
        src = CrmSource.query.filter_by(key=f.get('source')).first()
        product = f.get('product') if f.get('product') in CRM_PRODUCTS else None
        dep = None
        if f.get('departure_date'):
            try:
                dep = datetime.strptime(f['departure_date'], '%Y-%m-%d').date()
            except ValueError:
                dep = None
        errors = []
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
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('cs/crm/add.html', sources=manual, form=f, **_common())
        # a lead for a known product starts in that product's pipeline, whatever the source's default
        start = None
        if product and product != 'GEN' and (src.pipeline is None or src.pipeline.key == 'general'):
            pipe = crm.pipeline_for_product(product)
            start = pipe.first_stage if pipe else None
        mine = f.get('owner') == 'me'
        lead = crm.capture(src.key, name=f.get('name'), phone=e164, email=f.get('email'), identities=idents,
                           product=product, message=(f.get('note') or '').strip() or None,
                           departure_date=dep, utm={}, channel='chat' if src.kind == 'chat' else 'note',
                           created_by_id=current_user.id, start_stage=start, notify=not mine)
        if lead is None:
            flash('Could not add that lead.', 'danger')
            return redirect(crm_url('add'))
        # whoever added it takes it, unless they chose to share it out
        if mine:
            lead.owner_id = current_user.id
            for t in lead.tasks:
                if t.status == 'open':
                    t.owner_id = current_user.id
            db.session.commit()
        flash('Lead added.', 'success')
        return redirect(crm_url('lead', lead_id=lead.id))
    q = (request.args.get('q') or '').strip()
    found = crm.search_records(q) if request.args.get('from') == 'existing' else []
    return render_template('cs/crm/add.html', sources=manual, form={}, q=q, found=found,
                           mode='existing' if request.args.get('from') == 'existing' else 'new', **_common())


@crm_bp.route('/add/record', methods=['POST'])
@cs_required
def add_from_record():
    """Make a lead of something the site already has: from "Add a lead -> From existing data",
    or the "Add to Sales CRM" button beside a quote, a booking, a message or a post."""
    kind, rid = request.form.get('kind'), request.form.get('id', type=int)
    if kind not in crm.RECORD_KINDS or not rid:
        abort(400)
    lead, created = crm.lead_from_record(kind, rid, user=current_user)
    if lead is None:
        flash('That record has no phone number or e-mail to follow up, so it cannot become a lead.', 'danger')
        return redirect(request.referrer or crm_url('add', **{'from': 'existing'}))
    if created and request.form.get('mine') != '0':
        lead.owner_id = current_user.id
        for t in lead.tasks:
            if t.status == 'open':
                t.owner_id = current_user.id
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
    flash('%s was taken out of the Sales CRM.' % name, 'success')
    return jsonify({'success': True, 'next': crm_url('board', owner='all')})


# ============================================================================================ insights

@crm_bp.route('/insights')
@cs_required
@admin_only
def insights():
    days = request.args.get('days', type=int) or 30
    days = days if days in (7, 30, 90) else 30
    staff = _staff()
    who = request.args.get('who', type=int)
    person = next((u for u in staff if u.id == who), None)
    today = (datetime.utcnow() + crm.IST).date()
    first = today - timedelta(days=days - 1)
    day_list, groups = crm_kpi.table(first, today, person.id if person else None)
    _, before = crm_kpi.table(first - timedelta(days=days), first - timedelta(days=1), person.id if person else None)
    now_tot = {k: t for _, rows in groups for k, _, _, _, t in rows}
    old_tot = {k: t for _, rows in before for k, _, _, _, t in rows}
    series = {k: v for _, rows in groups for k, _, _, v, _ in rows}
    totals, _ = crm_reports.kpis(datetime.utcnow() - timedelta(days=days))
    log_day = today
    if request.args.get('log_day'):
        try:
            log_day = min(datetime.strptime(request.args['log_day'], '%Y-%m-%d').date(), today)
        except ValueError:
            pass
    return render_template('cs/crm/insights.html', data=crm.insights(days), days=days, staff=staff,
                           person=person, day_list=day_list, groups=groups, now_tot=now_tot,
                           old_tot=old_tot, series=series, totals=totals, today=today,
                           overdue=crm_reports.overdue_by_owner(), METRICS=crm_reports.METRICS,
                           MANUAL=[(k, crm_kpi.METRICS[k][0]) for k in crm_kpi.MANUAL],
                           log_day=log_day, my_log=crm_kpi.entries(log_day, current_user.id),
                           **_common())


@crm_bp.route('/insights/log', methods=['POST'])
@cs_required
def log_work():
    """Log today's work: the few numbers the CRM cannot count by itself."""
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
    if request.form.get('back') == 'today' or not current_user.is_admin:
        return redirect(crm_url('today') + '#finish')
    return redirect(crm_url('insights', days=request.form.get('days') or 30, log_day=day.isoformat()) + '#log')


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
    return redirect(crm_url('process'))


# ============================================================================================ lead extras

@crm_bp.route('/lead/<int:lead_id>/event', methods=['POST'])
@cs_required
def event(lead_id):
    """Quote sent / Payment link sent: logged under Q / PLS, and the lead moves forward."""
    lead = _lead_or_404(lead_id)
    code = (_json().get('code') or '').upper()
    if code not in crm.EVENTS:
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
    resp = make_response(buf.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename=sales-numbers-%dd.csv' % days
    return resp


# ============================================================================================ setup

@crm_bp.route('/setup')
@cs_required
@admin_only
def setup():
    crm.ensure_defaults()
    tab = request.args.get('tab') or 'sources'
    pipelines = CrmPipeline.query.order_by(CrmPipeline.id).all()
    ctx = {'tab': tab, 'pipelines': pipelines, 'staff': _staff(),
           'STATUSES': CRM_SOURCE_STATUSES, 'STAGE_KINDS': CRM_STAGE_KINDS, 'AUTO_KINDS': CRM_AUTO_KINDS}
    if tab == 'sources':
        sources = CrmSource.query.all()
        order = {'unrouted': 0, 'live': 1, 'paused': 2}
        sources.sort(key=lambda s: (order.get(s.status, 3), s.name.lower()))
        edit = request.args.get('edit')
        ctx['sources'] = sources
        ctx['edit'] = (CrmSource() if edit == 'new' else
                       db.session.get(CrmSource, int(edit)) if edit and edit.isdigit() else None)
        ctx['is_new'] = edit == 'new'
    elif tab in ('pipelines', 'messages'):
        key = request.args.get('p')
        ctx['pipe'] = next((p for p in pipelines if p.key == key), pipelines[0] if pipelines else None)
        ctx['lead_counts'] = dict(db.session.query(CrmLead.stage_id, func.count(CrmLead.id))
                                  .group_by(CrmLead.stage_id).all())
    elif tab == 'answers':
        ctx['answers'] = CrmAnswer.query.order_by(CrmAnswer.product, CrmAnswer.title).all()
        edit = request.args.get('edit')
        ctx['edit'] = (CrmAnswer() if edit == 'new' else
                       db.session.get(CrmAnswer, int(edit)) if edit and edit.isdigit() else None)
    elif tab == 'connect':
        ctx['intake_url'] = _public_url('crm_public.intake')
        ctx['webhook_url'] = _public_url('crm_public.wacrm_webhook')
        ctx['meta_url'] = _public_url('crm_public.meta_webhook')
        ctx['snippet_url'] = url_for('static', filename='js/lead-capture.js', _external=True)
        ctx['wa_secret'] = bool(wacrm.webhook_secret())
        ctx['wa_mode'] = crm.crm_settings()['whatsapp_mode']
        ctx['WA_MODES'] = crm.WA_MODES
        ctx['wa_hook'] = (crm.crm_settings_raw().get('wacrm_webhook') or {})
        ctx['meta_ready'] = meta.enabled()
        ctx['meta_verify'] = bool(meta.verify_token())
    elif tab == 'import':
        ctx['preview'] = None
    elif tab == 'templates':
        from app.services import wa_templates
        ctx['templates'] = wa_templates.candidates()
        ctx['tpl_status'] = wa_templates.statuses(force=True)
        ctx['tpl_error'] = wa_templates.error()
    if tab == 'messages':
        from app.services import wa_templates
        ctx['tpl_status'] = wa_templates.statuses()
    return render_template('cs/crm/setup.html', **ctx, **_common())


@crm_bp.route('/setup/templates/<action>', methods=['GET', 'POST'])
@cs_required
@admin_only
def setup_templates(action):
    """WhatsApp templates for the messages: download the list, put the missing ones into the
    WhatsApp CRM as drafts (a person then submits each to Meta there), or move the ready answers
    into its quick replies, where agents pick them while they reply."""
    from app.services import wa_templates, wacrm_team
    if action == 'csv':
        resp = make_response(wa_templates.csv_text())
        resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
        resp.headers['Content-Disposition'] = 'attachment; filename=whatsapp-templates.csv'
        return resp
    if request.method != 'POST':
        abort(405)
    try:
        if action == 'drafts':
            out = wa_templates.push_drafts()
            flash('%d template(s) added to WhatsApp as drafts%s. Open WhatsApp -> Templates to submit them to Meta.'
                  % (out['created'], ('; %d left out (see the list)' % len(out['skipped'])) if out['skipped'] else ''),
                  'success')
        elif action == 'quick-replies':
            out = wa_templates.push_quick_replies()
            flash('Quick replies in WhatsApp: %d added, %d updated.' % (out['created'], out['updated']), 'success')
        else:
            abort(404)
    except wacrm_team.TeamError as exc:
        flash('The WhatsApp CRM said: %s' % exc, 'danger')
    return redirect(crm_url('setup', tab='answers' if action == 'quick-replies' else 'templates'))


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
    name = (f.get('name') or '').strip()[:100]
    if not name:
        flash('Give the source a name people will recognise.', 'danger')
        return redirect(crm_url('setup', tab='sources', edit=sid or 'new'))
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
    src.product = f.get('product') if f.get('product') in CRM_PRODUCTS else 'GEN'
    pipe = CrmPipeline.query.filter_by(key=f.get('pipeline')).first()
    src.pipeline = pipe
    status = f.get('status') if f.get('status') in ('live', 'paused') else 'live'
    src.status = status if pipe else 'unrouted'
    staff_ids = {u.id for u in _staff()}
    src.team = [int(x) for x in f.getlist('team') if x.isdigit() and int(x) in staff_ids] or None
    src.crm_tags = [t.strip().lower()[:30] for t in (f.get('crm_tags') or '').split(',') if t.strip()][:8] or None
    src.pages = [p.strip()[:200] for p in (f.get('pages') or '').split(',') if p.strip()][:10] or None
    try:
        src.dedupe_days = max(0, min(365, int(f.get('dedupe_days') or 30)))
    except ValueError:
        src.dedupe_days = 30
    src.updated_by_id = current_user.id
    db.session.flush()
    # leads that waited while this source was unrouted start their pipeline now
    if pipe:
        waiting = CrmLead.query.filter(CrmLead.source_id == src.id, CrmLead.pipeline_id.is_(None),
                                       CrmLead.status == 'open').all()
        for lead in waiting:
            crm.set_pipeline(lead, pipe, user=current_user)
            if not lead.owner_id:
                owner = crm.assign_owner(src)
                lead.owner = owner
                for t in lead.tasks:
                    if t.status == 'open':
                        t.owner_id = lead.owner_id
    db.session.commit()
    flash('Saved "%s".' % src.name, 'success')
    return redirect(crm_url('setup', tab='sources'))


@crm_bp.route('/setup/pipeline', methods=['POST'])
@cs_required
@admin_only
def save_pipeline():
    f = request.form
    action = f.get('action')
    if action == 'new':
        name = (f.get('name') or '').strip()[:80]
        if not name:
            flash('Name the new pipeline.', 'danger')
            return redirect(crm_url('setup', tab='pipelines'))
        key = _slug(name)[:40]
        base, n = key, 2
        while CrmPipeline.query.filter_by(key=key).first():
            key = '%s-%d' % (base[:36], n)
            n += 1
        product = f.get('product') if f.get('product') in CRM_PRODUCTS else 'GEN'
        p = CrmPipeline(key=key, name=name, product=product,
                        fallout_reasons=['No response', 'Not interested', 'Duplicate'])
        for pos, (skey, sname, kind, on_reply) in enumerate((
                ('new', 'New', 'open', False), ('talking', 'In conversation', 'open', True),
                ('won', 'Won', 'won', False), ('lost', 'Lost', 'lost', False))):
            p.stages.append(CrmStage(key=skey, name=sname, kind=kind, on_reply=on_reply, position=pos))
        db.session.add(p)
        db.session.commit()
        flash('Pipeline "%s" created. Add its stages and messages.' % name, 'success')
        return redirect(crm_url('setup', tab='pipelines', p=key))

    pipe = CrmPipeline.query.filter_by(key=f.get('pipeline')).first_or_404()
    if action == 'reasons':
        pipe.fallout_reasons = [r.strip()[:80] for r in (f.get('reasons') or '').splitlines() if r.strip()][:20]
        pipe.name = (f.get('name') or pipe.name).strip()[:80] or pipe.name
        pipe.is_active = f.get('is_active') == 'on'
        db.session.commit()
        flash('Saved.', 'success')
        return redirect(crm_url('setup', tab='pipelines', p=pipe.key))
    if action == 'stage':
        sid = f.get('stage_id')
        st = db.session.get(CrmStage, int(sid)) if sid and sid.isdigit() else None
        op = f.get('op')
        if st is None or st.pipeline_id != pipe.id:
            if op == 'add':
                name = (f.get('name') or '').strip()[:60]
                if not name:
                    flash('Name the stage.', 'danger')
                    return redirect(crm_url('setup', tab='pipelines', p=pipe.key))
                key = _slug(name)[:40].replace('-', '_')
                base, n = key, 2
                while any(s.key == key for s in pipe.stages):
                    key = '%s_%d' % (base[:36], n)
                    n += 1
                kind = f.get('kind') if f.get('kind') in CRM_STAGE_KINDS else 'open'
                # a new open stage goes after the last open one, before the finish lines
                pos = max([s.position for s in pipe.stages if s.kind == 'open'] or [-1]) + 1
                for s in pipe.stages:
                    if s.position >= pos:
                        s.position += 1
                pipe.stages.append(CrmStage(key=key, name=name, kind=kind, position=pos if kind == 'open'
                                            else max([s.position for s in pipe.stages] or [0]) + 1))
                db.session.commit()
                flash('Stage added.', 'success')
            return redirect(crm_url('setup', tab='pipelines', p=pipe.key))
        if op == 'save':
            st.name = (f.get('name') or st.name).strip()[:60] or st.name
            st.kind = f.get('kind') if f.get('kind') in CRM_STAGE_KINDS else st.kind
            st.on_reply = f.get('on_reply') == 'on'
            if st.on_reply:
                for s in pipe.stages:
                    if s.id != st.id:
                        s.on_reply = False
            sla = (f.get('sla_hours') or '').strip()
            st.sla_hours = int(sla) if sla.isdigit() else None
            kind = f.get('auto_kind') if f.get('auto_kind') in CRM_AUTO_KINDS else None
            to = db.session.get(CrmStage, int(f.get('auto_to') or 0)) if (f.get('auto_to') or '').isdigit() else None
            days = (f.get('auto_days') or '').strip()
            if kind and to is not None and to.pipeline_id == pipe.id and to.id != st.id:
                st.auto_kind, st.auto_to, st.auto_days = kind, to, int(days) if days.isdigit() else 0
                st.auto_reason = (f.get('auto_reason') or '').strip()[:80] or None
            else:
                st.auto_kind = st.auto_to = st.auto_days = st.auto_reason = None
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
                return redirect(crm_url('setup', tab='pipelines', p=pipe.key))
            CrmStageChange.query.filter((CrmStageChange.to_stage_id == st.id) |
                                        (CrmStageChange.from_stage_id == st.id)).delete(synchronize_session=False)
            db.session.delete(st)
        db.session.commit()
        flash('Saved.', 'success')
        return redirect(crm_url('setup', tab='pipelines', p=pipe.key))
    abort(400)


@crm_bp.route('/setup/step', methods=['POST'])
@cs_required
@admin_only
def save_step():
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
        return redirect(crm_url('setup', tab='messages', p=stage.pipeline.key))
    if step is None:
        step = CrmPlaybookStep(stage=stage, position=max([s.position for s in stage.steps] or [-1]) + 1)
        db.session.add(step)
    step.code = (f.get('code') or '').strip()[:20] or 'STEP'
    step.title = (f.get('title') or '').strip()[:160] or step.code
    step.channel = f.get('channel') if f.get('channel') in ('whatsapp', 'call', 'email') else 'whatsapp'
    step.trigger = f.get('trigger') if f.get('trigger') in CRM_STEP_TRIGGERS else 'after_hours'
    unit = f.get('unit') or 'hours'
    try:
        val = max(0, int(f.get('value') or 0))
    except ValueError:
        val = 0
    step.trigger_value = val * 24 if (step.trigger == 'after_hours' and unit == 'days') else val
    step.auto = f.get('auto') == 'on' and step.channel == 'whatsapp'
    step.body = (f.get('body') or '').strip()[:4000] or None
    step.wa_template = (f.get('wa_template') or '').strip()[:80] or None
    db.session.commit()
    flash('Saved %s.' % step.code, 'success')
    return redirect(crm_url('setup', tab='messages', p=stage.pipeline.key))


@crm_bp.route('/setup/answer', methods=['POST'])
@cs_required
@admin_only
def save_answer():
    f = request.form
    aid = f.get('id')
    a = db.session.get(CrmAnswer, int(aid)) if aid and aid.isdigit() else None
    if f.get('op') == 'delete' and a:
        db.session.delete(a)
        db.session.commit()
        flash('Answer removed.', 'success')
        return redirect(crm_url('setup', tab='answers'))
    title = (f.get('title') or '').strip()[:160]
    body = (f.get('body') or '').strip()[:4000]
    if not title or not body:
        flash('Write the question and the answer.', 'danger')
        return redirect(crm_url('setup', tab='answers', edit=aid or 'new'))
    if a is None:
        a = CrmAnswer()
        db.session.add(a)
    a.title, a.body = title, body
    a.keywords = (f.get('keywords') or '').strip()[:400] or None
    a.product = f.get('product') if f.get('product') in CRM_PRODUCTS else 'GEN'
    db.session.commit()
    flash('Answer saved.', 'success')
    return redirect(crm_url('setup', tab='answers'))


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
    return render_template('cs/crm/checks.html', day=day, today=today, now_slot=now_slot,
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


@crm_bp.route('/setup/whatsapp', methods=['POST'])
@cs_required
@admin_only
def save_whatsapp():
    action = request.form.get('action')
    if action == 'mode':
        mode = request.form.get('mode')
        if mode not in crm.WA_MODES:
            abort(400)
        crm.save_settings(current_user, whatsapp_mode=mode)
        flash('WhatsApp CRM: %s.' % crm.WA_MODES[mode].split(' -- ')[0], 'success')
    elif action == 'test':
        try:
            me = wacrm.me()
            scopes = set((me.get('key') or {}).get('scopes') or [])
            missing = {'contacts:write', 'contacts:read', 'messages:send'} - scopes
            flash('Connected to the WhatsApp CRM account "%s".%s' % (
                (me.get('account') or {}).get('name') or '?',
                ' This key cannot: %s.' % ', '.join(sorted(missing)) if missing else ' Everything the CRM needs is allowed.'),
                'warning' if missing else 'success')
        except wacrm.WacrmError as exc:
            flash('Could not reach the WhatsApp CRM: %s' % exc, 'danger')
    elif action == 'webhook':
        url = _public_url('crm_public.wacrm_webhook')
        if not url.startswith('https://') or '127.0.0.1' in url or 'localhost' in url:
            flash('Do this on the live site: the WhatsApp CRM can only send replies to a public https '
                  'address, and this one is %s.' % url, 'danger')
            return redirect(crm_url('setup', tab='connect'))
        try:
            old = (crm.crm_settings_raw().get('wacrm_webhook') or {}).get('id')
            if old:
                try:
                    wacrm.delete_webhook(old)
                except wacrm.WacrmError:
                    pass
            hook = wacrm.register_webhook(url)
            crm.save_settings(current_user, wacrm_webhook={'id': hook.get('id'), 'secret': hook.get('secret'),
                                                           'url': url, 'at': datetime.utcnow().isoformat()})
            flash('Replies are connected: the WhatsApp CRM now tells us when somebody writes.', 'success')
        except wacrm.WacrmError as exc:
            flash('The WhatsApp CRM did not accept the webhook: %s' % exc, 'danger')
    elif action == 'channels':
        names = [n.strip()[:40] for n in (request.form.get('channels') or '').splitlines() if n.strip()][:30]
        if names:
            crm.save_settings(current_user, check_channels=names)
            flash('Inbox list saved.', 'success')
        return redirect(crm_url('checks'))
    return redirect(crm_url('setup', tab='connect'))


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
    got = sum(v for k, v in out.items() if k not in ('already', 'unreachable'))
    flash('Brought in %d past enquir%s%s.' % (got, 'y' if got == 1 else 'ies',
                                              ' (%d were already here)' % out['already'] if out.get('already') else ''),
          'success')
    return redirect(crm_url('setup', tab='import'))


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
        return redirect(crm_url('setup', tab='import'))
    token = secrets.token_hex(12)
    path = _import_path(token)
    f.save(path)
    try:
        rows, stats, kpi = crm_import.read_sheet(path)
    except Exception:          # noqa: BLE001 -- not a workbook, or not this one
        current_app.logger.exception('Sales sheet unreadable')
        flash('That file could not be read as an Excel workbook.', 'danger')
        return redirect(crm_url('setup', tab='import'))
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
    pipelines = CrmPipeline.query.order_by(CrmPipeline.id).all()
    return render_template('cs/crm/setup.html', tab='import', preview=preview, pipelines=pipelines,
                           staff=_staff(), STATUSES=CRM_SOURCE_STATUSES, STAGE_KINDS=CRM_STAGE_KINDS,
                           **_common())


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
        return redirect(crm_url('setup', tab='import'))
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
    got = sum(v for k, v in out.items() if k not in ('already', 'unreachable') and not k.startswith('KPI'))
    flash('Imported %d lead%s from the sales sheet%s.' % (got, '' if got == 1 else 's',
                                                         ' (%d were already here)' % out['already'] if out.get('already') else ''),
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
                              details=fields, utm=utm, consent=bool(data.get('consent')))
    if lead is None:
        return _cors(make_response(jsonify({'success': False,
                                            'error': 'Sorry, that did not go through. Please try again.'}), 500))
    return _cors(make_response(jsonify({'success': True}), 201))


@crm_public_bp.route('/api/crm/wacrm-webhook', methods=['POST'])
@csrf.exempt
def wacrm_webhook():
    """Replies from the WhatsApp CRM. Signed by it; anything unsigned is refused."""
    raw = request.get_data()
    if not wacrm.verify_signature(request.headers.get('X-Wacrm-Signature', ''), raw):
        return jsonify({'error': 'Bad signature.'}), 401
    try:
        body = json.loads(raw.decode('utf-8') or '{}')
    except ValueError:
        return jsonify({'error': 'Not JSON.'}), 400
    event, data = body.get('event'), body.get('data') or {}
    if event == 'message.received':
        wamid = data.get('whatsapp_message_id')
        if wamid and CrmTouchpoint.query.filter_by(external_id=wamid).first():
            return jsonify({'ok': True, 'duplicate': True})
        person = (CrmPerson.query.filter_by(wacrm_contact_id=str(data.get('contact_id'))).first()
                  if data.get('contact_id') else None)
        if person is None and data.get('contact_id'):
            try:
                c = wacrm.get_contact(data['contact_id']) or {}
            except wacrm.WacrmError:
                c = {}
            phone = c.get('phone')
            if phone and not str(phone).startswith('+'):
                phone = '+' + str(phone)
            person = crm.find_person(crm.normalise_phone(phone) if phone else None, c.get('email'))
            if person is None:
                key = current_app.config.get('WACRM_SOURCE_KEY') or 'wa-india'
                lead = crm.capture(key, name=c.get('name'), phone=phone, email=c.get('email'),
                                   message=data.get('text') or '[%s]' % (data.get('content_type') or 'message'),
                                   channel='whatsapp', utm={}, external_id=wamid,
                                   # a WhatsApp user id with no number still reaches them through the CRM
                                   identities=[('wacrm', str(data['contact_id']))])
                if lead:
                    lead.person.wacrm_contact_id = str(data['contact_id'])
                    if data.get('conversation_id'):
                        lead.person.wacrm_conversation_id = str(data['conversation_id'])
                    db.session.commit()
                return jsonify({'ok': True, 'created': bool(lead)})
            person.wacrm_contact_id = str(data['contact_id'])
        if person is None:
            return jsonify({'ok': True, 'ignored': True})
        if data.get('conversation_id'):
            person.wacrm_conversation_id = str(data['conversation_id'])
        lead = next((l for l in person.leads if l.status == 'open'), None) or (person.leads[0] if person.leads else None)
        if lead is None:
            return jsonify({'ok': True, 'ignored': True})
        crm.record_reply(lead, data.get('text') or '[%s]' % (data.get('content_type') or 'message'),
                         channel='whatsapp', external_id=wamid)
        db.session.commit()
        return jsonify({'ok': True})
    if event == 'message.sent':
        return _wacrm_sent(data)
    if event == 'conversation.assigned':
        return _wacrm_assigned(data)
    if event == 'message.status_updated':
        wamid = data.get('whatsapp_message_id')
        tp = CrmTouchpoint.query.filter_by(external_id=wamid).first() if wamid else None
        status = str(data.get('status') or '')[:12]
        if tp and status and tp.status != status:
            # deliveries can repeat and arrive out of order: never step back from read / failed
            order = {'sending': 0, 'opened': 0, 'sent': 1, 'delivered': 2, 'read': 3, 'failed': 4}
            if order.get(status, 0) >= order.get(tp.status or '', 0):
                tp.status = status
                if status == 'failed' and tp.agent_id and tp.lead:
                    from app.services import notify
                    notify.push(tp.agent_id, 'crm_failed',
                                title='WhatsApp message not delivered: %s' % tp.lead.person.display_name,
                                body='Usually their last message is over 24 hours old. Send an approved '
                                     'template, call, or use "Send on WhatsApp" from your phone.',
                                link=crm._lead_link(tp.lead))
                db.session.commit()
    return jsonify({'ok': True})


def _wacrm_lead(data):
    """The open lead (else the latest) of the person a WhatsApp CRM event is about, or None."""
    person = (CrmPerson.query.filter_by(wacrm_contact_id=str(data.get('contact_id'))).first()
              if data.get('contact_id') else None)
    if person is None and data.get('contact_phone'):
        digits = ''.join(ch for ch in str(data['contact_phone']) if ch.isdigit())
        person = crm.find_person(crm.normalise_phone('+' + digits) if digits else None, None)
        if person is not None and data.get('contact_id'):
            person.wacrm_contact_id = str(data['contact_id'])
    if person is None:
        return None
    if data.get('conversation_id'):
        person.wacrm_conversation_id = str(data['conversation_id'])
    return next((l for l in person.leads if l.status == 'open'), None) or (person.leads[0] if person.leads else None)


def _staff_by_email(email):
    if not email:
        return None
    u = User.query.filter(db.func.lower(User.email) == str(email).lower(), User.is_active.is_(True)).first()
    return u if u is not None and (u.is_cs or u.is_admin) else None


def _wacrm_sent(data):
    """Somebody (or an automation, a flow, the AI) wrote to them from the WhatsApp CRM. It counts
    like a message sent from here: on the lead's history and in the numbers -- and when an agent
    wrote from the inbox, the WhatsApp step that was due is done."""
    wamid = data.get('whatsapp_message_id')
    if wamid and CrmTouchpoint.query.filter_by(external_id=wamid).first():
        return jsonify({'ok': True, 'duplicate': True})
    lead = _wacrm_lead(data)
    if lead is None:
        db.session.commit()
        return jsonify({'ok': True, 'ignored': True})
    source = str(data.get('source') or 'inbox')
    agent = _staff_by_email(data.get('sent_by_email')) if source == 'inbox' else None
    text = data.get('text') or ('[template %s]' % data['template_name'] if data.get('template_name')
                                else '[%s]' % (data.get('content_type') or 'message'))
    task = lead.open_task
    code = crm.ready_message_code(lead, data.get('text'), agent) if source == 'inbox' else None
    if code is None and source == 'inbox' and task is not None and task.channel == 'whatsapp' \
            and task.due_at <= datetime.utcnow() + timedelta(hours=12):
        code = task.code
        crm.complete_task(task, user=agent, note='Sent from the WhatsApp inbox')
    crm.log_touch(lead, 'whatsapp', 'out', body=text, code=code, user=agent, status='sent', external_id=wamid)
    if source != 'inbox':
        tp = CrmTouchpoint.query.filter_by(external_id=wamid).first() if wamid else None
        if tp is not None:
            tp.body = '%s (%s)' % (tp.body, {'automation': 'automation', 'flow': 'chatbot flow', 'ai': 'AI reply',
                                             'broadcast': 'broadcast'}.get(source, source))
    db.session.commit()
    return jsonify({'ok': True})


def _wacrm_assigned(data):
    """The conversation was given to somebody in the WhatsApp CRM: they look after the lead now.
    A change the portal made itself (origin "portal") is only the echo of ours."""
    if data.get('origin') == 'portal':
        return jsonify({'ok': True, 'echo': True})
    lead = _wacrm_lead(data)
    user = _staff_by_email(data.get('assignee_email'))
    if lead is None or user is None or lead.owner_id == user.id:
        db.session.commit()
        return jsonify({'ok': True, 'ignored': True})
    lead.owner_id = user.id
    for t in lead.tasks:
        if t.status == 'open':
            t.owner_id = user.id
    db.session.commit()
    return jsonify({'ok': True, 'owner': user.email})


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
