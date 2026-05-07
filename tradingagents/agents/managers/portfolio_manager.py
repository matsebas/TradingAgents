"""Portfolio Manager — meta-decider that runs after every per-ticker Risk Judge.

Closes a structural gap: the per-ticker Risk Judge optimises one position at a
time, but a real portfolio decision is inherently cross-ticker (sell X to fund
Y, rotate from value trap to scarcity asset, etc.). Without this layer the
user was running the aggregate report through an external Gemini agent by
hand. This module brings that role into the pipeline.

The framework lives in ``prompts/wealth_management_strategist.md`` (single
source of truth, also pasted into the user's external Gemini "gem"). Loaded
once at module import time so a missing/empty prompt fails fast at startup
rather than on the first portfolio run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from tradingagents.agents.utils.message_utils import content_to_text


_VALID_ACTIONS = {"BUY", "SELL", "TRIM", "HOLD", "BLOCK", "WATCHLIST", "NULL"}
_VALID_DECISIONS = {"BUY", "SELL", "HOLD"}
_VALID_PRIORITIES = {"P1", "P2", "P3"}
_VALID_REGIMES = {"normal", "stress"}
_FENCED_JSON_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_pm_json(narrative: str) -> dict[str, Any] | None:
    """Pull the fenced JSON block emitted at the end of the manager's response.

    The prompt requires a single ```json … ``` block. We grab the LAST match
    (the prose may show schema examples earlier) and parse it. Returns None
    if no valid block is found — callers fall back to per-ticker Risk Judge
    decisions when this happens.
    """
    if not narrative:
        return None
    matches = _FENCED_JSON_RE.findall(narrative)
    if not matches:
        return None
    raw = matches[-1].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _normalise_pm_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Coerce a parsed PM payload into a strict, typed dict.

    Drops unknown enum values, clamps numeric fields, and silently discards
    malformed action entries. Returns the cleaned payload — never raises so
    the report still writes.
    """
    regime = payload.get("regime")
    if regime not in _VALID_REGIMES:
        regime = "normal"

    triggers = payload.get("regime_triggers") or []
    if not isinstance(triggers, list):
        triggers = []
    triggers = [str(t) for t in triggers if t]

    rebalance_null = bool(payload.get("rebalance_null"))

    raw_actions = payload.get("actions") or []
    if not isinstance(raw_actions, list):
        raw_actions = []

    actions: list[dict[str, Any]] = []
    for entry in raw_actions:
        if not isinstance(entry, Mapping):
            continue
        ticker = entry.get("ticker")
        if not isinstance(ticker, str) or not ticker.strip():
            continue
        action = entry.get("action")
        if action not in _VALID_ACTIONS:
            continue
        effective = entry.get("effective_decision")
        if effective not in _VALID_DECISIONS:
            # Sensible default mapping when the LLM forgets the field.
            effective = {
                "BUY": "BUY",
                "SELL": "SELL",
                "TRIM": "SELL",
                "HOLD": "HOLD",
                "BLOCK": "HOLD",
                "WATCHLIST": "HOLD",
                "NULL": "HOLD",
            }[action]
        priority = entry.get("priority")
        if priority not in _VALID_PRIORITIES:
            priority = "P3"

        def _num(key: str) -> float | None:
            v = entry.get(key)
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        codes = entry.get("rationale_codes") or []
        if not isinstance(codes, list):
            codes = []
        codes = [str(c) for c in codes if c]

        actions.append(
            {
                "ticker": ticker.strip(),
                "priority": priority,
                "action": action,
                "effective_decision": effective,
                "size_usd": _num("size_usd"),
                "size_units": _num("size_units"),
                "trim_pct": _num("trim_pct"),
                "limit_price": _num("limit_price"),
                "stop_manual_close": _num("stop_manual_close"),
                "target": _num("target"),
                "rationale_codes": codes,
                "rationale": str(entry.get("rationale") or "").strip(),
                "override_rj": bool(entry.get("override_rj")),
            }
        )

    return {
        "regime": regime,
        "regime_triggers": triggers,
        "rebalance_null": rebalance_null,
        "actions": actions,
        "capital_destination": (payload.get("capital_destination") or None),
        "notes": (payload.get("notes") or None),
    }


_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "prompts"
    / "wealth_management_strategist.md"
)
try:
    _SYSTEM_FRAMEWORK = _PROMPT_PATH.read_text(encoding="utf-8").strip()
except FileNotFoundError as exc:  # pragma: no cover — startup guard
    raise RuntimeError(
        f"Wealth Management Strategist prompt missing at {_PROMPT_PATH}. "
        "This file is required and is the single source of truth for the "
        "Portfolio Manager system prompt."
    ) from exc
if not _SYSTEM_FRAMEWORK:
    raise RuntimeError(f"Prompt file {_PROMPT_PATH} is empty.")


