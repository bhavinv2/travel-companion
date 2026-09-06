"""`fetchall teach URL`: open the page in a visible browser with the teaching overlay, wait for Save."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .sniffer import USER_AGENT, launch_args

OVERLAY_PATH = Path(__file__).with_name("overlay.js")
DEFAULT_RECIPE_DIR = Path("recipes")


def recipe_filename(site: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "_", site).strip("_") or "site"


def save_recipe(recipe: dict, out_dir: str | Path = DEFAULT_RECIPE_DIR) -> Path:
    """Write `recipe` to <out_dir>/<site>.json (overwriting) and return the path."""
    out = Path(out_dir) / f"{recipe_filename(recipe.get('site', 'site'))}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(recipe, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def teach(url: str, out_dir: str | Path = DEFAULT_RECIPE_DIR, timeout_seconds: float = 45.0,
          storage_state: str | None = None, log=print, *, headless: bool = False,
          deadline_seconds: float | None = None) -> tuple[dict, Path] | None:
    """Returns (recipe, saved_path), or None if the window was closed (or `deadline_seconds` passed)
    without saving. `headless=True` is for scripted teaching sessions that drive the overlay themselves."""
    from playwright.sync_api import sync_playwright

    overlay = OVERLAY_PATH.read_text(encoding="utf-8")
    result: dict = {}
    deadline = time.monotonic() + deadline_seconds if deadline_seconds else None

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless, args=launch_args(headless, maximized=True))
        if headless:
            context = browser.new_context(viewport={"width": 1440, "height": 900}, user_agent=USER_AGENT,
                                          storage_state=storage_state)
        else:
            context = browser.new_context(no_viewport=True, user_agent=USER_AGENT, storage_state=storage_state)
        page = context.new_page()
        page.expose_function("fetchallSave", lambda payload: result.update(recipe=json.loads(payload)))
        page.expose_function("fetchallLog", lambda msg: log(f"  {msg}"))
        page.add_init_script(overlay)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        log("Teaching window open. Follow the panel in the top-right corner of the page.")
        log("(Close the browser window to abort.)")
        while "recipe" not in result:
            if page.is_closed():
                break
            if deadline is not None and time.monotonic() > deadline:
                log("  teaching session timed out without a saved recipe")
                break
            try:
                page.wait_for_timeout(300)
            except Exception:
                break
        if "recipe" in result:
            try:
                page.wait_for_timeout(800)   # let the "Saved" state show briefly
            except Exception:
                pass
        try:
            browser.close()
        except Exception:
            pass

    if "recipe" not in result:
        return None
    recipe = result["recipe"]
    return recipe, save_recipe(recipe, out_dir)


def load_recipe(ref: str, recipe_dir: str | Path = DEFAULT_RECIPE_DIR) -> tuple[dict, Path]:
    """Accepts a path to a recipe file, or a site name that maps to recipes/<site>.json."""
    candidates = [Path(ref), Path(recipe_dir) / f"{recipe_filename(ref)}.json", Path(recipe_dir) / ref]
    for path in candidates:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8")), path
    raise FileNotFoundError(f"No recipe found for '{ref}'. Looked in: " + ", ".join(str(c) for c in candidates))


def list_recipes(recipe_dir: str | Path = DEFAULT_RECIPE_DIR) -> list[Path]:
    d = Path(recipe_dir)
    return sorted(d.glob("*.json")) if d.is_dir() else []
