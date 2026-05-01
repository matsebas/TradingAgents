"""Portfolio-fit math for candidate tickers.

When evaluating a NEW position (not yet held), three things matter beyond
the standalone thesis:

* **Role gap** — does the candidate's target role bucket have room? E.g.
  if anchor target is 40% and current anchor weight is only 20%, an anchor
  candidate fills a real gap.
* **Sector overlap** — does the candidate duplicate exposure already in the
  book? If you hold SMH at 30% and the candidate is NVDA, that's full
  overlap (Tech / Semiconductors) — initiating it concentrates risk.
* **Initial sizing** — what's a reasonable starter size? Default 2% of book
  ("starter position" wisdom — leaves 4-7× room to scale up if thesis plays
  out). Capped by deployable USD liquidity in the prompt.

The function returns a ``CandidateFit`` dict that's injected into the
candidate's portfolio_context, surfaced in the Risk Judge prompt, and
echoed in the structured decision JSON.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping


# Default target weights per role. Sum to 100%. The Risk Judge uses these
# unless the caller overrides via ``role_targets`` arg.
DEFAULT_ROLE_TARGETS: dict[str, float] = {
    "anchor": 40.0,
    "tactical": 45.0,
    "speculative": 15.0,
}

# Default starter size for a new position (% of total book). Pre-set after
# discussion with the user — see plan in conversation history. The LLM can
# adjust to 1% (low conviction) or 3% (high conviction) but defaults to 2%.
DEFAULT_INITIAL_WEIGHT_PCT = 2.0

# A role bucket is considered "at target" when its current weight is within
# this many percentage points of the target. Anything above the target by
# this margin is "over target" and adds to that bucket are gated.
_AT_TARGET_TOLERANCE_PCT = 2.0


@dataclass(frozen=True)
class RoleGap:
    """Whether the candidate's role bucket has room for a new position."""

    role: str  # "anchor" | "tactical" | "speculative" | "candidate"
    has_gap: bool
    current_weight_pct: float
    target_weight_pct: float
    headroom_pct: float  # target - current (negative if over target)


@dataclass(frozen=True)
class SectorOverlap:
    """Sector / industry overlap with existing holdings."""

    level: str  # "none" | "partial" | "full"
    candidate_sector: str | None
    candidate_industry: str | None
    overlapping_tickers: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateFit:
    role_gap: RoleGap
    sector_overlap: SectorOverlap
    recommended_initial_weight_pct: float
    recommended_initial_size_usd: float | None  # None when total book unknown

    def to_dict(self) -> dict:
        return asdict(self)


def _classify_overlap(
    candidate_sector: str | None,
    candidate_industry: str | None,
    holdings_sectors: list[tuple[str, str | None, str | None]],
) -> SectorOverlap:
    """holdings_sectors is [(ticker, sector, industry), ...] for held positions."""
    if not candidate_sector:
        # We can't classify without the candidate's sector — be honest.
        return SectorOverlap(
            level="none",
            candidate_sector=None,
            candidate_industry=candidate_industry,
            overlapping_tickers=(),
        )

    same_sector = [
        t for t, s, _ in holdings_sectors if s and s == candidate_sector
    ]
    same_industry = [
        t
        for t, s, i in holdings_sectors
        if s
        and s == candidate_sector
        and candidate_industry
        and i == candidate_industry
    ]

    if same_industry:
        level = "full"
        overlapping = tuple(same_industry)
    elif same_sector:
        level = "partial"
        overlapping = tuple(same_sector)
    else:
        level = "none"
        overlapping = ()

    return SectorOverlap(
        level=level,
        candidate_sector=candidate_sector,
        candidate_industry=candidate_industry,
        overlapping_tickers=overlapping,
    )


