"""Cross-asset wealth snapshot — what the Portfolio Manager really needs to see.

Background. The system used to present the Portfolio Manager with two
disjoint views:

- ``portfolio_aggregate``: role buckets and concentrations computed against
  the *equity sleeve* (CEDEARs / stocks) only.
- ``Liquidity``: FCIs (money market + fixed income) + raw cash, treated as
  "deployable capital" — never aggregated with equities.

That made the manager believe the user's tactical bucket was 61% of the
portfolio when, against total wealth (equities + FCI + cash), it was
closer to 10%. The "concentration crisis" it diagnosed was an artefact of
a misleading denominator. For a retirement mandate the right denominator
is **total wealth**, broken down by asset class — equities, fixed income,
cash equivalent — so the manager can recommend allocation moves both
within and across sleeves.

This module unifies the two views. ``compute_wealth_snapshot`` consumes
the same ``holdings`` dict the per-ticker pipeline uses, the serialised
``Liquidity`` snapshot, and the post-analysis ``PortfolioResult`` list
(needed for unrealised P&L → mark-to-market). It returns a flat dict
that the prompt brief renders.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ars_to_usd(liquidity: Mapping[str, Any]) -> float:
    ars_native = _safe_float(liquidity.get("cash_ars_native"))
    rate = liquidity.get("cash_ars_to_usd_rate")
    if ars_native > 0 and rate:
        try:
            return ars_native / float(rate)
        except (TypeError, ValueError, ZeroDivisionError):
            return 0.0
    return 0.0


def compute_wealth_snapshot(
    results: Iterable[Any] | None,
    holdings: Mapping[str, Mapping[str, Any]] | None,
    liquidity: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build the unified equity + fixed income + cash snapshot.

    All amounts are in USD-MEP. ``results`` only contributes per-ticker
    unrealised return so we can mark-to-market the equity sleeve; if a
    ticker has no result (still pending, or candidate with qty=0) we fall
    back to its cost basis.
    """
    holdings = dict(holdings or {})
    liq = dict(liquidity or {})
    results_by_ticker: dict[str, Any] = {}
    for r in results or ():
        if getattr(r, "ticker", None):
            results_by_ticker[r.ticker] = r

    equity_items: list[dict[str, Any]] = []
    for ticker, ctx in holdings.items():
        qty = _safe_float(ctx.get("qty"))
        avg_cost = _safe_float(ctx.get("avg_cost"))
        cost_basis = qty * avg_cost
        if cost_basis <= 0:
            continue  # qty=0 candidates are not part of the wealth snapshot

        # Mark-to-market: prefer the unrealized return reported by the Risk
        # Judge layer (it's already injected into portfolio_context), fall
        # back to cost basis when missing.
        ret_pct = None
        result = results_by_ticker.get(ticker)
        if result is not None and result.state:
            pctx = result.state.get("portfolio_context") or {}
            ret_pct = pctx.get("unrealized_return_pct")
        # Some pipelines stash it directly on the input ctx — honour that too.
        if ret_pct is None:
            ret_pct = ctx.get("unrealized_return_pct")
        ret_pct_f = _safe_float(ret_pct, default=0.0) if ret_pct is not None else 0.0
        mtm = cost_basis * (1.0 + ret_pct_f / 100.0) if ret_pct is not None else cost_basis

        equity_items.append(
            {
                "ticker": ticker,
                "role": ctx.get("role"),
                "qty": qty,
                "avg_cost": avg_cost,
                "cost_basis_usd": round(cost_basis, 2),
                "mtm_usd": round(mtm, 2),
                "unrealized_return_pct": ret_pct,
                "currency": ctx.get("currency"),
                "instrument_type": ctx.get("instrument_type"),
            }
        )

    equity_total = round(sum(i["mtm_usd"] for i in equity_items), 2)

    # Fixed income vs money market: items already classified by liquidity_parser.
    raw_items = liq.get("items") or []
    fi_items = [
        {
            "ticker": it.get("ticker"),
            "description": it.get("description"),
            "usd": _safe_float(it.get("valoracion_mep_usd")),
        }
        for it in raw_items
        if isinstance(it, Mapping) and not it.get("is_money_market")
    ]
    mm_items = [
        {
            "ticker": it.get("ticker"),
            "description": it.get("description"),
            "usd": _safe_float(it.get("valoracion_mep_usd")),
        }
        for it in raw_items
        if isinstance(it, Mapping) and it.get("is_money_market")
    ]

    fi_total = round(_safe_float(liq.get("total_fixed_income_usd")), 2)
    mm_total = round(_safe_float(liq.get("total_money_market_usd")), 2)

    # Raw cash from --cash flag, including ARS converted via MEP rate.
    cash_mep = _safe_float(liq.get("cash_mep_usd"))
    cash_cable = _safe_float(liq.get("cash_cable_usd"))
    cash_ars_usd = _ars_to_usd(liq)
    cash_total = round(cash_mep + cash_cable + cash_ars_usd, 2)

    # Cash equivalent = raw cash + money market FCIs (both effectively cash
    # for retirement-horizon allocation purposes).
    cash_equiv_total = round(cash_total + mm_total, 2)

    total_wealth = round(equity_total + fi_total + cash_equiv_total, 2)

    def pct(amount: float) -> float | None:
        if total_wealth <= 0:
            return None
        return round(100.0 * amount / total_wealth, 2)

    # Per-ticker concentration against TOTAL WEALTH (not just equity).
    for it in equity_items:
        it["pct_of_wealth"] = pct(it["mtm_usd"])

    # Top concentrations across the whole book.
    top = sorted(
        (
            {"ticker": it["ticker"], "usd": it["mtm_usd"], "pct_of_wealth": it["pct_of_wealth"]}
            for it in equity_items
        ),
        key=lambda x: x["usd"],
        reverse=True,
    )[:5]

    # Equity role breakdown vs WEALTH (the existing portfolio_aggregate already
    # has role weights vs the equity sleeve — we recompute against wealth here
    # to give the manager both lenses without it having to renormalise).
    role_buckets: dict[str, dict[str, Any]] = {}
    for it in equity_items:
        role = it.get("role") or "unspecified"
        bucket = role_buckets.setdefault(
            role,
            {"role": role, "tickers": [], "mtm_usd": 0.0},
        )
        bucket["tickers"].append(it["ticker"])
        bucket["mtm_usd"] += it["mtm_usd"]
    for bucket in role_buckets.values():
        bucket["mtm_usd"] = round(bucket["mtm_usd"], 2)
        bucket["pct_of_wealth"] = pct(bucket["mtm_usd"])
        bucket["pct_of_equity"] = (
            round(100.0 * bucket["mtm_usd"] / equity_total, 2)
            if equity_total > 0
            else None
        )

    return {
        "total_wealth_usd": total_wealth,
        "equity": {
            "total_usd": equity_total,
            "pct_of_wealth": pct(equity_total),
            "items": equity_items,
            "role_buckets": role_buckets,
        },
        "fixed_income": {
            "total_usd": fi_total,
            "pct_of_wealth": pct(fi_total),
            "items": fi_items,
        },
        "cash_equiv": {
            "total_usd": cash_equiv_total,
            "pct_of_wealth": pct(cash_equiv_total),
            "money_market_usd": mm_total,
            "raw_cash_usd": cash_total,
            "items": mm_items,
            "raw_cash": {
                "mep_usd": round(cash_mep, 2),
                "cable_usd": round(cash_cable, 2),
                "ars_native": round(_safe_float(liq.get("cash_ars_native")), 2),
                "ars_to_usd_rate": liq.get("cash_ars_to_usd_rate"),
                "ars_usd_equivalent": round(cash_ars_usd, 2),
            },
        },
        "top_concentrations": top,
    }
