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
    prev = decision.previous_decision
    if prev.is_flip and prev.previous_decision is not None:
        if _is_technical_only(prev.structural_reason):
            issues.append(
                "Flip vs previous_decision is justified only by technical "
                "oscillators — binding rules require a STRUCTURAL reason "
                "(regime / fundamental / role reclass)."
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
        role=role if role in ("anchor", "tactical", "speculative") else None,
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
