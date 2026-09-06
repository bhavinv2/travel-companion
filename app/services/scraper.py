"""Admin web scraping — domain layer.

Recipes (taught with fetchall or detected data sources) produce ScrapeRows; a per-recipe *field mapping*
turns a scraped row into the importer's canonical record, and posts are created only through
`app.services.importer` so scraped posts follow the same rules as Excel imports (unconfirmed, unconsented
contact points, idempotent by import_key). Execution lives in `scraper_worker.py`.
"""
import difflib
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import MultiDict
from werkzeug.utils import secure_filename

from app import db
from app.models import ScrapeRecipe, ScrapeRow, ActivityEvent, SCRAPE_META_COLUMNS
from app.services import importer


class ScraperUnavailable(RuntimeError):
    pass


IGNORE = 'ignore'

TARGET_LABELS = {
    'title': 'Title / subject', 'message': 'Message / comments', 'origin': 'Origin (city or IATA)',
    'destination': 'Destination (city or IATA)', 'start': 'Departure date', 'end': 'Return date',
    'flight': 'Flight (e.g. QR573)', 'airline': 'Airline', 'role': 'Role (seeking / offering help)',
    'languages': 'Languages', 'contact': 'Contact (type auto-detected)', 'email': 'E-mail',
    'phone': 'Phone / WhatsApp', 'facebook': 'Facebook profile', 'poster_name': "Poster's name",
    'traveler_name': "Traveller's name", 'on_behalf_of': 'Relationship with the traveller',
    'need_help_with': 'Needs help with', 'pref_gender': 'Companion gender preference',
    'pref_age_min': 'Companion min age', 'pref_age_max': 'Companion max age', 'ticket_booked': 'Ticket booked',
    'source': 'Source (facebook / website)', 'source_url': 'Source URL', 'import_key': 'Import key (dedupe)',
}
MAPPED_EXPORT_COLUMNS = [
    'title', 'message', 'origin', 'destination', 'start', 'end', 'flight', 'airline', 'role', 'languages',
    'contact', 'email', 'phone', 'facebook', 'poster_name', 'traveler_name', 'on_behalf_of', 'need_help_with',
    'pref_gender', 'pref_age_min', 'pref_age_max', 'ticket_booked', 'source', 'source_url', 'import_key',
]


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------

_availability_cache: dict = {}


def is_enabled():
    return bool(current_app.config.get('SCRAPER_ENABLED', True))


def availability(force_refresh=False) -> dict:
    """{'ok', 'playwright', 'chromium', 'message', 'warning'} — whether scrapes can run on this server."""
    forced = current_app.config.get('SCRAPER_FORCE_AVAILABLE')
    if forced is not None:
        return {'ok': bool(forced), 'playwright': bool(forced), 'chromium': bool(forced), 'warning': '',
                'message': '' if forced else 'Scraping is not available on this server (test mode).'}
    if not is_enabled():
        return {'ok': False, 'playwright': False, 'chromium': False, 'warning': '',
                'message': 'Scraping is disabled on this server (SCRAPER_ENABLED=False).'}
    if not force_refresh and 'info' in _availability_cache:
        return _availability_cache['info']
    info = {'ok': False, 'playwright': False, 'chromium': False, 'message': '', 'warning': ''}
    try:
        import playwright.sync_api  # noqa: F401
        info['playwright'] = True
    except Exception:
        info['message'] = 'Playwright is not installed on this server (pip install playwright).'
        _availability_cache['info'] = info
        return info
    info['chromium'] = _chromium_installed()
    info['ok'] = True
    if not info['chromium']:
        info['warning'] = ('Could not confirm that Chromium is installed for Playwright; if runs fail, execute '
                           '"playwright install chromium" in the app environment.')
    _availability_cache['info'] = info
    return info


def _chromium_installed() -> bool:
    candidates = []
    base = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
    if base and base != '0':
        candidates.append(Path(base))
    if os.name == 'nt':
        candidates.append(Path(os.environ.get('LOCALAPPDATA', '')) / 'ms-playwright')
    candidates += [Path.home() / '.cache' / 'ms-playwright', Path.home() / 'Library' / 'Caches' / 'ms-playwright']
    if base == '0':
        try:
            import playwright
            candidates.append(Path(playwright.__file__).parent / 'driver' / 'package' / '.local-browsers')
        except Exception:
            pass
    for c in candidates:
        try:
            if c.is_dir() and any(p.name.startswith('chromium') for p in c.iterdir()):
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------

