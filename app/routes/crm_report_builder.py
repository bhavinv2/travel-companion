"""The report builder (Sales CRM 2.0, run 4b): Overview, after Forecast. Rules on crm_bp; the work is in
services/crm_report_builder.py (everything a person picks is checked against fixed lists there).

Saving, pinning (to Sales results) and deleting are plain form posts. Running and downloading are GETs that carry
the choices in the address, so a report is a link.
"""
import csv
import io
from datetime import datetime

from flask import flash, make_response, redirect, render_template, request
from flask_login import current_user

from app import db
from app.models import ActivityEvent, CrmPipeline, CrmSource
from app.routes.crm import _common, _staff, crm_bp, crm_url
from app.routes.cs import cs_required
from app.services import crm_access, crm_report_builder as rb

CONFIG_KEYS = tuple(rb.DEFAULT)


@crm_bp.app_template_global('RB_PCT')
def rb_pct(value, biggest):
    return rb.pct(value, biggest)


def _args(source):
    return {k: source.get(k) for k in CONFIG_KEYS if source.get(k)}


def _page(cfg=None, error=None, result=None, **extra):
    staff = crm_access.limit_users(current_user, _staff())
    return render_template('cs/crm/report_builder.html', cfg=cfg or dict(rb.DEFAULT), error=error, result=result,
                           SOURCES=rb.SOURCES, MEASURES=rb.MEASURES, GROUPS=rb.GROUPS, DATE_FIELDS=rb.DATE_FIELDS,
                           STATUSES=rb.STATUSES, OFFERS=rb.OFFERS, pipelines=CrmPipeline.query.order_by(CrmPipeline.id).all(),
                           sources=CrmSource.query.order_by(CrmSource.name).all(), staff=staff,
                           saved=rb.listing(current_user), **extra, **_common())


@crm_bp.route('/reports/build')
@cs_required
def report_builder():
    """Build a report: what to count, how to measure it, how to group it. Shows a bar chart and a table."""
    if not request.args.get('run') and not request.args.get('what'):
        return _page()
    try:
        cfg = rb.clean_config(request.args)
    except rb.ReportError as exc:
        return _page(cfg={**rb.DEFAULT, **_args(request.args)}, error=str(exc))
    return _page(cfg=cfg, result=rb.run(cfg, current_user))


@crm_bp.route('/downloads')
@cs_required
def downloads():
    """Reports › Downloads: every sales download in one place. Each button is the same file as the one on its own
    screen (Sales results, Forecast, Team analysis, a saved report, Leads, Contacts); the page shows only the ones
    this person's role includes."""
    return render_template('cs/crm/downloads.html', saved=rb.listing(current_user), **_common())


@crm_bp.route('/reports/build.csv')
@cs_required
def report_builder_csv():
    """Download for Excel: the table on the screen."""
    try:
        cfg = rb.clean_config(request.args)
    except rb.ReportError as exc:
        flash(str(exc), 'danger')
        return redirect(crm_url('report_builder'))
    res = rb.run(cfg, current_user)
    buf = io.StringIO()
    csv.writer(buf).writerows(rb.csv_rows(res))
    ActivityEvent.log('crm_export', actor=current_user, kind='report', what=cfg['what'])
    db.session.commit()
    resp = make_response('﻿' + buf.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename=report-%s.csv' % datetime.utcnow().strftime('%Y%m%d')
    return resp


@crm_bp.route('/reports/save', methods=['POST'])
@cs_required
def report_save():
    try:
        cfg = rb.clean_config({k[2:]: v for k, v in request.form.items() if k.startswith('c_')})
        rep = rb.create(current_user, request.form.get('name'), cfg, request.form.get('shared') == 'on')
    except (rb.ReportError, rb.SavedError) as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
        return redirect(crm_url('report_builder', **_args({k[2:]: v for k, v in request.form.items() if k.startswith('c_')}),
                                run=1))
    flash('Saved the report "%s".' % rep.name, 'success')
    return redirect(crm_url('report_builder', **{k: v for k, v in cfg.items() if v}, run=1))


@crm_bp.route('/reports/<int:report_id>/pin', methods=['POST'])
@cs_required
def report_pin(report_id):
    want = request.form.get('pinned') == '1'
    try:
        rep = rb.set_pinned(current_user, report_id, want)
        flash(('"%s" now shows at the bottom of Sales results.' if want else '"%s" is off Sales results.') % rep.name,
              'success')
    except rb.SavedError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(crm_url('report_builder'))


@crm_bp.route('/reports/<int:report_id>/move', methods=['POST'])
@cs_required
def report_move(report_id):
    try:
        rb.move(current_user, report_id, request.form.get('dir'))
    except rb.SavedError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(crm_url('report_builder'))


@crm_bp.route('/reports/<int:report_id>/delete', methods=['POST'])
@cs_required
def report_delete(report_id):
    try:
        rb.delete(current_user, report_id)
        flash('Report deleted.', 'success')
    except rb.SavedError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
    return redirect(crm_url('report_builder'))
