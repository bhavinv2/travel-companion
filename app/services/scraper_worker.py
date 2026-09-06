"""Background execution of scraper jobs. The ScrapeRun row is the source of truth; the UI polls it.

Jobs run in a small per-process thread pool (Playwright's sync API needs a plain thread with no asyncio
loop, which worker threads are). One Chromium (~300-500 MB) per running job; SCRAPER_MAX_WORKERS defaults
to 1. A partial unique index on scrape_runs guarantees a recipe runs at most once at a time even across
gunicorn workers. Rows stream into the DB as they are scraped, so a killed worker keeps its progress and
the next (incremental) run continues where it stopped.
"""
import atexit
import os
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from flask import current_app
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from app import db
from app.models import ScrapeRecipe, ScrapeRun, ScrapeRow, CompanionRequest, SCRAPE_RUN_KINDS
from app.services import scraper


class AlreadyRunning(RuntimeError):
    def __init__(self, run):
        super().__init__(f'Run #{run.id} is already {run.status}.')
        self.run = run


_executor = None
_executor_lock = threading.Lock()
_enqueue_lock = threading.Lock()


def _get_executor(app):
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=int(app.config.get('SCRAPER_MAX_WORKERS', 1)),
                                           thread_name_prefix='scraper')
            atexit.register(lambda: _executor.shutdown(wait=False))
    return _executor


# --- indirections so tests can monkeypatch the scraper without Playwright ---------------------------

def _run_recipe(recipe, **kw):
    from app.vendor.fetchall.runner import run_recipe
    return run_recipe(recipe, **kw)


def _inspect(url, **kw):
    from app.vendor.fetchall.sniffer import inspect
    return inspect(url, **kw)


def _fetch_direct(url):
    from app.vendor.fetchall.sniffer import fetch_direct
    return fetch_direct(url)


def _teach(url, **kw):
    from app.vendor.fetchall.teach import teach
    return teach(url, **kw)


# --- public API ---------------------------------------------------------------------------------------

def enqueue(kind, *, recipe=None, options=None, actor=None, trigger='manual') -> ScrapeRun:
    assert kind in SCRAPE_RUN_KINDS, kind
    avail = scraper.availability()
    if not avail['ok']:
        raise scraper.ScraperUnavailable(avail['message'])
    if kind == 'teach' and not current_app.config.get('SCRAPER_HEADED_TEACH'):
        raise scraper.ScraperUnavailable(
            'In-app teaching opens a real browser window and is only available when the app runs on a '
            'desktop with SCRAPER_HEADED_TEACH=True. Teach with "python -m fetchall teach <url>" and paste the recipe.')
    with _enqueue_lock:
        if kind == 'run' and recipe is not None:
            active = _active_run(recipe.id)
            if active:
                raise AlreadyRunning(active)
        run = ScrapeRun(recipe_id=recipe.id if recipe else None, kind=kind, options=options or {},
                        trigger=trigger, started_by_id=actor.id if actor else None, log='')
        db.session.add(run)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            active = _active_run(recipe.id) if recipe else None
            if active:
                raise AlreadyRunning(active)
            raise
    app = current_app._get_current_object()
    if app.config.get('SCRAPER_INLINE'):
        _execute(app, run.id, own_context=False)
        db.session.refresh(run)
    else:
        _get_executor(app).submit(_execute, app, run.id)
    return run


def request_cancel(run: ScrapeRun) -> None:
    if run.status == 'queued':
        run.status = 'cancelled'
        run.finished_at = datetime.utcnow()
    run.cancel_requested = True
    db.session.commit()


def recover_stale_runs(stale_minutes=None) -> int:
    """Runs whose worker died (server restart, OOM) never finish on their own — mark them failed."""
    minutes = stale_minutes or int(current_app.config.get('SCRAPER_STALE_MINUTES', 10))
    cutoff = datetime.utcnow() - timedelta(minutes=minutes)
    n = 0
    for run in ScrapeRun.query.filter(ScrapeRun.status.in_(['queued', 'running'])).all():
        last = run.heartbeat_at or run.started_at or run.created_at
        if last and last < cutoff:
            run.status = 'failed'
            run.error = 'Worker lost (server restarted or ran out of memory). Rows collected so far were kept.'
            run.finished_at = datetime.utcnow()
            if run.recipe and run.kind == 'run':
                run.recipe.last_status = 'failed'
            n += 1
    if n:
        db.session.commit()
    return n


