"""Tests for sector_lookup cache semantics — particularly the no-cache-on-failure
behaviour that prevents transient yfinance failures from poisoning the cache.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import tradingagents.dataflows.sector_lookup as sl
from tradingagents.dataflows.sector_lookup import lookup_sector, reset_cache


def setup_function(_):
    reset_cache()


# --- ETF fallback table -------------------------------------------------


def test_etf_fallback_resolves_known_tickers():
    # Don't even hit yfinance — fallback for SPY is hardcoded.
    info = lookup_sector("SPY")
    assert info.sector == "US Equity"
    assert info.industry == "Broad Market"


def test_etf_fallback_normalizes_case():
    info = lookup_sector("spy")
    assert info.sector == "US Equity"


# --- transient failure does NOT poison the cache ------------------------


def test_yfinance_failure_is_not_cached_when_no_fallback():
    """yfinance raises → result has sector=None → must NOT be cached so
    the next call retries instead of returning the stale failure."""
    class _BoomTicker:
        @property
        def info(self):
            raise RuntimeError("simulated 429 rate limit")

    with patch.object(sl, "_CACHE", {}) as cache, \
         patch("yfinance.Ticker", return_value=_BoomTicker()):
        info = lookup_sector("UNKNOWNTICKER123")
        assert info.sector is None
        # The transient-failure result must NOT be in the cache.
        assert "UNKNOWNTICKER123" not in cache


def test_etf_fallback_cached_even_when_yfinance_fails():
    """If yfinance raises but the ticker has an ETF fallback, the result IS
    stable (deterministic from the table) and SHOULD be cached."""
    class _BoomTicker:
        @property
        def info(self):
            raise RuntimeError("simulated network error")

    with patch.object(sl, "_CACHE", {}) as cache, \
         patch("yfinance.Ticker", return_value=_BoomTicker()):
        info = lookup_sector("SPY")
        assert info.sector == "US Equity"
        assert "SPY" in cache  # stable fallback hit IS cached


def test_successful_yfinance_result_is_cached():
    """A successful yfinance lookup with sector data is stable and should be
    cached so we don't hit the network repeatedly."""
    class _OkTicker:
        info = {
            "sector": "Technology",
            "industry": "Semiconductors",
            "quoteType": "EQUITY",
        }

    with patch.object(sl, "_CACHE", {}) as cache, \
         patch("yfinance.Ticker", return_value=_OkTicker()):
        info = lookup_sector("FAKE_NVDA")
        assert info.sector == "Technology"
        assert "FAKE_NVDA" in cache


def test_unknown_ticker_with_no_data_is_cached_as_none():
    """yfinance succeeds but returns no sector AND no fallback exists →
    that's a stable 'unknown ticker' result, safe to cache (avoids
    repeatedly thrashing yfinance for the same dud)."""
    class _EmptyTicker:
        info = {"quoteType": "UNKNOWN"}

    with patch.object(sl, "_CACHE", {}) as cache, \
         patch("yfinance.Ticker", return_value=_EmptyTicker()):
        info = lookup_sector("TRULY_UNKNOWN")
        assert info.sector is None
        # Stable result — yfinance returned, just empty. Cache it.
        assert "TRULY_UNKNOWN" in cache


def test_reset_cache_clears_entries():
    reset_cache()
    info1 = lookup_sector("SPY")
    assert info1.sector == "US Equity"
    reset_cache()
    # After reset the cache should be empty — next lookup recomputes.
    assert len(sl._CACHE) == 0
