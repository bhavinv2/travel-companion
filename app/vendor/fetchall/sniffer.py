"""Load a page in a real browser, watch what it fetches, and collect every structured-data response.

Also collects <table> elements rendered in the page, and the visible text used for scoring.
"""
from __future__ import annotations

import os
import shlex
import urllib.request
from urllib.parse import urlsplit

from .detect import detect, looks_skippable, table_from_grid
from .models import Candidate, Inspection

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)


def launch_args(headless: bool, *, maximized: bool = False) -> list[str]:
    """Chromium launch flags shared by every browser we open.

    Headless gets --disable-gpu; a headed teaching/login window gets --start-maximized. Anything in the
    FETCHALL_CHROMIUM_ARGS environment variable is appended verbatim (e.g. "--no-sandbox" when the
    process runs as root inside a container).
    """
    args = ["--disable-gpu"] if headless else (["--start-maximized"] if maximized else [])
    extra = os.environ.get("FETCHALL_CHROMIUM_ARGS", "").strip()
    if extra:
        args += shlex.split(extra)
    return args

_TABLES_JS = """
() => Array.from(document.querySelectorAll('table')).map((t, i) => {
  const rows = Array.from(t.rows).map(r =>
    Array.from(r.cells).map(c => (c.innerText || c.textContent || '').trim()));
  const first = t.rows[0];
  const hasHeader = !!first && Array.from(first.cells).every(c => c.tagName === 'TH');
  return { index: i, rows, hasHeader };
}).filter(t => t.rows.length >= 2)
"""


def inspect(url: str, wait_seconds: float = 4.0, headed: bool = False,
            timeout_seconds: float = 45.0, storage_state: str | None = None) -> Inspection:
    from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

    responses = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed, args=launch_args(not headed))
        context = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1366, "height": 900},
                                      storage_state=storage_state)
        page = context.new_page()
        page.on("response", lambda resp: responses.append(resp))

        page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PWTimeout:
            pass
        page.wait_for_timeout(int(wait_seconds * 1000))
        # One scroll to the bottom and back nudges lazy-loaded lists into fetching.
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)
        except Exception:
            pass

        title = _safe(lambda: page.title(), "")
        final_url = _safe(lambda: page.url, url)
        visible_text = _safe(lambda: page.inner_text("body"), "")
        dom_tables = _safe(lambda: page.evaluate(_TABLES_JS), [])

        candidates: list[Candidate] = []
        seen_sources: set[str] = set()
        for resp in responses:
            try:
                src = resp.url
                if src in seen_sources:
                    continue
                if not (200 <= resp.status < 300):
                    continue
                ctype = resp.headers.get("content-type", "")
                if looks_skippable(src, ctype):
                    continue
                body = resp.body()
            except Exception:
                continue
            found = detect(body, ctype, src)
            if found is None:
                continue
            kind, table = found
            seen_sources.add(src)
            candidates.append(Candidate(kind=kind, source=src, table=table,
                                        content_type=ctype.split(";")[0].strip(), size_bytes=len(body)))

        for t in dom_tables:
            table = table_from_grid(t["rows"], has_header=t["hasHeader"])
            if table is None:
                continue
            candidates.append(Candidate(kind="html-table", source=f"dom:table[{t['index']}]", table=table,
                                        content_type="text/html", size_bytes=0))

        context.close()
        browser.close()

    return Inspection(url=url, final_url=final_url, title=title, candidates=candidates,
                      responses_seen=len(responses), visible_text=visible_text)


def fetch_direct(source_url: str, timeout_seconds: float = 60.0) -> Candidate | None:
    """Download one known data URL without a browser and parse it."""
    req = urllib.request.Request(source_url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        body = resp.read()
        ctype = resp.headers.get("Content-Type", "")
    found = detect(body, ctype, source_url)
    if found is None:
        return None
    kind, table = found
    return Candidate(kind=kind, source=source_url, table=table,
                     content_type=ctype.split(";")[0].strip(), size_bytes=len(body))


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def host_of(url: str) -> str:
    return urlsplit(url).netloc or "page"
