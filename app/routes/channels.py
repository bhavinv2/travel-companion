"""Set-up › Channels › WhatsApp numbers (2026-10-29): every WhatsApp number and the system that answers it, the
numbers the portal talks to Meta for itself (connect one, its templates, a test message), and Meta's webhook for
them. Rules on crm_bp (both consoles) and crm_public_bp; the work is in services/channels.py and services/wa_meta.py.

A number of our own is connected in three steps on its Connection tab: save Meta's two ids, the access token and the
app secret (sealed; never shown again); "Check with Meta" reads the number; "Connect" makes our Meta app hear its
WhatsApp Business Account at OUR address (Meta's per-account override), so the WhatsApp CRM's address is untouched.
"""
import json
import re
from datetime import datetime

from flask import abort, current_app, flash, jsonify, redirect, render_template, request
from flask_login import current_user

from app import csrf, db
from app.models import ActivityEvent, CrmChannelLine
from app.routes.crm import _common, admin_only, crm_bp, crm_public_bp, crm_url
from app.routes.cs import cs_required
from app.services import access, channels, wa_meta

TABS = (('overview', 'Overview'), ('connect', 'Connection'), ('templates', 'Templates'))
ID_RE = re.compile(r'^\d{6,25}$')
ACTIONS = ('check', 'connect', 'disconnect', 'pause', 'resume', 'templates', 'copy', 'test', 'remove')
NOT_LIVE = frozenset({'PENDING', 'UNVERIFIED', 'DISCONNECTED', 'DELETED', 'MIGRATED', 'BANNED'})
NOT_LIVE_TEXT = ('Meta has this phone number ID as %s: it is not the live copy of the number. In WhatsApp Manager › '
                 'Phone numbers, switch between the accounts at the top and use the two ids of the account where the '
                 'number shows Connected. Do not verify this copy: that would take the number off the account that has it.')


def _line_or_404(line_id):
    line = channels.get(line_id)
    if line is None:
        abort(404)
    return line


def webhook_url():
    """The public address Meta sends this number's account to (the live site's, behind a proxy too)."""
    from app.services import integrations
    return integrations._addr('crm_public.lines_webhook')


def _log(what, line, **extra):
    ActivityEvent.log('channel_' + what, actor=current_user, line=line.key, **extra)


# ================================================================================================== pages

@crm_bp.route('/channels')
@cs_required
@admin_only
def channels_page():
    ws = access.current_workspace(current_user)
    return render_template('cs/crm/channels.html', rows=channels.numbers(ws), PROVIDERS=channels.PROVIDERS,
                           CHECKLIST=channels.CHECKLIST, label_of=channels.label_of, **_common())


@crm_bp.route('/channels/new', methods=['GET', 'POST'])
@cs_required
@admin_only
def channel_new():
    if request.method == 'GET':
        return render_template('cs/crm/channel.html', line=None, tab='connect', TABS=TABS, form={}, **_common())
    form, problems = _read_form(None)
    if problems:
        for p in problems:
            flash(p, 'danger')
        return render_template('cs/crm/channel.html', line=None, tab='connect', TABS=TABS, form=form, **_common()), 400
    ws = access.current_workspace(current_user)
    line = CrmChannelLine(key=channels.free_key(form['label']), label=form['label'], provider='meta',
                          phone_number_id=form['phone_number_id'], waba_id=form['waba_id'] or None,
                          verify_token=channels.new_verify_token(), prefixes=form['prefixes'] or None,
                          also_on=form['also_on'] or None, status='new', workspace_id=ws.id if ws else None,
                          created_by_id=current_user.id, created_at=datetime.utcnow())
    channels.set_secrets(line, token=form['token'], app_secret=form['app_secret'])
    db.session.add(line)
    db.session.flush()
    channels.ensure_source(line)
    _log('added', line)
    db.session.commit()
    flash('Saved %s. Now press “Check with Meta”, then “Connect”.' % line.label, 'success')
    return redirect(crm_url('channel', line_id=line.id, tab='connect'))


@crm_bp.route('/channels/<int:line_id>')
@cs_required
@admin_only
def channel(line_id):
    line = _line_or_404(line_id)
    tab = request.args.get('tab') if request.args.get('tab') in dict(TABS) else 'overview'
    kept = channels.secrets_of(line)
    return render_template('cs/crm/channel.html', line=line, tab=tab, TABS=TABS, form={},
                           has={'token': bool((kept or {}).get('token')), 'app_secret': bool((kept or {}).get('app_secret')),
                                'unreadable': kept is None},
                           counts=channels.counts(line), hook=webhook_url(), label_of=channels.label_of,
                           tpl=channels.templates(line), STATUS_WORDS=channels.STATUS_WORDS,
                           env_secret=bool([s for s in channels.app_secrets()
                                            if s != ((kept or {}).get('app_secret') or '')]), **_common())