def compute_portfolio_fit(
    candidate_ticker: str,
    candidate_role: str,
    portfolio_aggregate: Mapping[str, Any] | None,
    holdings: Mapping[str, Mapping[str, Any]] | None,
    sector_lookup_fn: Callable[[str], Any],
    *,
    role_targets: Mapping[str, float] | None = None,
    initial_weight_pct: float = DEFAULT_INITIAL_WEIGHT_PCT,
    total_deployable_usd: float | None = None,
) -> CandidateFit:
    """Compute fit attributes for a single candidate against the existing book.

    ``sector_lookup_fn`` is a callable that takes a ticker string and returns
    an object with ``.sector`` and ``.industry`` attributes (typically
    ``tradingagents.dataflows.sector_lookup.lookup_sector``). Injected for
    testability.

    ``total_deployable_usd`` is the FCI + cash liquidity (when available).
    When the equity cost basis is tiny (CEDEAR ratios deflate it relative to
    actual wealth), this is used as a fallback denominator so the suggested
    USD size reflects realistic deployable capital instead of equity-only
    cost basis. Pass ``None`` to disable the fallback.

    Returns a ``CandidateFit`` whose ``recommended_initial_size_usd`` is
    ``None`` when neither the aggregate nor liquidity carries a usable total.
    """
    targets = dict(role_targets or DEFAULT_ROLE_TARGETS)

    # --- Role gap ---
    target_for_role = targets.get(candidate_role, DEFAULT_ROLE_TARGETS.get(candidate_role, 0.0))
    current_weight_for_role = 0.0
    if portfolio_aggregate:
        by_role = portfolio_aggregate.get("by_role") or {}
        bucket = by_role.get(candidate_role)
        if bucket:
            current_weight_for_role = float(
                bucket.get("cost_basis_weight_pct", 0.0)
                if isinstance(bucket, Mapping)
                else getattr(bucket, "cost_basis_weight_pct", 0.0)
            )
    headroom = target_for_role - current_weight_for_role
    role_gap = RoleGap(
        role=candidate_role,
        has_gap=headroom > _AT_TARGET_TOLERANCE_PCT,
        current_weight_pct=round(current_weight_for_role, 2),
        target_weight_pct=round(target_for_role, 2),
        headroom_pct=round(headroom, 2),
    )

    # --- Sector overlap ---
    candidate_info = sector_lookup_fn(candidate_ticker)
    candidate_sector = getattr(candidate_info, "sector", None)
    candidate_industry = getattr(candidate_info, "industry", None)

    holdings_sectors: list[tuple[str, str | None, str | None]] = []
    if holdings:
        for ticker in holdings.keys():
            info = sector_lookup_fn(ticker)
            holdings_sectors.append(
                (
                    ticker,
                    getattr(info, "sector", None),
                    getattr(info, "industry", None),
                )
            )
    sector_overlap = _classify_overlap(
        candidate_sector, candidate_industry, holdings_sectors
    )

    # --- Sizing ---
    # Prefer "total wealth" (equity cost basis + deployable liquidity) when
    # the equity book alone is too small to be meaningful — this happens with
    # CEDEAR-denominated holdings whose PPPC is per-CEDEAR-unit (a fraction of
    # the underlying share). Fall back to equity-only when liquidity is unknown.
    equity_book = 0.0
    if portfolio_aggregate:
        equity_book = float(portfolio_aggregate.get("total_cost_basis_usd") or 0.0)
    deployable = float(total_deployable_usd or 0.0)
    sizing_base = equity_book + deployable
    recommended_size = (
        round(initial_weight_pct / 100.0 * sizing_base, 2)
        if sizing_base > 0
        else None
    )

    return CandidateFit(
        role_gap=role_gap,
        sector_overlap=sector_overlap,
        recommended_initial_weight_pct=initial_weight_pct,
        recommended_initial_size_usd=recommended_size,
    )


def is_buy_blocked_by_overlap_and_at_target(
    fit: CandidateFit,
    *,
    role_targets: Mapping[str, float] | None = None,
) -> bool:
    """Hard gate: BUY a candidate is INVALID when sector_overlap == 'full'
    AND the role bucket is already at/above target weight.

    Used by the validator to enforce the rule we agreed on with the user.
    """
    targets = dict(role_targets or DEFAULT_ROLE_TARGETS)
    role_target = targets.get(fit.role_gap.role, DEFAULT_ROLE_TARGETS.get(fit.role_gap.role, 0.0))
    bucket_at_target = (
        fit.role_gap.current_weight_pct >= role_target - _AT_TARGET_TOLERANCE_PCT
    )
    return fit.sector_overlap.level == "full" and bucket_at_target
