"""The Promotion dashboard and its designer (2026-10-29). The numbers are services/mkt_engine's, the dashboards
services/mkt_dashboards', the website's services/ga4's.

    /promotion                       main.promo_dashboard -> page(): the tabs, the dates, every box
    /promotion/box                   one box's numbers (GET): the website boxes, which the page asks for after it draws
    /promotion/live                  who is on the website right now (GET), every 30 seconds
    /promotion/designer              Reports > Dashboard designer: every dashboard, new, publish, order
    /promotion/designer/<id>         the designer itself: the grid, the box settings, Save and Publish
    /promotion/designer/preview      one box's numbers while it is being made (POST, changes nothing)
    /promotion/designer/options      the values a filter can choose
    /promotion/designer/library      reusable boxes: save one for every designer, delete one
    /promotion/designer/google       the Google Analytics connection

Who: the Promotion dashboard is the `promo` page (a role gives it; an Influencer account has it too); designing is
`mkt_design` (the Marketing head profile). Every route checks itself as well as the staff guard: an influencer is
not staff, and the guard only turns staff away.
"""
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.services import access, ga4, mkt_dashboards as md, mkt_engine as eng

marketing_bp = Blueprint('marketing', __name__, url_prefix='/promotion')

VIEW_ENDPOINTS = ('main.promo_dashboard', 'marketing.box', 'marketing.live')
DESIGN_ENDPOINTS = ('marketing.designer', 'marketing.designer_new', 'marketing.designer_edit',
                    'marketing.designer_save', 'marketing.designer_publish', 'marketing.designer_unpublish',
                    'marketing.designer_discard', 'marketing.designer_duplicate', 'marketing.designer_delete',
                    'marketing.designer_move', 'marketing.preview', 'marketing.options', 'marketing.library_add',
                    'marketing.library_delete', 'marketing.google',
                    'marketing.google_test', 'marketing.google_disconnect')


def _period(args, default='last_30'):
    return eng.period_for(args.get('range') or default, args.get('from'), args.get('to'))


