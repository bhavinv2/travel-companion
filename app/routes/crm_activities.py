"""Tasks, the Calendar, and e-mail from the lead page (Sales CRM 2.0, run 3a).

The rules are on crm_bp (routes/crm.py), so they exist under /cs/crm and /admin/crm; the inbound-mail door is on
crm_public_bp. The logic is in services/crm_tasks.py and services/crm_email.py; this file reads the request and draws.
"""
from datetime import datetime, timedelta

from flask import abort, jsonify, render_template, request
from flask_login import current_user

from app import csrf, db
from app.models import CrmLead, CrmPerson, CrmTask
from app.routes.crm import _common, _json, _lead_or_404, crm_bp, crm_public_bp, crm_url
from app.routes.cs import cs_required
from app.services import crm, crm_email, crm_tasks

CAL_VIEWS = ('month', 'week')


def _person_or_404(person_id):
    from app.services import crm_access, crm_scope
    p = db.session.get(CrmPerson, person_id)
    if p is None or not crm_access.can_see_person(current_user, p) or not crm_scope.visible(p):
        abort(404)
    return p


def _task_json(t):
    return {'id': t.id, 'title': t.title, 'kind': t.kind, 'due': crm_tasks.input_value(t.due_at),
            'ends': crm_tasks.input_value(t.ends_at), 'location': t.location or '', 'notes': t.notes or '',
            'priority': t.priority or 'normal', 'owner_id': t.owner_id}


@crm_bp.app_template_global('TASK_STAFF')
def task_staff():
    return crm_tasks.staff()


@crm_bp.app_template_global('TASKS_FOR')
def tasks_for(lead=None, person=None):
    return crm_tasks.for_record(lead=lead, person=person)


@crm_bp.app_template_global('TASK_WHEN')
def task_when(task):
    """'Fri 23 Oct, 10:00' (or '10:00-11:30' for a meeting) in India time."""
    d = crm_tasks.from_utc(task.due_at)
    out = '%s %d %s, %s' % (d.strftime('%a'), d.day, d.strftime('%b'), d.strftime('%H:%M'))
    if task.ends_at:
        out += '-' + crm_tasks.from_utc(task.ends_at).strftime('%H:%M')
    return out


@crm_bp.app_template_global('TASK_INPUT')
def task_input(dt):
    return crm_tasks.input_value(dt)


@crm_bp.app_template_global('TASK_DEFAULT_DUE')
def task_default_due():
    return crm_tasks.input_value(crm_tasks.default_due())


@crm_bp.app_template_global('CAN_CHANGE_TASK')
def can_change_task(task):
    return crm_tasks.can_change(current_user, task)


# ============================================================================================ add, edit, delete

@crm_bp.route('/tasks/add', methods=['POST'])
@cs_required
def task_add():
    """+ Task on a lead page or a contact page: a to-do, a call or a meeting."""
    data = _json()
    lead = person = None
    if str(data.get('lead_id') or '').isdigit():
        lead = _lead_or_404(int(data['lead_id']))
    elif str(data.get('person_id') or '').isdigit():
        person = _person_or_404(int(data['person_id']))
    else:
        return jsonify({'error': 'Choose who it is about.'}), 400
    task, err = crm_tasks.create(current_user, data, lead=lead, person=person)
    if err:
        return jsonify({'error': err}), 400
    db.session.commit()
    return jsonify({'success': True, 'id': task.id})


@crm_bp.route('/tasks/<int:task_id>/edit', methods=['POST'])
@cs_required
def task_edit(task_id):
    from app.services import crm_scope
    task = db.session.get(CrmTask, task_id)
    if task is None or task.is_step or not crm_scope.visible(task):
        abort(404)
    ok, err = crm_tasks.update(current_user, task, _json())
    if not ok:
        return jsonify({'error': err}), 403 if err == crm_tasks.NOT_YOURS else 400
    db.session.commit()
    return jsonify({'success': True})


@crm_bp.route('/tasks/<int:task_id>/delete', methods=['POST'])
@cs_required
def task_delete(task_id):
    from app.services import crm_scope
    task = db.session.get(CrmTask, task_id)
    if task is None or task.is_step or not crm_scope.visible(task):
        abort(404)
    ok, err = crm_tasks.delete(current_user, task)
    if not ok:
        return jsonify({'error': err}), 403
    db.session.commit()
    return jsonify({'success': True})


# ============================================================================================ the Calendar

MONTH_CAP = 4             # items a month's day shows before "+ N more" (the week has them all)


