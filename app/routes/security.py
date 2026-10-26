"""Team › Security (2026-10-26): the sign-in rules, the staff and their two-step sign-in, every open session, and the
audit log -- who signed in, downloaded, deleted or changed the set-up, and when. The rules themselves are applied by
services/signin.py on every request."""
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_

from app import db
from app.models import ActivityEvent, User, UserSession, WorkspaceMember
from app.routes.workspace import staff_page
from app.services import signin

security_bp = Blueprint('security', __name__, url_prefix='/admin/security')

TABS = (('rules', 'Sign-in rules'), ('people', 'Staff'), ('sessions', 'Open sessions'), ('log', 'Audit log'))
PER_PAGE = 100
DAYS = (1, 7, 30, 90)

SIGNIN = ('signin', 'signin_failed', 'signout', 'session_ended', 'signed_out_elsewhere', 'signed_out_everywhere',
          'two_step_on', 'two_step_off', 'two_step_ok', 'two_step_failed', 'two_step_codes', 'two_step_reset',
          'password_changed', 'password_reset', 'user_reset_link_sent')
ACCESS = ('user_roles_changed', 'user_created_by_admin', 'security_rules', 'workspace_created', 'workspace_member_added',
          'workspace_member_removed', 'workspace_member_saved', 'workspace_role_saved', 'workspace_role_deleted',
          'workspace_team_saved', 'workspace_team_deleted', 'workspace_saved', 'workspace_menu_saved',
          'workspace_menu_reset')
DATA = ('crm_export', 'scrape_exported', 'crm_lead_removed', 'crm_lead_purged', 'crm_lead_restored', 'crm_person_erased',
        'crm_people_merged', 'crm_csv_import', 'contact_viewed', 'contact_values_viewed', 'attachment_deleted',
        'notifications_bulk_deleted')
SETUP = ('integration_saved', 'crm_whatsapp_mode', 'crm_pipeline_created', 'crm_pipeline_saved', 'crm_pipeline_active',
         'crm_pipeline_tag_changed', 'crm_source_saved', 'crm_source_moved', 'crm_rule_saved', 'crm_rule_deleted',
         'crm_rule_switched', 'crm_targets_saved', 'crm_ai_switched', 'crm_scoring_switched', 'crm_email_sender_saved',
         'crm_rates_saved', 'crm_product_saved', 'crm_inboxes_saved', 'options_changed', 'options_reset',
         'theme_saved', 'theme_activated', 'theme_deleted', 'notification_switches_changed', 'message_template_changed',
         'message_snippets_changed', 'landing_settings_changed', 'help_center_saved', 'insurance_page_saved',
         'sahayak_services_saved', 'translations_changed')
KINDS = (('important', 'Everything important', SIGNIN + ACCESS + DATA + SETUP), ('signin', 'Sign-ins', SIGNIN),
         ('access', 'People, roles & rules', ACCESS), ('data', 'Downloads & deletes', DATA),
         ('setup', 'Set-up changes', SETUP), ('all', 'Everything', None))
WORDS = {
    'signin': 'Signed in', 'signin_failed': 'Sign-in failed', 'signout': 'Signed out',
    'session_ended': 'Ended a session', 'signed_out_elsewhere': 'Signed out their other browsers',
    'signed_out_everywhere': 'Signed somebody out everywhere', 'two_step_on': 'Turned two-step sign-in on',
    'two_step_off': 'Turned two-step sign-in off', 'two_step_ok': 'Passed two-step sign-in',
    'two_step_failed': 'Typed a wrong two-step code', 'two_step_codes': 'Made new backup codes',
    'two_step_reset': "Turned off somebody's two-step sign-in", 'password_changed': 'Changed their password',
    'password_reset': 'Reset their password by e-mail', 'user_reset_link_sent': 'Sent a password link',
    'user_roles_changed': "Changed somebody's roles", 'user_created_by_admin': 'Made an account',
    'security_rules': 'Changed the sign-in rules', 'crm_export': 'Downloaded data', 'scrape_exported': 'Downloaded scraper data',
    'crm_lead_removed': 'Removed a lead', 'crm_lead_purged': 'Deleted leads for good', 'crm_lead_restored': 'Put a lead back',
    'crm_person_erased': 'Erased a person', 'crm_people_merged': 'Merged two people', 'crm_csv_import': 'Imported a list',
    'contact_viewed': 'Opened contact details', 'contact_values_viewed': 'Opened contact details',
    'integration_saved': 'Changed an integration', 'crm_whatsapp_mode': 'Changed what the CRM does with WhatsApp',
}
SKIP_META = {'ip', 'device'}


def _detail(ev):
    m = ev.meta or {}
    bits = []
    if ev.event == 'signin':
        bits = [m.get('how'), m.get('device'), m.get('ip')]
    elif ev.event == 'signin_failed':
        bits = ['for %s' % m.get('email') if m.get('email') else None, m.get('why'), m.get('ip')]
    else:
        for k, v in m.items():
            if k in SKIP_META or v in (None, '', [], {}):
                continue
            if isinstance(v, (list, dict)):
                v = ', '.join(map(str, v)) if isinstance(v, list) else ', '.join('%s %s' % kv for kv in v.items())
            bits.append('%s: %s' % (k.replace('_', ' '), str(v)[:80]))
    return ' · '.join(b for b in bits if b)


def _staff():
    ids = {m.user_id for m in WorkspaceMember.query.all()}
    q = User.query.filter(or_(User.is_admin.is_(True), User.role.in_(('cs', 'admin')), User.id.in_(ids or [-1])))
    return q.order_by(User.first_name, User.username).all()


