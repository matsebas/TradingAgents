import json
from typing import Any

from tradingagents.agents.managers.decision_validator import (
    auto_downgrade_to_hold,
    extract_decision_json,
    validate_decision,
)
from tradingagents.agents.utils.portfolio_context import format_portfolio_context


def _content_to_text(content: Any) -> str:
    """Flatten BaseMessage.content into a plain string.

    Gemini 3 family models (and other reasoning models) can return ``.content``
    as a list of content blocks like ``[{"type":"text","text":"..."}, ...]``
    or with ``thinking`` parts, instead of a flat string. Regex / string-concat
    over that raw structure raises ``TypeError: expected string or bytes-like
    object``. This helper joins the visible-text parts into a single string
    so downstream parsing works regardless of provider.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # Skip thinking / tool-call blocks; keep visible text.
                btype = block.get("type")
                if btype in ("thinking", "tool_use", "tool_result"):
                    continue
                if "text" in block and block["text"] is not None:
                    parts.append(str(block["text"]))
                elif "content" in block and block["content"] is not None:
                    parts.append(str(block["content"]))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


_STRUCTURED_OUTPUT_INSTRUCTIONS = '''
## SECTION 9: Structured Decision (JSON) — REQUIRED

After Section 8, append a fenced ```json block with the final decision in the
exact schema below. The downstream validator will REJECT decisions that
contradict the binding role guidance — write the JSON honestly, not as a
veneer over a prose argument the rules forbid.

```json
{
  "ticker": "<TICKER>",
  "decision": "BUY" | "SELL" | "HOLD",
  "qty_change": 0,
  "entry_plan": {
    "tier_now_pct": 0,
    "tier_pullback_target": "e.g. SMA 50d at $X",
    "basis": "one-line justification"
  },
  "stop_loss": {
    "type": "trailing" | "hard",
    "value": "10%" | "$X" | "below SMA 200d at $Y",
    "basis": "one-line justification"
  },
  "triggers": {
    "entry_trigger": "If <observable condition>, add <N> units",
    "exit_trigger": "If <observable condition>, trim <N> units",
    "profit_take_levels": []
  },
  "previous_decision": {
    "previous_date": "YYYY-MM-DD or null",
    "previous_decision": "BUY" | "SELL" | "HOLD" | null,
    "is_flip": false,
    "structural_reason": "required when is_flip=true; null otherwise"
  },
  "cited_role_guidance": "verbatim short quote from the role guidance line",
  "role": "anchor" | "tactical" | "speculative",
  "entry_quality": "optimal" | "stretched" | "chasing" | "n/a",
  "portfolio_weight_math": {
    "current_weight_pct": 0.0,
    "target_weight_pct": 0.0,
    "action_brings_to_pct": 0.0,
    "weight_gate_passes": false
  },
  "falsification_criteria": ["concrete observation 1", "concrete observation 2"],
  "rationale": "2-4 sentence summary of why this is the call",
  "candidate": null
}
```

If the position role is **candidate** (a NEW position being evaluated for
initiation), populate the optional `candidate` object instead of leaving it
null. Schema:

```json
"candidate": {
  "score": 7.5,
  "role_gap_aligned": true,
  "sector_overlap": "none" | "partial" | "full",
  "sector_overlap_with": ["NVDA", "SMH"],
  "thesis_strength": "high" | "medium" | "low",
  "recommended_size_pct": 2.0,
  "recommended_size_usd": 1000.0
}
```

For candidates, `decision` is interpreted as: **BUY = initiate**, **HOLD =
watchlist**, **SELL = reject the thesis**. Scoring guidance (sum to 0-10):
thesis_strength 0-3, entry_quality 0-3, role_gap fit 0-3, sector
diversification 0-1.

Rules the validator enforces (do not produce JSON that violates them):
* If `decision` is BUY, `entry_plan` is required (not null).
* If `previous_decision.is_flip` is true, `structural_reason` must cite a
  regime / fundamental / role-reclassification reason — NOT RSI/MACD/Bollinger
  alone.
* For tactical positions with P&L >= +20%, BUY requires
  `portfolio_weight_math.weight_gate_passes == true` AND
  `entry_quality == "optimal"`.
* Anchor SELL requires a structural reason in `rationale`, not technical
  oscillators alone.
* For role="candidate" with decision=BUY: entry_quality MUST NOT be
  "chasing"; thesis_strength MUST be "medium" or "high"; rationale MUST
  cite a fundamental thesis (not technical-only); `sector_overlap=="full"
  AND role_gap_aligned==false` is a HARD reject — must HOLD instead.
'''


def create_risk_manager(llm, memory):
    def risk_manager_node(state) -> dict:

        company_name = state["company_of_interest"]

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        market_research_report = state["market_report"]
        news_report = state["news_report"]
        fundamentals_report = state["news_report"]
        sentiment_report = state["sentiment_report"]
        trader_plan = state["investment_plan"]
        portfolio_ctx = state.get("portfolio_context")
        portfolio_block = format_portfolio_context(portfolio_ctx, company_name)

        curr_situation = f"{market_research_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
        past_memories = memory.get_memories(curr_situation, n_matches=2)

        past_memory_str = ""
        for i, rec in enumerate(past_memories, 1):
            past_memory_str += rec["recommendation"] + "\n\n"

        portfolio_section = (
            f"\n\n---\n\n**Portfolio Context (binding rules):**\n{portfolio_block}\n\n"
            "The role-based guidance and previous-decision directive above "
            "are BINDING. Anchors require structural thesis changes; tactical "
            "names with P&L > +20% default to HOLD-with-trailing-stop unless "
            "both weight and entry-quality gates pass; speculative names "
            "tolerate drawdowns and only exit on thesis break. Never trim a "
            "structural anchor for short-term yield capture."
            if portfolio_block
            else ""
        )

        prompt = f"""You are the Risk Management Judge. Decide BUY / SELL / HOLD for the position under review. The role-based rules in the Portfolio Context (when present) are BINDING — they are not aspirational and you may not rationalize around them.