def enqueue_scheduled(now=None) -> int:
    """Start runs for recipes whose schedule is due. Called from the jobs endpoint / flask run-jobs."""
    if not scraper.is_enabled() or not scraper.availability()['ok']:
        return 0
    now = now or datetime.utcnow()
    started = 0
    for rec in ScrapeRecipe.query.filter_by(schedule_enabled=True, is_active=True).all():
        every = timedelta(hours=max(int(rec.schedule_every_hours or 24), 1))
        if rec.last_run_at and rec.last_run_at > now - every:
            continue
        try:
            enqueue('run', recipe=rec, options={'incremental': True}, trigger='scheduled')
            started += 1
        except (AlreadyRunning, scraper.ScraperUnavailable):
            continue
    return started


def execute_inline(run: ScrapeRun) -> None:
    _execute(current_app._get_current_object(), run.id, own_context=False)


def known_keys(recipe: ScrapeRecipe) -> set:
    return {k for (k,) in db.session.query(ScrapeRow.key).filter_by(recipe_id=recipe.id).all()}


# --- execution ----------------------------------------------------------------------------------------

def _active_run(recipe_id):
    return (ScrapeRun.query.filter(ScrapeRun.recipe_id == recipe_id, ScrapeRun.status.in_(['queued', 'running']))
            .first())


def _execute(app, run_id, own_context=True):
    if own_context:
        with app.app_context():
            try:
                _execute_inner(run_id)
            finally:
                db.session.remove()
    else:
        _execute_inner(run_id)


def _execute_inner(run_id):
    run = db.session.get(ScrapeRun, run_id)
    if run is None or run.status != 'queued':
        return
    now = datetime.utcnow()
    if run.cancel_requested:
        run.status, run.finished_at = 'cancelled', now
        db.session.commit()
        return
    run.status, run.started_at, run.heartbeat_at = 'running', now, now
    run.worker_id = f'{socket.gethostname()}:{os.getpid()}'
    db.session.commit()
    hook = _LogHook(run)
    try:
        {'detect': _do_detect, 'preview': _do_preview, 'teach': _do_teach, 'run': _do_run}[run.kind](run, hook)
        if run.status == 'running':
            run.status = 'cancelled' if hook.cancel_seen else 'done'
    except Exception as exc:
        db.session.rollback()
        run = db.session.get(ScrapeRun, run_id)
        hook.run = run
        run.status = 'failed'
        run.error = f'{type(exc).__name__}: {exc}'[:2000]
        hook(f'error: {run.error}')
        current_app.logger.exception('scrape run %s failed', run_id)
    finally:
        run.finished_at = datetime.utcnow()
        if run.recipe_id and run.kind == 'run':
            rec = db.session.get(ScrapeRecipe, run.recipe_id)
            if rec:
                rec.last_run_at = run.finished_at
                rec.last_status = run.status
        db.session.commit()


class _LogHook:
    """`log=` callback for fetchall: keeps the last lines on the run, parses progress, heartbeats,
    and exposes `should_stop()` for cooperative cancellation."""
    PAGE_RE = re.compile(r'(?:page|batch)\s+(\d+):\s+(\d+)\s+items')

    def __init__(self, run):
        self.run = run
        self.lines = (run.log or '').splitlines()
        self.cancel_seen = False
        self._last_hb = time.monotonic()

    def __call__(self, line):
        line = str(line).rstrip()
        if not line:
            return
        self.lines.append(line)
        self.lines = self.lines[-300:]
        m = self.PAGE_RE.search(line)
        if m:
            self.run.progress_pages = int(m.group(1))
            self.run.progress_items = (self.run.progress_items or 0) + int(m.group(2))
        self.run.log = '\n'.join(self.lines)
        self.run.heartbeat_at = datetime.utcnow()
        self._commit()

    def should_stop(self) -> bool:
        try:
            if time.monotonic() - self._last_hb > 5:
                self.run.heartbeat_at = datetime.utcnow()
                self._commit()
            db.session.expire(self.run, ['cancel_requested'])
            if self.run.cancel_requested:
                self.cancel_seen = True
                return True
        except Exception:
            db.session.rollback()
        return False

    def _commit(self):
        try:
            db.session.commit()
            self._last_hb = time.monotonic()
        except Exception:
            db.session.rollback()


