"""Admin web-scraping console: recipes, detection, teach/paste, mapping, runs, rows -> posts, export."""
import json
import os
from functools import wraps

from flask import (Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort,
                   current_app, send_file, after_this_request)
from flask_login import login_required, current_user

from app import db
from app.models import (ScrapeRecipe, ScrapeRun, ScrapeRow, ActivityEvent, TRIP_SOURCES,
                        SCRAPE_ROW_STATUSES, SCRAPE_RUN_STATUSES)
from app.routes.admin import admin_required
from app.routes.cs import _choices
from app.services import scraper, scraper_worker

scraper_bp = Blueprint('scraper', __name__)

ROWS_PER_PAGE = 50


@scraper_bp.before_request
def _gate():
    if not current_app.config.get('SCRAPER_ENABLED', True):
        abort(404)


def _wants_json():
    return request.is_json or request.path.startswith('/cs/scraper/api/') or request.args.get('format') == 'json'


def _require_available():
    """Return a response when scraping cannot run on this server, else None."""
    avail = scraper.availability()
    if avail['ok']:
        return None
    if _wants_json():
        return jsonify({'error': avail['message']}), 503
    flash(avail['message'], 'danger')
    return redirect(url_for('scraper.recipes'))


def _ctx(**extra):
    d = dict(_choices())
    d.update(availability=scraper.availability(), headed_teach=bool(current_app.config.get('SCRAPER_HEADED_TEACH')),
             targets=scraper.canonical_targets())
    d.update(extra)
    return d


def _run_or_404(run_id, kind=None):
    run = ScrapeRun.query.get_or_404(run_id)
    if kind and run.kind != kind:
        abort(404)
    return run


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------

@scraper_bp.route('/')
@login_required
@admin_required
def recipes():
    scraper_worker.recover_stale_runs()
    try:
        page = max(int(request.args.get('page') or 1), 1)
    except ValueError:
        page = 1
    per_page = 20
    query = ScrapeRecipe.query.order_by(ScrapeRecipe.created_at.desc())
    total = query.count()
    pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, pages)
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    counts = {}
    for r in items:
        counts[r.id] = {
            'rows': r.rows.count(),
            'new': r.rows.filter_by(status='new').count(),
            'imported': r.rows.filter_by(status='imported').count(),
            'active': r.active_run,
        }
    return render_template('cs/scraper/recipes.html', recipes=items, counts=counts, page=page, pages=pages, **_ctx())


@scraper_bp.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_recipe():
    if request.method == 'POST':
        blocked = _require_available()
        if blocked:
            return blocked
        url = (request.form.get('url') or '').strip()
        if not url.startswith(('http://', 'https://')):
            flash('Enter the full page URL, starting with http:// or https://', 'danger')
            return render_template('cs/scraper/new.html', run=None, form=request.form, **_ctx())
        try:
            wait = float(request.form.get('wait') or 4)
        except ValueError:
            wait = 4.0
        run = scraper_worker.enqueue('detect', options={'url': url, 'wait': max(1.0, min(wait, 30.0)),
                                                         'name': (request.form.get('name') or '').strip()[:120],
                                                         'default_source': request.form.get('default_source') or 'website'},
                                     actor=current_user)
        return redirect(url_for('scraper.new_recipe_detect', run_id=run.id))
    return render_template('cs/scraper/new.html', run=None, form=None, **_ctx())


@scraper_bp.route('/new/<int:run_id>')
@login_required
@admin_required
def new_recipe_detect(run_id):
    run = _run_or_404(run_id, 'detect')
    return render_template('cs/scraper/new.html', run=run, form=None, **_ctx())