**Required output structure (in this exact order, with the headings shown).** Use `## SECTION N:` headings as below — analyst reports may use their own `###` markers, so we deliberately use a different style here to avoid collision.

## SECTION 1: Summary of Key Arguments
The strongest single point from each of the three risk analysts (Risky, Safe/Conservative, Neutral).

## SECTION 2: Previous-Decision Consistency Check
If the Portfolio Context shows a "Previous Decision", state whether you are continuing or flipping it. A FLIP is INVALID unless you cite a STRUCTURAL change (regime shift, fundamental thesis break, role reclassification). Technical oscillator changes (RSI / MACD / Bollinger) ALONE do NOT justify a flip — if those are your only basis, your decision MUST match the previous one.

## SECTION 3: Role-Discipline Check
Quote the role guidance from the Portfolio Context verbatim (one short phrase). State the role's default action (HOLD for anchors not in thesis change, HOLD-with-trailing-stop for tactical winners >+20%, etc). Then state whether your recommendation MATCHES that default. If it does not, you MUST cite the specific gate / condition in the guidance that justifies deviating (e.g. "tactical add allowed because weight gate passes AND entry quality is optimal"). If those conditions don't apply or you can't verify them, your final decision MUST be the role's default action.

## SECTION 4: Final Recommendation
A single line: **BUY**, **SELL**, or **HOLD**.

## SECTION 5: Entry Trigger
Under what observable condition would you BUY (or add) to this position? Be concrete — price level, indicator threshold, fundamental event. "If A happens, add B units." Even if your current decision is SELL or HOLD, define the entry trigger so the position has a forward roadmap.

## SECTION 6: Exit Trigger
Under what observable condition would you SELL (or trim)? Be concrete — trailing-stop level, technical break, fundamental event. Even if your current decision is BUY or HOLD, define the exit trigger.

## SECTION 7: Falsification Criteria
Two or three concrete observations that would invalidate your current thesis and force re-evaluation. These are NOT the same as the exit trigger — they are the upstream signals that would cause you to reconsider the entire stance.

## SECTION 8: Refined Trader's Plan
Adjust the trader's original plan ({trader_plan}) accordingly. Include trailing-stop level, profit-take levels (if any), and tier sizing (if BUY).
{_STRUCTURED_OUTPUT_INSTRUCTIONS}
---

**Past lessons to consider:**
{past_memory_str}

---

<analyst_history>
{history}
</analyst_history>{portfolio_section}

---

Be decisive but disciplined. HOLD is a valid answer when the role guidance demands it — do not force a BUY/SELL when discipline says HOLD. Your reasoning must engage with the binding rules, not work around them."""

        response = llm.invoke(prompt)
        response_text = _content_to_text(response.content)

        # --- Validate the structured JSON block at the end of the response. ---
        parsed = extract_decision_json(response_text)
        outcome = None
        validated_decision = None
        if parsed is not None:
            outcome = validate_decision(parsed, portfolio_context=portfolio_ctx)
            if outcome.ok:
                validated_decision = outcome.decision

        # If parsing or validation failed, retry ONCE with the issues fed back.
        if validated_decision is None:
            issue_summary = (
                "; ".join(outcome.issues)
                if outcome is not None
                else "no fenced JSON block found"
            )
            retry_prompt = (
                prompt
                + "\n\n---\n\nYour previous response was REJECTED by the "
                "validator. Issues: "
                + issue_summary
                + "\nFix the JSON to comply with the binding role rules and "
                "the schema. Re-emit the FULL response (sections 1-9)."
            )
            retry_response = llm.invoke(retry_prompt)
            response_text = _content_to_text(retry_response.content)
            parsed = extract_decision_json(response_text)
            if parsed is not None:
                outcome = validate_decision(parsed, portfolio_context=portfolio_ctx)
                if outcome.ok:
                    validated_decision = outcome.decision

        # If still failing, auto-downgrade to HOLD with explicit reasoning.
        if validated_decision is None:
            validated_decision = auto_downgrade_to_hold(
                outcome.decision if outcome is not None else None,
                outcome.issues if outcome is not None else ["no JSON block emitted"],
                ticker=company_name,
                portfolio_context=portfolio_ctx,
            )
            response_text = (
                response_text
                + "\n\n---\n\n**⚠ AUTO-DOWNGRADED to HOLD** — the LLM-emitted "
                "decision did not satisfy the binding role rules after one "
                "retry. The structured decision below reflects the downgrade.\n\n"
                + "```json\n"
                + json.dumps(validated_decision.model_dump(), indent=2)
                + "\n```"
            )

        new_risk_debate_state = {
            "judge_decision": response_text,
            "history": risk_debate_state["history"],
            "risky_history": risk_debate_state["risky_history"],
            "safe_history": risk_debate_state["safe_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_risky_response": risk_debate_state["current_risky_response"],
            "current_safe_response": risk_debate_state["current_safe_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": response_text,
            "trade_decision_structured": validated_decision.model_dump(),
        }

    return risk_manager_node