def _storage_state_for(session_key):
    if not session_key:
        return None
    path = Path(current_app.config['SCRAPER_SESSION_DIR']) / secure_filename(session_key)
    return str(path) if path.is_file() else None


def _stats_dict(stats) -> dict:
    return {
        'pages': stats.pages, 'rows_seen': stats.rows_seen, 'rows_new': stats.rows_new,
        'skipped_known': stats.skipped_known, 'detail_errors': stats.detail_errors,
        'detail_aborted': stats.detail_aborted, 'close_fallbacks_used': sorted(stats.close_fallbacks_used),
        'blank_counts': dict(stats.blank_counts), 'stopped_because': stats.stopped_because,
        'interrupted': stats.interrupted,
    }


def _report_dict(report) -> dict:
    return {'status': report.status, 'headline': report.headline, 'messages': list(report.messages),
            'exit_code': report.exit_code}


def _do_detect(run, hook):
    from app.vendor.fetchall.score import rank
    opts = run.options or {}
    url = opts['url']
    hook(f'loading {url} and watching what it fetches…')
    insp = _inspect(url, wait_seconds=float(opts.get('wait', 4.0)),
                    storage_state=_storage_state_for(opts.get('session_key')))
    cands = rank(insp.candidates, insp.visible_text)
    run.result = {
        'page_url': insp.final_url, 'title': insp.title, 'responses_seen': insp.responses_seen,
        'candidates': [{
            'index': i, 'kind': c.kind, 'source': c.source, 'score': round(float(c.score), 1),
            'rows': c.table.row_count, 'columns': list(c.table.columns), 'notes': list(c.notes),
            'sample': c.table.rows[:5],
        } for i, c in enumerate(cands)],
    }
    hook(f'found {len(cands)} data source(s) on {insp.final_url}')


def _do_preview(run, hook):
    from app.vendor.fetchall.monitor import assess
    opts = run.options or {}
    recipe = opts.get('recipe') or (run.recipe.recipe_json if run.recipe else None)
    if not recipe:
        raise ValueError('No recipe to preview.')
    hook('replaying the recipe on the first page (up to 5 items)…')
    table, stats = _run_recipe(recipe, max_pages=1, max_rows=5, log=hook, should_stop=hook.should_stop,
                               storage_state=_storage_state_for(opts.get('session_key')))
    run.result = {'columns': list(table.columns), 'rows': table.rows, 'stats': _stats_dict(stats),
                  'report': _report_dict(assess(stats))}
    run.rows_total = len(table.rows)


def _do_teach(run, hook):
    opts = run.options or {}
    out_dir = Path(current_app.config['SCRAPER_EXPORT_DIR']) / 'taught'
    hook('opening the teaching window on this machine — follow the panel in the browser, then Save…')
    res = _teach(opts['url'], out_dir=str(out_dir), headless=False,
                 deadline_seconds=int(opts.get('deadline', current_app.config.get('SCRAPER_TEACH_DEADLINE_SECONDS', 900))),
                 storage_state=_storage_state_for(opts.get('session_key')), log=hook)
    if res is None:
        run.status = 'failed'
        run.error = 'The teaching window was closed (or timed out) without saving a recipe.'
        return
    recipe, path = res
    run.result = {'recipe': recipe, 'saved_path': str(path)}
    hook('recipe saved')