def _summarize_ticker_for_prompt(result: Any) -> str:
    """Compress one PortfolioResult into a brief the manager can reason over.

    Pulls the Risk Judge structured decision (``trade_decision_structured``),
    the role classification, and key portfolio-context fields. Computes
    derived dollar values (cost basis, mark-to-market) so the manager can
    fill ``size_usd`` / ``size_units`` when proposing trims without having
    to multiply numbers itself. Skips the full debate history — the Risk
    Judge already digested it.
    """
    ticker = result.ticker
    decision_short = result.short_decision()
    state = result.state or {}

    portfolio_ctx = state.get("portfolio_context") or {}
    role = portfolio_ctx.get("role", "unspecified")
    is_candidate = bool(portfolio_ctx.get("is_candidate"))
    avg_cost = portfolio_ctx.get("avg_cost")
    qty = portfolio_ctx.get("qty")
    unrealized_return_pct = portfolio_ctx.get("unrealized_return_pct")
    weight = portfolio_ctx.get("cost_basis_weight_pct")

    # The state actually carries ``trade_decision_structured`` (set by the
    # Risk Judge after JSON validation). Earlier the brief tried to read
    # ``structured_decision`` and silently shipped an empty dict, leaving
    # the manager without entry plans, stop levels or falsification tests.
    structured = state.get("trade_decision_structured") or {}
    final_text = content_to_text(state.get("final_trade_decision"))

    lines = [f"## {ticker}"]
    lines.append(f"- Risk Judge decisión: **{decision_short}**")
    lines.append(
        f"- Rol asignado: {role}"
        f"{' (CANDIDATO, qty=0)' if is_candidate else ''}"
    )
    if qty is not None and avg_cost is not None:
        cost_basis_usd = qty * avg_cost
        lines.append(
            f"- Posición: qty={qty}, avg_cost=${avg_cost:.2f}, "
            f"cost basis ≈ ${cost_basis_usd:,.0f} USD"
        )
        if unrealized_return_pct is not None:
            mtm_usd = cost_basis_usd * (1 + unrealized_return_pct / 100)
            lines.append(
                f"- Valor mark-to-market actual ≈ ${mtm_usd:,.0f} USD"
            )
    if weight is not None:
        lines.append(f"- Peso en cartera: {weight:.1f}% (cost-basis)")
    if unrealized_return_pct is not None:
        lines.append(f"- P&L no realizado: {unrealized_return_pct:+.1f}%")
    if structured:
        # Pull the keys the Risk Judge actually emits in
        # ``trade_decision_structured``. These map directly onto the fields
        # the PM is asked to fill (limit_price, stop_manual_close, etc.) so
        # the LLM can reuse Risk Judge levels or override them explicitly.
        compact = {
            k: structured.get(k)
            for k in (
                "decision",
                "qty_change",
                "entry_plan",
                "stop_loss",
                "triggers",
                "falsification_criteria",
                "entry_quality",
                "rationale",
            )
            if structured.get(k) not in (None, "", [], {})
        }
        if compact:
            lines.append("- Risk Judge structured (entry/exit + tesis):")
            lines.append("```json")
            lines.append(json.dumps(compact, ensure_ascii=False, indent=2))
            lines.append("```")
    if final_text:
        snippet = final_text.strip()
        if len(snippet) > 1500:
            snippet = snippet[:1500] + "\n…[truncado para el manager]"
        lines.append("- Razonamiento textual del Risk Judge:")
        lines.append(snippet)
    return "\n".join(lines)


def _summarize_portfolio_aggregate(agg: Mapping[str, Any] | None) -> str:
    if not agg:
        return "_(sin agregado de cartera disponible — corrida sin posiciones)_"
    lines = ["## Agregado de cartera (cost-basis)"]
    role_buckets = agg.get("role_buckets") or {}
    for role, bucket in role_buckets.items():
        if not isinstance(bucket, Mapping):
            continue
        weight = bucket.get("cost_basis_weight_pct")
        ret = bucket.get("avg_unrealized_return_pct")
        tickers = bucket.get("tickers") or []
        weight_str = f"{weight:.1f}%" if weight is not None else "?"
        ret_str = f"{ret:+.1f}%" if ret is not None else "n/a"
        lines.append(
            f"- {role}: {weight_str} del libro, P&L medio {ret_str}, tickers: {', '.join(tickers) or '—'}"
        )
    if "max_single_weight_pct" in agg:
        lines.append(f"- Concentración máxima en un ticker: {agg['max_single_weight_pct']:.1f}%")
    return "\n".join(lines)