@scraper_bp.route('/new/<int:run_id>/use-source', methods=['POST'])
@login_required
@admin_required
def use_source(run_id):
    run = _run_or_404(run_id, 'detect')
    if not run.done or not (run.result or {}).get('candidates'):
        flash('Detection has not finished yet.', 'danger')
        return redirect(url_for('scraper.new_recipe_detect', run_id=run.id))
    try:
        idx = int(request.form.get('candidate'))
        cand = run.result['candidates'][idx]
    except (TypeError, ValueError, IndexError):
        flash('Pick a data source.', 'danger')
        return redirect(url_for('scraper.new_recipe_detect', run_id=run.id))
    opts = run.options or {}
    name = (request.form.get('name') or opts.get('name') or scraper.site_of(opts.get('url', ''))).strip()[:120] or 'recipe'
    if ScrapeRecipe.query.filter_by(name=name).first():
        name = f'{name}-{run.id}'
    columns = list(cand['columns'])
    rec = ScrapeRecipe(
        name=name, site=scraper.site_of(run.result.get('page_url') or opts.get('url', '')),
        start_url=opts.get('url') or run.result.get('page_url'), mode='source',
        source_json={'source': cand['source'], 'kind': cand['kind'], 'page_url': run.result.get('page_url'),
                     'columns': columns, 'detected_rows': cand.get('rows')},
        field_mapping=scraper.suggest_mapping(columns + ['_url', '_key']),
        default_source=opts.get('default_source') if opts.get('default_source') in TRIP_SOURCES else 'website',
        created_by_id=current_user.id,
    )
    db.session.add(rec)
    db.session.commit()
    ActivityEvent.log('scrape_recipe_created', actor=current_user, recipe_id=rec.id, mode='source', source=cand['source'])
    db.session.commit()
    flash(f'Recipe "{rec.name}" created from the detected {cand["kind"]} source. Check the field mapping, then run it.', 'success')
    return redirect(url_for('scraper.mapping', recipe_id=rec.id))


@scraper_bp.route('/new/teach', methods=['POST'])
@login_required
@admin_required
def start_teach():
    blocked = _require_available()
    if blocked:
        return blocked
    url = (request.form.get('url') or '').strip()
    if not url.startswith(('http://', 'https://')):
        flash('Enter the page URL first.', 'danger')
        return redirect(url_for('scraper.new_recipe'))
    try:
        run = scraper_worker.enqueue('teach', options={'url': url, 'name': (request.form.get('name') or '').strip()[:120],
                                                        'default_source': request.form.get('default_source') or 'website'},
                                     actor=current_user)
    except scraper.ScraperUnavailable as e:
        flash(str(e), 'danger')
        return redirect(url_for('scraper.new_recipe'))
    flash('A browser window is opening on this machine. Follow the panel, click Save, then come back here.', 'info')
    return redirect(url_for('scraper.recipe_form', teach_run=run.id))


