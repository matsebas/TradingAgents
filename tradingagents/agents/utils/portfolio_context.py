"""Formatting helpers for the portfolio_context injected into prompts."""

from __future__ import annotations

from typing import Any, Mapping


def _format_number(value: Any) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.2f}"
    return str(value)


def format_portfolio_context(
    portfolio_context: Mapping[str, Any] | None, ticker: str
) -> str:
    """Render a ``portfolio_context`` dict as a short markdown block.

    Returns an empty string when the context is missing or has no usable
    fields, so callers can safely concatenate it into a prompt.

    Recognised keys (all optional):
    * ``avg_cost`` / ``pppc`` — weighted-average purchase price (row currency)
    * ``currency`` — e.g. ``"USD"`` / ``"MEP"``
    * ``quantity`` — number of shares / units held
    * ``unrealized_return_pct`` — fraction (e.g. ``0.219`` for +21.9%)
    * ``weight_pct`` — share of the portfolio (0-100)
    * ``instrument_type`` — e.g. ``"CEDEARS"`` (triggers a ratio warning)
    * ``notes`` — free-form string
    """
    if not portfolio_context:
        return ""

    avg_cost = portfolio_context.get("avg_cost")
    if avg_cost is None:
        avg_cost = portfolio_context.get("pppc")
    currency = portfolio_context.get("currency", "USD")
    quantity = portfolio_context.get("quantity")
    unrealized_pct = portfolio_context.get("unrealized_return_pct")
    weight_pct = portfolio_context.get("weight_pct")
    instrument_type = portfolio_context.get("instrument_type")
    notes = portfolio_context.get("notes")

    is_cedear = bool(instrument_type) and "cedear" in str(instrument_type).lower()

    lines: list[str] = [f"**Current Portfolio Position — {ticker}**"]
    if unrealized_pct is not None:
        sign = "+" if unrealized_pct >= 0 else ""
        lines.append(
            f"- Unrealized P&L on this position: {sign}{unrealized_pct * 100:.2f}%"
        )
    if quantity is not None:
        lines.append(f"- Quantity held: {_format_number(quantity)}")
    if avg_cost is not None:
        cost_label = "Weighted-average purchase price (PPPC)"
        if is_cedear:
            cost_label += " — CEDEAR units"
        lines.append(f"- {cost_label}: {_format_number(avg_cost)} {currency}")
    if weight_pct is not None:
        lines.append(f"- Portfolio weight: {_format_number(weight_pct)}%")
    if instrument_type:
        lines.append(f"- Instrument type: {instrument_type}")
    if notes:
        lines.append(f"- Notes: {notes}")

    if is_cedear and avg_cost is not None:
        lines.append(
            "- ⚠ The PPPC above is expressed in CEDEAR units (a CEDEAR "
            "represents a fraction of an underlying share), so it is NOT "
            "directly comparable to the underlying share price quoted in "
            "the Market/News reports. Use the Unrealized P&L % as the "
            "ground-truth measure of position performance."
        )

    # If the only line we produced is the heading, treat as no-op.
    if len(lines) == 1:
        return ""
    return "\n".join(lines)
