"""Tests for --candidates and --cash CLI parsing."""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from cli.utils import (
    CashHoldings,
    parse_candidates_input,
    parse_cash_input,
)


# --- parse_candidates_input ----------------------------------------------


def test_returns_empty_for_none_or_blank():
    assert parse_candidates_input(None) == {}
    assert parse_candidates_input("") == {}
    assert parse_candidates_input("  ") == {}


def test_default_role_is_tactical():
    out = parse_candidates_input("NVO")
    assert out["NVO"]["role"] == "tactical"
    assert out["NVO"]["is_candidate"] is True
    assert out["NVO"]["quantity"] == 0
    assert out["NVO"]["avg_cost"] == 0


def test_role_override_via_colon_syntax():
    out = parse_candidates_input("NVO:anchor,GOOGL:speculative")
    assert out["NVO"]["role"] == "anchor"
    assert out["GOOGL"]["role"] == "speculative"


def test_mixed_with_and_without_role():
    out = parse_candidates_input("NVO,GOOGL:anchor,XOM")
    assert out["NVO"]["role"] == "tactical"
    assert out["GOOGL"]["role"] == "anchor"
    assert out["XOM"]["role"] == "tactical"


def test_normalizes_ticker_case_and_role_case():
    out = parse_candidates_input("nvo:Anchor")
    assert "NVO" in out
    assert out["NVO"]["role"] == "anchor"


def test_invalid_role_raises():
    with pytest.raises(ValueError, match="Invalid role"):
        parse_candidates_input("NVO:weird")


def test_invalid_default_role_raises():
    with pytest.raises(ValueError, match="default_role"):
        parse_candidates_input("NVO", default_role="weird")


def test_skips_empty_chunks():
    out = parse_candidates_input("NVO,,GOOGL,")
    assert set(out.keys()) == {"NVO", "GOOGL"}


# --- parse_cash_input ----------------------------------------------------


def test_returns_empty_for_none_or_blank():
    assert parse_cash_input(None) == CashHoldings()
    assert parse_cash_input("") == CashHoldings()


def test_parses_mep_cable_ars():
    out = parse_cash_input("MEP=3000,CABLE=1500,ARS=750000")
    assert out.mep_usd == 3000.0
    assert out.cable_usd == 1500.0
    assert out.ars_native == 750000.0


def test_keys_are_case_insensitive():
    out = parse_cash_input("mep=100,Cable=200,ars=300")
    assert out.mep_usd == 100.0
    assert out.cable_usd == 200.0
    assert out.ars_native == 300.0


def test_decimal_uses_period_separator():
    # Comma is reserved as the entry separator; decimals must use period.
    out = parse_cash_input("MEP=3000.5")
    assert out.mep_usd == 3000.5


def test_unknown_currency_raises():
    with pytest.raises(ValueError, match="Unknown currency"):
        parse_cash_input("EUR=100")


def test_negative_amount_raises():
    with pytest.raises(ValueError, match="Negative"):
        parse_cash_input("MEP=-100")


def test_missing_equals_raises():
    with pytest.raises(ValueError, match="KEY=VALUE"):
        parse_cash_input("MEP3000")


def test_invalid_amount_raises():
    with pytest.raises(ValueError, match="Invalid amount"):
        parse_cash_input("MEP=abc")


def test_needs_ars_rate_only_when_ars_present():
    no_ars = CashHoldings(mep_usd=1000)
    assert no_ars.has_ars() is False
    assert no_ars.needs_ars_rate() is False

    has_ars_no_rate = CashHoldings(ars_native=1000)
    assert has_ars_no_rate.has_ars() is True
    assert has_ars_no_rate.needs_ars_rate() is True

    has_ars_with_rate = CashHoldings(ars_native=1000, ars_to_usd_rate=1200)
    assert has_ars_with_rate.has_ars() is True
    assert has_ars_with_rate.needs_ars_rate() is False
