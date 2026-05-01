"""Portfolio-level aggregates computed once per multi-ticker run.

These aggregates are injected into each ticker's ``portfolio_context`` so the
Risk Judge sees the *whole* book — not just the position under review. Closes
the structural gap where the system used to evaluate one ticker at a time and
recommend additions that pushed concentration past target.

Cost-basis weights are used (qty * pppc), since current market price is not
available at this layer. P&L is the position's reported unrealized return,
which is already mark-to-market on the broker side. Cost-basis weights
slightly understate winners and overstate laggards, but for action-sizing
decisions the bias is acceptable and the formula is auditable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class RoleBucket:
    """Aggregate stats for one position role."""

    count: int
    cost_basis_weight_pct: float  # 0-100, share of total cost basis in this bucket
    avg_unrealized_return_pct: float | None  # simple average of constituents
    tickers: tuple[str, ...]  # ordered by cost-basis weight desc


@dataclass(frozen=True)
class PortfolioAggregate:
    """Snapshot of portfolio composition at the start of a run."""

    total_positions: int
    by_role: Mapping[str, RoleBucket] = field(default_factory=dict)
    top_concentrations: tuple[tuple[str, float], ...] = ()  # [(ticker, weight_pct), ...]
    total_cost_basis_usd: float = 0.0  # sum of qty * avg_cost across measured positions

    def to_dict(self) -> dict:
        """Plain-dict form for state injection / JSON persistence."""
        return asdict(self)


def _position_cost_basis(ctx: Mapping[str, Any]) -> float | None:
    """Return ``qty * avg_cost`` if both are present, else None."""
    qty = ctx.get("quantity")
    avg_cost = ctx.get("avg_cost") or ctx.get("pppc")
    if qty is None or avg_cost is None:
        return None
    try:
        product = float(qty) * float(avg_cost)
    except (TypeError, ValueError):
        return None
    return product if product > 0 else None


def compute_portfolio_aggregate(
    holdings: Mapping[str, Mapping[str, Any]] | None,
) -> PortfolioAggregate | None:
    """Compute cost-basis-weighted aggregates across all positions.

    Returns ``None`` when no position has both ``quantity`` and ``avg_cost``
    (or ``pppc``) — without those we cannot weight by cost basis, and a
    partial aggregate is more misleading than no aggregate. Positions that
    lack one of those fields are silently excluded from weight calculations
    but still counted in ``total_positions``.
    """
    if not holdings:
        return None

    # Per-position cost basis (skips positions without qty + avg_cost).
    weighted: list[tuple[str, str, float, float | None]] = []
    # (ticker, role, cost_basis, unrealized_return_pct)
    for ticker, ctx in holdings.items():
        if not ctx:
            continue
        cost = _position_cost_basis(ctx)
        if cost is None:
            continue
        role = str(ctx.get("role") or "tactical")
        ret = ctx.get("unrealized_return_pct")
        try:
            ret_f = float(ret) if ret is not None else None
        except (TypeError, ValueError):
            ret_f = None
        weighted.append((ticker, role, cost, ret_f))

    if not weighted:
        return None

    total_cost = sum(c for _, _, c, _ in weighted)
    if total_cost <= 0:
        return None

    # Group by role
    by_role: dict[str, list[tuple[str, float, float | None]]] = {}
    for ticker, role, cost, ret_f in weighted:
        by_role.setdefault(role, []).append((ticker, cost, ret_f))

    role_buckets: dict[str, RoleBucket] = {}
    for role, items in by_role.items():
        bucket_cost = sum(c for _, c, _ in items)
        returns = [r for _, _, r in items if r is not None]
        avg_ret = sum(returns) / len(returns) if returns else None
        items_sorted = sorted(items, key=lambda x: x[1], reverse=True)
        role_buckets[role] = RoleBucket(
            count=len(items),
            cost_basis_weight_pct=round(bucket_cost / total_cost * 100, 2),
            avg_unrealized_return_pct=avg_ret,
            tickers=tuple(t for t, _, _ in items_sorted),
        )

    # Top 3 concentrations across the whole book
    all_sorted = sorted(weighted, key=lambda x: x[2], reverse=True)
    top = tuple(
        (t, round(c / total_cost * 100, 2)) for t, _, c, _ in all_sorted[:3]
    )

    return PortfolioAggregate(
        total_positions=len(holdings),
        by_role=role_buckets,
        top_concentrations=top,
        total_cost_basis_usd=round(total_cost, 2),
    )
