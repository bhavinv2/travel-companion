"""Command line: `fetchall inspect URL` lists the data behind a page; `fetchall export URL --out file.xlsx` saves it."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlsplit

import json
import os

from . import __version__
from .excel import append_run, now_iso, read_history, write_workbook
from .models import Candidate, Inspection, Table
from .monitor import assess, blank_ratios
from .runner import run_recipe
from .schedule import cron_line, install, quote, schtasks_create, schtasks_delete, task_name, write_batch
from .score import rank
from .session import find_session, login
from .sniffer import fetch_direct, host_of, inspect
from .teach import list_recipes, load_recipe, teach


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fetchall",
                                description="Find the structured data behind a web page and export it to Excel.")
    p.add_argument("--version", action="version", version=f"fetchall {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def add_session_opt(sp):
        sp.add_argument("--session", default=None,
                        help="login session file from `fetchall login` (default: sessions/<host>.json if present)")

    def add_browser_opts(sp):
        sp.add_argument("--wait", type=float, default=4.0,
                        help="extra seconds to wait after the page settles (default 4)")
        sp.add_argument("--headed", action="store_true", help="show the browser window while loading")
        sp.add_argument("--timeout", type=float, default=45.0, help="page load timeout in seconds")
        add_session_opt(sp)

    sp = sub.add_parser("inspect", help="list every structured-data source the page loads")
    sp.add_argument("url")
    add_browser_opts(sp)

    sp = sub.add_parser("export", help="save the page's data to an .xlsx file")
    sp.add_argument("url", help="page URL (with --source, only recorded in the Source sheet)")
    sp.add_argument("--out", "-o", default=None, help="output .xlsx path (default: <host>.xlsx)")
    sp.add_argument("--pick", type=int, default=None, help="candidate number from `inspect` (default: best)")
    sp.add_argument("--all", action="store_true", help="write every candidate, one sheet each")
    sp.add_argument("--source", default=None, help="download this data URL directly, no browser")
    add_browser_opts(sp)

    sp = sub.add_parser("teach", help="open the page and show, by clicking, what to fetch")
    sp.add_argument("url")
    sp.add_argument("--recipes", default="recipes", help="folder for recipe files (default: recipes/)")
    sp.add_argument("--no-preview", action="store_true", help="skip the preview run after saving")
    sp.add_argument("--timeout", type=float, default=45.0, help="page load timeout in seconds")
    add_session_opt(sp)

    sp = sub.add_parser("run", help="replay a saved recipe and save the rows to .xlsx")
    sp.add_argument("recipe", help="recipe file, or a site name that maps to recipes/<site>.json")
    sp.add_argument("--out", "-o", default=None, help="output .xlsx path (default: <site>.xlsx)")
    sp.add_argument("--max-pages", type=int, default=None, help="stop after this many pages")
    sp.add_argument("--max-rows", type=int, default=None, help="stop after this many rows")
    sp.add_argument("--headed", action="store_true", help="show the browser while it runs")
    sp.add_argument("--delay", type=float, default=0.5, help="seconds to pause after each page (default 0.5)")
    sp.add_argument("--recipes", default="recipes", help="folder to look up site names in")
    sp.add_argument("--incremental", action="store_true",
                    help="append only new items to the workbook (created on the first run); logs each run in a 'runs' sheet")
    add_session_opt(sp)

    sp = sub.add_parser("recipes", help="list saved recipes")
    sp.add_argument("--recipes", default="recipes")

    sp = sub.add_parser("login", help="log in once in a visible browser and save the session for later runs")
    sp.add_argument("url")
    sp.add_argument("--sessions", default="sessions", help="folder for session files (default: sessions/)")
    sp.add_argument("--timeout", type=float, default=45.0, help="page load timeout in seconds")

    sp = sub.add_parser("schedule", help="show (or install) a scheduled task that runs a recipe incrementally")
    sp.add_argument("recipe", help="recipe file or site name")
    sp.add_argument("--every", default="daily", help="30m, 6h, daily (default) or weekly")
    sp.add_argument("--at", default="07:00", help="start time for daily/weekly, HH:MM (default 07:00)")
    sp.add_argument("--out", "-o", default=None, help="workbook to append to (default: <site>.xlsx)")
    sp.add_argument("--install", action="store_true", help="create the Windows task now (schtasks /Create)")
    sp.add_argument("--remove", action="store_true", help="delete the Windows task (schtasks /Delete)")
    sp.add_argument("--recipes", default="recipes")
    return p


def main(argv: list[str] | None = None) -> int:
    _make_console_safe()
    args = build_parser().parse_args(argv)
    commands = {"inspect": cmd_inspect, "export": cmd_export, "teach": cmd_teach, "run": cmd_run,
                "recipes": cmd_recipes, "login": cmd_login, "schedule": cmd_schedule}
    try:
        return commands[args.command](args)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except FileNotFoundError as exc:
        print(exc)
        return 2


# ------------------------------------------------------------ inspect

def cmd_inspect(args) -> int:
    insp = _run_inspection(args)
    print_candidates(insp)
    return 0 if insp.candidates else 1


def _run_inspection(args) -> Inspection:
    print(f"Loading {args.url} ...", flush=True)
    session = _session_for(args.url, args)
    insp = inspect(args.url, wait_seconds=args.wait, headed=args.headed, timeout_seconds=args.timeout,
                   storage_state=session)
    insp.candidates = rank(insp.candidates, insp.visible_text)
    return insp


def _session_for(url: str, args) -> str | None:
    session = find_session(url, getattr(args, "session", None))
    if session:
        print(f"Using login session {session}")
    return session


def print_candidates(insp: Inspection) -> None:
    title = insp.title or "(no title)"
    print(f"\nPage: {title}")
    if insp.final_url != insp.url:
        print(f"      {insp.final_url}")
    print(f"Responses seen: {insp.responses_seen}   Structured data found: {len(insp.candidates)}\n")
    if not insp.candidates:
        print("No JSON, CSV, XML or HTML tables were loaded by this page.")
        print("Try --wait 10 (slow site), --headed (to log in or click something), or a different URL.")
        return
    print(f" {'#':>2}  {'score':>5}  {'kind':<10} {'rows':>6} {'cols':>5}  source")
    for i, c in enumerate(insp.candidates, start=1):
        print(f" {i:>2}  {c.score:>5.0f}  {c.kind:<10} {c.table.row_count:>6} {c.table.column_count:>5}  {c.source}")
        for note in c.notes:
            print(f"{'':>34}{note}")
        cols = ", ".join(c.table.columns[:8]) + (", ..." if c.table.column_count > 8 else "")
        print(f"{'':>34}columns: {cols}")
    print("\nNext: fetchall export <url> --pick N --out file.xlsx   (or --all for every candidate)")


# ------------------------------------------------------------ export

def cmd_export(args) -> int:
    if args.source:
        print(f"Downloading {args.source} ...", flush=True)
        cand = fetch_direct(args.source)
        if cand is None:
            print("That URL did not parse as JSON, CSV or XML.")
            return 1
        rank([cand], "")
        cand.notes = ["downloaded directly"]
        chosen = [cand]
        page_url = args.url
    else:
        insp = _run_inspection(args)
        print_candidates(insp)
        if not insp.candidates:
            return 1
        page_url = insp.final_url
        if args.all:
            chosen = insp.candidates
        else:
            n = args.pick or 1
            if not 1 <= n <= len(insp.candidates):
                print(f"\n--pick must be between 1 and {len(insp.candidates)}.")
                return 2
            chosen = [insp.candidates[n - 1]]

    out = Path(args.out) if args.out else Path(f"{host_of(page_url).replace(':', '_')}.xlsx")
    sheets, meta = [], []
    for c in chosen:
        name = sheet_name_for(c)
        sheets.append((name, c.table))
        meta.append({"sheet": name, "kind": c.kind, "rows": c.table.row_count, "columns": c.table.column_count,
                     "score": c.score, "source": c.source, "page": page_url, "fetched_at": now_iso()})
    path = write_workbook(out, sheets, meta)
    print(f"\nWrote {path.resolve()}")
    for c in chosen:
        print(f"  {c.table.row_count} rows x {c.table.column_count} columns  <-  {c.source}")
    return 0


# ------------------------------------------------------------ teach / run / recipes

def cmd_teach(args) -> int:
    print(f"Opening {args.url} for teaching ...", flush=True)
    session = _session_for(args.url, args)
    result = teach(args.url, out_dir=args.recipes, timeout_seconds=args.timeout, storage_state=session)
    if result is None:
        print("Window closed without saving. Nothing written.")
        return 1
    recipe, path = result
    print(f"\nSaved recipe -> {path}")
    describe_recipe(recipe)
    if args.no_preview:
        return 0
    print("\nPreview run (first page, up to 5 items) ...", flush=True)
    table, stats = run_recipe(recipe, max_pages=1, max_rows=5, storage_state=session)
    print_preview(table)
    print(f"\nNext: fetchall run {path} --out {recipe['site']}.xlsx")
    return 0


def describe_recipe(recipe: dict) -> None:
    print(f"  site:       {recipe.get('site')}")
    print(f"  items:      {recipe['list']['row']}")
    for name, spec in recipe.get("fields", {}).items():
        print(f"  field:      {name:<16} {spec['sel'] or '(item itself)'}" + (f"  [{spec['attr']}]" if spec.get("attr", "text") != "text" else ""))
    detail = recipe.get("detail")
    if detail:
        where = detail.get("container") if detail.get("mode") == "popup" else "separate page"
        print(f"  details:    open via {detail['open']['sel'] or '(click the item)'} -> {where}")
        for x in detail.get("expand") or []:
            print(f"    show more: {x['sel']}  (clicked before the fields are read)")
        for name, spec in detail.get("fields", {}).items():
            print(f"    field:    {name:<16} {spec['sel']}" + (f"  [{spec['attr']}]" if spec.get("attr", "text") != "text" else ""))
        if detail.get("close"):
            print(f"    close:    {detail['close']['sel']}")
    pg = recipe.get("paginate")
    if pg:
        mode = pg.get("mode", "click")
        label = {"click": "next page", "load_more": "load more", "scroll": "scroll"}.get(mode, mode)
        print(f"  {label + ':':<11} {pg.get('click') or '(scroll to the end of the list)'}")


def print_preview(table: Table, limit: int = 5) -> None:
    if not table.rows:
        print("  (no rows found - the selectors may need a re-teach)")
        return
    names = [c for c in table.columns if not c.startswith("_")]
    for i, row in enumerate(table.rows[:limit], start=1):
        print(f"  {i}.")
        for n in names:
            v = str(row.get(n, "")).replace("\n", " ")
            print(f"     {n:<16} {v[:70]}{'...' if len(v) > 70 else ''}")


def cmd_run(args) -> int:
    recipe, path = load_recipe(args.recipe, args.recipes)
    out = Path(args.out) if args.out else Path(f"{recipe.get('site', 'rows')}.xlsx")
    if out.suffix.lower() != ".xlsx":
        out = out.with_suffix(".xlsx")
    known, previous = (read_history(out) if args.incremental else (set(), None))
    if args.incremental and known:
        print(f"Incremental: {len(known)} items already in {out}; only new ones will be opened and added.")
    print(f"Running {path} ...", flush=True)
    session = _session_for(recipe["start_url"], args)
    table, stats = run_recipe(recipe, max_pages=args.max_pages, max_rows=args.max_rows,
                              headed=args.headed, delay=args.delay, storage_state=session, skip_keys=known)

    report = assess(stats, previous)
    entry = {"fetched_at": now_iso(), "pages": stats.pages, "items_seen": stats.rows_seen + stats.skipped_known,
             "new_rows": table.row_count, "stopped": stats.stopped_because, "status": report.status,
             "notes": "; ".join(report.messages), "blank_ratios": json.dumps(blank_ratios(stats))}
    if not args.incremental and out.exists():
        out.unlink()
    written, added = append_run(out, table, entry)

    print(f"\n{'Appended to' if args.incremental else 'Wrote'} {written.resolve()}")
    print(f"  {added} new rows from {stats.pages} page(s), {stats.rows_seen + stats.skipped_known} items seen"
          f"{f' ({stats.skipped_known} already known)' if stats.skipped_known else ''}; stopped: {stats.stopped_because}")
    if stats.detail_errors:
        print(f"  {stats.detail_errors} item(s) failed to open details (see the _error column)")
    print(f"\nSTATUS: {report.headline}")
    for msg in report.messages:
        print(f"  - {msg}")
    if report.status == "critical":
        print(f"  Fix: python -m fetchall teach {recipe['start_url']}")
    return report.exit_code


def cmd_login(args) -> int:
    print(f"Opening {args.url} ...", flush=True)
    path = login(args.url, session_dir=args.sessions, timeout_seconds=args.timeout)
    print(f"inspect, teach and run will now use {path} automatically for this site.")
    print("The file holds your cookies - keep it private and delete it to log out.")
    return 0


def cmd_schedule(args) -> int:
    recipe, path = load_recipe(args.recipe, args.recipes)
    site = recipe.get("site") or path.stem
    out = Path(args.out) if args.out else Path(f"{site}.xlsx")
    workdir = Path(os.getcwd()).resolve()
    if args.remove:
        cmd = schtasks_delete(site)
        if os.name != "nt":
            print("Task Scheduler is Windows-only; remove the crontab line by hand.")
            return 2
        result = install(cmd)
        print(result.stdout.strip() or result.stderr.strip())
        return 0 if result.returncode == 0 else 1

    script = write_batch(site, out.resolve(), workdir)
    cmd = schtasks_create(site, args.every, args.at, script)
    print(f"Task name:   {task_name(site)}")
    print(f"Schedule:    every {args.every}" + (f" at {args.at}" if args.every in ('daily', 'weekly') else ""))
    print(f"Appends to:  {out.resolve()}")
    print(f"Runs:        {script}")
    print(f"Log file:    {workdir / 'logs' / (site + '.log')}")
    print("\nWindows (Task Scheduler):")
    print("  " + quote(cmd))
    print("\nmacOS / Linux (crontab -e):")
    print("  " + cron_line(site, args.every, args.at, out.resolve(), workdir))
    if not args.install:
        print("\nAdd --install to create the Windows task now, or paste the line above yourself.")
        return 0
    if os.name != "nt":
        print("\n--install only works on Windows; paste the crontab line instead.")
        return 2
    result = install(cmd)
    print("\n" + (result.stdout.strip() or result.stderr.strip()))
    if result.returncode == 0:
        print(f"Remove later with: python -m fetchall schedule {args.recipe} --remove")
    return 0 if result.returncode == 0 else 1


def cmd_recipes(args) -> int:
    paths = list_recipes(args.recipes)
    if not paths:
        print(f"No recipes in {args.recipes}/ yet. Create one with: fetchall teach <url>")
        return 1
    for p in paths:
        try:
            recipe, _ = load_recipe(str(p))
            print(f"{p.name:<40} {len(recipe.get('fields', {}))} fields"
                  f"{' + details' if recipe.get('detail') else ''}{' + pages' if recipe.get('paginate') else ''}"
                  f"   {recipe.get('start_url', '')}")
        except Exception as exc:
            print(f"{p.name:<40} (unreadable: {exc})")
    return 0


def sheet_name_for(c: Candidate) -> str:
    if c.source.startswith("dom:"):
        return c.source.replace("dom:", "")
    path = urlsplit(c.source).path.rstrip("/")
    last = path.rsplit("/", 1)[-1] if path else ""
    return last.rsplit(".", 1)[0] or c.kind


def _make_console_safe() -> None:
    """Never crash on characters the console cannot show, and flush every line so a log file
    written by a scheduled task (`> run.log`) shows progress while the run is going."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace", line_buffering=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