def _do_run(run, hook):
    from app.vendor.fetchall.excel import now_iso
    from app.vendor.fetchall.monitor import assess, blank_ratios
    recipe = run.recipe
    opts = run.options or {}
    storage = _storage_state_for(recipe.session_key)
    counter = {'index': 0, 'stored': 0}

    def store(rec, columns):
        counter['index'] += 1
        if _store_row(run, recipe, counter['index'], rec, columns):
            counter['stored'] += 1

    if recipe.mode == 'source':
        src = recipe.source_json or {}
        source = src.get('source') or ''
        hook(f'fetching data source {source}…')
        if source.startswith('dom:'):
            insp = _inspect(src.get('page_url') or recipe.start_url, storage_state=storage)
            cand = next((c for c in insp.candidates if c.source == source), None)
        else:
            cand = _fetch_direct(source)
        if cand is None:
            raise RuntimeError(f'Data source {source} returned no table.')
        columns = list(cand.table.columns)
        fetched = now_iso()
        for rec in cand.table.rows:
            rec = dict(rec)
            rec.setdefault('_page', 1)
            rec.setdefault('_url', recipe.start_url)
            rec.setdefault('_fetched_at', fetched)
            rec['_key'] = scraper.row_key(rec, columns)
            store(rec, columns)
        hook(f'source: {len(cand.table.rows)} rows, {counter["stored"]} new')
        run.rows_total = len(cand.table.rows)
        run.stats = {'rows_seen': len(cand.table.rows), 'rows_new': counter['stored'], 'skipped_known': 0,
                     'columns': columns + [m for m in ('_page', '_url', '_fetched_at', '_key') if m not in columns],
                     'report': {'status': 'ok', 'headline': 'OK', 'messages': [], 'exit_code': 0}}
    else:
        recipe_json = recipe.recipe_json or {}
        incremental = opts.get('incremental', True)
        known = known_keys(recipe) if incremental else set()
        columns = recipe.columns
        hook(f'replaying recipe ({len(known)} items already known)…' if known else 'replaying recipe…')
        table, stats = _run_recipe(recipe_json, max_pages=opts.get('max_pages'), max_rows=opts.get('max_rows'),
                                   storage_state=storage, skip_keys=known, log=hook,
                                   on_row=lambda rec: store(rec, columns), should_stop=hook.should_stop)
        report = assess(stats, _previous_for_monitor(recipe))
        run.rows_total = stats.rows_seen
        run.stats = {**_stats_dict(stats), 'blank_ratios': blank_ratios(stats), 'columns': list(table.columns),
                     'report': _report_dict(report), 'known_before': len(known)}
        if stats.stopped_because == 'cancelled':
            hook.cancel_seen = True
    run.rows_new = counter['stored']
    run.rows_duplicate = ScrapeRow.query.filter_by(run_id=run.id, status='duplicate').count()
    db.session.commit()


def _store_row(run, recipe, index, rec, columns) -> bool:
    key = scraper.row_key(rec, columns)
    if ScrapeRow.query.filter_by(recipe_id=recipe.id, key=key).first():
        return False
    dup = CompanionRequest.query.filter_by(import_key=key).first()
    row = ScrapeRow(run_id=run.id, recipe_id=recipe.id, row_index=index, key=key, data=rec,
                    page_url=str(rec.get('_url') or '')[:500],
                    status='duplicate' if dup else 'new', duplicate_of_id=dup.id if dup else None)
    db.session.add(row)
    try:
        db.session.commit()
        return True
    except IntegrityError:
        db.session.rollback()
        return False


def _previous_for_monitor(recipe):
    import json
    last = (ScrapeRun.query.filter(ScrapeRun.recipe_id == recipe.id, ScrapeRun.kind == 'run',
                                   ScrapeRun.status == 'done', ScrapeRun.stats.isnot(None))
            .order_by(ScrapeRun.finished_at.desc()).first())
    if not last or not last.stats:
        return None
    s = last.stats
    return {'items_seen': int(s.get('rows_seen', 0) or 0) + int(s.get('skipped_known', 0) or 0),
            'blank_ratios': json.dumps(s.get('blank_ratios') or {})}
