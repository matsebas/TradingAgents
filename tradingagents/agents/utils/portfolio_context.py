"""Formatting helpers for the portfolio_context injected into prompts."""

from __future__ import annotations

from typing import Any, Mapping


# Role-based decision guidance injected into Trader and Risk Judge prompts.
# These rules are intentionally specific (with enumerated thesis-change
# criteria, weight gates, and entry-quality conditions) so the LLM cannot
# rationalise around them. The Risk Judge prompt cites these rules as
# binding and the Phase-3 validator rejects outputs that contradict the
# role's default action without an explicit gate citation.
_ROLE_GUIDANCE_BASE: dict[str, str] = {
    "anchor": (
        "Anchors absorb cycles in full. Recommend SELL only if a STRUCTURAL "
        "thesis change is documented — cite which one explicitly:\n"
        "  • regime shift in monetary policy (sustained rate-path inversion);\n"
        "  • 3 consecutive quarters of YoY operating-income decline in "
        "underlying constituents;\n"
        "  • dividend cut / distribution halt (for income anchors);\n"
        "  • major regulatory or geopolitical event affecting the sector/index;\n"
        "  • structural change in index methodology that degrades quality.\n"
        "Default action: HOLD with a raised trailing stop. Technical "
        "extension (RSI / MACD / Bollinger) alone is NOT a thesis change. "
        "Never trim a structural anchor for short-term yield capture."
    ),
    "tactical": (
        "Tactical / single-name exposure. BUY (add) is permitted only if "
        "BOTH gates pass: (a) current portfolio weight for this position "
        "is BELOW the role's target band; (b) entry quality is 'optimal' — "
        "price is within ~1× ATR of the 20-day or 50-day SMA, NOT pegged "
        "to the upper Bollinger band. If either gate fails, default to "
        "HOLD. SELL only on trailing-stop hit OR on a fundamental shift "
        "(earnings revision, guidance cut, sector regime change) — not on "
        "RSI extremes alone."
    ),
    "speculative": (
        "Speculative / high-convexity. Expect 30%+ drawdowns as normal — "
        "do NOT exit on RSI/Bollinger touches. Adds are permitted only on "
        "a confirmed breakout above the prior 30-day range with elevated "
        "volume; never average up on momentum extension alone. Exits "
        "require a thesis break: supply/demand shift, regulation, "
        "protocol/security failure, or counterparty failure. Size discipline "
        "matters more than entry/exit timing."
    ),
}

# When a tactical position is already deep in the green, the asymmetry of
# adding worsens — protect the win first. This guidance overrides the base
# tactical rule when P&L >= +20%.
_TACTICAL_WINNER_HARDENED = (
    "Tactical / single-name exposure with P&L > +20%. Default action: "
    "HOLD with a tightened trailing stop — let the runner run. BUY (add) "
    "is permitted ONLY if BOTH gates pass:\n"
    "  • current portfolio weight is BELOW the role's target band, AND\n"
    "  • entry quality is 'optimal' — price within ~1× ATR of the 20-day "
    "or 50-day SMA, NOT riding the upper Bollinger band.\n"
    "If either gate fails, the decision MUST be HOLD. Do NOT chase price "
    "on a winner — the trailing stop manages the position from here. "
    "SELL only on trailing-stop hit or on a fundamental thesis break."
)


def role_guidance_for(
    role: str | None, ctx: Mapping[str, Any] | None = None
) -> str | None:
    """Return the role-based decision guidance, optionally hardened by P&L state.

    Tactical positions with unrealized return >= +20% receive the hardened
    "winner" guidance that requires both a weight gate and an entry-quality
    gate before any add. All other roles return their base guidance unchanged.
    """
    if not role:
        return None
    if role == "tactical" and ctx is not None:
        ret = ctx.get("unrealized_return_pct")
        try:
            ret_f = float(ret) if ret is not None else None
        except (TypeError, ValueError):
            ret_f = None
        if ret_f is not None and ret_f >= 0.20:
            return _TACTICAL_WINNER_HARDENED
    return _ROLE_GUIDANCE_BASE.get(role)


