"""Parse FCI / cash-equivalent rows from a positions CSV into structured liquidity.

The same broker-export CSV that ``position_parser`` consumes also contains
rows with ``descripcion_tipo_especie == "Fondos"`` — Argentinian FCIs (mutual
funds), which act as the user's deployable USD liquidity. They split into:

* **Money market** — true cash-equivalent, immediate deploy. Detected by the
  literal ``MONEY MARKET`` substring in ``descripcion_instrumento``.
* **Fixed income** — short-duration USD bonds; 1-2 day deploy. Anything else
  under ``Fondos`` (typically ``RENTA FIJA`` lines).

Used by the candidate-evaluation pipeline so the Risk Judge can size new
positions against actual deployable capital, not against guesses.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from tradingagents.dataflows.position_parser import (
    _detect_separator,
    _parse_number,
)


FCI_TYPE_LABEL = "Fondos"
DESCRIPTION_COLUMN = "descripcion_instrumento"
TYPE_COLUMN = "descripcion_tipo_especie"
TICKER_COLUMN = "abreviatura_instrumento"
USD_VALUE_COLUMN = "valoracion_mep"  # USD-MEP equivalent of the FCI position


@dataclass(frozen=True)
class LiquidityItem:
    """One FCI row, classified."""

    ticker: str  # e.g. "27751"
    description: str  # e.g. "MAX MONEY MARKET DOLARES Clase A"
    valoracion_mep_usd: float
    is_money_market: bool


@dataclass(frozen=True)
class Liquidity:
    """Aggregated deployable-capital snapshot from the user's CSV."""

    items: tuple[LiquidityItem, ...] = ()
    total_money_market_usd: float = 0.0
    total_fixed_income_usd: float = 0.0
    # Optional cash holdings layered on top of FCI (passed via --cash flag).
    # Stored as plain floats in the source currency; ARS conversion is the
    # caller's responsibility (see CashHoldings in cli/utils.py).
    cash_mep_usd: float = 0.0
    cash_cable_usd: float = 0.0
    cash_ars_native: float = 0.0
    cash_ars_to_usd_rate: float | None = None  # MEP rate, when supplied

    @property
    def total_deployable_usd(self) -> float:
        """Sum of all USD-equivalent liquidity, including ARS converted via MEP rate."""
        ars_usd = 0.0
        if self.cash_ars_native > 0 and self.cash_ars_to_usd_rate:
            ars_usd = self.cash_ars_native / self.cash_ars_to_usd_rate
        return (
            self.total_money_market_usd
            + self.total_fixed_income_usd
            + self.cash_mep_usd
            + self.cash_cable_usd
            + ars_usd
        )

    def to_dict(self) -> dict:
        """Plain-dict form for prompt injection / JSON persistence."""
        return {
            "items": [
                {
                    "ticker": it.ticker,
                    "description": it.description,
                    "valoracion_mep_usd": it.valoracion_mep_usd,
                    "is_money_market": it.is_money_market,
                }
                for it in self.items
            ],
            "total_money_market_usd": self.total_money_market_usd,
            "total_fixed_income_usd": self.total_fixed_income_usd,
            "cash_mep_usd": self.cash_mep_usd,
            "cash_cable_usd": self.cash_cable_usd,
            "cash_ars_native": self.cash_ars_native,
            "cash_ars_to_usd_rate": self.cash_ars_to_usd_rate,
            "total_deployable_usd": self.total_deployable_usd,
        }


def _is_money_market(description: str) -> bool:
    """Detect money-market FCIs by description. Substring check is enough —
    the broker uses ``MAX MONEY MARKET`` consistently for cash-equivalent funds.
    """
    return "MONEY MARKET" in (description or "").upper()


def parse_liquidity_csv(path: str | Path) -> Liquidity:
    """Read ``Fondos`` rows from a positions CSV and return aggregated liquidity.

    Returns an empty ``Liquidity`` (totals = 0) when the file lacks a Fondos
    section — that's a valid state for a portfolio without FCIs.
    """
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Positions file not found: {csv_path}")

    items: list[LiquidityItem] = []
    money_market_total = 0.0
    fixed_income_total = 0.0

    with csv_path.open("r", encoding="utf-8") as f:
        sample = f.read(4096)
        f.seek(0)
        sep = _detect_separator(sample)
        reader = csv.DictReader(f, delimiter=sep)

        if reader.fieldnames is None or TYPE_COLUMN not in reader.fieldnames:
            return Liquidity()

        for row in reader:
            row_type = (row.get(TYPE_COLUMN, "") or "").strip()
            if row_type != FCI_TYPE_LABEL:
                continue

            ticker = (row.get(TICKER_COLUMN, "") or "").strip()
            description = (row.get(DESCRIPTION_COLUMN, "") or "").strip()
            usd_value = _parse_number(row.get(USD_VALUE_COLUMN))

            if not ticker or usd_value is None or usd_value <= 0:
                continue

            is_mm = _is_money_market(description)
            items.append(
                LiquidityItem(
                    ticker=ticker,
                    description=description,
                    valoracion_mep_usd=usd_value,
                    is_money_market=is_mm,
                )
            )
            if is_mm:
                money_market_total += usd_value
            else:
                fixed_income_total += usd_value

    return Liquidity(
        items=tuple(items),
        total_money_market_usd=round(money_market_total, 2),
        total_fixed_income_usd=round(fixed_income_total, 2),
    )


def merge_with_cash(
    liquidity: Liquidity,
    *,
    cash_mep_usd: float = 0.0,
    cash_cable_usd: float = 0.0,
    cash_ars_native: float = 0.0,
    cash_ars_to_usd_rate: float | None = None,
) -> Liquidity:
    """Layer cash holdings on top of an FCI-only Liquidity snapshot.

    Pure function; returns a new Liquidity. ARS holdings without an FX rate
    are stored but excluded from ``total_deployable_usd`` — caller should
    surface a warning to the user.
    """
    return Liquidity(
        items=liquidity.items,
        total_money_market_usd=liquidity.total_money_market_usd,
        total_fixed_income_usd=liquidity.total_fixed_income_usd,
        cash_mep_usd=cash_mep_usd,
        cash_cable_usd=cash_cable_usd,
        cash_ars_native=cash_ars_native,
        cash_ars_to_usd_rate=cash_ars_to_usd_rate,
    )