def validate_recipe(recipe) -> list:
    errors = []
    if not isinstance(recipe, dict):
        return ['The recipe must be a JSON object.']
    if not re.match(r'^https?://', str(recipe.get('start_url') or '')):
        errors.append('start_url must be an http(s) URL.')
    lst = recipe.get('list')
    if not isinstance(lst, dict) or not str(lst.get('row') or '').strip():
        errors.append('list.row (the item selector) is required.')
    fields = recipe.get('fields')
    if not isinstance(fields, dict) or not fields:
        errors.append('fields must be a non-empty object of {name: {"sel": ..., "attr": ...}}.')
    else:
        for name, spec in fields.items():
            if not isinstance(spec, dict) or 'sel' not in spec:
                errors.append(f'field "{name}" needs {{"sel": ..., "attr": ...}}.')
    detail = recipe.get('detail')
    if detail:
        if not isinstance(detail, dict):
            errors.append('detail must be an object.')
        else:
            if detail.get('mode', 'popup') not in ('popup', 'page', 'inline'):
                errors.append('detail.mode must be popup, page or inline.')
            if not isinstance(detail.get('fields', {}), dict):
                errors.append('detail.fields must be an object.')
    pag = recipe.get('paginate')
    if pag:
        if not isinstance(pag, dict):
            errors.append('paginate must be an object.')
        else:
            mode = pag.get('mode', 'click')
            if mode not in ('click', 'load_more', 'scroll'):
                errors.append('paginate.mode must be click, load_more or scroll.')
            if mode in ('click', 'load_more') and not str(pag.get('click') or '').strip():
                errors.append(f'paginate.click (the selector of the control) is required for mode "{mode}".')
    return errors


def recipe_columns(recipe: dict) -> list:
    fields = list((recipe.get('fields') or {}).keys())
    detail_fields = [c for c in ((recipe.get('detail') or {}).get('fields') or {}) if c not in fields]
    return fields + detail_fields + [m for m in SCRAPE_META_COLUMNS if m not in fields]


def site_of(url: str) -> str:
    from urllib.parse import urlsplit
    return urlsplit(url).netloc or url


# ---------------------------------------------------------------------------
# Field mapping (scraped column -> importer canonical column)
# ---------------------------------------------------------------------------

def canonical_targets() -> list:
    return [(IGNORE, '— ignore —')] + [(k, TARGET_LABELS.get(k, k)) for k in importer.COLUMN_ALIASES]


EDITABLE_TARGETS = [k for k in importer.COLUMN_ALIASES if k != 'import_key']


def set_row_edits(row: ScrapeRow, edits: dict, actor=None) -> dict:
    """Store per-row corrections (spellings, source, dates, ...) applied on top of the mapping.

    Values are canonical-target keyed; an empty value drops the mapped value; an empty dict clears all
    corrections. Used by previews, post creation and the mapped export alike (via apply_mapping)."""
    from app import db
    clean = {}
    for k, v in (edits or {}).items():
        if k not in EDITABLE_TARGETS:
            continue
        clean[k] = ('' if v is None else str(v).strip())[:500]
    data = dict(row.data or {})
    base = {c: t for c, t in data.items() if c != '_edits'}
    base_canon = apply_mapping(base, (row.recipe.field_mapping if row.recipe else None) or {})
    # keep only real differences from the plain mapping, so re-typing the original un-edits the field
    clean = {k: v for k, v in clean.items() if v != (base_canon.get(k) or '')}
    if clean:
        data['_edits'] = clean
    else:
        data.pop('_edits', None)
    row.data = data
    db.session.commit()
    return clean


def suggest_mapping(columns) -> dict:
    """Auto-map scraped column names using the importer's aliases, then a fuzzy match, else ignore."""
    aliases = list(importer._ALIAS_TO_CANON)
    mapping = {}
    for col in columns:
        norm = importer._norm_header(col)
        target = importer._ALIAS_TO_CANON.get(norm)
        if target is None and norm in importer.COLUMN_ALIASES:
            target = norm
        if target is None:
            close = difflib.get_close_matches(norm, aliases, n=1, cutoff=0.8)
            if close:
                target = importer._ALIAS_TO_CANON[close[0]]
        mapping[col] = target or IGNORE
    return mapping


