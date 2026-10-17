"""Messaging and its set-up: Quick replies (E10), Set-up -> WhatsApp connection (E21) and Automatic
messages -> What goes out by itself (E14).

The rules are on `crm_bp`, so they exist under /cs/crm and under /admin/crm. The logic is in services
(`wa_templates`, `crm_connection`, `crm`). This file only reads the request and draws.
"""
from datetime import datetime

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from app import db
from app.models import ActivityEvent, CrmAnswer, CrmPerson, CrmTask, CRM_STEP_KINDS
from app.routes import crm as crm_routes
from app.routes.crm import _common, admin_only, crm_bp, crm_url
from app.routes.cs import cs_required
from app.services import (access, crm, crm_connection, crm_people, crm_products, meta, wa_templates, wacrm,
                           wacrm_team)


def _ws():
    ws = access.current_workspace(current_user)
    if ws is None:
        ws = access.ensure_defaults()
    if ws is None:
        abort(404)
    return ws


# ============================================================================================ Quick replies

def _quick_context(form=None, error=None):
    """What Quick replies draws: the list (own replies, the Help & FAQ questions, the button replies WhatsApp
    keeps), the form when one is open, and the WhatsApp state."""
    from app.routes import messaging
    own = CrmAnswer.query.order_by(CrmAnswer.product, func.lower(CrmAnswer.title)).all()
    state = wa_templates.quick_state()
    return dict(own=own, help=wa_templates.help_rows([a.title for a in own]),
                works={a.id: wa_templates.works_in(a.body) for a in own}, state=state,
                conflicts={t.lower() for t in state['conflicts']},
                buttons_url=(messaging.frame_link('/settings?tab=quick-replies')
                             if access.can(current_user, 'wa_quick') or access.can(current_user, 'crm_quick') else None),
                GENERAL=crm_products.general_code(), FILLS=wa_templates.FILL_LABELS, STEP_KINDS=CRM_STEP_KINDS,
                form=form, error=error, can_push=access.can(current_user, 'crm_connection'),
                writes_on=crm.wa_writes_on(), wa_enabled=wacrm_team.enabled(),
                NEEDS_UPDATE=crm_people.NEEDS_UPDATE, QR_BUTTON_CONFLICT=wa_templates.QR_BUTTON_CONFLICT,
                QUICK_WAITING=wa_templates.QUICK_WAITING, WORKS_HELP=wa_templates.WORKS_HELP,
                WORKS_BUTTONS=wa_templates.WORKS_BUTTONS, **_common())


def _form_of(a):
    return {'id': a.id, 'title': a.title or '', 'keywords': a.keywords or '', 'product': a.product,
            'body': a.body or '', 'kind': crm.answer_kind(a), 'code': a.code, 'locked': a.code == 'SE'}


@crm_bp.route('/quick-replies')
@cs_required
def quick_replies():
    """Messaging -> Quick replies: the ready-made answers offered while chatting, edited here by whoever has the
    page (cs_required checks crm_quick). ?edit=<id> or ?edit=new opens one."""
    crm.ensure_defaults()
    edit, form = request.args.get('edit'), None
    if edit == 'new':
        form = {'id': None, 'title': '', 'keywords': '', 'product': crm_products.general_code(), 'body': '',
                'kind': '', 'code': None, 'locked': False}
    elif edit and edit.isdigit():
        a = db.session.get(CrmAnswer, int(edit))
        if a is None:
            abort(404)
        form = _form_of(a)
    return render_template('cs/crm/quick_replies.html', **_quick_context(form))


