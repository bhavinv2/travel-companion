"""Login sessions: log in once in a visible browser, save the cookies/storage, reuse them on every run."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from .sniffer import USER_AGENT, launch_args
from .teach import recipe_filename

DEFAULT_SESSION_DIR = Path("sessions")


def session_path(url_or_site: str, session_dir: str | Path = DEFAULT_SESSION_DIR) -> Path:
    host = urlsplit(url_or_site).netloc if "://" in url_or_site else url_or_site
    return Path(session_dir) / f"{recipe_filename(host)}.json"


def find_session(url_or_site: str, explicit: str | None = None,
                 session_dir: str | Path = DEFAULT_SESSION_DIR) -> str | None:
    """--session wins; otherwise sessions/<host>.json if it exists; otherwise None."""
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise FileNotFoundError(f"Session file not found: {p}")
        return str(p)
    p = session_path(url_or_site, session_dir)
    return str(p) if p.is_file() else None


def save_session(context, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(path))
    return path


def login(url: str, session_dir: str | Path = DEFAULT_SESSION_DIR, timeout_seconds: float = 45.0,
          wait=None, log=print) -> Path:
    """Open the page headed, let the user log in, then save the session when `wait()` returns."""
    from playwright.sync_api import sync_playwright

    if wait is None:
        wait = lambda: input("Log in inside the browser window, then come back here and press Enter... ")  # noqa: E731
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=launch_args(False, maximized=True))
        context = browser.new_context(no_viewport=True, user_agent=USER_AGENT)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        wait()
        path = save_session(context, session_path(url, session_dir))
        log(f"Session saved -> {path}")
        browser.close()
    return path
