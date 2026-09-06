"""Decide whether a run looks healthy, or whether the site changed and the recipe needs a re-teach."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from .runner import RunStats

OK, WARNING, CRITICAL = "ok", "warning", "critical"
EXIT_CODES = {OK: 0, WARNING: 3, CRITICAL: 4}

BLANK_NOW = 0.5          # a field empty in more than half of the items...
BLANK_BEFORE = 0.2       # ...that used to be filled, is a broken selector
FIRST_RUN_BLANK = 0.9    # with nothing to compare with, only a nearly-always-empty field is suspicious
                         # (an optional field like a flight number is often blank in half the items)
DROP_RATIO = 0.3         # items seen fell below 30% of last time
DETAIL_FAIL_RATIO = 0.3  # details failed for more than 30% of items


@dataclass
class Report:
    status: str = OK
    messages: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.status]

    def add(self, level: str, message: str) -> None:
        self.messages.append(message)
        if level == CRITICAL or (level == WARNING and self.status == OK):
            self.status = level

    @property
    def headline(self) -> str:
        return {OK: "OK", WARNING: "WARNING - check the output", CRITICAL: "RE-TEACH NEEDED"}[self.status]


def blank_ratios(stats: RunStats) -> dict[str, float]:
    if not stats.rows_seen:
        return {}
    return {name: round(count / stats.rows_seen, 3) for name, count in stats.blank_counts.items()}


def assess(stats: RunStats, previous: dict | None = None) -> Report:
    """`previous` is the last entry of the workbook's `runs` sheet (see excel.read_history), or None."""
    report = Report()
    items_this_run = stats.rows_seen + stats.skipped_known

    if items_this_run == 0:
        report.add(CRITICAL, "no items found: the list selector no longer matches anything on the page")
        return report
    if stats.detail_aborted:
        report.add(CRITICAL, "details failed repeatedly: re-teach the item click and the popup's close control")
        return report

    prev_ratios: dict[str, float] = {}
    prev_items = 0
    if previous:
        try:
            prev_ratios = json.loads(previous.get("blank_ratios") or "{}")
        except (TypeError, ValueError):
            prev_ratios = {}
        try:
            prev_items = int(previous.get("items_seen") or 0)
        except (TypeError, ValueError):
            prev_items = 0

    for name, ratio in blank_ratios(stats).items():
        was = prev_ratios.get(name)
        pct = int(ratio * 100)
        if was is None:          # first run, or a column added since the last run
            if ratio >= FIRST_RUN_BLANK:
                report.add(WARNING, f"'{name}' is empty in {pct}% of items: its selector may have broken")
            elif ratio > BLANK_NOW:
                report.add(OK, f"'{name}' is empty in {pct}% of items - fine if it is optional on this site; "
                               "later runs only flag it if it gets worse")
        elif ratio > BLANK_NOW and was < BLANK_BEFORE:
            report.add(WARNING, f"'{name}' is empty in {pct}% of items (was {int(was * 100)}%): its selector may have broken")

    if prev_items and items_this_run < DROP_RATIO * prev_items:
        report.add(WARNING, f"items seen dropped from {prev_items} to {items_this_run}")

    if stats.rows_seen and stats.detail_errors > DETAIL_FAIL_RATIO * stats.rows_seen:
        report.add(WARNING, f"details failed for {stats.detail_errors} of {stats.rows_seen} items: the popup or close control may have changed")

    if stats.interrupted:
        report.add(WARNING, "run was interrupted; results are partial")

    return report