@crm_bp.route('/setup/answer', methods=['POST'])
@cs_required
def save_answer():
    """A quick reply saved or removed, by whoever has the Quick replies page (cs_required checks it). Both go to
    WhatsApp chats by themselves while the switch is on (wa_templates.quick_replies_changed)."""
    f = request.form
    aid = f.get('id')
    a = db.session.get(CrmAnswer, int(aid)) if aid and aid.isdigit() else None
    if f.get('op') == 'delete' and a:
        title = a.title
        db.session.delete(a)
        db.session.commit()
        ActivityEvent.log('crm_quick_reply_removed', actor=current_user, title=title)
        db.session.commit()
        wa_templates.quick_replies_changed()
        flash(wa_templates.QR_REMOVED + (wa_templates.QR_REMOVED_WA if crm.wa_writes_on() else ''), 'success')
        return redirect(crm_url('quick_replies'))
    title = (f.get('title') or '').strip()[:160]
    body = (f.get('body') or '').strip()[:4000]
    chosen = crm_products.by_code(f.get('product'))
    product = chosen.code if chosen is not None else crm_products.general_code()
    shown = {'id': a.id if a else None, 'title': title, 'keywords': (f.get('keywords') or '').strip()[:400],
             'product': product, 'body': body, 'kind': f.get('kind') if 'kind' in f else (crm.answer_kind(a) if a else ''),
             'code': a.code if a else None, 'locked': bool(a and a.code == 'SE')}
    if not title or not body:
        return render_template('cs/crm/quick_replies.html',
                               **_quick_context(shown, 'Write what the customer asks and the reply.'))
    clash = CrmAnswer.query.filter(func.lower(func.trim(CrmAnswer.title)) == title.lower(),
                                   CrmAnswer.id != (a.id if a else -1)).first()
    if clash is not None:
        return render_template('cs/crm/quick_replies.html', **_quick_context(
            shown, 'Another quick reply already asks this. Change the words, or edit that one.'))
    if a is None:
        a = CrmAnswer()
        db.session.add(a)
    a.title, a.body, a.keywords, a.product = title, body, shown['keywords'] or None, product
    if 'kind' in f and a.code != 'SE':
        db.session.flush()
        a.code = crm.answer_code(f.get('kind'), a.product, current=a.code, exclude_id=a.id)
    db.session.commit()
    wa_templates.quick_replies_changed()
    lo = wa_templates.lead_only(body)
    if lo:
        flash(wa_templates.QR_SAVED_LEAD % wa_templates.lead_only_reason(lo), 'success')
    elif crm.wa_writes_on():
        flash(wa_templates.QR_SAVED_WA, 'success')
    else:
        flash(wa_templates.QR_SAVED_OFF, 'success')
    return redirect(crm_url('quick_replies'))


@crm_bp.route('/quick-replies/push', methods=['POST'])
@cs_required
@admin_only
def quick_replies_push():
    """Push all the quick replies to WhatsApp chats now (admins), for one that is missing there."""
    if not crm.wa_writes_on():
        flash(crm.WA_WRITES_OFF, 'warning')
        return redirect(crm_url('quick_replies'))
    try:
        with wacrm.short_timeouts():
            out = wa_templates.push_quick_replies()
        said = 'Quick replies in WhatsApp: %d added, %d updated, %d removed.' % (out['created'], out['updated'],
                                                                                 out['removed'])
        if out['conflicts']:
            flash(said + ' ' + wa_templates.conflict_words(out['conflicts']), 'warning')
        else:
            flash(said, 'success')
    except wacrm_team.TeamError as exc:
        flash(wa_templates.QUICK_TOO_MANY if exc.code == 'rule_too_large' else 'WhatsApp said: %s' % exc, 'danger')
    ActivityEvent.log('crm_quick_push', actor=current_user)
    db.session.commit()
    return redirect(crm_url('quick_replies'))


@crm_bp.route('/quick-replies/import', methods=['POST'])
@cs_required
@admin_only
def quick_replies_import():
    """One-off (admins): WhatsApp's own text quick replies become quick replies here."""
    if not wacrm_team.enabled():
        flash(crm_people.WA_FEED_OFF, 'warning')
        return redirect(crm_url('quick_replies'))
    try:
        out = wa_templates.import_quick_replies()
    except wacrm_team.TeamError as exc:
        flash(crm_people.NEEDS_UPDATE if exc.status == 404 else 'WhatsApp said: %s' % exc,
              'warning' if exc.status == 404 else 'danger')
        return redirect(crm_url('quick_replies'))
    wa_templates.quick_replies_changed()           # nothing while writes are off
    n = out['added']
    said = 'Brought in %d text repl%s from WhatsApp.' % (n, 'y' if n == 1 else 'ies')
    if out['already']:
        said += ' %d were here already.' % out['already']
    said += (' They are kept in step from here now.' if crm.wa_writes_on()
             else ' They reach WhatsApp chats again once WhatsApp is connected.')
    flash(said, 'success')
    ActivityEvent.log('crm_quick_import', actor=current_user, added=n)
    db.session.commit()
    return redirect(crm_url('quick_replies'))


# ============================================================================================ WhatsApp connection

