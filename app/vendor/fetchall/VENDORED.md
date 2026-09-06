# Vendored copy of `fetchall`

Source: `E:\OS\webscrapping\fetchall\` (the "show once, fetch all" scraper), copied 2026-08-30.
Only `*.py` (minus `__main__.py`) and `overlay.js` are vendored; the CLI (`cli.py`) is present but must
**never** be invoked from the app (`cli._make_console_safe()` reconfigures the process's stdout).

Upstream patches that this copy relies on (already applied in the source tree, with tests in
`E:\OS\webscrapping\tests\test_teach_runner.py`):

1. `sniffer.launch_args(headless, maximized=False)` — shared Chromium flags; honours the
   `FETCHALL_CHROMIUM_ARGS` env var (e.g. `--no-sandbox` in a root container). Used by runner, sniffer, teach, session.
2. `teach.teach(..., *, headless=False, deadline_seconds=None)` + `teach.save_recipe(recipe, out_dir)`.
3. `runner.run_recipe(..., on_row=None, should_stop=None)` — rows stream to the caller as they are collected;
   per-item cooperative cancellation (`stats.stopped_because == "cancelled"`).

Re-sync after changing the source tree (PowerShell, from the app folder):

```powershell
Copy-Item ..\..\fetchall\*.py app\vendor\fetchall\ -Force
Copy-Item ..\..\fetchall\overlay.js app\vendor\fetchall\ -Force
Remove-Item app\vendor\fetchall\__main__.py -ErrorAction SilentlyContinue
```

Playwright is imported lazily inside `run_recipe` / `inspect` / `teach`, so importing this package never
requires a browser; only actually running a scrape does.
