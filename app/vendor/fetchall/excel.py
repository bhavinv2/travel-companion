"""Write one or more Tables to an .xlsx workbook, plus a Source sheet that records where each came from."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import Table

EXCEL_MAX_CELL = 32767
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def safe_sheet_name(name: str, taken: set[str]) -> str:
    base = _BAD_SHEET_CHARS.sub("_", name).strip() or "data"
    base = base[:31]
    candidate = base
    n = 2
    while candidate.lower() in taken:
        suffix = f"_{n}"
        candidate = base[: 31 - len(suffix)] + suffix
        n += 1
    taken.add(candidate.lower())
    return candidate


def _cell_value(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    text = ILLEGAL_CHARACTERS_RE.sub("", text)
    if len(text) > EXCEL_MAX_CELL:
        text = text[: EXCEL_MAX_CELL - 1] + "…"
    return text


def _write_table(ws, table: Table) -> None:
    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="E8EEEC")
    for col_idx, name in enumerate(table.columns, start=1):
        cell = ws.cell(row=1, column=col_idx, value=_cell_value(name) or f"column_{col_idx}")
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="top")
    for row_idx, row in enumerate(table.rows, start=2):
        for col_idx, name in enumerate(table.columns, start=1):
            value = _cell_value(row.get(name))
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
                cell.data_type = "s"   # keep text that looks like a formula as text
    ws.freeze_panes = "A2"
    if table.columns:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(table.columns))}{max(len(table.rows) + 1, 1)}"
    _fit_columns(ws, table)


def _fit_columns(ws, table: Table, sample_rows: int = 200, max_width: int = 60) -> None:
    for col_idx, name in enumerate(table.columns, start=1):
        longest = len(str(name))
        for row in table.rows[:sample_rows]:
            v = row.get(name)
            if v is not None:
                longest = max(longest, len(str(v).split("\n", 1)[0]))
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(10, longest + 2), max_width)


def write_workbook(path: str | Path, sheets: list[tuple[str, Table]], meta: list[dict]) -> Path:
    """sheets: [(sheet_name, table)], meta: one dict per sheet describing its origin."""
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    wb.remove(wb.active)
    taken: set[str] = set()
    for name, table in sheets:
        ws = wb.create_sheet(safe_sheet_name(name, taken))
        _write_table(ws, table)

    src = wb.create_sheet(safe_sheet_name("Source", taken))
    keys = ["sheet", "kind", "rows", "columns", "score", "source", "page", "fetched_at"]
    src.append([k for k in keys])
    for cell in src[1]:
        cell.font = Font(bold=True)
    for m in meta:
        src.append([_cell_value(m.get(k, "")) for k in keys])
    for i, key in enumerate(keys, start=1):
        width = max([len(key)] + [len(str(m.get(key, ""))) for m in meta] + [8])
        src.column_dimensions[get_column_letter(i)].width = min(width + 2, 90)
    src.freeze_panes = "A2"

    wb.save(path)
    return path


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ------------------------------------------------------------------ recipe runs: append + history

ROWS_SHEET = "rows"
RUNS_SHEET = "runs"
RUN_LOG_KEYS = ["fetched_at", "pages", "items_seen", "new_rows", "stopped", "status", "notes", "blank_ratios"]
KEY_COLUMN = "_key"


def _style_header(ws, row: int = 1) -> None:
    for cell in ws[row]:
        if cell.value is not None:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="E8EEEC")


def _append_row(ws, values: list) -> None:
    ws.append(values)
    for cell in ws[ws.max_row]:
        if isinstance(cell.value, str) and cell.value[:1] in ("=", "+", "-", "@"):
            cell.data_type = "s"


def append_run(path: str | Path, table: Table, run_entry: dict) -> tuple[Path, int]:
    """Append table.rows to the 'rows' sheet (creating the workbook if needed) and log the run.

    Columns are matched by name, so a recipe that gained a field simply adds a column at the end.
    Returns (path, rows appended).
    """
    from openpyxl import load_workbook

    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        wb = load_workbook(path)
    else:
        wb = Workbook()
        wb.remove(wb.active)
    ws = wb[ROWS_SHEET] if ROWS_SHEET in wb.sheetnames else wb.create_sheet(ROWS_SHEET, 0)
    header = [c.value for c in ws[1]] if ws.max_row >= 1 else []
    header = [h for h in header if h is not None]
    fresh = not header
    if fresh:
        header = list(table.columns)
        for i, name in enumerate(header, start=1):
            ws.cell(row=1, column=i, value=name)
    else:
        for name in table.columns:
            if name not in header:
                header.append(name)
                ws.cell(row=1, column=len(header), value=name)
    _style_header(ws)
    for row in table.rows:
        _append_row(ws, [_cell_value(row.get(name)) for name in header])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(header))}{max(ws.max_row, 1)}"
    if fresh:
        _fit_columns(ws, Table(columns=header, rows=table.rows))

    runs = wb[RUNS_SHEET] if RUNS_SHEET in wb.sheetnames else wb.create_sheet(RUNS_SHEET)
    if runs.cell(row=1, column=1).value is None:      # fresh sheet: write the header in place (append would skip a row)
        for i, key in enumerate(RUN_LOG_KEYS, start=1):
            runs.cell(row=1, column=i, value=key)
        _style_header(runs)
        for i, key in enumerate(RUN_LOG_KEYS, start=1):
            runs.column_dimensions[get_column_letter(i)].width = {"notes": 60, "stopped": 36, "fetched_at": 27}.get(key, 12)
        runs.freeze_panes = "A2"
    _append_row(runs, [_cell_value(run_entry.get(k, "")) for k in RUN_LOG_KEYS])

    wb.save(path)
    return path, len(table.rows)


def read_history(path: str | Path) -> tuple[set[str], dict | None]:
    """Keys of rows already in the workbook, and the last run's log entry (or None)."""
    from openpyxl import load_workbook

    path = Path(path)
    if not path.exists():
        return set(), None
    wb = load_workbook(path, read_only=True)
    keys: set[str] = set()
    if ROWS_SHEET in wb.sheetnames:
        ws = wb[ROWS_SHEET]
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None) or ()
        if KEY_COLUMN in header:
            idx = list(header).index(KEY_COLUMN)
            for row in rows:
                if idx < len(row) and row[idx]:
                    keys.add(str(row[idx]))
    last: dict | None = None
    if RUNS_SHEET in wb.sheetnames:
        ws = wb[RUNS_SHEET]
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) >= 2:
            header, tail = rows[0], rows[-1]
            last = {str(h): v for h, v in zip(header, tail) if h is not None}
    wb.close()
    return keys, last