# Back-compat alias so external callers reading the old name still resolve.
_ROLE_GUIDANCE = _ROLE_GUIDANCE_BASE


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
    * ``role`` — ``"anchor"`` / ``"tactical"`` / ``"speculative"``; renders
      a short decision-bias snippet so the agent treats anchors structurally
      and doesn't trim winners on momentary technical signals.
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
    role = portfolio_context.get("role")
    notes = portfolio_context.get("notes")

    is_cedear = bool(instrument_type) and "cedear" in str(instrument_type).lower()

    lines: list[str] = [f"**Current Portfolio Position — {ticker}**"]
    if role:
        lines.append(f"- Position role: **{role}**")
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

    role_guidance = role_guidance_for(role, portfolio_context)
    if role_guidance:
        lines.append(f"- Decision guidance for **{role}**: {role_guidance}")

    if is_cedear and avg_cost is not None:
        lines.append(
            "- ⚠ The PPPC above is expressed in CEDEAR units (a CEDEAR "
            "represents a fraction of an underlying share), so it is NOT "
            "directly comparable to the underlying share price quoted in "
            "the Market/News reports. Use the Unrealized P&L % as the "
            "ground-truth measure of position performance."
        )

    aggregate_block = _format_portfolio_aggregate(
        portfolio_context.get("portfolio_aggregate")
    )
    if aggregate_block:
        lines.append("")
        lines.append(aggregate_block)

    prev_block = _format_previous_decision(
        portfolio_context.get("previous_decision")
    )
    if prev_block:
        lines.append("")
        lines.append(prev_block)

    # If the only line we produced is the heading, treat as no-op.
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _format_portfolio_aggregate(agg: Any) -> str:
    """Render the portfolio-level aggregate as a short block.

    Accepts either a ``PortfolioAggregate`` dataclass or the equivalent
    ``dict`` shape produced by ``PortfolioAggregate.to_dict()``.
    """
    if not agg:
        return ""

    if hasattr(agg, "to_dict"):
        data = agg.to_dict()
    elif isinstance(agg, Mapping):
        data = dict(agg)
    else:
        return ""

    total = data.get("total_positions")
    by_role = data.get("by_role") or {}
    top = data.get("top_concentrations") or ()

    if not by_role and not top:
        return ""

    lines: list[str] = ["**Portfolio-Level Context (whole book, computed once per run)**"]
    if total is not None:
        lines.append(f"- Total positions: {total}")

    role_lines: list[str] = []
    for role, bucket in by_role.items():
        if isinstance(bucket, Mapping):
            count = bucket.get("count")
            weight = bucket.get("cost_basis_weight_pct")
            avg_ret = bucket.get("avg_unrealized_return_pct")
        else:  # dataclass
            count = getattr(bucket, "count", None)
            weight = getattr(bucket, "cost_basis_weight_pct", None)
            avg_ret = getattr(bucket, "avg_unrealized_return_pct", None)
        if count is None or weight is None:
            continue
        ret_str = ""
        if avg_ret is not None:
            sign = "+" if avg_ret >= 0 else ""
            ret_str = f", avg P&L {sign}{avg_ret * 100:.2f}%"
        role_lines.append(
            f"  - **{role}**: {count} positions, {weight:.1f}% of cost basis{ret_str}"
        )
    if role_lines:
        lines.append("- Composition by role:")
        lines.extend(role_lines)

    if top:
        top_str = ", ".join(
            f"{t} {w:.1f}%" for t, w in top if t and w is not None
        )
        if top_str:
            lines.append(f"- Top concentrations (cost basis): {top_str}")

    lines.append(
        "- ⚠ Use this whole-book view when sizing recommendations. Do NOT "
        "recommend additions that push concentration past target weights, "
        "and do NOT exit anchor positions to fund tactical trades."
    )
    return "\n".join(lines)


def _format_previous_decision(prev: Any) -> str:
    """Render the prior decision for this ticker, with a stability directive."""
    if not prev:
        return ""

    if hasattr(prev, "to_dict"):
        data = prev.to_dict()
    elif isinstance(prev, Mapping):
        data = dict(prev)
    else:
        return ""

    decision = data.get("decision")
    date = data.get("date")
    days_ago = data.get("days_ago")
    if not decision:
        return ""

    suffix = f" ({days_ago} days ago)" if days_ago is not None else ""
    when = date or ""

    lines = [
        f"**Previous Decision** — {decision} on {when}{suffix}".rstrip(),
        (
            "- If your final call differs from the previous decision, you "
            "MUST cite a structural change (regime shift, thesis break, "
            "fundamental data shift, role reclassification). Technical "
            "oscillator changes (RSI/MACD/Bollinger) ALONE do not justify "
            "a flip — call those out as continuity, not as new information."
        ),
    ]
    return "\n".join(lines)
