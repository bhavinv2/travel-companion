"""Forecast and Targets (Sales CRM 2.0, Phase 1): money won against target, what is committed, and the targets.

The rules are on crm_bp (routes/crm.py), so they exist under /cs/crm and /admin/crm. Forecast may be held by an
agent (it shows only their own row); Targets is a management page (MANAGE). The sums are in
services/crm_money.py; this file reads the request and draws.
"""
import csv
import io
from datetime import datetime

from flask import flash, make_response, redirect, render_template, request
from flask_login import current_user

from app import db
from app.models import ActivityEvent, CrmPipeline
from app.routes.crm import _common, _my_teams, _staff, admin_only, crm_bp, crm_url
from app.routes.cs import cs_required
from app.services import access, crm, crm_money, crm_reports, download_reason

TOKEN_FORMAT = '%04d-Q%d'


def _sees_team():
    """Admins, people who can open the workspace's people page, team leads (Team today) and anybody with Sales
    results look at more than themselves; anyone else sees their own row only."""
    return bool(current_user.is_admin or access.can(current_user, 'ws_members')
                or access.can(current_user, 'crm_tracker') or access.can(current_user, 'crm_insights'))


def _who_is_shown():
    """(staff, teams, sees_all): the people the viewer may see, and the teams to list."""
    everyone = _staff()
    if not _sees_team():
        return [current_user], [], False
    staff = crm_reports.visible_staff(current_user, everyone)
    sees_all = len(staff) == len(everyone)
    ws = access.current_workspace(current_user)
    teams = (list(ws.teams) if ws is not None else []) if sees_all else _my_teams()
    return staff, teams, sees_all


