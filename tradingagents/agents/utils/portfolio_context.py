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
    "candidate": (
        "Candidate / new position being evaluated for INITIATION. The "
        "decision space is reinterpreted: BUY = initiate the position; "
        "HOLD = add to watchlist (don't initiate now); SELL = reject "
        "the thesis. BUY (initiate) requires ALL of: (a) a fundamental "
        "thesis with explicit citation (not technical-only), (b) entry "
        "quality of 'optimal' or 'stretched' (NOT 'chasing'), (c) the "
        "candidate's target role bucket has headroom (current bucket weight "
        "below target), and (d) sector overlap is NOT 'full' when the "
        "target role bucket is already at/above target. The default "
        "starter size is 2% of total book, with the LLM permitted to "
        "scale to 1% (low-conviction starter) or 3% (high-conviction "
        "with rare circumstances). NEVER initiate a position whose size "
        "exceeds 5% of available USD-deployable liquidity."
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

    liquidity_block = _format_liquidity(portfolio_context.get("liquidity"))
    if liquidity_block:
        lines.append("")
        lines.append(liquidity_block)

    fit_block = _format_candidate_fit(portfolio_context.get("candidate_fit"))
    if fit_block:
        lines.append("")
        lines.append(fit_block)

    broker_block = _format_broker_constraints(
        portfolio_context.get("broker_features")
    )
    if broker_block:
        lines.append("")
        lines.append(broker_block)

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


def _format_liquidity(liquidity: Any) -> str:
    """Render the Liquidity snapshot for sizing new positions.

    Only relevant for candidates — for existing positions the Risk Judge
    doesn't size against deployable cash, it sizes against the existing
    holding. Caller decides when to inject this into the ctx.
    """
    if not liquidity:
        return ""
    if isinstance(liquidity, Mapping):
        data = dict(liquidity)
    elif hasattr(liquidity, "to_dict"):
        data = liquidity.to_dict()
    else:
        return ""

    mm = data.get("total_money_market_usd") or 0.0
    rf = data.get("total_fixed_income_usd") or 0.0
    cash_mep = data.get("cash_mep_usd") or 0.0
    cash_cable = data.get("cash_cable_usd") or 0.0
    cash_ars = data.get("cash_ars_native") or 0.0
    ars_rate = data.get("cash_ars_to_usd_rate")
    total = data.get("total_deployable_usd") or 0.0

    if total <= 0 and mm <= 0 and rf <= 0 and cash_mep <= 0 and cash_cable <= 0:
        return ""

    lines = ["**Available Liquidity for new positions**:"]
    if mm > 0:
        lines.append(f"- Money market FCI: ${mm:,.2f} USD — immediate deploy")
    if rf > 0:
        lines.append(f"- Fixed-income FCI: ${rf:,.2f} USD — 1-2 day deploy")
    if cash_mep > 0:
        lines.append(f"- Cash MEP: ${cash_mep:,.2f} USD")
    if cash_cable > 0:
        lines.append(f"- Cash CABLE: ${cash_cable:,.2f} USD")
    if cash_ars > 0:
        if ars_rate:
            usd_eq = cash_ars / ars_rate
            lines.append(
                f"- Cash ARS: ${cash_ars:,.2f} (≈ ${usd_eq:,.2f} USD @ rate {ars_rate})"
            )
        else:
            lines.append(
                f"- Cash ARS: ${cash_ars:,.2f} — NOT counted toward deployable USD (no rate)"
            )
    lines.append(f"- **TOTAL deployable**: ${total:,.2f} USD")
    lines.append(
        "- ⚠ Initial size for a new position MUST NOT exceed 5% of total "
        "deployable USD, regardless of book-weight target."
    )
    return "\n".join(lines)


def _format_candidate_fit(fit: Any) -> str:
    """Render the precomputed CandidateFit attributes for a candidate."""
    if not fit:
        return ""
    if isinstance(fit, Mapping):
        data = dict(fit)
    elif hasattr(fit, "to_dict"):
        data = fit.to_dict()
    else:
        return ""

    role_gap = data.get("role_gap") or {}
    overlap = data.get("sector_overlap") or {}

    role = role_gap.get("role") if isinstance(role_gap, Mapping) else getattr(role_gap, "role", "?")
    has_gap = role_gap.get("has_gap") if isinstance(role_gap, Mapping) else getattr(role_gap, "has_gap", False)
    cur = role_gap.get("current_weight_pct") if isinstance(role_gap, Mapping) else getattr(role_gap, "current_weight_pct", 0.0)
    tgt = role_gap.get("target_weight_pct") if isinstance(role_gap, Mapping) else getattr(role_gap, "target_weight_pct", 0.0)
    headroom = role_gap.get("headroom_pct") if isinstance(role_gap, Mapping) else getattr(role_gap, "headroom_pct", 0.0)

    overlap_level = overlap.get("level") if isinstance(overlap, Mapping) else getattr(overlap, "level", "none")
    overlap_sector = overlap.get("candidate_sector") if isinstance(overlap, Mapping) else getattr(overlap, "candidate_sector", None)
    overlap_industry = overlap.get("candidate_industry") if isinstance(overlap, Mapping) else getattr(overlap, "candidate_industry", None)
    overlap_with = overlap.get("overlapping_tickers") if isinstance(overlap, Mapping) else getattr(overlap, "overlapping_tickers", ())

    rec_pct = data.get("recommended_initial_weight_pct")
    rec_usd = data.get("recommended_initial_size_usd")

    lines = ["**Portfolio Fit for this Candidate**:"]
    gap_label = "FILLS gap" if has_gap else ("AT target" if abs(headroom) < 2.5 else "OVER target")
    lines.append(
        f"- Role gap ({role}): {gap_label} — current {cur:.1f}% vs target {tgt:.1f}% "
        f"(headroom {headroom:+.1f}%)"
    )

    sector_str = overlap_sector or "unknown"
    industry_str = overlap_industry or "unknown"
    if overlap_level == "full":
        with_str = ", ".join(overlap_with) if overlap_with else "—"
        lines.append(
            f"- Sector overlap: **FULL** — {sector_str} / {industry_str} "
            f"overlaps with: {with_str}"
        )
    elif overlap_level == "partial":
        with_str = ", ".join(overlap_with) if overlap_with else "—"
        lines.append(
            f"- Sector overlap: **partial** — same sector ({sector_str}) "
            f"as: {with_str}, different industry ({industry_str})"
        )
    else:
        lines.append(
            f"- Sector overlap: none — {sector_str} / {industry_str} is novel exposure"
        )

    if rec_pct is not None:
        if rec_usd is not None:
            lines.append(
                f"- Recommended initial size: {rec_pct:.1f}% of book = ${rec_usd:,.2f} USD "
                f"(scale 1-3% based on conviction; cap at 5% of deployable liquidity)"
            )
        else:
            lines.append(
                f"- Recommended initial size: {rec_pct:.1f}% of book "
                f"(USD figure unknown — book size not provided)"
            )

    lines.append(
        "- ⚠ HARD GATE: BUY (initiate) is INVALID if sector overlap == 'full' AND "
        "the target role bucket is already at/above target weight. In that case "
        "the only valid call is HOLD (watchlist) until the bucket frees up."
    )
    return "\n".join(lines)


def _format_broker_constraints(broker_features: Any) -> str:
    """Render broker-capability constraints when restricted.

    Only emits a block when the broker is missing automatic execution features
    (stop_loss, bracket) — otherwise the LLM has no reason to reframe its
    output. When emitted, the block tells the Risk Judge to express exits as
    manual-monitoring conditions and to use ``stop_loss.type = "manual_monitor"``.
    """
    if not broker_features:
        return ""
    if isinstance(broker_features, str):
        features = {broker_features.lower().strip()}
    elif isinstance(broker_features, (list, tuple, set, frozenset)):
        features = {str(f).lower().strip() for f in broker_features}
    else:
        return ""

    has_gtd = "gtd" in features
    has_stop = "stop_loss" in features or "stop-loss" in features
    has_bracket = "bracket" in features

    # If the broker has stops AND brackets, no special framing needed.
    if has_stop and has_bracket:
        return ""

    if not has_gtd:
        # Without GTD we can't even suggest a price-conditional order.
        return (
            "**Broker constraints**: limited capability. The user cannot "
            "place price-conditional orders. Express ALL entries and exits "
            "as conditions to monitor manually, with explicit price levels."
        )

    lines = ["**Broker constraints**: GTD (limit) orders only."]
    missing = []
    if not has_stop:
        missing.append("automatic stop-loss")
    if not has_bracket:
        missing.append("bracket / OCO orders")
    if missing:
        lines.append(f"- The broker does NOT support: {', '.join(missing)}.")
    lines.append(
        "- Entries: express as a GTD limit price + plazo (e.g. \"GTD buy "
        "limit at $X for N days\")."
    )
    lines.append(
        "- Exits: express as MANUAL monitoring conditions, NOT automatic "
        "orders. Set ``stop_loss.type = \"manual_monitor\"`` and write the "
        "value as the trigger level. Example: \"if close < $35, place GTD "
        "sell at $34 next session\"."
    )
    lines.append(
        "- The user reads this report and places the GTD orders himself; "
        "any exit logic that requires an automatic stop will not execute."
    )
    return "\n".join(lines)
