"""Rank candidates by how well their values match what the page actually shows."""
from __future__ import annotations

import re

from .detect import normalize_text
from .models import Candidate

SAMPLE_SIZE = 150
PER_ROW_LIMIT = 4
PAGE_LINE_LIMIT = 400
ROWS_CAP = 300
COLS_CAP = 12
HTML_TABLE_BASE = 0.30   # a rendered table is always "visible"; give it a fixed base instead of overlap

_LINE_SPLIT = re.compile(r"[\r\n\t]+|\s{2,}")


def sample_values(rows: list[dict], limit: int = SAMPLE_SIZE) -> list[str]:
    """Pick readable string cells spread across the whole table, a few per row.

    Spreading matters: a page often shows only one slice (this month, page 1),
    so sampling only the first rows would under-count a perfectly good source.
    """
    picked: list[str] = []
    if not rows:
        return picked
    columns = list(rows[0].keys())
    if not columns:
        return picked
    stride = max(1, len(rows) // (limit // PER_ROW_LIMIT))
    for row in rows[::stride]:
        taken = 0
        for col in columns:
            value = row.get(col)
            if isinstance(value, str):
                v = value.strip()
                if 4 <= len(v) <= 80 and not v.lower().startswith(("http://", "https://")):
                    picked.append(v)
                    taken += 1
                    if len(picked) >= limit:
                        return picked
                    if taken >= PER_ROW_LIMIT:
                        break
    return picked


def values_on_page(rows: list[dict], visible_text: str) -> float:
    """data -> page: fraction of sampled cell values that appear in the page text."""
    if not visible_text:
        return 0.0
    haystack = normalize_text(visible_text)
    values = sample_values(rows)
    if not values:
        return 0.0
    hits = sum(1 for v in values if normalize_text(v) in haystack)
    return hits / len(values)


def page_lines(visible_text: str, limit: int = PAGE_LINE_LIMIT) -> list[str]:
    """Distinct readable fragments of the page: split on newlines, tabs and runs of spaces."""
    seen: set[str] = set()
    lines: list[str] = []
    for raw in _LINE_SPLIT.split(visible_text):
        line = normalize_text(raw)
        if 5 <= len(line) <= 300 and line not in seen:
            seen.add(line)
            lines.append(line)
    if len(lines) > limit:
        stride = len(lines) / limit
        lines = [lines[int(i * stride)] for i in range(limit)]
    return lines


def page_explained_by(rows: list[dict], visible_text: str) -> float:
    """page -> data: fraction of page fragments that occur inside some cell of this table.

    Robust to a page that shows only a slice of the data (this month, page 1):
    what *is* on screen should still be found in the right source.
    """
    lines = page_lines(visible_text)
    if not lines:
        return 0.0
    values: set[str] = set()
    for row in rows:
        for v in row.values():
            if isinstance(v, str):
                n = normalize_text(v)
                if len(n) >= 5:
                    values.add(n)
    if not values:
        return 0.0
    blob = "\n" + "\n".join(values) + "\n"
    hits = sum(1 for line in lines if line in blob)
    return hits / len(lines)


def overlap_with_page(rows: list[dict], visible_text: str) -> float:
    """Best of both directions; either one being high is strong evidence."""
    return max(values_on_page(rows, visible_text), page_explained_by(rows, visible_text))


def score_candidate(c: Candidate, visible_text: str) -> Candidate:
    rows_part = min(c.table.row_count, ROWS_CAP) / ROWS_CAP
    cols_part = min(c.table.column_count, COLS_CAP) / COLS_CAP
    if c.kind == "html-table":
        c.overlap = 1.0
        visibility = HTML_TABLE_BASE
    else:
        c.overlap = overlap_with_page(c.table.rows, visible_text)
        visibility = 0.6 * c.overlap
    c.score = round(100 * (visibility + 0.25 * rows_part + 0.15 * cols_part), 1)
    c.notes = []
    if c.kind == "html-table":
        c.notes.append("table rendered in the page")
    elif c.overlap >= 0.5:
        c.notes.append("values match what is on screen")
    elif c.overlap > 0:
        c.notes.append(f"{int(c.overlap * 100)}% of sampled values appear on screen")
    else:
        c.notes.append("not visible on the page (config, tracking or hidden data)")
    return c


def rank(candidates: list[Candidate], visible_text: str) -> list[Candidate]:
    scored = [score_candidate(c, visible_text) for c in candidates]
    scored.sort(key=lambda c: (c.score, c.table.row_count), reverse=True)
    return scored