def _json_error(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code


def _deny_view():
    if not md.can_view(current_user):
        if request.accept_mimetypes.best == 'application/json' or request.path.endswith(('/box', '/live')):
            return _json_error('Your role does not include the Promotion dashboard.', 403)
        flash('That dashboard is for the promotion team.', 'warning')
        return redirect(url_for('main.index'))
    return None


def _deny_design():
    if not md.can_design(current_user):
        if request.method != 'GET' or request.is_json:
            return _json_error('Only somebody who designs dashboards can do that.', 403)
        flash('Designing dashboards is for the Marketing head.', 'warning')
        return redirect(url_for('main.promo_dashboard'))
    return None


# ================================================================================================ the dashboard

def _which(tabs, key, draft):
    """The tab asked for (`d`), and the boxes to show: a designer may look at a draft (`draft=1`)."""
    dash = None
    if key and key != 'overview':
        dash = md.find(key)
        if dash is not None and (draft or dash.published is None) and md.can_design(current_user):
            return dash, md.boxes_for(dash, draft=True), True
        if dash is None or not any(t['key'] == str(dash.id) and not t['draft'] for t in tabs):
            return None, md.overview(), False
        return dash, md.boxes_for(dash), False
    return None, md.overview(), False


def page():
    """The Promotion dashboard (main.promo_dashboard). Read-only: the date picker is a GET form."""
    denied = _deny_view()
    if denied:
        return denied
    tabs = md.tabs(current_user)
    dash, boxes, is_draft = _which(tabs, request.args.get('d'), request.args.get('draft') == '1')
    period = _period(request.args, default=(dash.range_key if dash is not None else 'last_30'))
    items = md.render(boxes, period, current_user)
    from app.services import promo
    return render_template('pages/promo_dashboard.html', tabs=tabs, here=str(dash.id) if dash else 'overview',
                           reach=promo.reach(),
                           dash=dash, items=items, period=period, ranges=eng.PAGE_RANGES, is_draft=is_draft,
                           designer=md.can_design(current_user), ga=ga4.status(),
                           staff=access.is_staff(current_user))


@marketing_bp.route('/box')
@login_required
def box():
    """One box's numbers, for the page's script: `d` the tab, `b` the box id, and the page's dates."""
    denied = _deny_view()
    if denied:
        return denied
    tabs = md.tabs(current_user)
    _, boxes, _ = _which(tabs, request.args.get('d'), request.args.get('draft') == '1')
    found = next((b for b in boxes if b['id'] == request.args.get('b')), None)
    if found is None:
        return _json_error('That box is not on this dashboard any more. Reload the page.', 404)
    return jsonify(md.run_one(found, _period(request.args), current_user))


@marketing_bp.route('/live')
@login_required
def live():
    """Who is on the website now: the total, by device, by country and by page (the last 30 minutes)."""
    denied = _deny_view()
    if denied:
        return denied
    if not ga4.connected():
        return jsonify({'ok': False, 'connected': False})
    try:
        total = ga4.realtime(['activeUsers'])
        devices = ga4.realtime(['activeUsers'], ['deviceCategory'], limit=5)
        countries = ga4.realtime(['activeUsers'], ['country'], limit=6)
        pages = ga4.realtime(['activeUsers'], ['unifiedScreenName'], limit=5)
        minutes = ga4.realtime(['activeUsers'], ['minutesAgo'], limit=30)
    except ga4.GAError as e:
        return jsonify({'ok': False, 'connected': True, 'error': str(e)})
    by_minute = {int(r[0]): r[1] for r in minutes['rows'] if str(r[0]).isdigit()}

    def rows(data, label=lambda v: v):
        return [{'label': label(r[0]), 'n': r[1]} for r in data['rows']]
    return jsonify({'ok': True, 'now': (total['totals'] or [0])[0],
                    'devices': rows(devices, lambda v: (v or '').capitalize()), 'countries': rows(countries),
                    'pages': rows(pages), 'minutes': [by_minute.get(m, 0) for m in range(29, -1, -1)]})


# ================================================================================================ the designer

@marketing_bp.route('/designer')
@login_required
def designer():
    denied = _deny_design()
    if denied:
        return denied
    from app.models import MktDashboard
    rows = MktDashboard.query.order_by(MktDashboard.position, MktDashboard.id).all()
    return render_template('marketing/designer_list.html', rows=rows, ga=ga4.status(), audiences=md.AUDIENCES)


@marketing_bp.route('/designer/new', methods=['POST'])
@login_required
def designer_new():
    denied = _deny_design()
    if denied:
        return denied
    try:
        d = md.create(current_user, request.form.get('name'), start=request.form.get('start') or 'blank')
    except md.DashError as e:
        flash(str(e), 'warning')
        return redirect(url_for('marketing.designer'))
    return redirect(url_for('marketing.designer_edit', dash_id=d.id))


def _dash_or_404(dash_id):
    d = md.find(dash_id)
    if d is None:
        abort(404)
    return d


@marketing_bp.route('/designer/<int:dash_id>')
@login_required
def designer_edit(dash_id):
    denied = _deny_design()
    if denied:
        return denied
    d = _dash_or_404(dash_id)
    suggestions = [{'group': g, 'name': n, 'box': b} for g, n, b in md.SUGGESTIONS]
    return render_template('marketing/designer.html', dash=d, boxes=md.boxes_for(d, draft=True),
                           catalogue=eng.catalogue(), suggestions=suggestions, ranges=eng.PAGE_RANGES,
                           audiences=md.AUDIENCES, ga=ga4.status(), library=md.library())


@marketing_bp.route('/designer/<int:dash_id>/save', methods=['POST'])
@login_required
def designer_save(dash_id):
    denied = _deny_design()
    if denied:
        return denied
    d = _dash_or_404(dash_id)
    try:
        md.save(current_user, d, request.get_json(silent=True) or {})
        if (request.get_json(silent=True) or {}).get('publish'):
            md.publish(current_user, d)
    except md.DashError as e:
        return _json_error(str(e))
    return jsonify({'ok': True, 'boxes': d.draft, 'published': d.is_published, 'changes': d.has_changes,
                    'saved': d.updated_at.strftime('%H:%M') if d.updated_at else ''})


def _form_action(dash_id, fn, done):
    denied = _deny_design()
    if denied:
        return denied
    d = _dash_or_404(dash_id)
    try:
        fn(d)
        if done:
            flash(done % d.name if '%s' in done else done, 'success')
    except md.DashError as e:
        flash(str(e), 'warning')
    back = request.form.get('next')
    from app.services import urls
    return redirect(urls.safe_next(back) or url_for('marketing.designer'))


@marketing_bp.route('/designer/<int:dash_id>/publish', methods=['POST'])
@login_required
def designer_publish(dash_id):
    return _form_action(dash_id, lambda d: md.publish(current_user, d),
                        '"%s" is published: everybody it is for sees it on the Promotion dashboard.')


@marketing_bp.route('/designer/<int:dash_id>/unpublish', methods=['POST'])
@login_required
def designer_unpublish(dash_id):
    return _form_action(dash_id, lambda d: md.unpublish(current_user, d),
                        '"%s" is off the Promotion dashboard. Its boxes are kept as a draft.')


@marketing_bp.route('/designer/<int:dash_id>/discard', methods=['POST'])
@login_required
def designer_discard(dash_id):
    return _form_action(dash_id, lambda d: md.discard(current_user, d),
                        'The changes to "%s" are thrown away: it is back to what people see.')


@marketing_bp.route('/designer/<int:dash_id>/duplicate', methods=['POST'])
@login_required
def designer_duplicate(dash_id):
    return _form_action(dash_id, lambda d: md.duplicate(current_user, d), 'A copy of "%s" is in the list, as a draft.')


@marketing_bp.route('/designer/<int:dash_id>/delete', methods=['POST'])
@login_required
def designer_delete(dash_id):
    return _form_action(dash_id, lambda d: md.delete(current_user, d), 'The dashboard is deleted.')


@marketing_bp.route('/designer/<int:dash_id>/move', methods=['POST'])
@login_required
def designer_move(dash_id):
    return _form_action(dash_id, lambda d: md.move(current_user, d, request.form.get('direction')), '')


@marketing_bp.route('/designer/preview', methods=['POST'])
@login_required
def preview():
    """One box's numbers while it is being designed. Saves nothing."""
    denied = _deny_design()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        b = eng.clean_box(body.get('box') or {})
    except eng.EngineError as e:
        return _json_error(str(e))
    period = _period(body)
    out = {'ok': True, 'kind': b['chart'], 'title': eng.describe(b)}
    if b['chart'] == 'quotes':
        from app.services import promo
        out['quotes'] = [{'text': q['text'], 'rating': q['rating'], 'site': q['site'], 'who': q['who']}
                         for q in promo.quotable(limit=b.get('top') or 6)]
        return jsonify(out)
    if b['chart'] == 'links':
        from app.services import promo
        out['links'] = promo.links()
        return jsonify(out)
    if b['chart'] == 'text':
        return jsonify(out)
    res = eng.run(b, period, current_user)
    res['title'] = out['title']
    return jsonify(res)


@marketing_bp.route('/designer/library', methods=['POST'])
@login_required
def library_add():
    """Save a box to the library every designer can use again (JSON: {name, box})."""
    denied = _deny_design()
    if denied:
        return denied
    body = request.get_json(silent=True) or {}
    try:
        rows = md.library_add(current_user, body.get('name'), body.get('box'))
    except md.DashError as e:
        return _json_error(str(e))
    return jsonify({'ok': True, 'library': rows})


@marketing_bp.route('/designer/library/<lid>/delete', methods=['POST'])
@login_required
def library_delete(lid):
    denied = _deny_design()
    if denied:
        return denied
    return jsonify({'ok': True, 'library': md.library_delete(current_user, lid)})


@marketing_bp.route('/designer/options')
@login_required
def options():
    denied = _deny_design()
    if denied:
        return denied
    try:
        vals = eng.options(request.args.get('source') or '', request.args.get('dim') or '')
    except (eng.EngineError, ga4.GAError) as e:
        return _json_error(str(e))
    return jsonify({'ok': True, 'values': vals})


# ================================================================================================ Google Analytics

@marketing_bp.route('/designer/google', methods=['GET', 'POST'])
@login_required
def google():
    denied = _deny_design()
    if denied:
        return denied
    if request.method == 'POST':
        try:
            ga4.save(request.form.get('property_id'), request.form.get('key_json'), by=current_user,
                     sc_site=request.form.get('sc_site') or '')
        except ga4.GAError as e:
            flash(str(e), 'warning')
            return redirect(url_for('marketing.google'))
        flash('Saved. Use "Test the connection" to see the first numbers.', 'success')
        return redirect(url_for('marketing.google'))
    from app.services import analytics
    return render_template('marketing/google.html', ga=ga4.status(), measurement_id=analytics.ga4_id(),
                           site_verification=bool(analytics.site_verification()))


@marketing_bp.route('/designer/google/test', methods=['POST'])
@login_required
def google_test():
    """A small real question to each of the two that are set up: Analytics and Search Console."""
    denied = _deny_design()
    if denied:
        return denied
    from app.services import gsc
    if not ga4.connected() and not gsc.connected():
        flash('Nothing to test yet: save the key and a property first.', 'warning')
    if ga4.connected():
        try:
            got = ga4.test()
        except ga4.GAError as e:
            flash('Google Analytics did not work: %s' % e, 'warning')
        else:
            flash('Google Analytics works: %s visitors and %s visits in the last 7 days, %s on the site right now.'
                  % ('{:,}'.format(got['users']), '{:,}'.format(got['sessions']), '{:,}'.format(got['now'])),
                  'success')
    if gsc.connected():
        try:
            got = gsc.test()
        except ga4.GAError as e:
            flash('Search Console did not work: %s' % e, 'warning')
        else:
            flash('Search Console works: %s clicks from Google and shown %s times in the last 28 days.'
                  % ('{:,}'.format(got['clicks']), '{:,}'.format(got['impressions'])), 'success')
    return redirect(url_for('marketing.google'))


@marketing_bp.route('/designer/google/disconnect', methods=['POST'])
@login_required
def google_disconnect():
    denied = _deny_design()
    if denied:
        return denied
    ga4.disconnect(by=current_user)
    flash('Google is disconnected. The website and search boxes say so until it is connected again.', 'success')
    return redirect(url_for('marketing.google'))
