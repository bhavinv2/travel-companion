"""Plain data containers shared by the sniffer, detector, scorer and writer."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Table:
    """A rectangular result: a list of column names and a list of row dicts."""

    columns: list[str]
    rows: list[dict]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return len(self.columns)


@dataclass
class Candidate:
    """One structured-data source found while a page loaded."""

    kind: str                # "json" | "csv" | "xml" | "html-table"
    source: str              # URL of the response, or "dom:table[3]" for tables in the page
    table: Table
    content_type: str = ""
    size_bytes: int = 0
    score: float = 0.0       # 0..100, filled in by score.rank()
    overlap: float = 0.0     # 0..1, fraction of sampled values visible on the page
    notes: list[str] = field(default_factory=list)


@dataclass
class Inspection:
    """Everything one page load told us."""

    url: str
    final_url: str
    title: str
    candidates: list[Candidate]
    responses_seen: int
    visible_text: str = ""
