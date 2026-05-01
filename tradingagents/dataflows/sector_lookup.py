"""Sector / industry lookup for tickers, used by candidate-fit math.

Wraps ``yfinance.Ticker(t).info`` with a per-process cache. Single equities
(``quoteType == "EQUITY"``) get their real sector + industry; ETFs return
``None`` for sector from yfinance, so we layer a small curated fallback
table for the most common index/thematic ETFs the user might hold.

The lookup is best-effort: if yfinance fails or returns nothing useful, we
return a ``SectorInfo`` with ``sector=None`` so callers can degrade
gracefully (skip overlap check rather than block the whole pipeline).
"""

from __future__ import annotations

from dataclasses import dataclass


# ETF / fund quote types from yfinance.
_ETF_QUOTE_TYPES = {"ETF", "MUTUALFUND"}


# Curated mapping for ETFs that yfinance doesn't tag with sector/industry.
# Keep this list focused on the user's actual book + likely candidates;
# unknown ETFs gracefully return None.
_ETF_FALLBACK: dict[str, tuple[str, str]] = {
    # US broad
    "SPY": ("US Equity", "Broad Market"),
    "IVV": ("US Equity", "Broad Market"),
    "VOO": ("US Equity", "Broad Market"),
    "VTI": ("US Equity", "Total Market"),
    "ITOT": ("US Equity", "Total Market"),
    "QQQ": ("US Equity", "Large Cap Tech"),
    "DIA": ("US Equity", "Large Cap Industrial"),
    "IWM": ("US Equity", "Small Cap"),
    # Sector
    "SMH": ("Technology", "Semiconductors"),
    "SOXX": ("Technology", "Semiconductors"),
    "XLK": ("Technology", "Broad Tech"),
    "XLF": ("Financials", "Broad Financials"),
    "XLE": ("Energy", "Broad Energy"),
    "XLV": ("Healthcare", "Broad Healthcare"),
    "XLY": ("Consumer Cyclical", "Broad Discretionary"),
    "XLP": ("Consumer Defensive", "Broad Staples"),
    "XLI": ("Industrials", "Broad Industrials"),
    "XLU": ("Utilities", "Broad Utilities"),
    "XLB": ("Materials", "Broad Materials"),
    "XLRE": ("Real Estate", "Broad Real Estate"),
    "XLC": ("Communication Services", "Broad Communications"),
    # Crypto / digital assets
    "IBIT": ("Crypto", "Bitcoin"),
    "BITB": ("Crypto", "Bitcoin"),
    "FBTC": ("Crypto", "Bitcoin"),
    "ARKB": ("Crypto", "Bitcoin"),
    "GBTC": ("Crypto", "Bitcoin"),
    "ETHV": ("Crypto", "Ethereum"),
    "ETHA": ("Crypto", "Ethereum"),
    "FETH": ("Crypto", "Ethereum"),
    # Commodities
    "GLD": ("Commodities", "Gold"),
    "IAU": ("Commodities", "Gold"),
    "SLV": ("Commodities", "Silver"),
    "USO": ("Commodities", "Oil"),
    # International / EM
    "EFA": ("International Equity", "Developed Markets"),
    "VEA": ("International Equity", "Developed Markets"),
    "IEMG": ("International Equity", "Emerging Markets"),
    "VWO": ("International Equity", "Emerging Markets"),
    "EWZ": ("International Equity", "Brazil"),
    "EWJ": ("International Equity", "Japan"),
    # Fixed income
    "AGG": ("Fixed Income", "Aggregate"),
    "BND": ("Fixed Income", "Aggregate"),
    "TLT": ("Fixed Income", "Long Treasury"),
    "IEF": ("Fixed Income", "Intermediate Treasury"),
    "SHY": ("Fixed Income", "Short Treasury"),
    "LQD": ("Fixed Income", "IG Credit"),
    "HYG": ("Fixed Income", "High Yield"),
    # Innovation / thematic
    "ARKK": ("Technology", "Innovation High-Beta"),
}


@dataclass(frozen=True)
class SectorInfo:
    ticker: str
    sector: str | None
    industry: str | None
    quote_type: str  # "EQUITY" | "ETF" | "MUTUALFUND" | "UNKNOWN"

    @property
    def is_etf(self) -> bool:
        return self.quote_type in _ETF_QUOTE_TYPES

    @property
    def has_sector(self) -> bool:
        return self.sector is not None


# Manual cache (not lru_cache) so we can selectively avoid caching transient
# yfinance failures — caching ``sector=None`` for the entire process lifetime
# would silently disable the overlap check for any ticker that hits a
# rate-limit on its first lookup.
_CACHE: dict[str, SectorInfo] = {}


def lookup_sector(ticker: str) -> SectorInfo:
    """Return sector / industry for a ticker. Cached per-process.

    Order:
    1. Try yfinance live lookup. EQUITY rows return real sector/industry.
    2. For ETFs (or when yfinance lacks sector), consult the curated fallback.
    3. On yfinance exception (network, rate limit, parse error) WITHOUT a
       fallback hit, return ``sector=None`` but DO NOT cache the result —
       the next call retries. This prevents a single 429 from poisoning the
       cache for the rest of the run.
    4. Empty results (yfinance returned but no sector AND no fallback match)
       ARE cached — that's a stable "unknown ticker" result.
    """
    t = ticker.strip().upper()
    if not t:
        return SectorInfo(ticker=t, sector=None, industry=None, quote_type="UNKNOWN")

    cached = _CACHE.get(t)
    if cached is not None:
        return cached

    quote_type = "UNKNOWN"
    sector = None
    industry = None
    fetch_failed = False

    try:
        import yfinance as yf

        info = yf.Ticker(t).info or {}
        quote_type = (info.get("quoteType") or "UNKNOWN").upper()
        sector = info.get("sector")
        industry = info.get("industry")
    except Exception:
        # yfinance can fail in many ways (network, rate limits, parse errors).
        # Don't propagate — fall through to the ETF fallback. Mark as failed
        # so we don't cache the negative result.
        fetch_failed = True

    if not sector and t in _ETF_FALLBACK:
        sector, industry = _ETF_FALLBACK[t]
        if quote_type == "UNKNOWN":
            quote_type = "ETF"
        fetch_failed = False  # fallback recovered the result

    result = SectorInfo(
        ticker=t,
        sector=sector,
        industry=industry,
        quote_type=quote_type,
    )

    # Only cache stable results — transient failures retry on next call.
    if not fetch_failed:
        _CACHE[t] = result
    return result


def reset_cache() -> None:
    """Clear the per-process cache. Useful for tests."""
    _CACHE.clear()