def _connection_context(**extra):
    """What the WhatsApp connection page shows: the switch and its words, the consent setting, what needs
    attention, and the addresses to give out. It makes no call to the WhatsApp CRM (checks() does, afterwards)."""
    ws = _ws()
    settings = crm.crm_settings()
    ctx = {'intake_url': crm_routes._public_url('crm_public.intake'),
           'webhook_url': crm_routes._public_url('crm_public.wacrm_webhook'),
           'meta_url': crm_routes._public_url('crm_public.meta_webhook'),
           'snippet_url': url_for('static', filename='js/lead-capture.js', _external=True),
           'wa_secret': bool(wacrm.webhook_secret()),
           # the saved choice, ticked on the page; _common()['wa_mode'] is what is in force (Off without keys)
           'wa_mode_saved': settings['whatsapp_mode'], 'WA_MODES': crm.WA_MODES, 'WA_MODE_SAYS': crm.WA_MODE_SAYS,
           'first_ok': settings['wa_first_needs_ok'], 'WA_FIRST_OK_LABEL': crm.WA_FIRST_OK_LABEL,
           'WA_FIRST_OK_SAYS': crm.WA_FIRST_OK_SAYS,
           'wa_hook': crm.crm_settings_raw().get('wacrm_webhook') or {},
           'meta_ready': meta.enabled(), 'meta_verify': bool(meta.verify_token()),
           'writes_on': crm.wa_writes_on(), 'wa_enabled': wacrm.enabled(), 'team_enabled': wacrm_team.enabled(),
           'linked': wacrm_team.linked(ws),
           'env': {'WACRM_URL': bool(wacrm.base_url()), 'WACRM_API_KEY': bool(wacrm.api_key()),
                   'WACRM_PORTAL_SECRET': bool(wacrm_team.secret()),
                   'WACRM_WEBHOOK_SECRET': bool(wacrm.webhook_secret())},
           'needs': crm_connection.needs_attention(), 'confirm': None}
    ctx.update(extra)
    return {**_common(), **ctx}


@crm_bp.route('/connection')
@cs_required
@admin_only
def connection():
    """Set-up -> WhatsApp connection (E21): the checks (loaded after the page draws), what the Sales CRM does with
    WhatsApp, the existing leads, and what needs attention. No call to the WhatsApp CRM here."""
    return render_template('cs/crm/connection.html', **_connection_context())


@crm_bp.route('/connection/checks')
@cs_required
@admin_only
def connection_checks():
    """The live checks, drawn as two pieces of html for the page's script."""
    c = crm_connection.checks(_ws())
    return jsonify({'cards': render_template('cs/crm/_connection_cards.html', c=c, **_common()),
                    'rules': render_template('cs/crm/_connection_rules.html', c=c, **_common())})


@crm_bp.route('/setup/whatsapp', methods=['POST'])
@cs_required
@admin_only
def save_whatsapp():
    action = request.form.get('action')
    if action == 'mode':
        mode = request.form.get('mode')
        if mode not in crm.WA_MODES:
            abort(400)
        before = crm.crm_settings()['whatsapp_mode']
        changes = {'whatsapp_mode': mode}
        if request.form.get('first_ok_sent'):
            changes['wa_first_needs_ok'] = bool(request.form.get('first_ok'))
        if mode == 'send' and before != 'send' and not request.form.get('confirm'):
            p = crm.auto_send_preview()
            if p['now'] or p['older']:          # say what would go first; nothing is saved yet
                return render_template('cs/crm/connection.html', **_connection_context(
                    confirm=dict(p, first_ok=changes.get('wa_first_needs_ok', crm.crm_settings()['wa_first_needs_ok']))))
        crm.save_settings(current_user, **changes)
        ActivityEvent.log('crm_whatsapp_mode', actor=current_user, mode=mode, before=before)
        db.session.commit()
        if mode in ('contacts', 'send'):
            crm.wa_tag_rule_changed()          # the WhatsApp CRM learns which tags are the Sales CRM's
            if before not in ('contacts', 'send'):
                wa_templates.quick_replies_changed()     # the quick replies follow once writes are on
        flash('Saved: %s.' % crm.WA_MODES[mode], 'success')
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
        url = crm_routes._public_url('crm_public.wacrm_webhook')
        if not url.startswith('https://') or '127.0.0.1' in url or 'localhost' in url:
            flash('Do this on the live site: the WhatsApp CRM can only send replies to a public https '
                  'address, and this one is %s.' % url, 'danger')
            return redirect(crm_url('connection'))
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
    elif action == 'webhook_on':
        # allowed in any mode: it writes no customer data, the same as Connect replies
        hook = crm._wa_webhook_saved()
        if not hook.get('id'):
            flash('Connect replies first.', 'warning')
        else:
            try:
                wacrm.switch_webhook_on(hook['id'])
                from app.services import settings
                state = dict(settings.get_setting(crm.WA_HEALTH_KEY) or {})
                state['problem'] = None            # the next incident rings the admins again
                settings.set_setting(crm.WA_HEALTH_KEY, state)
                flash('Replies are switched back on.', 'success')
            except wacrm.WacrmError as exc:
                flash('WhatsApp did not switch it on: %s' % exc, 'danger')
    elif action == 'backfill':
        if not crm.wa_writes_on():
            flash(crm.WA_WRITES_OFF, 'warning')
        else:
            n = crm.wa_backfill()
            ActivityEvent.log('crm_wa_backfill', actor=current_user, marked=n)
            db.session.commit()
            flash(crm.WA_BACKFILL_SAID % (n, 'person' if n == 1 else 'people') if n else crm.WA_BACKFILL_NONE,
                  'success' if n else 'info')
    elif action == 'channels':
        names = [n.strip()[:40] for n in (request.form.get('channels') or '').splitlines() if n.strip()][:30]
        if names:
            # each name keeps the source and tick-itself of a row of the same name, else what its name suggests
            have = {r['name'].lower(): r for r in crm.crm_settings()['check_rows']}
            crm.save_settings(current_user, check_channels=[
                have.get(n.lower()) or crm.check_rows([n])[0] for n in names])
            flash('Inbox list saved.', 'success')
        return redirect(crm_url('sources', tab='inboxes'))
    return redirect(crm_url('connection'))