def merge_mapping(existing: dict, columns) -> dict:
    """Keep the admin's choices, add suggestions for columns that appeared since."""
    existing = dict(existing or {})
    suggested = suggest_mapping([c for c in columns if c not in existing])
    existing.update(suggested)
    return {c: existing.get(c, IGNORE) for c in columns}


def apply_mapping(data: dict, mapping: dict) -> dict:
    """Scraped row -> importer canonical record. Title/message from several columns are joined."""
    canon = {}
    for col, target in (mapping or {}).items():
        if not target or target == IGNORE:
            continue
        val = data.get(col)
        if val in (None, ''):
            continue
        val = str(val)
        if canon.get(target):
            if target in ('title', 'message'):
                canon[target] = canon[target] + '\n' + val
        else:
            canon[target] = val
    if not canon.get('source_url') and data.get('_url'):
        canon['source_url'] = str(data['_url'])
    if not canon.get('import_key') and data.get('_key'):
        canon['import_key'] = str(data['_key'])
    # Manual corrections made on the run page override the mapped values (empty = drop the value).
    for k, v in (data.get('_edits') or {}).items():
        if v in (None, ''):
            canon.pop(k, None)
        else:
            canon[k] = str(v)
    return {k: v for k, v in canon.items() if v}


def row_key(data: dict, columns) -> str:
    k = data.get('_key')
    if k:
        return str(k)[:64]
    from app.vendor.fetchall.runner import _row_key
    return _row_key(data, [c for c in columns if not str(c).startswith('_')])


# ---------------------------------------------------------------------------
# Rows -> posts
# ---------------------------------------------------------------------------

def import_row_for(row: ScrapeRow, recipe: ScrapeRecipe, mapping=None) -> dict:
    canon = apply_mapping(row.data or {}, mapping if mapping is not None else (recipe.field_mapping or {}))
    r = importer.build_row(canon, row.id, recipe.default_source or 'website')
    r['scrape_row_id'] = row.id
    return r


def preview_rows(rows, recipe: ScrapeRecipe, mapping=None) -> list:
    built = [import_row_for(r, recipe, mapping) for r in rows]
    return importer.annotate_duplicates(built) if built else []


def create_posts(recipe: ScrapeRecipe, row_ids, actor, publish_now=False) -> dict:
    """Create posts for the selected 'new' rows through the importer. Idempotent by import_key."""
    result = {'created': 0, 'duplicates': 0, 'errors': [], 'post_ids': []}
    if not row_ids:
        return result
    rows = (ScrapeRow.query.filter(ScrapeRow.recipe_id == recipe.id, ScrapeRow.id.in_(list(row_ids)),
                                   ScrapeRow.status == 'new').all())
    built = preview_rows(rows, recipe)
    by_row_id = {r['scrape_row_id']: r for r in built}
    created = importer.commit_rows(built, actor)
    by_key = {t.import_key: t for t in created}
    now = datetime.utcnow()
    for row in rows:
        r = by_row_id.get(row.id)
        if r is None:
            continue
        trip = by_key.get(r.get('import_key'))
        if trip is not None:
            row.status = 'imported'
            row.imported_post_id = trip.id
            row.imported_at = now
            row.imported_by_id = actor.id if actor else None
            if publish_now:
                trip.set_status('open')
                trip.claimed_at = now
            ActivityEvent.log('post_scraped', trip, actor=actor, recipe_id=recipe.id, run_id=row.run_id,
                              scrape_row_id=row.id, published=bool(publish_now))
            result['created'] += 1
            result['post_ids'].append(trip.id)
        elif r.get('status') == 'duplicate':
            row.status = 'duplicate'
            row.duplicate_of_id = r.get('duplicate_of')
            result['duplicates'] += 1
        else:
            result['errors'].append({'row_id': row.id, 'errors': r.get('errors') or ['Could not create a post from this row.']})
    db.session.commit()
    if publish_now and created:
        from app.services import matching
        for trip in created:
            matching.compute_matches_for(trip, actor=actor)
    return result