def _read_form(line):
    """The Connection form, cleaned: (values, [problems])."""
    f = request.form
    out = {'label': ' '.join((f.get('label') or '').split())[:60],
           'phone_number_id': (f.get('phone_number_id') or '').strip(),
           'waba_id': (f.get('waba_id') or '').strip(),
           'token': (f.get('token') or '').strip(), 'app_secret': (f.get('app_secret') or '').strip(),
           'prefixes': channels.clean_prefixes(f.get('prefixes')),
           'also_on': ['tawk'] if f.get('also_tawk') == 'on' else [], 'prefixes_text': f.get('prefixes') or ''}
    problems = []
    if not out['label']:
        problems.append('Give the number a name, such as USA.')
    if not ID_RE.match(out['phone_number_id']):
        problems.append('The phone number ID is the long number Meta shows under the number (digits only).')
    elif CrmChannelLine.query.filter(CrmChannelLine.phone_number_id == out['phone_number_id'],
                                     CrmChannelLine.id != (line.id if line else 0)).first() is not None:
        problems.append('That phone number ID is already one of the numbers here.')
    if out['waba_id'] and not ID_RE.match(out['waba_id']):
        problems.append('The WhatsApp Business Account ID is digits only.')
    if line is None and not out['waba_id']:
        problems.append('Add the WhatsApp Business Account ID: connecting needs it.')
    if line is None and not out['token']:
        problems.append('Paste the access token: nothing can be sent or checked without it.')
    for name in ('token', 'app_secret'):
        v = out[name]
        if v and (len(v) < 20 or len(v) > 1000 or any(ch.isspace() for ch in v)):
            problems.append('The %s does not look right. Copy it again.' %
                            ('access token' if name == 'token' else 'app secret'))
    return out, problems


@crm_bp.route('/channels/<int:line_id>/save', methods=['POST'])
@cs_required
@admin_only
def channel_save(line_id):
    line = _line_or_404(line_id)
    form, problems = _read_form(line)
    if problems:
        for p in problems:
            flash(p, 'danger')
        return redirect(crm_url('channel', line_id=line.id, tab='connect'))
    moved = form['phone_number_id'] != line.phone_number_id or (form['waba_id'] or None) != line.waba_id
    line.label = form['label']
    line.phone_number_id = form['phone_number_id']
    line.waba_id = form['waba_id'] or None
    line.prefixes = form['prefixes'] or None
    line.also_on = form['also_on'] or None
    if form['token'] or form['app_secret']:
        channels.set_secrets(line, token=form['token'] or None, app_secret=form['app_secret'] or None)
    if moved and line.status == 'live':
        line.status = 'new'             # another number or account: connect it again
    _log('saved', line, moved=moved, token=bool(form['token']), app_secret=bool(form['app_secret']))
    db.session.commit()
    flash('Saved.' + (' The number or account changed: press “Connect” again.' if moved else ''), 'success')
    return redirect(crm_url('channel', line_id=line.id, tab='connect'))


# ================================================================================================ actions

@crm_bp.route('/channels/<int:line_id>/do', methods=['POST'])
@cs_required
@admin_only
def channel_action(line_id):
    line = _line_or_404(line_id)
    what = request.form.get('action')
    if what not in ACTIONS:
        abort(400)
    back = crm_url('channel', line_id=line.id, tab=request.form.get('tab') or 'overview')
    try:
        if what == 'check':
            _check(line)
        elif what == 'connect':
            _check(line, quiet=True)
            wa_meta.subscribe(line, webhook_url())
            line.status, line.connected_at, line.last_error = 'live', datetime.utcnow(), None
            try:
                channels.refresh_templates(line)
            except wa_meta.LineError as exc:
                flash('Connected, but its templates could not be read yet: %s' % exc, 'warning')
            _log('connected', line)
            db.session.commit()
            flash('Connected. Messages to %s now come in here, and the lead page answers through it.'
                  % channels.label_of(line), 'success')
        elif what == 'disconnect':
            wa_meta.unsubscribe(line)
            line.status = 'new'
            _log('disconnected', line)
            db.session.commit()
            flash('Disconnected: our app no longer hears this number. tawk.to and any other app keep theirs.', 'success')
        elif what in ('pause', 'resume'):
            if what == 'resume' and line.connected_at is None:
                flash('Connect it first.', 'warning')
                return redirect(back)
            line.status = 'paused' if what == 'pause' else 'live'
            _log(what + 'd', line)
            db.session.commit()
            flash('Paused: nothing goes out on it; messages still come in.' if what == 'pause'
                  else 'Sending again.', 'success')
        elif what == 'templates':
            rows = channels.refresh_templates(line)
            db.session.commit()
            flash('Meta lists %d template(s) for this number, %d approved.'
                  % (len(rows), sum(1 for r in rows if r['status'] == 'APPROVED')), 'success')
        elif what == 'copy':
            try:
                channels.refresh_templates(line)
            except wa_meta.LineError:
                pass
            got = channels.copy_templates(line)
            try:
                channels.refresh_templates(line)
            except wa_meta.LineError:
                pass
            _log('templates_copied', line, sent=len(got['sent']), failed=len(got['failed']))
            db.session.commit()
            if got['sent']:
                flash('Sent %d template(s) to Meta for approval: %s. Approval usually takes minutes to a day.'
                      % (len(got['sent']), ', '.join(got['sent'])), 'success')
            if got['failed']:
                flash('Not sent: %s.' % '; '.join('%s (%s)' % (n, why) for n, why in got['failed'][:6]), 'warning')
            if not got['sent'] and not got['failed']:
                flash('This number already has every follow-up template (%d).' % len(got['had']), 'info')
        elif what == 'test':
            return _test(line, back)
        elif what == 'remove':
            label = line.label
            _log('removed', line)
            db.session.delete(line)
            db.session.commit()
            flash('Removed %s from the portal. Its messages stay on the leads. In Meta nothing changed.' % label,
                  'success')
            return redirect(crm_url('channels_page'))
    except wa_meta.LineError as exc:
        db.session.rollback()
        line = _line_or_404(line_id)
        line.last_error = str(exc)[:300]
        if what == 'connect':
            line.status = 'error'
        db.session.commit()
        flash('Meta said: %s' % exc, 'danger')
    return redirect(back)