def _span_token(period, quarter):
    if not quarter:
        return period
    first = crm_money.period_start(period)
    return TOKEN_FORMAT % (first.year, (first.month - 1) // 3 + 1)


def _num(v):
    """A Decimal for a spreadsheet cell: no trailing noise."""
    return '' if v is None else crm_money.plain_amount(v)


def _forecast_data():
    """Everything Forecast shows (the page and its Excel download both read it)."""
    today = (datetime.utcnow() + crm.IST).date()
    period = crm_money.parse_period(request.args.get('month'), today)
    quarter = request.args.get('span') == 'quarter'
    months = crm_money.span_months(period, quarter)
    first, last = crm_money.span_dates(months)
    pipelines = CrmPipeline.query.order_by(CrmPipeline.id).all()
    pipe = next((p for p in pipelines if p.id == request.args.get('pipeline', type=int)), None)
    pid = pipe.id if pipe else None
    staff, teams, sees_all = _who_is_shown()
    team = next((t for t in teams if t.id == request.args.get('team', type=int)), None)
    person = next((u for u in staff if u.id == request.args.get('who', type=int)), None)
    shown = staff
    if team is not None:
        ids = {u.id for u in team.users}
        shown = [u for u in staff if u.id in ids]
    if person is not None:
        shown = [person]
    data = crm_money.forecast(first, last, shown, pid, months)
    rows = data['rows']
    # team rows add up their members, who may not all be in the scope chosen above
    every = rows if len(staff) == len(shown) else crm_money.forecast(first, last, staff, pid, months)['rows']
    people = [{'user': u, 'row': rows[u.id]} for u in shown]
    people.sort(key=lambda r: (-r['row']['won'], r['user'].full_name or ''))
    sums = crm_money.target_sums(months, pid)
    # team rows: the members' numbers added up, with the team's own target when it has one
    team_rows = []
    for t in teams:
        members = [u for u in staff if u in t.users]
        if not members:
            continue
        own = sums.get(('t', t.id))
        trow = crm_money.team_row([every[m.id] for m in members],
                                  {'target': own['amount'], 'deals_target': own['deals'], 'leads_target': own['leads']}
                                  if own else None)
        trow['own_target'] = own['amount'] if own else None
        team_rows.append({'team': t, 'row': trow, 'n': len(members)})
    # the headline: one person, one team (its own target wins), or the whole team added up
    if person is not None:
        total = rows[person.id]
    elif team is not None:
        own = sums.get(('t', team.id))
        total = crm_money.team_row([rows[u.id] for u in shown],
                                   {'target': own['amount'], 'deals_target': own['deals'], 'leads_target': own['leads']}
                                   if own else None)
    else:
        total = crm_money.team_row([rows[u.id] for u in shown])
    company = sums.get(('c', None))
    if person is None and team is None and company and company['leads'] is not None:
        total['leads_target'] = company['leads']
    # new leads for the whole team count every lead that came in, owned or not
    if person is None and team is None and sees_all:
        from sqlalchemy import func
        from app.models import CrmLead
        start, end = crm_money.utc_bounds(first, last)
        q = db.session.query(func.count(CrmLead.id)).filter(CrmLead.created_at >= start, CrmLead.created_at < end,
                                                             CrmLead.imported.is_(False))
        if pid:
            q = q.filter(CrmLead.pipeline_id == pid)
        total['new_leads'] = q.scalar() or 0
    rate_counts = data.get('missing_counts') or {}
    return dict(period=period, quarter=quarter, months=months, first=first, last=last, today=today,
                pipelines=pipelines, pipe=pipe, staff=staff, teams=teams, team=team, person=person,
                sees_all=sees_all, shown=shown, people=people, team_rows=team_rows, total=total, fix=data['fix'],
                rate_warning=crm_money.rate_warning(rate_counts), token=_span_token(period, quarter),
                prev_period=crm_money.shift_period(period, -3 if quarter else -1),
                next_period=crm_money.shift_period(period, 3 if quarter else 1),
                period_label=(('Q%d %d' % ((crm_money.period_start(period).month - 1) // 3 + 1,
                                           crm_money.period_start(period).year)) if quarter
                              else crm_money.month_label(period)))


def _bar(total):
    """Segments of the stacked bar (percent of its width) and where the target marker sits."""
    parts = [('won', 'Closed won', total['won']), ('commit', 'Committed', total['commit']),
             ('best_case', 'Best case', total['best_case']), ('pipeline', 'Pipeline', total['pipeline'])]
    target = total['target'] or 0
    full = max(sum((v for _k, _l, v in parts), crm_money.ZERO), crm_money.dec(target) or crm_money.ZERO)
    if not full:
        return {'segs': [], 'marker': None}
    segs = [{'key': k, 'label': l, 'value': v, 'pct': float(v * 100 / full)} for k, l, v in parts if v]
    marker = float(crm_money.dec(target) * 100 / full) if target else None
    return {'segs': segs, 'marker': marker}


@crm_bp.route('/forecast')
@cs_required
def forecast():
    """Forecast: for the month (or quarter), what each person has won against their target, what is committed,
    in the best case, and still early. Every number opens the leads behind it."""
    d = _forecast_data()
    pipe_key = d['pipe'].key if d['pipe'] else 'all'
    solo = d['person'].id if d['person'] else (d['shown'][0].id if len(d['shown']) == 1 else None)

    def leads_link(owner=None, **kw):
        vals = {'p': pipe_key, 'view': 'list'}
        if owner:
            vals['owner'] = owner
        elif d['sees_all'] and d['team'] is None:
            vals['owner'] = 'all'
        vals.update({k: v for k, v in kw.items() if v is not None})
        return crm_url('board', **vals)

    return render_template('cs/crm/forecast.html', bar=_bar(d['total']), leads_link=leads_link, solo=solo,
                           can_export=access.can(current_user, 'crm_export'),
                           can_rates=access.can(current_user, 'crm_pipelines'),
                           can_targets=access.can(current_user, 'crm_targets'),
                           report_currency=crm_money.reporting_currency(), **d, **_common())


@crm_bp.route('/forecast.csv')
@cs_required
@download_reason.asked
def forecast_csv():
    """Download for Excel: the table on the Forecast page, a row per person and per team."""
    d = _forecast_data()
    cur = crm_money.reporting_currency()
    head = ['Person or team', 'Target (%s)' % cur, 'Closed won', 'Committed', 'Best case', 'Pipeline', 'Gap to target',
            '% of target', 'Deals won', 'Deals target', 'New leads', 'New leads target']

    def line(name, r):
        return [name, _num(r['target']), _num(r['won']), _num(r['commit']), _num(r['best_case']), _num(r['pipeline']),
                _num(r['gap']), '' if r['pct'] is None else r['pct'], r['won_n'], _num(r['deals_target']),
                r['new_leads'], _num(r['leads_target'])]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['Forecast', d['period_label']] + (['Pipeline: ' + d['pipe'].name] if d['pipe'] else []))
    w.writerow(head)
    for p in d['people']:
        w.writerow(line(p['user'].full_name, p['row']))
    for t in d['team_rows']:
        w.writerow(line('Team: ' + t['team'].name, t['row']))
    w.writerow(line('Total', d['total']))
    ActivityEvent.log('crm_export', actor=current_user, kind='forecast', month=d['period'],
                      reason=download_reason.given())
    db.session.commit()
    resp = make_response('﻿' + buf.getvalue())
    resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = 'attachment; filename=forecast-%s.csv' % d['token']
    return resp


# ============================================================================================ targets