def skip_rows(recipe: ScrapeRecipe, row_ids, actor=None) -> int:
    if not row_ids:
        return 0
    n = (ScrapeRow.query.filter(ScrapeRow.recipe_id == recipe.id, ScrapeRow.id.in_(list(row_ids)),
                                ScrapeRow.status == 'new')
         .update({'status': 'skipped'}, synchronize_session=False))
    db.session.commit()
    return n


def prefill_form(row: ScrapeRow, recipe: ScrapeRecipe):
    """(MultiDict, contact_rows) shaped like the CS post form's request.form, for 'open in post form'."""
    r = import_row_for(row, recipe)
    items = [
        ('source', r.get('source') or recipe.default_source or 'website'),
        ('source_url', r.get('source_url') or ''),
        ('poster_name', r.get('poster_name') or ''), ('traveler_name', r.get('traveler_name') or ''),
        ('on_behalf_of', r.get('on_behalf_of') or ''), ('role', r.get('role') or 'seeking_help'),
        ('trip_type', 'round_trip' if r.get('to_date') else 'one_way'),
        ('flying_from', r.get('flying_from') or ''), ('destination', r.get('destination') or ''),
        ('from_date', r.get('from_date') or ''), ('to_date', r.get('to_date') or ''),
        ('airline', r.get('airline') or ''), ('flight_number', r.get('flight_number') or ''),
        ('ticket_booked', 'on' if r.get('ticket_booked') else ''),
        ('pref_gender', r.get('pref_gender') or 'any'),
        ('pref_age_min', r.get('pref_age_min') or ''), ('pref_age_max', r.get('pref_age_max') or ''),
        ('additional_comments', '\n'.join(x for x in (r.get('title'), r.get('message')) if x)),
        ('cs_notes', f"Scraped row #{row.id} from {row.page_url or recipe.start_url}"),
        ('scrape_row_id', str(row.id)),
    ]
    items += [('traveller_needs', n) for n in (r.get('needs') or [])]
    items += [('preferred_languages', l) for l in (r.get('languages') or [])]
    contact_rows = [{'id': '', 'type': c['type'], 'value': c['value'], 'label': '', 'consent': False}
                    for c in (r.get('contacts') or [])]
    return MultiDict(items), contact_rows


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------

def export_workbook(recipe: ScrapeRecipe, rows, *, mapped=False, run=None) -> Path:
    """Write rows to an .xlsx in SCRAPER_EXPORT_DIR. `mapped` uses the importer's canonical columns so the
    file can be re-imported unchanged at /cs/import; otherwise the raw scraped columns are written."""
    from app.vendor.fetchall.excel import write_workbook, now_iso
    from app.vendor.fetchall.models import Table

    if mapped:
        columns = list(MAPPED_EXPORT_COLUMNS)
        out_rows = []
        for r in rows:
            canon = apply_mapping(r.data or {}, recipe.field_mapping or {})
            canon.setdefault('source', recipe.default_source or 'website')
            out_rows.append({c: canon.get(c, '') for c in columns})
    else:
        columns = list(recipe.columns)
        extra = sorted({k for r in rows for k in (r.data or {}) if k not in columns})
        columns += extra
        out_rows = [{**{c: (r.data or {}).get(c, '') for c in columns},
                     'scrape_status': r.status, 'post_id': r.imported_post_id or ''} for r in rows]
        columns += ['scrape_status', 'post_id']
    table = Table(columns=columns, rows=out_rows)
    # absolute: Flask's send_file resolves relative paths against app.root_path, not the working directory
    export_dir = Path(os.path.abspath(current_app.config['SCRAPER_EXPORT_DIR']))
    export_dir.mkdir(parents=True, exist_ok=True)
    stem = secure_filename(recipe.name) or 'scrape'
    name = f"{stem}-{'run' + str(run.id) if run else 'all'}-{'mapped' if mapped else 'raw'}-{uuid.uuid4().hex[:6]}.xlsx"
    meta = [{'sheet': 'rows', 'kind': recipe.mode, 'rows': len(out_rows), 'columns': len(columns), 'score': '',
             'source': (recipe.source_json or {}).get('source') or recipe.start_url,
             'page': recipe.start_url, 'fetched_at': now_iso()}]
    return write_workbook(export_dir / name, [('rows', table)], meta)
