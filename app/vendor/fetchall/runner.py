"""Replay a recipe headlessly: rows -> (open details -> fields -> close) -> next page, until it runs dry.

Pagination modes (recipe["paginate"]["mode"]):
  click      - a control replaces the list with the next page (default)
  load_more  - a control appends more items to the same list
  scroll     - scrolling to the bottom appends more items
Detail modes (recipe["detail"]["mode"]):
  popup      - a container on the same page becomes visible
  page       - a separate page opens; the runner reads it and goes back
  inline     - details expand inside the item itself
recipe["detail"]["expand"] lists "Show more" style controls to click inside the details before the
fields are read; one that is missing or hidden for an item (nothing to expand) is skipped.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime

from .models import Table
from .sniffer import USER_AGENT, launch_args

_VALUE_OF_JS = """
(el, attr) => {
  if (!el) return '';
  if (!attr || attr === 'text') return (el.innerText || el.textContent || '').trim();
  if (attr === 'href') { const a = el.closest('a[href]') || el.querySelector('a[href]'); return a ? a.href : (el.getAttribute('href') || ''); }
  if (attr === 'src') { const img = el.tagName === 'IMG' ? el : el.querySelector('img'); return img ? (img.currentSrc || img.src) : (el.getAttribute('src') || ''); }
  return el.getAttribute(attr) || '';
}
"""

_EXTRACT_FIELDS_JS = """
(root, fields, valueOf) => {
  const out = {};
  for (const [name, spec] of Object.entries(fields)) {
    let el = null;
    try { el = spec.sel ? root.querySelector(spec.sel) : root; } catch (e) {}
    out[name] = valueOf(el, spec.attr);
  }
  return out;
}
"""

EXTRACT_LIST_JS = """
([rowSel, fields]) => {
  const valueOf = %s;
  const extract = %s;
  return Array.from(document.querySelectorAll(rowSel)).map((row) => extract(row, fields, valueOf));
}
""" % (_VALUE_OF_JS, _EXTRACT_FIELDS_JS)

EXTRACT_SCOPE_JS = """
([rootSel, fields]) => {
  const valueOf = %s;
  const extract = %s;
  const root = rootSel ? document.querySelector(rootSel) : document;
  return root ? extract(root, fields, valueOf) : null;
}
""" % (_VALUE_OF_JS, _EXTRACT_FIELDS_JS)

EXTRACT_ELEMENT_JS = """
(root, fields) => {
  const valueOf = %s;
  const extract = %s;
  return extract(root, fields, valueOf);
}
""" % (_VALUE_OF_JS, _EXTRACT_FIELDS_JS)

COUNT_JS = "(sel) => document.querySelectorAll(sel).length"
PAGE_SIGNATURE_JS = "() => location.href + '|' + (document.body ? document.body.innerText : '')"
SCROLL_TO_END_JS = """
([rowSel, containerSel]) => {
  const rows = document.querySelectorAll(rowSel);
  const last = rows[rows.length - 1];
  let el = containerSel ? document.querySelector(containerSel) : (last ? last.parentElement : null);
  while (el) {   // every scrollable ancestor of the list gets scrolled to its end
    if (el.scrollHeight > el.clientHeight + 4) el.scrollTop = el.scrollHeight;
    el = el.parentElement;
  }
  window.scrollTo(0, document.documentElement.scrollHeight);
  if (last) last.scrollIntoView({ block: 'end' });
  window.dispatchEvent(new Event('scroll'));
}
"""

APPEND_MODES = ("scroll", "load_more")


class RunStats:
    def __init__(self) -> None:
        self.pages = 0
        self.rows_seen = 0          # items fully processed this run (details included)
        self.rows_new = 0           # items that went to the table
        self.skipped_known = 0      # items skipped because their key was in skip_keys (incremental runs)
        self.detail_errors = 0
        self.detail_aborted = False   # gave up on the run because details kept failing back to back
        self.close_fallbacks_used: set[str] = set()
        self.blank_counts: dict[str, int] = {}   # per field, how many processed items had it empty
        self.stopped_because = ""
        self.interrupted = False


MAX_CONSECUTIVE_DETAIL_ERRORS = 5


def run_recipe(recipe: dict, *, max_pages: int | None = None, max_rows: int | None = None,
               headed: bool = False, delay: float = 0.5, timeout_seconds: float = 45.0,
               storage_state: str | None = None, skip_keys: set[str] | None = None,
               log=print, on_row=None, should_stop=None) -> tuple[Table, RunStats]:
    """Replay `recipe`. `skip_keys` are list-field keys of items already collected: they are neither
    opened nor returned, which is what makes incremental runs cheap.

    `on_row(rec)` is called for every row as soon as it is collected, so a caller can persist rows
    while the run is still going. `should_stop()` is polled before each item and before every page
    change; returning True ends the run cleanly (partial rows kept, `stats.stopped_because == "cancelled"`).
    """
    from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

    def _cancelled() -> bool:
        try:
            return bool(should_stop and should_stop())
        except Exception:
            return False

    row_sel = recipe["list"]["row"]
    fields: dict = recipe.get("fields", {})
    detail: dict | None = recipe.get("detail") or None
    paginate: dict | None = recipe.get("paginate") or None
    detail_fields: dict = (detail or {}).get("fields", {})
    field_names = list(fields) + [c for c in detail_fields if c not in fields]
    columns = field_names + ["_page", "_url", "_fetched_at", "_key"]
    append_mode = bool(paginate) and paginate.get("mode", "click") in APPEND_MODES
    skip_keys = skip_keys or set()

    stats = RunStats()
    stats.blank_counts = {n: 0 for n in field_names}
    seen: set[str] = set()          # full-row keys -> what goes to Excel
    processed: set[str] = set()     # list-part keys -> items whose details were already opened (append modes)
    out_rows: list[dict] = []

    with sync_playwright() as pw:
        browser, context, page = _open_browser(pw, headless=not headed, storage_state=storage_state, log=log)
        page.set_default_timeout(15_000)
        try:
            page.goto(recipe["start_url"], wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            try:
                page.wait_for_selector(recipe.get("wait_for") or row_sel, timeout=20_000)
            except PWTimeout:
                log("  no items found on the first page (selector did not appear within 20s)")

            page_no = 1
            empty_streak = 0
            consecutive_detail_errors = 0
            while True:
                stats.pages = page_no
                list_rows: list[dict] = page.evaluate(EXTRACT_LIST_JS, [row_sel, fields]) or []
                new_here = 0
                for i, rec in enumerate(list_rows):
                    if _cancelled():
                        stats.interrupted = True
                        stats.stopped_because = "cancelled"
                        break
                    list_key = _row_key(rec, list(fields))
                    if list_key in skip_keys:
                        stats.skipped_known += 1
                        continue
                    if append_mode:
                        if list_key in processed:
                            continue
                        processed.add(list_key)
                    if detail:
                        rec.update(_open_detail(page, recipe, i, log, stats))
                        consecutive_detail_errors = consecutive_detail_errors + 1 if rec.get("_error") else 0
                        if consecutive_detail_errors >= MAX_CONSECUTIVE_DETAIL_ERRORS:
                            stats.detail_aborted = True
                            break
                    rec["_page"] = page_no
                    rec["_url"] = page.url
                    rec["_fetched_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                    rec["_key"] = list_key
                    stats.rows_seen += 1
                    for n in field_names:
                        if not str(rec.get(n) or "").strip():
                            stats.blank_counts[n] += 1
                    key = _row_key(rec, field_names)
                    if key in seen:
                        continue
                    seen.add(key)
                    out_rows.append(rec)
                    if on_row is not None:
                        on_row(rec)
                    new_here += 1
                    stats.rows_new += 1
                    if max_rows and len(out_rows) >= max_rows:
                        break
                log(f"  {'batch' if append_mode else 'page'} {page_no}: {len(list_rows)} items, {new_here} new"
                    + (f", {stats.skipped_known} already known" if stats.skipped_known else ""))

                if stats.stopped_because == "cancelled":
                    log("  cancelled - keeping what was collected so far")
                    break
                if stats.detail_aborted:
                    stats.stopped_because = (f"details failed {MAX_CONSECUTIVE_DETAIL_ERRORS} times in a row - "
                                             "the popup is probably not opening or closing the way the recipe expects")
                    break
                if max_rows and len(out_rows) >= max_rows:
                    stats.stopped_because = f"reached --max-rows {max_rows}"
                    break
                if not paginate:
                    stats.stopped_because = "single page recipe"
                    break
                if max_pages and page_no >= max_pages:
                    stats.stopped_because = f"reached --max-pages {max_pages}"
                    break
                empty_streak = empty_streak + 1 if new_here == 0 else 0
                if empty_streak >= int(paginate.get("stop_after_empty", 3)):
                    stats.stopped_because = f"{empty_streak} pages in a row with nothing new"
                    break
                if page_no >= int(paginate.get("max_pages", 50)):
                    stats.stopped_because = f"recipe max_pages ({paginate.get('max_pages', 50)})"
                    break
                if _cancelled():
                    stats.interrupted = True
                    stats.stopped_because = "cancelled"
                    log("  cancelled - keeping what was collected so far")
                    break
                reason = _advance(page, recipe, paginate, delay)
                if reason:
                    stats.stopped_because = reason
                    break
                page_no += 1
        except KeyboardInterrupt:
            stats.interrupted = True
            stats.stopped_because = "interrupted (partial results kept)"
            log("  interrupted - keeping what was collected so far")
        except Exception as exc:   # a browser hiccup must not throw away what was already collected
            stats.interrupted = True
            stats.stopped_because = f"stopped by an error: {type(exc).__name__}: {str(exc).splitlines()[0][:100]}"
            log(f"  {stats.stopped_because} - keeping the {len(out_rows)} rows collected so far")
        finally:
            try:
                context.close()
                browser.close()
            except Exception:
                pass

    return Table(columns=columns, rows=out_rows), stats


LAUNCH_ATTEMPTS = 3


def _open_browser(pw, *, headless: bool, storage_state: str | None, log=print, attempts: int = LAUNCH_ATTEMPTS):
    """Launch Chromium and open the first page, retrying when the browser dies while starting.

    A renderer that crashes at start-up ("BrowserContext.new_page: Target crashed") almost always
    means the machine is out of memory (dozens of Chrome/Edge tabs open); a pause and a retry
    usually gets through. Other launch errors (browser not installed, ...) are raised at once.
    """
    for attempt in range(1, attempts + 1):
        browser = None
        try:
            browser = pw.chromium.launch(headless=headless, args=launch_args(headless))
            context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1366, "height": 900},
                                          storage_state=storage_state)
            return browser, context, context.new_page()
        except Exception as exc:
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass
            if attempt >= attempts or not _is_crash(exc):
                raise
            log(f"  browser crashed while starting ({str(exc).splitlines()[0][:70]}); retrying in 3s "
                f"({attempt}/{attempts - 1}) - if this keeps happening the machine is low on memory: "
                "close some browser windows")
            time.sleep(3)
    raise RuntimeError("unreachable")


def _is_crash(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "crash" in msg or "target closed" in msg or "browser has been closed" in msg


def _row_key(rec: dict, names: list[str]) -> str:
    joined = "\x1f".join(str(rec.get(n, "")) for n in names)
    return hashlib.sha1(joined.encode("utf-8", errors="replace")).hexdigest()


# ------------------------------------------------------------------ details

def _open_detail(page, recipe: dict, index: int, log, stats: RunStats) -> dict:
    from playwright.sync_api import TimeoutError as PWTimeout

    detail = recipe["detail"]
    row_sel = recipe["list"]["row"]
    open_sel = (detail.get("open") or {}).get("sel") or ""
    mode = detail.get("mode", "popup")
    container = detail.get("container")
    dfields = detail.get("fields", {})
    close = detail.get("close") or {}
    list_url = page.url
    try:
        if mode == "popup" and container and _is_visible(page, container):
            _ensure_closed(page, container, close, log, stats)   # a leftover popup would block the click
        rows = page.query_selector_all(row_sel)
        if index >= len(rows):
            return {}
        row = rows[index]
        target = row.query_selector(open_sel) if open_sel else row
        if target is None:
            return {}
        target.scroll_into_view_if_needed()
        target.click(timeout=5_000)

        if mode == "page":
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except PWTimeout:
                pass
            wait_for = detail.get("wait_for")
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=10_000)
                except PWTimeout:
                    pass
            _expand(page, detail, None)
            data = page.evaluate(EXTRACT_SCOPE_JS, [None, dfields]) or {}
            page.go_back(wait_until="domcontentloaded")
            page.wait_for_selector(row_sel, timeout=15_000)
            return data

        if mode == "inline":
            page.wait_for_timeout(int(detail.get("wait_ms", 600)))
            row = page.query_selector_all(row_sel)[index]     # re-query: the click may have re-rendered
            _expand(page, detail, row)
            data = row.evaluate(EXTRACT_ELEMENT_JS, dfields) or {}
            if close.get("sel"):
                ctl = row.query_selector(close["sel"]) if close.get("scope", "row") == "row" else page.query_selector(close["sel"])
                if ctl is not None:
                    ctl.click(timeout=5_000)
            return data

        # popup
        if container:
            page.wait_for_selector(container, state="visible", timeout=int(detail.get("timeout_ms", 10_000)))
        else:
            page.wait_for_timeout(500)
        _expand(page, detail, page.query_selector(container) if container else None)
        data = page.evaluate(EXTRACT_SCOPE_JS, [container, dfields]) or {}
        if close.get("sel"):
            try:
                _click_close(page, container, close)
            except Exception:
                pass
        else:
            page.keyboard.press("Escape")
        if container and not _ensure_closed(page, container, close, log, stats):
            raise RuntimeError("popup did not close")
        return data
    except Exception as exc:  # keep going; one bad row must not sink the run
        stats.detail_errors += 1
        log(f"  item {index + 1}: details failed ({type(exc).__name__}: {str(exc).splitlines()[0][:80]})")
        try:
            if mode == "page" and page.url != list_url:
                page.go_back(wait_until="domcontentloaded")
                page.wait_for_selector(row_sel, timeout=15_000)
            elif container:
                _ensure_closed(page, container, close, log, stats)
            else:
                page.keyboard.press("Escape")
        except Exception:
            pass
        return {"_error": f"{type(exc).__name__}"}


def _expand(page, detail: dict, root) -> None:
    """Click the recorded "Show more" / expand controls before the fields are read. Best effort: a
    control that is missing or hidden for this item (short text, nothing to expand) is skipped."""
    for spec in detail.get("expand") or []:
        sel = spec.get("sel")
        if not sel:
            continue
        try:
            scope = page if spec.get("scope", "container") == "document" or root is None else root
            ctl = scope.query_selector(sel)
            if ctl is None or not ctl.is_visible():
                continue
            ctl.click(timeout=2_000)
            page.wait_for_timeout(int(detail.get("expand_wait_ms", 400)))
        except Exception:
            continue


COMMON_CLOSE = (".close, .modal-close, .btn-close, button.close, [aria-label='Close'], [aria-label='close'], "
                "[data-dismiss], [data-bs-dismiss], [title='Close']")
HIDE_JS = "(sel) => { const el = document.querySelector(sel); if (el) el.style.display = 'none'; }"


def _is_visible(page, selector: str) -> bool:
    try:
        el = page.query_selector(selector)
        return bool(el) and el.is_visible()
    except Exception:
        return False


def _ensure_closed(page, container: str, close: dict, log, stats: RunStats) -> bool:
    """Make sure the popup is gone, trying progressively blunter tools. True if it is hidden now."""
    from playwright.sync_api import TimeoutError as PWTimeout

    def hidden(timeout_ms: int) -> bool:
        try:
            page.wait_for_selector(container, state="hidden", timeout=timeout_ms)
            return True
        except PWTimeout:
            return False

    if hidden(1_500):
        return True
    attempts = [
        ("Escape", lambda: page.keyboard.press("Escape")),
        ("a common close button", lambda: _click_common_close(page, container)),
        ("the backdrop", lambda: _click_backdrop(page, container)),
        ("hiding it", lambda: page.evaluate(HIDE_JS, container)),
    ]
    for name, action in attempts:
        try:
            action()
        except Exception:
            continue
        if hidden(1_000):
            if name not in stats.close_fallbacks_used:
                stats.close_fallbacks_used.add(name)
                log(f"  note: the recorded close control did not close the popup; closing with {name} instead")
            return True
    return False


def _click_common_close(page, container: str) -> None:
    box = page.query_selector(container)
    if box is None:
        return
    for ctl in box.query_selector_all(COMMON_CLOSE):
        if ctl.is_visible():
            ctl.click(timeout=2_000)
            return
    raise LookupError("no common close control")


def _click_backdrop(page, container: str) -> None:
    box = page.query_selector(container)
    bb = box.bounding_box() if box else None
    if not bb:
        raise LookupError("no bounding box")
    page.mouse.click(bb["x"] + 3, bb["y"] + 3)


def _click_close(page, container: str | None, close: dict) -> None:
    """The close control was recorded relative to the popup when it lives inside it."""
    sel = close.get("sel")
    if not sel:
        return
    if container and close.get("scope", "container") == "container":
        box = page.query_selector(container)
        ctl = box.query_selector(sel) if box else None
        if ctl is not None:
            ctl.click(timeout=5_000)
            return
    page.click(sel, timeout=5_000)


# ------------------------------------------------------------------ pagination

def _advance(page, recipe: dict, paginate: dict, delay: float) -> str:
    """Move to the next page / batch. Returns '' on success, else the reason to stop."""
    mode = paginate.get("mode", "click")
    if mode == "click":
        return _go_next(page, paginate, delay)

    row_sel = recipe["list"]["row"]
    before = page.evaluate(COUNT_JS, row_sel)
    if mode == "load_more":
        el = page.query_selector(paginate["click"])
        if el is None:
            return "load-more control not found (end of list)"
        state = _control_state(el)
        if state:
            return f"load-more control is {state} (end of list)"
        try:
            el.scroll_into_view_if_needed()
            el.click()
        except Exception as exc:
            return f"could not click the load-more control ({type(exc).__name__})"
    else:
        page.evaluate(SCROLL_TO_END_JS, [row_sel, recipe["list"].get("container")])

    deadline = time.time() + float(paginate.get("wait_seconds", 8))
    while time.time() < deadline:
        page.wait_for_timeout(300)
        try:
            if page.evaluate(COUNT_JS, row_sel) > before:
                page.wait_for_timeout(int(delay * 1000))
                return ""
        except Exception:
            pass
        if mode == "scroll":
            page.evaluate(SCROLL_TO_END_JS, [row_sel, recipe["list"].get("container")])
    return "no new items after " + ("scrolling to the end" if mode == "scroll" else "clicking load more")


def _control_state(el) -> str:
    """'' if the control looks usable, else 'hidden' or 'disabled'."""
    try:
        if not el.is_visible():
            return "hidden"
        if el.is_disabled() or (el.get_attribute("aria-disabled") or "").lower() == "true" \
                or "disabled" in (el.get_attribute("class") or "").split():
            return "disabled"
    except Exception:
        pass
    return ""


def _go_next(page, paginate: dict, delay: float) -> str:
    """Click the next control. Returns '' if the page changed, else the reason to stop."""
    from playwright.sync_api import TimeoutError as PWTimeout

    el = page.query_selector(paginate["click"])
    if el is None:
        return "next control not found"
    state = _control_state(el)
    if state:
        return f"next control is {state} (last page)"
    before = _signature(page)
    for attempt in (1, 2):
        try:
            el.scroll_into_view_if_needed()
            el.click()
            break
        except Exception as exc:
            if attempt == 2:
                return f"could not click the next control ({type(exc).__name__})"
            page.wait_for_timeout(3_000)     # the page was busy; give it a moment and try once more
            el = page.query_selector(paginate["click"])
            if el is None:
                return "next control not found"
    deadline = time.time() + 10
    changed = False
    while time.time() < deadline:
        page.wait_for_timeout(300)
        try:
            if _signature(page) != before:
                changed = True
                break
        except Exception:
            pass  # navigation in progress
    if not changed:
        return "page did not change after clicking next"
    try:
        page.wait_for_load_state("networkidle", timeout=5_000)
    except PWTimeout:
        pass
    page.wait_for_timeout(int(delay * 1000))
    return ""


def _signature(page) -> str:
    text = page.evaluate(PAGE_SIGNATURE_JS) or ""
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()
