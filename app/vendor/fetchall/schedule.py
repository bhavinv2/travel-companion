"""Build (and optionally install) a Windows Task Scheduler task that runs a recipe incrementally."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from .teach import recipe_filename


def parse_every(every: str) -> tuple[str, str | None]:
    """'30m' -> ('MINUTE','30'); '6h' -> ('HOURLY','6'); 'daily' -> ('DAILY',None); 'weekly' -> ('WEEKLY',None)."""
    e = every.strip().lower()
    if e in ("daily", "1d", "24h"):
        return "DAILY", None
    if e in ("weekly", "7d"):
        return "WEEKLY", None
    m = re.fullmatch(r"(\d+)\s*([mh])", e)
    if not m:
        raise ValueError(f"--every must look like 30m, 6h, daily or weekly (got {every!r})")
    n, unit = int(m.group(1)), m.group(2)
    if unit == "h" and n >= 24 and n % 24 == 0:
        return "DAILY", None
    return ("MINUTE", str(n)) if unit == "m" else ("HOURLY", str(n))


def task_name(site: str) -> str:
    return f"fetchall {recipe_filename(site)}"


def batch_script(site: str, out: str | Path, workdir: str | Path, python: str | None = None) -> str:
    """A .cmd file the task runs: an incremental run, output appended to logs/<site>.log.

    Task Scheduler's /TR argument cannot carry nested quotes reliably, so the command lives in a file.
    """
    py = python or sys.executable
    log = Path("logs") / f"{recipe_filename(site)}.log"
    return (f"@echo off\r\ncd /d \"{Path(workdir)}\"\r\n"
            f"\"{py}\" -m fetchall run \"{site}\" --incremental --out \"{out}\" >> \"{log}\" 2>&1\r\n")


def batch_path(site: str, workdir: str | Path) -> Path:
    return Path(workdir) / "logs" / f"run-{recipe_filename(site)}.cmd"


def write_batch(site: str, out: str | Path, workdir: str | Path, python: str | None = None) -> Path:
    path = batch_path(site, workdir)
    path.parent.mkdir(parents=True, exist_ok=True)
    # bytes, not text mode: Windows text mode would turn the CRLF endings into CR CR LF
    path.write_bytes(batch_script(site, out, workdir, python).encode("utf-8"))
    return path


def schtasks_create(site: str, every: str, at: str | None, script: str | Path) -> list[str]:
    sc, modifier = parse_every(every)
    cmd = ["schtasks", "/Create", "/F", "/TN", task_name(site), "/SC", sc]
    if modifier:
        cmd += ["/MO", modifier]
    if at and sc in ("DAILY", "WEEKLY"):
        cmd += ["/ST", at]
    cmd += ["/TR", str(script)]
    return cmd


def schtasks_delete(site: str) -> list[str]:
    return ["schtasks", "/Delete", "/F", "/TN", task_name(site)]


def cron_line(site: str, every: str, at: str | None, out: str | Path, workdir: str | Path,
              python: str | None = None) -> str:
    """Equivalent crontab line for macOS/Linux users."""
    sc, modifier = parse_every(every)
    hour, minute = (at or "07:00").split(":")
    spec = {"MINUTE": f"*/{modifier} * * * *", "HOURLY": f"{int(minute)} */{modifier} * * *",
            "DAILY": f"{int(minute)} {int(hour)} * * *", "WEEKLY": f"{int(minute)} {int(hour)} * * 1"}[sc]
    py = python or "python3"
    return (f"{spec} cd '{workdir}' && {py} -m fetchall run '{site}' --incremental --out '{out}' "
            f">> logs/{recipe_filename(site)}.log 2>&1")


def quote(cmd: list[str]) -> str:
    return " ".join(f'"{c}"' if " " in c and not c.startswith('"') else c for c in cmd)


def install(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)
