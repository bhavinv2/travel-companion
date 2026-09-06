"""Turn a response body (or a DOM table) into a Table when it holds structured data.

Order of attempts: JSON, then CSV/TSV, then XML. Anything else returns None.
"""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from .models import Table

MAX_BODY_BYTES = 25 * 1024 * 1024
MIN_ROWS = 2

_SKIP_EXTENSIONS = (
    ".js", ".mjs", ".css", ".map", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".ico", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp4", ".webm", ".mp3", ".pdf", ".wasm",
)
_SKIP_CONTENT_TYPES = (
    "image/", "font/", "video/", "audio/", "application/javascript", "text/javascript",
    "application/x-javascript", "text/css", "application/pdf", "application/wasm",
    "application/octet-stream", "application/font",
)
_JSON_HIJACK_PREFIXES = (")]}',", ")]}'", "while(1);", "for(;;);")


def looks_skippable(url: str, content_type: str) -> bool:
    """Cheap pre-filter so we never download images, fonts or scripts."""
    ct = (content_type or "").lower()
    if any(ct.startswith(p) for p in _SKIP_CONTENT_TYPES):
        return True
    path = urlsplit(url).path.lower()
    return path.endswith(_SKIP_EXTENSIONS)


def decode(body: bytes) -> str:
    if body[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return body.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return body.decode("latin-1", errors="replace")


def detect(body: bytes, content_type: str = "", url: str = "") -> tuple[str, Table] | None:
    """Return ("json" | "csv" | "xml", Table) or None if the body is not tabular data."""
    if not body or len(body) > MAX_BODY_BYTES:
        return None
    text = decode(body).strip()
    if not text:
        return None
    ct = (content_type or "").lower()
    path = urlsplit(url).path.lower()

    table = table_from_json_text(text)
    if table is not None:
        return "json", table

    if text[0] != "<":
        prefer_csv = "csv" in ct or "tab-separated" in ct or path.endswith((".csv", ".tsv", ".txt"))
        table = table_from_csv_text(text, strict=not prefer_csv)
        if table is not None:
            return "csv", table

    if text[0] == "<" and not _looks_like_html(text):
        table = table_from_xml_text(text)
        if table is not None:
            return "xml", table
    return None


# ---------------------------------------------------------------- JSON

def table_from_json_text(text: str) -> Table | None:
    stripped = text
    for prefix in _JSON_HIJACK_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):].lstrip()
            break
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        data = json.loads(stripped)
    except ValueError:
        return None
    return table_from_json(data)


def table_from_json(data: Any) -> Table | None:
    """Find the best record collection anywhere inside a parsed JSON value."""
    best: list[dict] | None = None
    best_key = (0, 0.0)
    for records in _iter_record_collections(data):
        if len(records) < MIN_ROWS:
            continue
        key = (len(records), sum(len(r) for r in records) / max(len(records), 1))
        if key > best_key:
            best, best_key = records, key
    if best is None:
        return None
    return _table_from_records(best)


def _iter_record_collections(node: Any, depth: int = 0):
    """Yield every list-of-dicts (or dict-of-dicts, or grid) found in the JSON tree."""
    if depth > 12:
        return
    if isinstance(node, list):
        dict_items = [x for x in node if isinstance(x, dict)]
        if node and len(dict_items) >= max(MIN_ROWS, int(0.6 * len(node))):
            yield dict_items
        grid = _grid_records(node)
        if grid is not None:
            yield grid
        for item in node:
            if isinstance(item, (dict, list)):
                yield from _iter_record_collections(item, depth + 1)
    elif isinstance(node, dict):
        keyed = _keyed_records(node)
        if keyed is not None:
            yield keyed
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _iter_record_collections(value, depth + 1)


def _keyed_records(node: dict) -> list[dict] | None:
    """Firebase-style {"id1": {...}, "id2": {...}} -> records with a _key column."""
    values = list(node.values())
    if len(values) < 3 or not all(isinstance(v, dict) for v in values):
        return None
    key_sets = [set(v.keys()) for v in values]
    common = set.intersection(*key_sets) if key_sets else set()
    if not common:
        return None
    return [{"_key": k, **v} for k, v in node.items()]


def _grid_records(node: list) -> list[dict] | None:
    """[[header...], [row...], ...] (e.g. Google Sheets API) -> records."""
    if len(node) < MIN_ROWS + 1 or not all(isinstance(r, list) for r in node):
        return None
    if not all(_is_scalar(c) for r in node for c in r):
        return None
    header = node[0]
    if not header or not all(isinstance(h, str) and h.strip() for h in header):
        return None
    names = _unique_names([str(h).strip() for h in header])
    records = []
    for row in node[1:]:
        records.append({names[i]: row[i] for i in range(min(len(names), len(row)))})
    return records


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _table_from_records(records: list[dict]) -> Table:
    flat_rows = [flatten(r) for r in records]
    columns: list[str] = []
    seen = set()
    for row in flat_rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return Table(columns=columns, rows=flat_rows)


