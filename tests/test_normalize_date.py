"""Tests for the normalize_date / parse_date helpers used by all vendors."""

import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.dataflows.utils import normalize_date, parse_date


def test_clean_date_roundtrips():
    assert normalize_date("2026-04-17") == "2026-04-17"


def test_strips_trailing_junk_from_llm_tool_call():
    # This is the exact shape Gemini produced in the prod log
    assert normalize_date("2026-04-17,indicator:macd") == "2026-04-17"


def test_handles_leading_and_trailing_whitespace():
    assert normalize_date("  2026-04-17  ") == "2026-04-17"


def test_extracts_date_from_natural_language():
    assert normalize_date("on 2026-04-17 at market close") == "2026-04-17"


def test_accepts_datetime_object():
    d = dt.datetime(2026, 4, 17, 10, 30)
    assert normalize_date(d) == "2026-04-17"


def test_accepts_date_object():
    d = dt.date(2026, 4, 17)
    assert normalize_date(d) == "2026-04-17"


def test_raises_with_field_name_when_no_date():
    with pytest.raises(ValueError, match="curr_date has no YYYY-MM-DD"):
        normalize_date("not a date at all", field_name="curr_date")


def test_raises_on_impossible_calendar_date():
    with pytest.raises(ValueError, match="not a valid calendar date"):
        normalize_date("2026-13-40")


def test_raises_on_wrong_type():
    with pytest.raises(TypeError):
        normalize_date(12345)  # type: ignore[arg-type]


def test_parse_date_returns_datetime():
    result = parse_date("2026-04-17,indicator:macd")
    assert isinstance(result, dt.datetime)
    assert result.year == 2026 and result.month == 4 and result.day == 17
