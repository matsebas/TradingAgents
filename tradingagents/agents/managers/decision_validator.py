"""Post-LLM validator for the Risk Judge's structured decision.

Extracts the fenced JSON block from a free-text LLM response, parses it
against ``TradeDecision``, and runs role-discipline checks. When the
LLM contradicts its own cited role guidance (or flips a decision on
technical reasons alone), the validator returns the issues so the
caller can either retry or auto-downgrade to HOLD.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import ValidationError

from tradingagents.agents.utils.decision_schema import (
    StopLoss,
    TradeDecision,
    Triggers,
    PrevDecisionConsistency,
)


_JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)

# Phrases that, if present alone in `structural_reason` for a flip, mean the
# Judge tried to flip on technical/oscillator grounds — which the binding
# rules forbid.
_TECHNICAL_ONLY_TOKENS = (
    "rsi",
    "macd",
    "bollinger",
    "boll",
    "stochastic",
    "sma",
    "ema",
    "vwma",
    "atr",
    "overbought",
    "oversold",
    "bullish crossover",
    "bearish crossover",
)


@dataclass(frozen=True)
class ValidationOutcome:
    decision: TradeDecision | None
    issues: list[str]

    @property
    def ok(self) -> bool:
        return self.decision is not None and not self.issues


def extract_decision_json(response_text: str) -> dict | None:
    """Return the parsed dict from the LAST ``json fenced block in the text.

    Returns ``None`` if no fence is found or the JSON doesn't parse.
    """
    if not response_text:
        return None
    matches = _JSON_FENCE_RE.findall(response_text)
    if not matches:
        return None
    try:
        parsed = json.loads(matches[-1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


_MIN_STRUCTURAL_REASON_WORDS = 8


def _is_technical_only(reason: str | None) -> bool:
    """Return True when ``reason`` is empty, technical-oscillator-only, or
    too vague to be a structural justification.

    The third case (vague non-empty) is critical: an LLM can emit a short
    plausible-sounding flip reason like "volatility" or "momentum looks bad"
    that contains no technical token AND no structural keyword. Without a
    minimum-content gate, the heuristic would silently pass it as compliant.
    """
    if not reason:
        return True  # absent reason is treated as failure for flips
    text = reason.lower()
    has_technical = any(tok in text for tok in _TECHNICAL_ONLY_TOKENS)
    # Heuristic: if a structural keyword is also present, treat as compliant.
    has_structural = any(
        kw in text
        for kw in (
            "regime",
            "thesis",
            "earnings",
            "guidance cut",
            "operating income",
            "operating-income",
            "dividend",
            "regulation",
            "regulatory",
            "geopolitic",
            "supply chain",
            "supply/demand",
            "bankruptcy",
            "downgrade",
            "rating",
            "balance sheet",
            "cash flow",
            "fundamental",
            "monetary policy",
            "rate path",
            "role reclass",
            "role re-class",
            "re-classified",
            "reclassified",
            "size discipline",
        )
    )
    if has_structural:
        return False
    if has_technical:
        return True
    # No technical tokens AND no structural keywords → must clear a length gate
    # to count as a real reason. Short vague answers fail.
    word_count = len(text.split())
    return word_count < _MIN_STRUCTURAL_REASON_WORDS


def validate_decision(
    parsed: Mapping[str, Any],
    *,
    portfolio_context: Mapping[str, Any] | None = None,
) -> ValidationOutcome:
    """Validate a parsed decision dict against role-discipline rules.

    Returns a ``ValidationOutcome`` with ``decision`` set when parsing
    succeeded (even if some role checks failed) and ``issues`` listing
    every binding-rule violation. The caller decides whether to retry,
    accept with warnings, or auto-downgrade.
    """
    issues: list[str] = []

    try:
        decision = TradeDecision.model_validate(parsed)
    except ValidationError as e:
        return ValidationOutcome(
            decision=None,
            issues=[f"Schema validation failed: {e.errors()}"],
        )

    role = decision.role or (
        portfolio_context.get("role") if portfolio_context else None
    )
    pnl = (
        portfolio_context.get("unrealized_return_pct")
        if portfolio_context
        else None
    )
    try:
        pnl_f = float(pnl) if pnl is not None else None
    except (TypeError, ValueError):
        pnl_f = None

    # --- Cross-run continuity ---
    # Derive is_flip from the actual decision values rather than trusting the
    # LLM's self-report. The model can (and has) emitted ``is_flip: false``
    # while changing decisions — that bypasses the structural-reason gate.
    prev = decision.previous_decision
    actual_is_flip = (
        prev.previous_decision is not None
        and prev.previous_decision != decision.decision
    )
    if actual_is_flip:
        if _is_technical_only(prev.structural_reason):
            issues.append(
                "Flip vs previous_decision "
                f"({prev.previous_decision} → {decision.decision}) is justified "
                "only by technical oscillators or no real reason — binding "
                "rules require a STRUCTURAL reason "
                "(regime / fundamental / role reclass)."
            )
        if not prev.is_flip:
            issues.append(
                "Decision differs from previous_decision but is_flip=false — "
                "the structured output must declare is_flip=true so the "
                "structural-reason gate applies."
            )

    # --- BUY requires entry_plan ---
    if decision.decision == "BUY" and decision.entry_plan is None:
        issues.append("BUY decision is missing `entry_plan`.")

    # --- Tactical winner gates ---
    if role == "tactical" and pnl_f is not None and pnl_f >= 0.20:
        if decision.decision == "BUY":
            wm = decision.portfolio_weight_math
            if wm is None or not wm.weight_gate_passes:
                issues.append(
                    "Tactical winner (P&L >= +20%) BUY without weight gate "
                    "passing — role guidance requires current_weight < target."
                )
            if decision.entry_quality != "optimal":
                issues.append(
                    "Tactical winner (P&L >= +20%) BUY with entry_quality "
                    f"{decision.entry_quality!r} — role guidance requires 'optimal'."
                )

    # --- Candidate (new position) gates ---
    if role == "candidate" and decision.decision == "BUY":
        if decision.entry_quality == "chasing":
            issues.append(
                "Candidate BUY with entry_quality='chasing' — initiating a "
                "new position on a chasing entry is forbidden by the role "
                "rules; require optimal or stretched entry."
            )
        if decision.candidate is None:
            issues.append(
                "Candidate BUY missing required `candidate` attributes "
                "(score / role_gap_aligned / sector_overlap / thesis_strength)."
            )
        else:
            cand = decision.candidate

            # Re-derive sector_overlap and role_gap_aligned from the precomputed
            # CandidateFit instead of trusting the LLM's self-report. Same
            # pattern as the is_flip fix — the LLM can (and has) emitted
            # boolean fields that don't match the underlying data, and the
            # hard gate must be unforgeable.
            ctx_fit = (
                portfolio_context.get("candidate_fit") if portfolio_context else None
            )
            actual_overlap = cand.sector_overlap
            actual_role_gap_aligned = cand.role_gap_aligned
            if isinstance(ctx_fit, Mapping):
                ctx_overlap = (ctx_fit.get("sector_overlap") or {}).get("level")
                ctx_role_gap = (ctx_fit.get("role_gap") or {}).get("has_gap")
                if ctx_overlap is not None:
                    actual_overlap = ctx_overlap
                    if ctx_overlap != cand.sector_overlap:
                        issues.append(
                            f"Candidate self-reported sector_overlap="
                            f"{cand.sector_overlap!r} but precomputed value is "
                            f"{ctx_overlap!r}. Use the precomputed value."
                        )
                if ctx_role_gap is not None:
                    actual_role_gap_aligned = bool(ctx_role_gap)
                    if bool(ctx_role_gap) != cand.role_gap_aligned:
                        issues.append(
                            f"Candidate self-reported role_gap_aligned="
                            f"{cand.role_gap_aligned} but precomputed value is "
                            f"{bool(ctx_role_gap)}. Use the precomputed value."
                        )

            # Hard gate uses the trusted (precomputed if available) values.
            if actual_overlap == "full" and not actual_role_gap_aligned:
                issues.append(
                    "Candidate BUY blocked: sector_overlap='full' AND "
                    "role_gap_aligned=false (the target role bucket is at/over "
                    "target). The only valid call here is HOLD (watchlist)."
                )
            if cand.thesis_strength == "low":
                issues.append(
                    "Candidate BUY with thesis_strength='low' — initiating a "
                    "new position requires medium or high thesis conviction."
                )
            # Rationale must not be technical-only — initiating a position on
            # RSI/MACD/Bollinger alone is exactly the asymmetric-risk pattern
            # we're closing.
            if _is_technical_only(decision.rationale):
                issues.append(
                    "Candidate BUY rationale is technical-oscillator-only — "
                    "initiating a new position requires a fundamental thesis."
                )

    # --- Anchor SELL requires structural reason ---
    if role == "anchor" and decision.decision == "SELL":
        # The anchor exit case treats the recommendation itself as a flip-style
        # event: structural_reason on prev_decision should still apply, but
        # also the rationale must mention a structural cause.
        rationale = (decision.rationale or "").lower()
        cited = (decision.cited_role_guidance or "").lower()
        joined = rationale + " " + cited
        if _is_technical_only(joined):
            issues.append(
                "Anchor SELL is justified only by technical oscillators — "
                "anchors require a documented structural thesis change."
            )

    return ValidationOutcome(decision=decision, issues=issues)


def auto_downgrade_to_hold(
    decision: TradeDecision | None,
    issues: list[str],
    *,
    ticker: str,
    portfolio_context: Mapping[str, Any] | None = None,
) -> TradeDecision:
    """Build a synthetic HOLD decision when the LLM output cannot be salvaged.

    The downgraded decision keeps any usable fields from the original (when
    present) but flips ``decision`` to HOLD and overwrites the rationale
    with the validation issues so the user sees exactly why.
    """
    role = None
    if decision is not None:
        role = decision.role
    if role is None and portfolio_context is not None:
        role = portfolio_context.get("role")  # type: ignore[assignment]

    base_stop = (
        decision.stop_loss
        if decision is not None
        else StopLoss(
            type="trailing",
            value="10%",
            basis="auto-downgrade default",
        )
    )
    base_triggers = (
        decision.triggers
        if decision is not None
        else Triggers(
            entry_trigger="re-evaluate on next run with corrected output",
            exit_trigger="trailing stop",
        )
    )
    base_prev = (
        decision.previous_decision
        if decision is not None
        else PrevDecisionConsistency(is_flip=False)
    )
    falsification = (
        decision.falsification_criteria
        if decision is not None
        else ["LLM produced an invalid structured decision; manual review needed"]
    )

    issue_text = "; ".join(issues) if issues else "structured output invalid"
    return TradeDecision(
        ticker=ticker.strip().upper(),
        decision="HOLD",
        qty_change=0,
        entry_plan=None,
        stop_loss=base_stop,
        triggers=base_triggers,
        previous_decision=base_prev,
        cited_role_guidance=(
            decision.cited_role_guidance
            if decision is not None
            else "auto-downgrade default — role guidance not cited"
        ),
        role=role if role in ("anchor", "tactical", "speculative", "candidate") else None,
        entry_quality=decision.entry_quality if decision is not None else "n/a",
        portfolio_weight_math=(
            decision.portfolio_weight_math if decision is not None else None
        ),
        falsification_criteria=falsification,
        rationale=(
            "AUTO-DOWNGRADED to HOLD due to validation failure. "
            f"Issues: {issue_text}"
        ),
    )
