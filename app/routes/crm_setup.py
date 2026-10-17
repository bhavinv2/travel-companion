"""Set-up -> Pipelines (E18, E19): the pipeline list with its Products and "Needs a WhatsApp template" checklist,
the new-pipeline wizard and the pipeline editor.

The rules are on crm_bp, so they exist under /cs/crm and /admin/crm; every one is in MANAGE (routes/crm.py) and
needs the crm_pipelines page. The logic is in services/crm_editor.py; this file only reads the request and draws.
"""
from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from markupsafe import Markup, escape

from app import db
from app.models import CrmPipeline, CrmPlaybookStep, CrmProduct
from app.routes.crm import _common, _json, admin_only, crm_bp, crm_url
from app.routes.cs import cs_required
from app.services import crm, crm_editor


@crm_bp.app_template_filter('quote_ok')
def quote_ok(text):
    """Escaped like any text, except that a plain apostrophe stays one (the tag sentence reads "uses 'TI'")."""
    return Markup(str(escape(text)).replace('&#39;', "'"))


@crm_bp.app_template_global('CRM_REL')
def crm_rel(endpoint, **values):
    """A Set-up address relative to the Sales CRM's base, for crm-setup.js (it posts to BASE + path)."""
    return crm_editor.rel_url(endpoint, **values)


def _pipeline_or_404(pid):
    pipe = db.session.get(CrmPipeline, pid)
    if pipe is None:
        abort(404)
    return pipe


@crm_bp.route('/pipelines')
@cs_required
@admin_only
def pipelines():
    """Set-up -> Pipelines: a card for each pipeline, the Products tab (?tab=products) and the checklist of
    follow-ups that need a WhatsApp template (?show=templates). The old ?p=<key> opens that pipeline."""
    crm.ensure_defaults()
    a = request.args
    if a.get('p'):
        pipe = CrmPipeline.query.filter_by(key=a['p']).first()
        return redirect(crm_url('pipeline_edit', pid=pipe.id) if pipe is not None else crm_url('pipelines'))
    tab = 'products' if a.get('tab') == 'products' else 'templates' if a.get('show') == 'templates' else 'pipelines'
    ctx = {**_common(), **crm_editor.list_context(tab, edit=a.get('edit'))}
    return render_template('cs/crm/pipelines.html', **ctx)


@crm_bp.route('/pipelines/new', methods=['GET', 'POST'])
@cs_required
@admin_only
def pipeline_new():
    """The new-pipeline wizard: name, product, where to start from, the WhatsApp tag, how leads arrive."""
    crm.ensure_defaults()
    if request.method == 'POST':
        snippet_url = url_for('static', filename='js/lead-capture.js', _external=True)
        pipe, notes, errors = crm_editor.create_pipeline(request.form, current_user, snippet_url)
        if errors:
            db.session.rollback()
            ctx = {**_common(), **crm_editor.wizard_context(request.form, errors)}
            return render_template('cs/crm/pipeline_new.html', **ctx), 400
        flash(notes['said'], 'success')
        extra = {'made': 'form', 'source': notes['source_key']} if notes.get('source_key') else {}
        return redirect(crm_url('pipeline_edit', pid=pipe.id, **extra))
    ctx = {**_common(), **crm_editor.wizard_context({}, {})}
    return render_template('cs/crm/pipeline_new.html', **ctx)


@crm_bp.route('/pipelines/<int:pid>')
@cs_required
@admin_only
def pipeline_edit(pid):
    """One pipeline: its details, stages and follow-ups, all changed together and saved with one button."""
    pipe = _pipeline_or_404(pid)
    ctx = {**_common(), **crm_editor.editor_context(pipe, current_user, open_step=request.args.get('step', type=int),
                                                   made=request.args.get('made'),
                                                   source_key=request.args.get('source'))}
    return render_template('cs/crm/pipeline_edit.html', **ctx)


@crm_bp.route('/pipelines/<int:pid>/save', methods=['POST'])
@cs_required
@admin_only
def pipeline_save(pid):
    pipe = _pipeline_or_404(pid)
    out = crm_editor.save(pipe, _json(), current_user)
    return jsonify(out['body']), out['status']


@crm_bp.route('/pipelines/<int:pid>/active', methods=['POST'])
@cs_required
@admin_only
def pipeline_active(pid):
    """The "Taking new leads" switch on a card or in the editor's header."""
    pipe = _pipeline_or_404(pid)
    message = crm_editor.set_active(pipe, bool(_json().get('on')), current_user)
    return jsonify({'success': True, 'message': message})


@crm_bp.route('/pipelines/<int:pid>/tag')
@cs_required
@admin_only
def pipeline_tag_check(pid):
    """What changing this pipeline's WhatsApp tag would do, before anything is changed."""
    pipe = _pipeline_or_404(pid)
    return jsonify(crm_editor.tag_report(pipe, request.args.get('mode'), request.args.get('label')))


@crm_bp.route('/pipelines/<int:pid>/tag', methods=['POST'])
@cs_required
@admin_only
def pipeline_tag(pid):
    pipe = _pipeline_or_404(pid)
    d = _json()
    out = crm_editor.change_tag(pipe, d.get('mode'), d.get('label'), bool(d.get('take_over')), current_user,
                                d.get('stamp'))
    return jsonify(out['body']), out['status']


@crm_bp.route('/pipelines/tag-check')
@cs_required
@admin_only
def tag_check():
    """Is this product code (or this pipeline tag) free, and does WhatsApp already use that name by hand?"""
    a = request.args
    if a.get('code') is not None:
        return jsonify(crm_editor.name_check(code=a.get('code'), product_id=a.get('product_id') or None))
    return jsonify(crm_editor.name_check(label=a.get('label'), pipeline_id=a.get('pipeline_id') or None))


@crm_bp.route('/pipelines/products', methods=['POST'])
@cs_required
@admin_only
def save_product():
    prod, errors = crm_editor.save_product(request.form, current_user)
    if errors:
        db.session.rollback()
        edit = request.form.get('id') or 'new'
        ctx = {**_common(), **crm_editor.list_context('products', edit=edit, errors=errors, form=request.form)}
        return render_template('cs/crm/pipelines.html', **ctx), 400
    flash('Saved “%s”.' % prod.name, 'success')
    return redirect(crm_url('pipelines', tab='products'))


@crm_bp.route('/pipelines/products/<int:prod_id>/offered', methods=['POST'])
@cs_required
@admin_only
def product_offered(prod_id):
    prod = db.session.get(CrmProduct, prod_id)
    if prod is None:
        abort(404)
    crm_editor.set_offered(prod, bool(_json().get('on')), current_user)
    return jsonify({'success': True, 'message': 'Saved'})


@crm_bp.route('/pipelines/template-draft', methods=['POST'])
@cs_required
@admin_only
def template_draft():
    """"Make it a WhatsApp template": one follow-up's words as one draft in the WhatsApp CRM. Only while the
    portal may write to WhatsApp. From the editor (JSON) or the checklist (a form)."""
    d = _json() if request.is_json else request.form
    sid = d.get('step_id')
    step = db.session.get(CrmPlaybookStep, int(sid)) if sid and str(sid).isdigit() else None
    if step is None:
        abort(404)
    out = crm_editor.make_template(step, current_user, stamp_in=d.get('stamp') if request.is_json else None)
    if request.is_json:
        return jsonify({k: v for k, v in out.items() if k != 'status'}), out['status']
    if out.get('success'):
        flash(out['message'], 'success')
    else:
        flash(out['error'], 'warning' if out['status'] == 409 else 'danger')
    return redirect(crm_url('pipelines', show='templates'))
