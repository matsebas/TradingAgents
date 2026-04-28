"""Cross-run decision history — read the previous portfolio report's decision
for a given ticker so the Risk Judge can be challenged when flipping.

The portfolio reporter writes ``reports/portfolio_<DATE>.md`` with a top
summary table:

    | Ticker | Decision | Duration | Log | Error |
    |--------|----------|---------:|-----|-------|
    | NVDA   | BUY      | 254.9s   | ... |       |

This module parses that table from the most recent report dated strictly
before the current run, so the Risk Judge can compare its proposed call
against the prior call and justify any change with a structural reason.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import asdict, dataclass
from pathlib import Path


# Match a row in the summary table. Decisions are normalized to upper-case.
_TABLE_ROW_RE = re.compile(
    r"^\|\s*([A-Z][A-Z0-9.\-]*)\s*\|\s*(BUY|SELL|HOLD)\b",
    re.IGNORECASE,
)
_FILENAME_DATE_RE = re.compile(r"^portfolio_(\d{4}-\d{2}-\d{2})\.md$")


@dataclass(frozen=True)
class PreviousDecision:
    ticker: str
    decision: str  # "BUY" | "HOLD" | "SELL"
    date: str  # ISO YYYY-MM-DD
    days_ago: int

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_date(s: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(s)
    except ValueError:
        return None


def _list_prior_reports(reports_dir: Path, before: _dt.date) -> list[tuple[_dt.date, Path]]:
    """List ``(date, path)`` for portfolio_*.md files dated strictly before
    ``before``, most-recent first. Filenames that don't parse are ignored.
    """
    if not reports_dir.exists():
        return []
    out: list[tuple[_dt.date, Path]] = []
    for entry in reports_dir.iterdir():
        if not entry.is_file():
            continue
        m = _FILENAME_DATE_RE.match(entry.name)
        if not m:
            continue
        d = _parse_date(m.group(1))
        if d is None or d >= before:
            continue
        out.append((d, entry))
    out.sort(key=lambda x: x[0], reverse=True)
    return out


def _scan_decision(report_path: Path, ticker: str) -> str | None:
    """Return the decision string for ``ticker`` from a portfolio report,
    or None if not found. Only the summary table is consulted — the per-ticker
    sections later in the file are detailed prose, not authoritative.
    """
    target = ticker.strip().upper()
    try:
        with report_path.open("r", encoding="utf-8") as f:
            for line in f:
                # The summary table sits before the first ``## Detailed`` block.
                # Once we cross that, stop scanning to avoid matching prose.
                if line.startswith("## Detailed decisions"):
                    break
                m = _TABLE_ROW_RE.match(line)
                if not m:
                    continue
                if m.group(1).upper() == target:
                    return m.group(2).upper()
    except OSError:
        return None
    return None


def load_previous_decision(
    ticker: str,
    current_date: str,
    reports_dir: str | Path = "reports",
) -> PreviousDecision | None:
    """Find the most recent portfolio report dated strictly before
    ``current_date`` and return the prior decision for ``ticker``.

    Returns ``None`` when:
    * ``reports_dir`` doesn't exist;
    * no prior portfolio report exists;
    * no prior report contains a row for ``ticker``;
    * ``current_date`` is malformed.

    The ``current_date`` filter is exclusive — a report dated the same day
    is ignored (we want history, not the current run's own output).
    """
    cur = _parse_date(current_date)
    if cur is None:
        return None

    reports_path = Path(reports_dir)
    for prior_date, path in _list_prior_reports(reports_path, before=cur):
        decision = _scan_decision(path, ticker)
        if decision is None:
            continue
        return PreviousDecision(
            ticker=ticker.strip().upper(),
            decision=decision,
            date=prior_date.isoformat(),
            days_ago=(cur - prior_date).days,
        )
    return None