@crm_bp.route('/connection/team/<action>', methods=['POST'])
@cs_required
@admin_only
def connection_team(action):
    """Link this workspace to the WhatsApp team, check it now, unlink it, take somebody the workspace does not have
    out of WhatsApp, or try one member again. (These used to be on the Workspace screen.)"""
    if action not in ('link', 'sync', 'unlink', 'remove-extra', 'retry'):
        abort(404)
    ws = _ws()
    try:
        if action == 'link':
            ok, failed = wacrm_team.link(ws)
            flash('Linked to WhatsApp. %d team member(s) in step%s.' % (ok, ', %d not yet' % failed if failed else ''),
                  'success' if not failed else 'warning')
        elif action == 'sync':
            ok, failed = wacrm_team.sync_all(ws)
            flash('Team sign-in checked: %d in step%s.' % (ok, ', %d not yet' % failed if failed else ''),
                  'success' if not failed else 'warning')
        elif action == 'unlink':
            wacrm_team.unlink(ws)
            flash('Disconnected. Nobody was removed from WhatsApp.', 'success')
        elif action == 'remove-extra':
            email = (request.form.get('email') or '').strip()
            wacrm_team.remove_extra(ws, email)
            flash('%s no longer has access to WhatsApp.' % email, 'success')
        else:
            member = next((m for m in ws.members if str(m.id) == request.form.get('member_id')), None)
            if member is None:
                abort(404)
            wacrm_team.member_changed(member)
            name = member.user.full_name or member.user.username
            if member.wacrm_error:
                flash('Still not in WhatsApp: %s' % member.wacrm_error, 'warning')
            else:
                flash('%s can use WhatsApp now.' % name, 'success')
    except wacrm_team.TeamError as exc:
        flash('WhatsApp said: %s' % exc, 'danger')
    ActivityEvent.log('workspace_whatsapp_' + action.replace('-', '_'), actor=current_user, workspace=ws.id)
    db.session.commit()
    return redirect(crm_url('connection'))


@crm_bp.route('/connection/retry/<int:person_id>', methods=['POST'])
@cs_required
@admin_only
def connection_retry(person_id):
    """Needs attention: try one person again (marked due, quietly; the jobs runner brings them in)."""
    p = db.session.get(CrmPerson, person_id)
    if p is None:
        abort(404)
    if not crm.mark_wa_due(p, quiet=True):
        flash(crm.WA_WRITES_OFF, 'warning')
    else:
        db.session.commit()
        flash('Trying again for %s.' % p.display_name, 'success')
    return redirect(crm_url('connection'))


@crm_bp.route('/connection/settle/<int:task_id>', methods=['POST'])
@cs_required
@admin_only
def connection_settle(task_id):
    """Needs attention: a follow-up stuck "sending" -- it went (done) or it did not (back to open)."""
    task = db.session.get(CrmTask, task_id)
    if task is None:
        abort(404)
    went = request.form.get('went') == '1'
    if crm.settle_send(task, went, user=current_user):
        flash('Marked done.' if went else 'Back on the list of whoever looks after the lead.', 'success')
        ActivityEvent.log('crm_send_settled', actor=current_user, task=task_id, went=went)
        db.session.commit()
    else:
        flash('That follow-up is not waiting any more.', 'info')
    return redirect(crm_url('connection'))


# ============================================================================================ What goes out by itself

@crm_bp.route('/automatic')
@cs_required
@admin_only
def automatic():
    """Automatic messages -> What goes out by itself (E14): follow-ups and stage moves set in Pipelines, and
    the reply rules, chatbot and AI replies set in WhatsApp."""
    page = crm_connection.automatic_page()
    return render_template('cs/crm/automatic.html', RULE_STRIP=crm.rule_strip(page['conflicts']),
                           NEEDS_UPDATE=crm_people.NEEDS_UPDATE, **page, **_common())