def _check(line, quiet=False):
    """Read the number from Meta with its token; check the number belongs to the account. Raises LineError."""
    info = wa_meta.phone_info(line)
    shown = info.get('display_phone_number')
    if shown:
        line.phone = '+' + wa_meta.digits(shown)
    state = (info.get('status') or '').upper()
    if state in NOT_LIVE:
        # Meta keeps unfinished copies of a number (WhatsApp Manager, the app's API Setup) beside the live one; verifying
        # a copy would take the number off the account that has it -- tawk.to and the phone's WhatsApp Business app
        raise wa_meta.LineError(NOT_LIVE_TEXT % state.lower(), status=400, code='meta_error')
    if line.waba_id:
        ids = {str(r.get('id')) for r in wa_meta.account_numbers(line)}
        if line.phone_number_id not in ids:
            raise wa_meta.LineError('The phone number ID is not one of the numbers of WhatsApp Business Account %s. '
                                    'Check the two ids.' % line.waba_id, status=400, code='meta_error')
    line.last_error = None
    db.session.commit()
    if not quiet:
        flash('Meta knows this number: %s%s, quality %s, %s.'
              % (shown or line.phone_number_id, ' (%s)' % info['verified_name'] if info.get('verified_name') else '',
                 (info.get('quality_rating') or 'not rated').lower(),
                 (info.get('status') or info.get('code_verification_status') or 'state unknown').lower().replace('_', ' ')),
              'success')
    return info


def _test(line, back):
    """One message to a number of the admin's choosing: an approved template (any time) or free text (only inside
    their 24 hours). Nothing is recorded on a lead."""
    to = wa_meta.digits(request.form.get('to'))
    if len(to) < 8:
        flash('Type the number to send the test to, with its country code.', 'warning')
        return redirect(back)
    name = (request.form.get('template') or '').strip()
    text = (request.form.get('text') or '').strip()[:1000]
    tpl = channels.templates(line)
    if name:
        info = tpl.info(name)
        if not tpl.approved(name):
            flash('That template is not approved for this number.', 'warning')
            return redirect(back)
        wamid = wa_meta.send_template(line, to, name, language=info.get('language'),
                                      params=['Test'] * int(info.get('variables') or 0))
    elif text:
        wamid = wa_meta.send_text(line, to, text)
    else:
        flash('Choose a template or write a message.', 'warning')
        return redirect(back)
    line.last_out_at = datetime.utcnow()
    _log('test_sent', line, template=name or None)
    db.session.commit()
    flash('Meta took the test message (id …%s). It shows on the phone within seconds.' % wamid[-8:], 'success')
    return redirect(back)


# ================================================================================================ webhook

@crm_public_bp.route('/api/whatsapp/lines-webhook', methods=['GET', 'POST'])
@csrf.exempt
def lines_webhook():
    """Meta, for the WhatsApp numbers the portal talks to itself (services/channels). GET is Meta checking the
    address when a number is connected: it must echo hub.challenge for a verify token one of our numbers holds. POST
    deliveries are signed with the Meta app's secret; anything unsigned is refused. A delivery that breaks answers
    500, so Meta sends it again (a message is filed once, by its id)."""
    if request.method == 'GET':
        token = request.args.get('hub.verify_token') or ''
        if (request.args.get('hub.mode') == 'subscribe' and token
                and CrmChannelLine.query.filter_by(verify_token=token).first() is not None):
            return request.args.get('hub.challenge') or '', 200, {'Content-Type': 'text/plain'}
        return 'Forbidden', 403
    raw = request.get_data()
    if not wa_meta.verify_signature(raw, request.headers.get('X-Hub-Signature-256'), channels.app_secrets()):
        return jsonify({'error': 'Bad signature.'}), 401
    try:
        payload = json.loads(raw.decode('utf-8') or '{}')
    except ValueError:
        return jsonify({'error': 'Not JSON.'}), 400
    try:
        done = channels.record(wa_meta.parse(payload))
    except Exception:          # noqa: BLE001 -- logged; Meta sends it again and nothing is filed twice
        db.session.rollback()
        current_app.logger.exception('WhatsApp (Meta direct) delivery not stored')
        return jsonify({'ok': False}), 500
    return jsonify({'ok': True, **done})
