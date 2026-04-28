"""Tests for cross-run decision history."""

import os
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.dataflows.previous_decision import (
    PreviousDecision,
    load_previous_decision,
)


def _write_report(tmp_path: Path, date: str, rows: list[tuple[str, str]]) -> Path:
    """Write a minimal portfolio_<date>.md fixture and return its path."""
    body = textwrap.dedent(
        f"""\
        # Portfolio Analysis — {date}

        | Ticker | Decision | Duration | Log | Error |
        |--------|----------|---------:|-----|-------|
        """
    )
    for ticker, decision in rows:
        body += f"| {ticker} | {decision} | 100.0s | [JSON](x) |  |\n"
    body += "\n## Detailed decisions\n\n"
    # A trailing per-ticker section that should NOT be matched.
    for ticker, _ in rows:
        body += f"### {ticker} — IGNOREME\n\n"
    path = tmp_path / f"portfolio_{date}.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_returns_none_when_reports_dir_missing(tmp_path: Path):
    assert (
        load_previous_decision(
            "NVDA", "2026-04-28", reports_dir=tmp_path / "missing"
        )
        is None
    )


def test_returns_none_when_no_prior_report(tmp_path: Path):
    # Same-day report should NOT count.
    _write_report(tmp_path, "2026-04-28", [("NVDA", "BUY")])
    assert (
        load_previous_decision("NVDA", "2026-04-28", reports_dir=tmp_path) is None
    )


def test_returns_none_when_ticker_missing_from_prior_report(tmp_path: Path):
    _write_report(tmp_path, "2026-04-17", [("NVDA", "BUY")])
    assert (
        load_previous_decision("AMZN", "2026-04-28", reports_dir=tmp_path) is None
    )


def test_finds_decision_in_most_recent_prior_report(tmp_path: Path):
    _write_report(tmp_path, "2026-04-17", [("SPY", "SELL")])
    _write_report(tmp_path, "2026-04-23", [("SPY", "HOLD")])

    prev = load_previous_decision("SPY", "2026-04-28", reports_dir=tmp_path)
    assert isinstance(prev, PreviousDecision)
    assert prev.ticker == "SPY"
    assert prev.decision == "HOLD"
    assert prev.date == "2026-04-23"
    assert prev.days_ago == 5


def test_skips_reports_that_dont_contain_the_ticker(tmp_path: Path):
    # Most recent prior doesn't have NVDA → fall through to older one.
    _write_report(tmp_path, "2026-04-17", [("NVDA", "BUY")])
    _write_report(tmp_path, "2026-04-23", [("AMZN", "HOLD")])

    prev = load_previous_decision("NVDA", "2026-04-28", reports_dir=tmp_path)
    assert prev is not None
    assert prev.date == "2026-04-17"
    assert prev.decision == "BUY"


def test_decision_is_normalized_to_uppercase(tmp_path: Path):
    # Some reports may use mixed case in the table.
    _write_report(tmp_path, "2026-04-23", [("NVDA", "Buy")])
    prev = load_previous_decision("NVDA", "2026-04-28", reports_dir=tmp_path)
    assert prev is not None
    assert prev.decision == "BUY"


def test_only_summary_table_is_consulted_not_per_ticker_sections(tmp_path: Path):
    # Detailed section claims SELL, but summary table has BUY. We trust the
    # table — it's the authoritative source-of-truth.
    body = textwrap.dedent(
        """\
        # Portfolio Analysis — 2026-04-23

        | Ticker | Decision | Duration | Log | Error |
        |--------|----------|---------:|-----|-------|
        | NVDA | BUY | 100s | x |  |

        ## Detailed decisions

        ### NVDA — SELL

        | NVDA | SELL | should-not-match |
        """
    )
    path = tmp_path / "portfolio_2026-04-23.md"
    path.write_text(body, encoding="utf-8")

    prev = load_previous_decision("NVDA", "2026-04-28", reports_dir=tmp_path)
    assert prev is not None
    assert prev.decision == "BUY"


def test_invalid_current_date_returns_none(tmp_path: Path):
    _write_report(tmp_path, "2026-04-23", [("NVDA", "BUY")])
    assert load_previous_decision("NVDA", "not-a-date", reports_dir=tmp_path) is None


def test_unparseable_filenames_are_ignored(tmp_path: Path):
    # Files that don't match portfolio_YYYY-MM-DD.md must be skipped.
    (tmp_path / "portfolio.md").write_text("nope", encoding="utf-8")
    (tmp_path / "portfolio_invalid.md").write_text("nope", encoding="utf-8")
    _write_report(tmp_path, "2026-04-17", [("NVDA", "HOLD")])

    prev = load_previous_decision("NVDA", "2026-04-28", reports_dir=tmp_path)
    assert prev is not None and prev.decision == "HOLD"


def test_to_dict_round_trip_is_json_friendly():
    import json

    pd = PreviousDecision(
        ticker="SPY", decision="HOLD", date="2026-04-23", days_ago=5
    )
    json.dumps(pd.to_dict())