@scraper_bp.route('/recipes/new', methods=['GET', 'POST'], defaults={'recipe_id': None})
@scraper_bp.route('/recipes/<int:recipe_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def recipe_form(recipe_id):
    rec = ScrapeRecipe.query.get_or_404(recipe_id) if recipe_id else None
    teach_run = None
    if request.args.get('teach_run'):
        teach_run = ScrapeRun.query.get(int(request.args['teach_run']))
        if teach_run and teach_run.kind != 'teach':
            teach_run = None
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()[:120]
        raw = request.form.get('recipe_json') or ''
        upload = request.files.get('recipe_file')
        if upload and upload.filename:
            raw = upload.read().decode('utf-8', errors='replace')
        try:
            recipe = json.loads(raw) if raw.strip() else {}
        except ValueError as e:
            flash(f'Recipe JSON is not valid: {e}', 'danger')
            return render_template('cs/scraper/recipe_form.html', recipe=rec, form=request.form, teach_run=teach_run, **_ctx())
        errors = scraper.validate_recipe(recipe)
        if not name:
            errors.insert(0, 'Name is required.')
        clash = ScrapeRecipe.query.filter_by(name=name).first()
        if clash and (rec is None or clash.id != rec.id):
            errors.insert(0, f'A recipe named "{name}" already exists.')
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('cs/scraper/recipe_form.html', recipe=rec, form=request.form, teach_run=teach_run, **_ctx())
        if rec is None:
            rec = ScrapeRecipe(created_by_id=current_user.id, mode='recipe')
            db.session.add(rec)
        rec.name = name
        rec.mode = 'recipe'
        rec.recipe_json = recipe
        rec.start_url = recipe['start_url']
        rec.site = recipe.get('site') or scraper.site_of(recipe['start_url'])
        rec.default_source = request.form.get('default_source') if request.form.get('default_source') in TRIP_SOURCES else 'website'
        sess = request.files.get('session_file')
        if sess and sess.filename:
            from werkzeug.utils import secure_filename
            key = secure_filename(f'{rec.site}-{sess.filename}')[:120]
            folder = current_app.config['SCRAPER_SESSION_DIR']
            os.makedirs(folder, exist_ok=True)
            sess.save(os.path.join(folder, key))
            rec.session_key = key
        rec.field_mapping = scraper.merge_mapping(rec.field_mapping, rec.columns)
        db.session.commit()
        ActivityEvent.log('scrape_recipe_saved', actor=current_user, recipe_id=rec.id)
        db.session.commit()
        flash('Recipe saved. Check the field mapping below.', 'success')
        return redirect(url_for('scraper.mapping', recipe_id=rec.id))
    return render_template('cs/scraper/recipe_form.html', recipe=rec, form=None, teach_run=teach_run, **_ctx())


@scraper_bp.route('/api/recipes/preview', methods=['POST'])
@login_required
@admin_required
def preview_recipe():
    blocked = _require_available()
    if blocked:
        return blocked
    data = request.get_json(silent=True) or {}
    recipe = data.get('recipe')
    if isinstance(recipe, str):
        try:
            recipe = json.loads(recipe)
        except ValueError as e:
            return jsonify({'error': f'Recipe JSON is not valid: {e}'}), 400
    errors = scraper.validate_recipe(recipe or {})
    if errors:
        return jsonify({'error': ' '.join(errors)}), 400
    run = scraper_worker.enqueue('preview', options={'recipe': recipe, 'session_key': data.get('session_key')},
                                 actor=current_user)
    return jsonify({'run_id': run.id, 'status': run.status})


@scraper_bp.route('/recipes/<int:recipe_id>/mapping', methods=['GET', 'POST'])
@login_required
@admin_required
def mapping(recipe_id):
    rec = ScrapeRecipe.query.get_or_404(recipe_id)
    columns = rec.columns
    if request.method == 'POST':
        new_map = {}
        valid = {k for k, _ in scraper.canonical_targets()}
        for col in columns:
            target = request.form.get(f'map__{col}') or scraper.IGNORE
            new_map[col] = target if target in valid else scraper.IGNORE
        rec.field_mapping = new_map
        rec.default_source = request.form.get('default_source') if request.form.get('default_source') in TRIP_SOURCES else rec.default_source
        db.session.commit()
        flash('Mapping saved.', 'success')
        nxt = request.form.get('next')
        return redirect(nxt if nxt and nxt.startswith('/') else url_for('scraper.recipe_runs', recipe_id=rec.id))
    mapping_now = scraper.merge_mapping(rec.field_mapping, columns)
    sample_row = rec.rows.order_by(ScrapeRow.id.desc()).first()
    samples = {}
    if sample_row:
        samples = {c: (sample_row.data or {}).get(c, '') for c in columns}
    elif rec.mode == 'source':
        samples = {}
    preview = scraper.import_row_for(sample_row, rec, mapping_now) if sample_row else None
    return render_template('cs/scraper/mapping.html', recipe=rec, columns=columns, mapping=mapping_now,
                           samples=samples, sample_row=sample_row, preview=preview, **_ctx())


@scraper_bp.route('/api/recipes/<int:recipe_id>/mapping/preview', methods=['POST'])
@login_required
@admin_required
def mapping_preview(recipe_id):
    rec = ScrapeRecipe.query.get_or_404(recipe_id)
    data = request.get_json(silent=True) or {}
    mapping_now = {c: (data.get('mapping') or {}).get(c, scraper.IGNORE) for c in rec.columns}
    row = None
    if data.get('row_id'):
        row = ScrapeRow.query.filter_by(id=int(data['row_id']), recipe_id=rec.id).first()
    if row is None:
        row = rec.rows.order_by(ScrapeRow.id.desc()).first()
    if row is None:
        return jsonify({'preview': None, 'message': 'Run the recipe once to preview a mapped row.'})
    r = scraper.import_row_for(row, rec, mapping_now)
    return jsonify({'preview': r})


@scraper_bp.route('/recipes/<int:recipe_id>/runs')
@login_required
@admin_required
def recipe_runs(recipe_id):
    rec = ScrapeRecipe.query.get_or_404(recipe_id)
    scraper_worker.recover_stale_runs()
    runs = rec.runs.filter(ScrapeRun.kind == 'run').order_by(ScrapeRun.created_at.desc()).limit(50).all()
    stats = {'rows': rec.rows.count(), 'new': rec.rows.filter_by(status='new').count(),
             'imported': rec.rows.filter_by(status='imported').count()}
    return render_template('cs/scraper/runs.html', recipe=rec, runs=runs, stats=stats, active=rec.active_run, **_ctx())


@scraper_bp.route('/recipes/<int:recipe_id>/run', methods=['POST'])
@login_required
@admin_required
def start_run(recipe_id):
    rec = ScrapeRecipe.query.get_or_404(recipe_id)
    blocked = _require_available()
    if blocked:
        return blocked
    src = request.get_json(silent=True) or request.form

    def _int(v):
        try:
            return int(v) if v not in (None, '') else None
        except (TypeError, ValueError):
            return None
    options = {'incremental': src.get('incremental', 'on') not in ('off', 'false', False, '0'),
               'max_pages': _int(src.get('max_pages')), 'max_rows': _int(src.get('max_rows'))}
    try:
        run = scraper_worker.enqueue('run', recipe=rec, options=options, actor=current_user)
    except scraper_worker.AlreadyRunning as e:
        if _wants_json():
            return jsonify({'error': str(e), 'run_id': e.run.id}), 409
        flash(str(e), 'info')
        return redirect(url_for('scraper.run_detail', run_id=e.run.id))
    except scraper.ScraperUnavailable as e:
        if _wants_json():
            return jsonify({'error': str(e)}), 503
        flash(str(e), 'danger')
        return redirect(url_for('scraper.recipe_runs', recipe_id=rec.id))
    if _wants_json():
        return jsonify({'run_id': run.id, 'status': run.status})
    return redirect(url_for('scraper.run_detail', run_id=run.id))


@scraper_bp.route('/recipes/<int:recipe_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_recipe(recipe_id):
    rec = ScrapeRecipe.query.get_or_404(recipe_id)
    what = request.form.get('what')
    if what == 'active':
        rec.is_active = not rec.is_active
    elif what == 'schedule':
        rec.schedule_enabled = not rec.schedule_enabled
        try:
            rec.schedule_every_hours = max(1, int(request.form.get('every_hours') or rec.schedule_every_hours or 24))
        except ValueError:
            pass
    db.session.commit()
    flash('Recipe updated.', 'success')
    return redirect(request.form.get('next') or url_for('scraper.recipes'))


@scraper_bp.route('/recipes/<int:recipe_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_recipe(recipe_id):
    rec = ScrapeRecipe.query.get_or_404(recipe_id)
    if rec.active_run:
        flash('Cancel the running job first.', 'danger')
        return redirect(url_for('scraper.recipes'))
    db.session.delete(rec)   # runs and rows cascade; created posts are untouched
    db.session.commit()
    flash(f'Recipe "{rec.name}" and its scraped rows were deleted. Posts already created are kept.', 'success')
    return redirect(url_for('scraper.recipes'))


# ---------------------------------------------------------------------------
# Runs & rows
# ---------------------------------------------------------------------------

@scraper_bp.route('/runs/<int:run_id>')
@login_required
@admin_required
def run_detail(run_id):
    run = _run_or_404(run_id)
    if run.kind == 'detect':
        return redirect(url_for('scraper.new_recipe_detect', run_id=run.id))
    if run.kind != 'run':
        abort(404)
    scraper_worker.recover_stale_runs()
    rec = run.recipe
    status = request.args.get('status') or 'new'
    page = max(int(request.args.get('page') or 1), 1)
    q = ScrapeRow.query.filter_by(run_id=run.id)
    if status in SCRAPE_ROW_STATUSES:
        q = q.filter_by(status=status)
    total = q.count()
    rows = q.order_by(ScrapeRow.id).offset((page - 1) * ROWS_PER_PAGE).limit(ROWS_PER_PAGE).all()
    previews = {p['scrape_row_id']: p for p in scraper.preview_rows(rows, rec)} if rows else {}
    counts = {s: ScrapeRow.query.filter_by(run_id=run.id, status=s).count() for s in SCRAPE_ROW_STATUSES}
    pages = max((total + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE, 1)
    return render_template('cs/scraper/run.html', run=run, recipe=rec, rows=rows, previews=previews, counts=counts,
                           status=status, page=page, pages=pages, total=total, **_ctx())


@scraper_bp.route('/api/runs/<int:run_id>/status')
@login_required
@admin_required
def run_status(run_id):
    run = _run_or_404(run_id)
    if not run.done:
        scraper_worker.recover_stale_runs()
        db.session.refresh(run)
    return jsonify(run.to_dict())


@scraper_bp.route('/runs/<int:run_id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel_run(run_id):
    run = _run_or_404(run_id)
    if run.done:
        flash('This job has already finished.', 'info')
    else:
        scraper_worker.request_cancel(run)
        flash('Cancellation requested — the job stops after the current item.', 'info')
    if _wants_json():
        return jsonify({'success': True, 'status': run.status})
    return redirect(request.form.get('next') or url_for('scraper.run_detail', run_id=run.id)
                    if run.kind == 'run' else url_for('scraper.recipes'))


def _selected_row_ids(run):
    if request.form.get('select') == 'all_new':
        return [r.id for r in ScrapeRow.query.filter_by(run_id=run.id, status='new').all()]
    ids = []
    for v in request.form.getlist('include'):
        try:
            ids.append(int(v))
        except ValueError:
            continue
    return ids


@scraper_bp.route('/runs/<int:run_id>/create-posts', methods=['POST'])
@login_required
@admin_required
def create_posts(run_id):
    run = _run_or_404(run_id, 'run')
    ids = _selected_row_ids(run)
    if not ids:
        flash('Select at least one new row.', 'danger')
        return redirect(url_for('scraper.run_detail', run_id=run.id, status='new'))
    publish_now = request.form.get('publish_now') == 'on'
    result = scraper.create_posts(run.recipe, ids, current_user, publish_now=publish_now)
    msg = f"Created {result['created']} {'open' if publish_now else 'unconfirmed'} post(s)"
    if result['duplicates']:
        msg += f", {result['duplicates']} already existed"
    if result['errors']:
        msg += f", {len(result['errors'])} could not be created (fix the mapping or open them in the post form)"
    flash(msg + '.', 'success' if result['created'] else 'info')
    for e in result['errors'][:5]:
        flash(f"Row #{e['row_id']}: " + ' '.join(e['errors']), 'danger')
    return redirect(url_for('scraper.run_detail', run_id=run.id, status='imported' if result['created'] else 'new'))


@scraper_bp.route('/runs/<int:run_id>/skip', methods=['POST'])
@login_required
@admin_required
def skip_rows(run_id):
    run = _run_or_404(run_id, 'run')
    n = scraper.skip_rows(run.recipe, _selected_row_ids(run), current_user)
    flash(f'Skipped {n} row(s).', 'info')
    return redirect(url_for('scraper.run_detail', run_id=run.id))


@scraper_bp.route('/api/rows/<int:row_id>')
@login_required
@admin_required
def row_detail(row_id):
    row = ScrapeRow.query.get_or_404(row_id)
    mapping = (row.recipe.field_mapping if row.recipe else None) or {}
    base = {k: v for k, v in (row.data or {}).items() if k != '_edits'}
    return jsonify({
        'row': row.to_dict(),
        'mapped': scraper.import_row_for(row, row.recipe),
        'canon': scraper.apply_mapping(row.data or {}, mapping),        # effective values (incl. corrections)
        'base': scraper.apply_mapping(base, mapping),                   # values from mapping alone
        'edits': (row.data or {}).get('_edits', {}),
        'mapping': mapping,
        'fields': [{'key': k, 'label': scraper.TARGET_LABELS.get(k, k)} for k in scraper.EDITABLE_TARGETS],
        'editable': row.status in ('new', 'skipped'),
    })


@scraper_bp.route('/api/rows/<int:row_id>/edit', methods=['POST'])
@login_required
@admin_required
def row_edit(row_id):
    """Save manual corrections for one scraped row (spellings, source, dates, ...)."""
    row = ScrapeRow.query.get_or_404(row_id)
    if row.status not in ('new', 'skipped'):
        return jsonify({'error': 'This row is already a post - edit the post itself instead.'}), 400
    payload = request.get_json(silent=True) or {}
    scraper.set_row_edits(row, payload.get('edits') or {}, current_user)
    mapped = scraper.preview_rows([row], row.recipe)[0]
    return jsonify({'success': True, 'edits': (row.data or {}).get('_edits', {}), 'mapped': mapped})


def _send_export(recipe, rows, mapped, run=None):
    path = scraper.export_workbook(recipe, rows, mapped=mapped, run=run)

    @after_this_request
    def _cleanup(response):
        try:
            os.remove(path)
        except OSError:
            pass
        return response

    return send_file(path, as_attachment=True, download_name=path.name,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@scraper_bp.route('/runs/<int:run_id>/export.xlsx')
@login_required
@admin_required
def export_run(run_id):
    run = _run_or_404(run_id, 'run')
    mapped = request.args.get('mapped') == '1'
    scope = request.args.get('scope') or 'run'
    ids = [int(x) for x in request.args.get('ids', '').split(',') if x.strip().isdigit()]
    if ids:
        rows = ScrapeRow.query.filter(ScrapeRow.recipe_id == run.recipe_id, ScrapeRow.id.in_(ids)).order_by(ScrapeRow.id).all()
    elif scope == 'all':
        rows = run.recipe.rows.order_by(ScrapeRow.id).all()
    else:
        rows = ScrapeRow.query.filter_by(run_id=run.id).order_by(ScrapeRow.id).all()
    ActivityEvent.log('scrape_exported', actor=current_user, recipe_id=run.recipe_id, run_id=run.id, rows=len(rows), mapped=mapped)
    db.session.commit()
    return _send_export(run.recipe, rows, mapped, run=run if scope != 'all' else None)


@scraper_bp.route('/recipes/<int:recipe_id>/export.xlsx')
@login_required
@admin_required
def export_recipe(recipe_id):
    rec = ScrapeRecipe.query.get_or_404(recipe_id)
    mapped = request.args.get('mapped') == '1'
    rows = rec.rows.order_by(ScrapeRow.id).all()
    ActivityEvent.log('scrape_exported', actor=current_user, recipe_id=rec.id, rows=len(rows), mapped=mapped)
    db.session.commit()
    return _send_export(rec, rows, mapped)