def _targets_scope():
    """(staff, teams, company): who the viewer may set targets for. Admins and the people page: everybody, every
    team and the company's new-leads target. A team lead: their own teams and those teams' members."""
    everyone = _staff()
    if current_user.is_admin or access.can(current_user, 'ws_members'):
        ws = access.current_workspace(current_user)
        return everyone, (list(ws.teams) if ws is not None else []), True
    return crm_reports.visible_staff(current_user, everyone), _my_teams(), False


def _targets_args(source):
    today = (datetime.utcnow() + crm.IST).date()
    period = crm_money.parse_period(source.get('month'), today)
    pid = source.get('pipeline', type=int) or None
    pipe = db.session.get(CrmPipeline, pid) if pid else None
    return period, (pipe.id if pipe else None)


@crm_bp.route('/targets')
@cs_required
@admin_only
def targets():
    """Targets: for a month (and optionally one pipeline), what each person and team aims to win, in deals,
    and in new leads."""
    period, pid = _targets_args(request.args)
    staff, teams, company = _targets_scope()
    have = crm_money.targets_for(period, pid)
    last = crm_money.shift_period(period, -1)
    rows = [{'user': u, 'row': have.get(('u', u.id))} for u in staff]
    team_rows = [{'team': t, 'row': have.get(('t', t.id))} for t in teams]
    total = {'amount': sum((r['row'].amount or 0 for r in rows if r['row']), crm_money.ZERO),
             'deals': sum((r['row'].deals or 0 for r in rows if r['row'])),
             'leads': sum((r['row'].leads or 0 for r in rows if r['row']))}
    return render_template('cs/crm/targets.html', period=period, period_label=crm_money.month_label(period),
                           prev_period=last, next_period=crm_money.shift_period(period, 1),
                           pipelines=CrmPipeline.query.order_by(CrmPipeline.id).all(), pipeline_id=pid,
                           rows=rows, team_rows=team_rows, total=total, company=company,
                           company_row=have.get(('c', None)) if company else None,
                           last_label=crm_money.month_label(last), report_currency=crm_money.reporting_currency(),
                           **_common())


@crm_bp.route('/targets/save', methods=['POST'])
@cs_required
@admin_only
def targets_save():
    period, pid = _targets_args(request.form)
    staff, teams, company = _targets_scope()
    f = request.form
    errors, n = [], 0

    def one(prefix, name, **who):
        nonlocal n
        try:
            before = {k: f.get(prefix + k) for k in ('amount', 'deals', 'leads')}
            crm_money.save_target(period, pipeline_id=pid, amount=before['amount'], deals=before['deals'],
                                  leads=before['leads'], actor=current_user, **who)
            n += 1
        except ValueError:
            errors.append(name)

    for u in staff:
        if any((f.get('u%d_%s' % (u.id, k)) is not None) for k in ('amount', 'deals', 'leads')):
            one('u%d_' % u.id, u.full_name, user_id=u.id)
    for t in teams:
        if any((f.get('t%d_%s' % (t.id, k)) is not None) for k in ('amount', 'deals', 'leads')):
            one('t%d_' % t.id, t.name, team_id=t.id)
    if company and f.get('c_leads') is not None:
        try:
            crm_money.save_target(period, pipeline_id=pid, leads=f.get('c_leads'), actor=current_user)
        except ValueError:
            errors.append('the whole company')
    if errors:
        db.session.rollback()
        flash('Check the numbers for %s. Use whole numbers, like 300000 or 12.' % ', '.join(errors), 'danger')
    else:
        ActivityEvent.log('crm_targets_saved', actor=current_user, month=period, rows=n)
        db.session.commit()
        flash('Targets saved for %s.' % crm_money.month_label(period), 'success')
    return redirect(crm_url('targets', month=period, pipeline=pid))


@crm_bp.route('/targets/copy', methods=['POST'])
@cs_required
@admin_only
def targets_copy():
    """Copy last month's targets into this month, for the rows that are still empty."""
    period, pid = _targets_args(request.form)
    staff, teams, company = _targets_scope()
    n = crm_money.copy_targets(crm_money.shift_period(period, -1), period, pid,
                               user_ids={u.id for u in staff}, team_ids={t.id for t in teams}, company=company,
                               actor=current_user)
    db.session.commit()
    flash(('Copied %d target%s from %s.' % (n, '' if n == 1 else 's', crm_money.month_label(crm_money.shift_period(period, -1))))
          if n else 'Nothing to copy: last month has no targets, or this month already has them.',
          'success' if n else 'info')
    return redirect(crm_url('targets', month=period, pipeline=pid))
