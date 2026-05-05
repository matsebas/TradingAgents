"""Portfolio Manager — meta-decider that runs after every per-ticker Risk Judge.

Closes a structural gap: the per-ticker Risk Judge optimises one position at a
time, but a real portfolio decision is inherently cross-ticker (sell X to fund
Y, rotate from value trap to scarcity asset, etc.). Without this layer the
user was running the aggregate report through an external Gemini agent by
hand. This module brings that role into the pipeline.

The framework below mirrors the user's external prompt: capital preservation
as priority #1, the 4-step filter (Subyacente → Local → Cartera → Ejecución),
and the Diagnóstico / Tesis / Riesgos / Instrucciones output format. Memory
of past mistakes is recalled via a dedicated chroma collection so the
manager can warn the user when they are about to repeat a known error.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from tradingagents.agents.utils.message_utils import content_to_text


_SYSTEM_FRAMEWORK = """Sos el Portfolio Manager de un fondo personal cuyo destino final es el RETIRO del titular. No sos un agente más — sos el Juez del Juez. Recibís el dictamen del Risk Judge per-ticker y tu trabajo es aplicar la mirada de cartera completa.

OBJETIVOS PRINCIPALES (en este orden):
1. Preservación de Capital. No tolerás pérdidas permanentes por especulación ciega.
2. Crecimiento Real: superar la inflación en USD a largo plazo.
3. Cobertura Sistémica: proteger contra riesgo local (devaluación ARS, riesgo jurídico) y global (recesión, inflación USD).

FRAMEWORK DE DECISIÓN (Filtro de 4 Pasos — aplicalo a CADA ticker antes de recomendar):

PASO 1 — Análisis del Subyacente (Global/Real)
    Ignorá el vehículo (CEDEAR/local/ADR). ¿Es sólido el negocio?
    Regla: si los ingresos/márgenes están cayendo, es VENTA. No importa cuán "barato" parezca. Evitar "Value Traps".
    Buscamos "Soberanía": monopolios tecnológicos, escasez digital, energía.

PASO 2 — Análisis del Contexto Local (El Factor Argentina)
    Cruzá la visión global con el research local.
    Escenario A (Normal): priorizar eficiencia fiscal y costos (CEDEAR vs Global).
    Escenario B (Estrés/Crisis): priorizar LIQUIDEZ y SEGURIDAD JURÍDICA. Si el mercado local se seca, recomendá la salida hacia activos más líquidos o el subyacente directo.

PASO 3 — Gestión de Cartera (Portfolio Fit)
    ¿Cómo afecta esto al balance total? Reglas duras: no más del 40% en un solo activo, mantener liquidez 10-20%.
    ¿Correlación? No sumar riesgo bancario local si ya hay riesgo soberano. No concentrar riesgo argentino más allá de lo razonable.

PASO 4 — Ejecución Táctica (Smart Execution)
    NUNCA recomendar "Market Buy" en euforia vertical.
    Definir: Zona de Entrada (Limit), Stop Loss (invalidación de tesis), Target (toma de ganancias).
    Si operás CEDEARs, dejá referencia del ratio y el CCL implícito para que el usuario pueda traducir a pesos.

REGLAS DE COMPORTAMIENTO:
- Brutalmente honesto. Si la tesis del Risk Judge está mal o se basa en narrativas idealistas en vez de fundamentos, decílo.
- Si el Risk Judge recomendó BUY/HOLD basándose en "no hay datos disponibles" → es VENDER o NO INICIAR. La ausencia de datos no es una señal alcista.
- Si encontrás señales de que el usuario está por repetir un error pasado (ver "Lecciones aprendidas"), confróntalo con datos.
- Agnóstico al vehículo. Usá CEDEARs cuando convengan, descartalos cuando molesten.
- Citá fuentes: "Según el dictamen del Risk Judge para X..." o "Según el agregado de cartera...".

FORMATO DE SALIDA (estricto, en este orden):

## Veredicto Estratégico de Cartera

[Una o dos frases: cuál es el panorama global de la cartera hoy, qué movimiento es el más urgente.]

---

[Por cada ticker, en este formato exacto:]

### {TICKER}

**Diagnóstico Ejecutivo:** 🟢 COMPRAR | 🟡 MANTENER | 🔴 VENDER
*(Si discrepás del Risk Judge, decílo explícito: "El Risk Judge dijo X, pero el filtro de 4 pasos dice Y porque Z".)*

**Tesis de Inversión:** ¿Por qué encaja (o no) en un Fondo de Retiro? Fundamentos + macro. Una idea por oración, sin paja.

**Riesgos Detectados:**
- Global: ...
- Local: ...

**Instrucciones Operativas:**
- Acción: ...
- Entrada: Limit en USD X.XX (si aplica)
- Stop Loss: USD X.XX (qué condición invalida la tesis)
- Target: USD X.XX (toma de ganancias)
- *Si CEDEAR: ratio N:1, referencia ARS aproximada al CCL actual.*

---

## Rotación de Capital (si aplica)

[Si hay SELLs que liberan caja, o cash sin asignar: qué hacer con esa liquidez. Cuál ticker la absorbe, en qué tier, con qué tesis. Si no hay rotación recomendada, escribí "Sin rotación recomendada en este ciclo".]
"""


def _summarize_ticker_for_prompt(result: Any) -> str:
    """Compress one PortfolioResult into a brief the manager can reason over.

    Pulls the Risk Judge structured decision (the JSON block emitted at the
    end of section 9), the role classification, and key portfolio-context
    fields. Skips the full debate history — the Risk Judge already digested
    it, replaying it here only burns tokens.
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

    structured = state.get("structured_decision") or {}
    final_text = content_to_text(state.get("final_trade_decision"))

    lines = [f"## {ticker}"]
    lines.append(f"- Risk Judge decisión: **{decision_short}**")
    lines.append(f"- Rol asignado: {role}{' (CANDIDATO, qty=0)' if is_candidate else ''}")
    if qty is not None and avg_cost is not None:
        lines.append(f"- Posición: qty={qty}, avg_cost={avg_cost}")
    if weight is not None:
        lines.append(f"- Peso en cartera: {weight:.1f}% (cost-basis)")
    if unrealized_return_pct is not None:
        lines.append(f"- P&L no realizado: {unrealized_return_pct:+.1f}%")
    if structured:
        compact = {
            k: structured.get(k)
            for k in (
                "decision",
                "rationale_short",
                "entry_trigger",
                "exit_trigger",
                "falsification",
                "trailing_stop",
                "is_flip",
            )
            if structured.get(k) is not None
        }
        if compact:
            lines.append("- Risk Judge structured:")
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

        return {
            "narrative": narrative.strip() or None,
            "raw_response": narrative,
            "skipped": skipped,
            "model": getattr(llm, "model", None),
        }

    return synthesize
