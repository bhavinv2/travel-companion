"""CS Excel/CSV import: upload → preview (validated, de-duplicated) → commit as unconfirmed posts."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.routes.cs import cs_required, _choices
from app.services import importer

imports_bp = Blueprint('imports', __name__)


@imports_bp.route('/cs/import', methods=['GET', 'POST'])
@login_required
@cs_required
def import_page():
    if request.method == 'POST' and request.form.get('step') == 'commit':
        rows = importer.payload_to_rows(request.form.get('payload'))
        selected = set(request.form.getlist('include'))
        for r in rows:
            if str(r.get('idx')) not in selected:
                r['status'] = 'skipped'
        importer.annotate_duplicates([r for r in rows if r.get('status') == 'ok']) if rows else None
        created = importer.commit_rows(rows, current_user)
        flash(f'Imported {len(created)} post(s) as unconfirmed.', 'success')
        return redirect(url_for('cs.posts', status='unconfirmed', sort='newest'))

    if request.method == 'POST':
        f = request.files.get('file')
        if not f or not f.filename:
            flash('Choose an .xlsx or .csv file.', 'danger')
            return redirect(url_for('imports.import_page'))
        default_source = request.form.get('default_source') if request.form.get('default_source') in ('facebook', 'website', 'excel') else 'website'
        records, err = importer.parse_file(f.stream, f.filename)
        if err:
            flash(err, 'danger')
            return redirect(url_for('imports.import_page'))
        rows = importer.annotate_duplicates([importer.build_row(rec, i, default_source) for i, rec in enumerate(records)])
        counts = {s: sum(1 for r in rows if r['status'] == s) for s in ('ok', 'error', 'duplicate')}
        return render_template('cs/import.html', rows=rows, counts=counts, payload=importer.rows_to_payload(rows),
                               filename=f.filename, **_choices())

    return render_template('cs/import.html', rows=None, counts=None, payload=None, filename=None, **_choices())