def flatten(record: dict, prefix: str = "", out: dict | None = None) -> dict:
    """Nested dicts become dotted keys; lists of scalars join with '; '; other lists stay JSON."""
    if out is None:
        out = {}
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            if value:
                flatten(value, name + ".", out)
            else:
                out[name] = None
        elif isinstance(value, list):
            if all(_is_scalar(v) for v in value):
                out[name] = "; ".join("" if v is None else str(v) for v in value)
            else:
                out[name] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            out[name] = value
    return out


# ---------------------------------------------------------------- CSV

_CSV_DELIMITERS = (",", "\t", ";", "|")


def table_from_csv_text(text: str, strict: bool = True) -> Table | None:
    """Try each delimiter; keep the one whose data rows agree most on their width.

    Consistency is measured against the most common row width, not the header,
    because real exports often carry stray trailing header cells the rows lack.
    """
    threshold = 0.9 if strict else 0.7
    best_grid: list[list[str]] | None = None
    best_key = (0.0, 0)
    for delim in _CSV_DELIMITERS:
        try:
            grid = [row for row in csv.reader(io.StringIO(text), delimiter=delim)
                    if any(cell.strip() for cell in row)]
        except csv.Error:
            continue
        if len(grid) < MIN_ROWS + 1:
            continue
        body = grid[1:]
        widths: dict[int, int] = {}
        for r in body:
            widths[len(r)] = widths.get(len(r), 0) + 1
        mode_width, mode_count = max(widths.items(), key=lambda kv: (kv[1], kv[0]))
        consistent = mode_count / len(body)
        if mode_width < 2 or consistent < threshold:
            continue
        if strict:
            # Nothing told us this is CSV, so demand a header that fits the rows exactly
            # and reads like column names, not sentences.
            if len(grid[0]) != mode_width or any(len(h) > 80 for h in grid[0]):
                continue
        key = (consistent, mode_width)
        if key > best_key:
            best_grid, best_key = grid, key
    if best_grid is None:
        return None
    return table_from_grid(best_grid, has_header=True)


def table_from_grid(grid: list[list[str]], has_header: bool) -> Table | None:
    """Rows of cells (from CSV or an HTML table) -> Table."""
    grid = [r for r in grid if any(str(c).strip() for c in r)]
    if not grid:
        return None
    width = max(len(r) for r in grid)
    if has_header:
        raw_header = [str(h).strip() for h in grid[0]] + [""] * (width - len(grid[0]))
        body = grid[1:]
    else:
        raw_header = [""] * width
        body = grid
    names = _unique_names([h or f"column_{i + 1}" for i, h in enumerate(raw_header)])
    rows = []
    for r in body:
        cells = list(r) + [""] * (width - len(r))
        rows.append({names[i]: cells[i] for i in range(width)})
    if len(rows) < MIN_ROWS:
        return None
    return Table(columns=names, rows=rows)


def _unique_names(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 1
            out.append(n)
    return out


# ---------------------------------------------------------------- XML

def _looks_like_html(text: str) -> bool:
    head = text[:512].lower()
    return "<!doctype html" in head or "<html" in head


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def table_from_xml_text(text: str) -> Table | None:
    try:
        root = ET.fromstring(text.encode("utf-8", errors="replace"))
    except ET.ParseError:
        return None
    best_parent: ET.Element | None = None
    best_tag = ""
    best_count = 0
    for parent in root.iter():
        counts: dict[str, int] = {}
        for child in parent:
            t = _strip_ns(child.tag)
            counts[t] = counts.get(t, 0) + 1
        for tag, count in counts.items():
            if count > best_count:
                best_parent, best_tag, best_count = parent, tag, count
    if best_parent is None or best_count < MIN_ROWS:
        return None
    records = [_xml_record(el) for el in best_parent if _strip_ns(el.tag) == best_tag]
    return _table_from_records(records)


def _xml_record(el: ET.Element) -> dict:
    rec: dict = {f"@{k}": v for k, v in el.attrib.items()}
    children = list(el)
    if not children:
        rec["text"] = (el.text or "").strip()
        return rec
    for child in children:
        name = _strip_ns(child.tag)
        if list(child):
            rec[name] = _xml_record(child)
        else:
            value = (child.text or "").strip()
            for k, v in child.attrib.items():
                rec[f"{name}@{k}"] = v
            if name in rec and isinstance(rec[name], str):
                rec[name] = rec[name] + "; " + value
            else:
                rec[name] = value
    return rec


_WS = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    return _WS.sub(" ", value).strip().lower()