def _summarize_liquidity(liq: Mapping[str, Any] | None) -> str:
    if not liq:
        return "_(sin snapshot de liquidez)_"
    lines = ["## Liquidez disponible"]
    if liq.get("total_deployable_usd") is not None:
        lines.append(f"- Total desplegable: ${liq['total_deployable_usd']:,.0f} USD")
    if liq.get("cash_mep_usd"):
        lines.append(f"- Cash MEP: ${liq['cash_mep_usd']:,.0f} USD")
    if liq.get("cash_cable_usd"):
        lines.append(f"- Cash CABLE: ${liq['cash_cable_usd']:,.0f} USD")
    if liq.get("total_money_market_usd"):
        lines.append(f"- Money market: ${liq['total_money_market_usd']:,.0f} USD")
    if liq.get("total_fixed_income_usd"):
        lines.append(f"- Renta fija: ${liq['total_fixed_income_usd']:,.0f} USD")
    return "\n".join(lines)


def _build_situation_key(results: Iterable[Any], agg: Mapping[str, Any] | None) -> str:
    """Build a compact situation string for memory lookup.

    Memory matches by semantic similarity, so the key just needs to capture
    the high-level shape of the book today (decisions per ticker + role
    distribution).
    """
    parts: list[str] = []
    for r in results:
        if not r.ok:
            continue
        parts.append(f"{r.ticker}:{r.short_decision()}")
    if agg:
        for role, bucket in (agg.get("role_buckets") or {}).items():
            if isinstance(bucket, Mapping) and bucket.get("count"):
                parts.append(f"{role}={bucket.get('cost_basis_weight_pct', 0):.0f}%")
    return " | ".join(parts) or "empty book"


def create_portfolio_manager(llm, memory):
    """Factory for the cross-ticker Portfolio Manager synthesizer.

    The returned callable consumes a list of ``PortfolioResult`` (already
    populated by per-ticker Risk Judges) plus the run-level aggregate and
    liquidity snapshot, and returns a synthesis dict::

        {
            "narrative": str,   # markdown ready to drop into the report
            "raw_response": str,
            "model": str | None,
            "skipped": list[str],  # tickers excluded (errors)
        }

    Failures inside the synthesizer are caught and surface as ``narrative=None``
    plus an ``error`` key so the report writer can fall back gracefully.
    """

    def synthesize(
        results: Iterable[Any],
        portfolio_aggregate: Mapping[str, Any] | None = None,
        liquidity: Mapping[str, Any] | None = None,
        trade_date: str | None = None,
    ) -> dict[str, Any]:
        results = list(results)
        ok_results = [r for r in results if r.ok]
        skipped = [r.ticker for r in results if not r.ok]

        if not ok_results:
            return {
                "narrative": None,
                "raw_response": "",
                "skipped": skipped,
                "error": "no successful tickers to synthesize",
            }

        # Past mistakes — relevant lessons for THIS book composition.
        past_memory_str = ""
        try:
            situation = _build_situation_key(ok_results, portfolio_aggregate)
            past = memory.get_memories(situation, n_matches=3) if memory else []
            if past:
                past_memory_str = "\n\n".join(
                    f"- {rec.get('recommendation', '').strip()}" for rec in past
                )
        except Exception:  # noqa: BLE001 — memory is auxiliary
            past_memory_str = ""

        per_ticker_blocks = "\n\n".join(
            _summarize_ticker_for_prompt(r) for r in ok_results
        )
        agg_block = _summarize_portfolio_aggregate(portfolio_aggregate)
        liq_block = _summarize_liquidity(liquidity)

        skipped_block = (
            f"\n\n**Tickers omitidos (error en Risk Judge):** {', '.join(skipped)}"
            if skipped
            else ""
        )
        memory_block = (
            f"\n\n## Lecciones aprendidas (memoria activa)\n{past_memory_str}"
            if past_memory_str
            else ""
        )

        prompt = (
            _SYSTEM_FRAMEWORK
            + "\n\n---\n\n# Inputs del ciclo "
            + (trade_date or "")
            + "\n\n"
            + agg_block
            + "\n\n"
            + liq_block
            + memory_block
            + "\n\n## Dictámenes del Risk Judge per-ticker\n\n"
            + per_ticker_blocks
            + skipped_block
            + "\n\n---\n\nProducí ahora el Veredicto Estratégico de Cartera siguiendo el formato exacto."
        )

        try:
            response = llm.invoke(prompt)
            narrative = content_to_text(response.content)
        except Exception as exc:  # noqa: BLE001 — fail-soft, report still writes
            return {
                "narrative": None,
                "raw_response": "",
                "skipped": skipped,
                "error": f"{type(exc).__name__}: {exc}",
            }

        parsed = _extract_pm_json(narrative)
        structured = _normalise_pm_payload(parsed) if parsed is not None else None

        return {
            "narrative": narrative.strip() or None,
            "raw_response": narrative,
            "skipped": skipped,
            "model": getattr(llm, "model", None),
            "structured": structured,
        }

    return synthesize