@crm_bp.route('/calendar')
@cs_required
def calendar():
    """Calendar (Daily work, after Leads): month and week views, and a List of everything open."""
    today = (datetime.utcnow() + crm.IST).date()
    tab = 'list' if request.args.get('tab') == 'list' else 'calendar'
    who = request.args.get('who') or 'mine'
    ctx = dict(tab=tab, today=today, who_options=crm_tasks.who_options(current_user), kinds=crm_tasks.KINDS,
               priorities=crm_tasks.PRIORITIES, icons=crm_tasks.KIND_ICONS)
    if tab == 'list':
        kind = request.args.get('kind') if request.args.get('kind') in crm_tasks.KINDS else ''
        prio = request.args.get('priority') if request.args.get('priority') in crm_tasks.PRIORITIES else ''
        res = crm_tasks.open_list(current_user, who, kind or None, prio or None)
        ctx.update(res, kind=kind, prio=prio)
    else:
        view = request.args.get('view') if request.args.get('view') in CAL_VIEWS else 'month'
        day = crm_tasks.clamp_day(request.args.get('on'), today)
        if view == 'month':
            weeks = crm_tasks.month_grid(day)
            first, last = weeks[0][0], weeks[-1][-1]
            prev, nxt = crm_tasks.shift_month(day, -1), crm_tasks.shift_month(day, 1)
            title = day.strftime('%B %Y')
        else:
            weeks = [crm_tasks.week_days(day)]
            first, last = weeks[0][0], weeks[0][-1]
            prev, nxt = first - timedelta(days=7), first + timedelta(days=7)
            title = '%d %s - %d %s %d' % (first.day, first.strftime('%b'), last.day, last.strftime('%b'), last.year)
        used, _ = crm_tasks.owner_scope(current_user, who)
        items = crm_tasks.calendar_items(current_user, first, last, who)
        # a team's or everyone's week: a row per person, their name down the side
        lanes = crm_tasks.lanes(items, current_user) if view == 'week' and used != 'mine' else None
        ctx.update(view=view, day=day, weeks=weeks, items=items, prev=prev, next=nxt, cal_title=title,
                   who=used, days=[d for w in weeks for d in w], lanes=lanes, month_cap=MONTH_CAP)
    if tab == 'list':
        ctx.setdefault('who', who)
    return render_template('cs/crm/calendar.html', **ctx, **_common())


# ============================================================================================ e-mail

def _email_target(data):
    """(person, lead) the composer is for: a lead, or a person."""
    if str(data.get('lead_id') or '').isdigit():
        lead = _lead_or_404(int(data['lead_id']))
        return lead.person, lead
    if str(data.get('person_id') or '').isdigit():
        return _person_or_404(int(data['person_id'])), None
    abort(400)


@crm_bp.route('/email/compose')
@cs_required
def lead_email():
    """What the composer needs: the address, whether this server can send, the ready answers."""
    person, lead = _email_target(request.args)
    return jsonify(crm_email.composer(person, lead, current_user))


@crm_bp.route('/email/send', methods=['POST'])
@cs_required
def lead_email_send():
    """Send (a person pressed Send), or log an e-mail written in their own mail app (nothing is sent)."""
    data = _json()
    person, lead = _email_target(data)
    if data.get('own_app'):
        if data.get('log') is True:
            crm_email.log_own_app(current_user, person, lead, data.get('subject'), data.get('answer_id'))
            db.session.commit()
            return jsonify({'success': True, 'message': 'Logged on the timeline.'})
        return jsonify({'success': True, 'message': 'Nothing was logged.'})
    ok, message = crm_email.send(current_user, person, lead, data.get('subject'), data.get('body'),
                                 data.get('answer_id'))
    if not ok:
        db.session.rollback()
        return jsonify({'error': message, 'can_send': crm_email.can_send()}), 400
    db.session.commit()
    return jsonify({'success': True, 'message': message})


@crm_public_bp.route('/api/crm/email-inbound', methods=['POST'])
@csrf.exempt
def email_inbound():
    """SendGrid Inbound Parse: a customer's e-mail comes in. 404 while CRM_INBOUND_EMAIL_TOKEN is unset."""
    if not crm_email.inbound_token():
        abort(404)
    if not crm_email.token_ok(request.args.get('token')):
        return jsonify({'error': 'Bad token.'}), 403
    try:
        res = crm_email.receive(request.form)
    except Exception:          # noqa: BLE001 -- answered, logged; the sender's mail host must not retry forever
        db.session.rollback()
        from flask import current_app
        current_app.logger.exception('Inbound e-mail not stored')
        return jsonify({'ok': False}), 200
    return jsonify({'ok': True, **res})
