"""Set-up > Integrations (2026-10-26): the cards (services/integrations.py), one integration's three tabs, the two
settings kept here (tawk.to's key, the other websites allowed to send leads), and tawk.to's webhook."""
import json

from flask import abort, current_app, flash, jsonify, redirect, render_template, request
from flask_login import current_user

from app import csrf, db
from app.models import ActivityEvent, CrmSource
from app.routes.crm import _common, admin_only, crm_bp, crm_public_bp, crm_url
from app.routes.cs import cs_required
from app.services import crm_editor, integrations, tawk

TABS = (('overview', 'Overview'), ('install', 'Installation'), ('settings', 'Settings'))


def _ctx():
    return integrations.Ctx(link=crm_url, user=current_user)


@crm_bp.route('/integrations')
@cs_required
@admin_only
def integrations_page():
    rows = sorted(integrations.cards(_ctx()), key=lambda c: integrations.KEYS.index(c['key']))
    group = request.args.get('group') if request.args.get('group') in dict(integrations.GROUPS) else None
    return render_template('cs/crm/integrations.html', rows=rows, GROUPS=integrations.GROUPS, group=group,
                           counts=integrations.summary(rows), **_common())


@crm_bp.route('/integrations/<key>')
@cs_required
@admin_only
def integration(key):
    c = integrations.card(key, _ctx())
    if c is None:
        abort(404)
    tab = request.args.get('tab') if request.args.get('tab') in dict(TABS) else 'overview'
    snippet = None
    if c['key'] == 'website' and c.get('sources'):
        keys = [k for k, _ in c['sources']]
        pick = request.args.get('form') if request.args.get('form') in keys else keys[0]
        src = CrmSource.query.filter_by(key=pick).first()
        snippet = {'key': pick, 'code': crm_editor.form_snippet(pick, src.product if src else None, c['script'])}
    return render_template('cs/crm/integration.html', c=c, tab=tab, TABS=TABS, snippet=snippet,
                           GROUP_NAMES=dict(integrations.GROUPS), **_common())


@crm_bp.route('/integrations/<key>/save', methods=['POST'])
@cs_required
@admin_only
def integration_save(key):
    """The two settings that live on an integration's own Settings tab."""
    if key == 'tawk':
        if request.form.get('action') == 'remove':
            tawk.save_secret('', current_user)
            flash('The tawk.to key is removed: tawk chats no longer come in.', 'success')
        else:
            value = (request.form.get('secret') or '').strip()
            if len(value) < 16 or len(value) > 200 or any(ch.isspace() for ch in value):
                flash('That does not look like the Secret Key tawk.to shows for the webhook. Copy it again.', 'danger')
                return redirect(crm_url('integration', key=key, tab='settings'))
            tawk.save_secret(value, current_user)
            flash('Saved. tawk chats that leave a phone or e-mail now come in as leads.', 'success')
        ActivityEvent.log('integration_saved', actor=current_user, integration='tawk',
                          action=request.form.get('action') or 'save')
        db.session.commit()
    elif key == 'website':
        kept, refused = integrations.save_origins(request.form.get('sites'), current_user)
        ActivityEvent.log('integration_saved', actor=current_user, integration='website', sites=kept)
        db.session.commit()
        if refused:
            flash('Saved %d website(s). Not saved, as they are not https web addresses: %s.'
                  % (len(kept), ', '.join(refused)), 'warning')
        else:
            flash('Saved: %s.' % (', '.join(kept) if kept else 'no other websites'), 'success')
    else:
        abort(404)
    return redirect(crm_url('integration', key=key, tab='settings'))


@crm_public_bp.route('/api/crm/tawk-webhook', methods=['POST'])
@csrf.exempt
def tawk_webhook():
    """tawk.to's webhook (services/tawk.py). 404 while no key is set; 401 for a bad signature; otherwise 200, even
    for an event that is not filed, so tawk never switches the address off."""
    if not tawk.enabled():
        abort(404)
    raw = request.get_data()
    if not tawk.verify_signature(request.headers.get('X-Tawk-Signature', ''), raw):
        return jsonify({'error': 'Bad signature.'}), 401
    try:
        payload = json.loads(raw.decode('utf-8') or '{}')
    except ValueError:
        return jsonify({'error': 'Not JSON.'}), 400
    ev = tawk.parse(payload)
    if ev is None:
        return jsonify({'ok': True, 'stored': False})
    try:
        lead = tawk.record(ev)
    except Exception:          # noqa: BLE001 -- answered and logged; tawk would only resend
        db.session.rollback()
        current_app.logger.exception('tawk event not stored')
        return jsonify({'ok': False}), 200
    return jsonify({'ok': True, 'stored': lead is not None})