def _can_touch(person):
    """A Super admin's account is changed by Super admins only (as on Users)."""
    return not person.is_super or current_user.is_super


@security_bp.route('/')
@staff_page
def index():
    tab = request.args.get('tab') if request.args.get('tab') in dict(TABS) else 'rules'
    ctx = dict(tab=tab, TABS=TABS, rules=signin.rules(), TWO_STEP_RULES=signin.TWO_STEP_RULES,
               IDLE_CHOICES=signin.IDLE_CHOICES, REASONS=signin.REASONS)
    staff = _staff()
    ctx['staff_total'] = len(staff)
    ctx['staff_on'] = sum(1 for u in staff if u.two_step_on)
    if tab == 'people':
        open_by = {}
        for s in UserSession.query.filter(UserSession.ended_at.is_(None)).all():
            open_by.setdefault(s.user_id, []).append(s)
        ctx.update(staff=staff, open_by=open_by, required=signin.required_for)
    elif tab == 'sessions':
        ids = [u.id for u in staff]
        ctx['sessions'] = (UserSession.query.filter(UserSession.ended_at.is_(None), UserSession.user_id.in_(ids or [-1]))
                           .order_by(UserSession.last_seen_at.desc()).limit(300).all())
        ctx['here'] = signin.current_row()
    elif tab == 'log':
        kind = request.args.get('kind') if request.args.get('kind') in {k for k, _, _ in KINDS} else 'important'
        days = int(request.args.get('days')) if (request.args.get('days') or '').isdigit() and \
            int(request.args.get('days')) in DAYS else 30
        who = request.args.get('who') if (request.args.get('who') or '').isdigit() else None
        page = max(int(request.args.get('page')), 1) if (request.args.get('page') or '').isdigit() else 1
        q = ActivityEvent.query.filter(ActivityEvent.created_at >= datetime.utcnow() - timedelta(days=days))
        events = dict((k, e) for k, _, e in KINDS)[kind]
        if events:
            q = q.filter(ActivityEvent.event.in_(events))
        if who:
            q = q.filter(ActivityEvent.actor_id == int(who))
        total = q.count()
        rows = q.order_by(ActivityEvent.created_at.desc()).offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()
        actors = {u.id: u for u in User.query.filter(User.id.in_({r.actor_id for r in rows if r.actor_id} or {-1}))}

        def who_name(ev):
            u = actors.get(ev.actor_id)
            return u.full_name if u is not None else ('Somebody' if ev.event == 'signin_failed' else 'The system')
        ctx.update(rows=rows, total=total, page=page, pages=max(1, -(-total // PER_PAGE)), kind=kind, days=days,
                   who=who, KINDS=KINDS, DAYS=DAYS, staff=staff, WORDS=WORDS, detail=_detail, who_name=who_name)
    return render_template('workspace/security.html', **ctx)


@security_bp.route('/rules', methods=['POST'])
@staff_page
def save_rules():
    hours = request.form.get('idle_hours')
    now = signin.save_rules(current_user, two_step=request.form.get('two_step'),
                            idle_hours=int(hours) if (hours or '').isdigit() else None)
    flash('Saved. Two-step sign-in: %s. Staff are signed out after %d hours without activity.'
          % (signin.TWO_STEP_RULES[now['two_step']].lower(), now['idle_hours']), 'success')
    return redirect(url_for('security.index', tab='rules'))


@security_bp.route('/sessions/<int:sid>/end', methods=['POST'])
@staff_page
def end_session(sid):
    row = db.session.get(UserSession, sid)
    if row is None or row.ended_at is not None:
        abort(404)
    if not _can_touch(row.user):
        flash("Only a Super admin can end a Super admin's session.", 'danger')
    else:
        signin.end(row, 'ended_by_admin', by=current_user._get_current_object())
        db.session.commit()
        flash('Ended: %s, %s.' % (row.user.full_name, row.device), 'success')
    return redirect(request.form.get('back') or url_for('security.index', tab='sessions'))


@security_bp.route('/people/<int:uid>/sign-out', methods=['POST'])
@staff_page
def sign_out_person(uid):
    person = db.session.get(User, uid) or abort(404)
    me = current_user._get_current_object()
    if not _can_touch(person):
        flash("Only a Super admin can sign a Super admin out.", 'danger')
    else:
        signin.sign_out_everywhere(person, 'everywhere', by=me, keep_this=person.id == me.id)
        ActivityEvent.log('signed_out_everywhere', actor=me, user_id=person.id)
        db.session.commit()
        flash('%s is signed out everywhere: every browser and "remember me" cookie.' % person.full_name, 'success')
    return redirect(url_for('security.index', tab='people'))


@security_bp.route('/people/<int:uid>/two-step-off', methods=['POST'])
@staff_page
def two_step_off(uid):
    """For somebody who lost their phone and their backup codes: they sign in with their password and set it up
    again (at once, when the rules require it)."""
    person = db.session.get(User, uid) or abort(404)
    me = current_user._get_current_object()
    if person.id == me.id:
        flash('Turn your own two-step sign-in off under Sign-in & security.', 'warning')
    elif not _can_touch(person):
        flash("Only a Super admin can change a Super admin's two-step sign-in.", 'danger')
    elif person.two_step_on:
        person.totp_secret = person.totp_on_at = person.backup_codes = None
        ActivityEvent.log('two_step_reset', actor=me, user_id=person.id)
        signin.sign_out_everywhere(person, 'two_step', by=me, keep_this=False)
        flash("%s's two-step sign-in is off and they are signed out. They set it up again after their password."
              % person.full_name, 'success')
    return redirect(url_for('security.index', tab='people'))
