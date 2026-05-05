"""Portfolio-level result types and reporting helpers."""

from __future__ import annotations

import csv
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table


# Map LangGraph node names to user-facing labels shown in the progress table.
_NODE_DISPLAY = {
    "Market Analyst": "📊 Market",
    "Social Analyst": "💬 Social",
    "News Analyst": "📰 News",
    "Fundamentals Analyst": "📈 Fundamentals",
    "Bull Researcher": "🐂 Bull",
    "Bear Researcher": "🐻 Bear",
    "Research Manager": "🧠 Research Mgr",
    "Trader": "💼 Trader",
    "Risky Analyst": "🔥 Risky",
    "Safe Analyst": "🛡 Safe",
    "Neutral Analyst": "⚖ Neutral",
    "Risk Judge": "⚖ Risk Judge",
}


def _is_utility_node(node_name: str) -> bool:
    """Tool invocations and message-clear nodes are noise for users."""
    lower = node_name.lower()
    return lower.startswith("tools_") or lower.startswith("msg clear")


def _coerce_to_text(value: Any) -> str:
    """Flatten Gemini / LangChain message content into a plain string.

    Gemini sometimes returns content as ``[{"type": "text", "text": "BUY", ...}]``
    instead of a plain string. We keep the rest of the code base dealing with
    plain text by normalising at the boundary.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
                    continue
                nested = item.get("content")
                if nested is not None:
                    parts.append(_coerce_to_text(nested))
            elif isinstance(item, str):
                parts.append(item)
            else:
                parts.append(str(item))
        return "\n\n".join(p for p in parts if p)
    if isinstance(value, dict):
        text = value.get("text")
        if text:
            return str(text)
        return _coerce_to_text(value.get("content"))
    return str(value)


@dataclass
class TickerProgressState:
    ticker: str
    phase: str = "queued"
    status: str = "pending"  # pending | running | completed | error
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    final_label: Optional[str] = None  # short decision or error summary


class PortfolioProgress:
    """Live-updating dashboard with one row per ticker.

    Designed to be used as a context manager wrapping the parallel run:

        with PortfolioProgress(tickers, console) as progress:
            results = await ta.propagate_portfolio(tickers, date, progress=progress)
    """

    def __init__(self, tickers: Iterable[str], console: Console | None = None):
        self.console = console or Console()
        self.states: dict[str, TickerProgressState] = {
            t: TickerProgressState(ticker=t) for t in tickers
        }
        self._live: Live | None = None

    # --- progress updates -------------------------------------------------

    def start(self, ticker: str) -> None:
        st = self.states[ticker]
        st.status = "running"
        st.started_at = time.time()
        st.phase = "starting"
        self._refresh()

    def on_node(self, ticker: str, node_name: str) -> None:
        if _is_utility_node(node_name):
            return
        st = self.states[ticker]
        st.phase = _NODE_DISPLAY.get(node_name, node_name)
        self._refresh()

    def finish(
        self,
        ticker: str,
        decision: str | None = None,
        error: str | None = None,
    ) -> None:
        st = self.states[ticker]
        st.ended_at = time.time()
        if error:
            st.status = "error"
            st.final_label = error[:60]
            st.phase = "[red]failed[/red]"
        else:
            st.status = "completed"
            st.final_label = _extract_short_decision(decision) or "done"
            st.phase = "[green]done[/green]"
        self._refresh()

    # --- context manager --------------------------------------------------

    def __enter__(self) -> "PortfolioProgress":
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=4,
            transient=False,
            # Do NOT let Live hijack stdout/stderr — the CLI wraps this block
            # with contextlib.redirect_stdout to send vendor prints to a log
            # file, and Live's own redirect would override that.
            redirect_stdout=False,
            redirect_stderr=False,
        )
        self._live.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        if self._live is not None:
            # Final snapshot so the table stays on-screen after the loop ends.
            self._live.update(self._render(), refresh=True)
            self._live.__exit__(*exc)
            self._live = None

    # --- rendering --------------------------------------------------------

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._render())

    def _render(self) -> Table:
        table = Table(
            title="Portfolio progress",
            show_header=True,
            header_style="bold magenta",
            expand=True,
        )
        table.add_column("Ticker", style="cyan", no_wrap=True)
        table.add_column("Status", justify="center", width=12)
        table.add_column("Phase", style="white")
        table.add_column("Elapsed", justify="right", width=10)
        table.add_column("Result", overflow="fold")

        now = time.time()
        for st in self.states.values():
            status_cell: Any
            if st.status == "pending":
                status_cell = "[dim]pending[/dim]"
            elif st.status == "running":
                status_cell = Spinner("dots", text="[cyan]running[/cyan]")
            elif st.status == "completed":
                status_cell = "[green]✓ done[/green]"
            else:
                status_cell = "[red]✗ error[/red]"

            if st.started_at is None:
                elapsed_cell = ""
            else:
                end = st.ended_at or now
                elapsed_cell = f"{end - st.started_at:.1f}s"

            if st.final_label is None:
                result_cell = ""
            elif st.status == "error":
                result_cell = f"[red]{st.final_label}[/red]"
            else:
                color = {
                    "BUY": "bold green",
                    "SELL": "bold red",
                    "HOLD": "bold yellow",
                }.get(st.final_label, "white")
                result_cell = f"[{color}]{st.final_label}[/{color}]"

            table.add_row(st.ticker, status_cell, st.phase, elapsed_cell, result_cell)

        return table


# Ordered list of (state_key, section_heading) pairs for plain-text reports.
# These mirror the fields dumped to `full_states_log_{date}.json`.
_DETAIL_REPORT_SECTIONS: tuple[tuple[str, str], ...] = (
    ("market_report", "📊 Market Analyst Report"),
    ("sentiment_report", "💬 Social Sentiment Report"),
    ("news_report", "📰 News Analyst Report"),
    ("fundamentals_report", "📈 Fundamentals Analyst Report"),
)

# Ordered list of (sub_key, section_heading) for the bull/bear debate.
_DETAIL_INVEST_DEBATE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("bull_history", "🐂 Bull Researcher"),
    ("bear_history", "🐻 Bear Researcher"),
    ("history", "Debate Transcript"),
    ("current_response", "Latest Response"),
    ("judge_decision", "🧠 Research Manager Decision"),
)

# Ordered list of (sub_key, section_heading) for the risk debate.
_DETAIL_RISK_DEBATE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("risky_history", "🔥 Risky Analyst"),
    ("safe_history", "🛡 Safe Analyst"),
    ("neutral_history", "⚖ Neutral Analyst"),
    ("history", "Risk Debate Transcript"),
    ("judge_decision", "⚖ Risk Judge Decision"),
)


def _append_section(lines: list[str], heading: str, body: Any, level: int = 4) -> None:
    """Append a markdown sub-section with the given heading and body.

    No-op when the body is empty after flattening Gemini-shape content.
    """
    text = _coerce_to_text(body).strip()
    if not text:
        return
    lines.append("")
    lines.append(f"{'#' * level} {heading}")
    lines.append("")
    lines.append(text)


def _broker_features_for_result(r: "PortfolioResult") -> set[str]:
    """Extract the broker feature set from a result's portfolio_context.
    Returns ``set()`` when not set (caller treats that as no restriction)."""
    if r.state is None:
        return set()
    ctx = r.state.get("portfolio_context") or {}
    raw = ctx.get("broker_features") or []
    return {str(f).lower().strip() for f in raw}


def _is_broker_restricted(features: set[str]) -> bool:
    """True when broker can't auto-execute stops/brackets — exits must be manual."""
    if not features:
        return False
    has_stop = "stop_loss" in features or "stop-loss" in features
    has_bracket = "bracket" in features
    return not (has_stop and has_bracket)


def _render_broker_orders(results: list["PortfolioResult"]) -> list[str]:
    """Render the consolidated GTD-actionable orders section.

    Only emits when at least one result indicates a restricted broker
    (e.g. ``broker_features=["gtd"]``). Reads ``trade_decision_structured``
    from each result's state and extracts the entry plan + stop level
    expressed as plain GTD instructions the user can take to his broker.
    """
    if not results:
        return []

    # Detect restriction from the first result that has the field. All
    # tickers in a run share the same config so any one is representative.
    restricted = False
    for r in results:
        feats = _broker_features_for_result(r)
        if feats and _is_broker_restricted(feats):
            restricted = True
            break
    if not restricted:
        return []

    lines = ["## Broker-Actionable Orders (GTD-only)"]
    lines.append("")
    lines.append(
        "_Listo para llevar al broker. Entries son limit GTD; exits son "
        "niveles a monitorear manualmente — si el precio toca el nivel, "
        "vas al broker y ponés una GTD sell._"
    )
    lines.append("")
    lines.append(
        "| Ticker | Action | Limit price | Plazo / qty | Manual exit triggers |"
    )
    lines.append(
        "|--------|--------|-------------|-------------|----------------------|"
    )

    any_row = False
    for r in results:
        state = r.state or {}
        structured = state.get("trade_decision_structured") or {}
        if not structured:
            continue

        decision = (structured.get("decision") or "").upper()
        ctx = state.get("portfolio_context") or {}
        is_cand = bool(ctx.get("is_candidate"))

        action = _broker_action_label(decision, is_cand)
        if action == "—":
            # Pure HOLD on existing positions with no actionable order — skip
            # to keep the table dense. The position still has a manual-monitor
            # exit, surfaced in the next column.
            entry_str = "—"
            qty_str = "—"
        else:
            entry_str, qty_str = _broker_entry_text(structured)

        exit_str = _broker_exit_text(structured)

        # Skip entirely empty rows (no action AND no monitor trigger).
        if action == "—" and exit_str == "—":
            continue

        lines.append(
            f"| {r.ticker} | {action} | {entry_str} | {qty_str} | {exit_str} |"
        )
        any_row = True

    if not any_row:
        return []
    return lines


def _broker_action_label(decision: str, is_candidate: bool) -> str:
    """Map (decision, is_candidate) to the broker-action verb."""
    decision = (decision or "").upper()
    if is_candidate:
        if decision == "BUY":
            return "**ADD** (initiate)"
        if decision == "HOLD":
            return "WATCHLIST"
        if decision == "SELL":
            return "REJECT"
    else:
        if decision == "BUY":
            return "**ADD** (scale up)"
        if decision == "SELL":
            return "**TRIM / EXIT**"
        # HOLD on existing position → no broker action, only monitoring.
        return "—"
    return "—"


def _broker_entry_text(structured: dict) -> tuple[str, str]:
    """Extract limit price + plazo/qty from the structured decision."""
    plan = structured.get("entry_plan") or {}
    triggers = structured.get("triggers") or {}
    qty = structured.get("qty_change", 0)

    target = plan.get("tier_pullback_target") or plan.get("basis") or "—"
    tier_now = plan.get("tier_now_pct")

    # Try to surface a concrete price from the entry trigger string.
    entry_str = str(target).strip() or "—"
    qty_parts: list[str] = []
    if isinstance(qty, int) and qty != 0:
        qty_parts.append(f"qty {qty:+d}")
    if tier_now is not None:
        qty_parts.append(f"{tier_now}% now")
    qty_str = " / ".join(qty_parts) if qty_parts else "—"

    # If there's no concrete price in entry_plan, fall back to the entry
    # trigger phrasing so the user has SOMETHING to act on.
    if entry_str in ("—", ""):
        entry_str = (triggers.get("entry_trigger") or "—").strip() or "—"

    return entry_str, qty_str


def _broker_exit_text(structured: dict) -> str:
    """Express the exit/stop as a manual monitoring instruction."""
    stop = structured.get("stop_loss") or {}
    triggers = structured.get("triggers") or {}

    stop_value = (stop.get("value") or "").strip()
    stop_type = (stop.get("type") or "").lower()
    exit_trigger = (triggers.get("exit_trigger") or "").strip()

    parts: list[str] = []
    if stop_value:
        if stop_type == "manual_monitor":
            parts.append(f"Monitor: if price breaches {stop_value} → GTD sell")
        elif stop_type == "trailing":
            parts.append(
                f"Monitor trailing {stop_value}: if breached → GTD sell "
                "(broker has no auto-trailing)"
            )
        elif stop_type == "hard":
            parts.append(
                f"Monitor: if close < {stop_value} → GTD sell next session"
            )
        else:
            parts.append(f"Stop level: {stop_value} (manual)")

    if exit_trigger and exit_trigger.lower() not in (s.lower() for s in parts):
        parts.append(exit_trigger)

    return "; ".join(parts) if parts else "—"


def _is_candidate_result(r: "PortfolioResult") -> bool:
    """True iff this ticker was evaluated as a NEW-position candidate."""
    if r.state is None:
        return False
    ctx = r.state.get("portfolio_context") or {}
    return bool(ctx.get("is_candidate"))


def _candidate_decision_label(decision: str) -> str:
    """Map BUY/HOLD/SELL to candidate-specific labels."""
    return {
        "BUY": "ADD",
        "HOLD": "WATCHLIST",
        "SELL": "REJECT",
    }.get((decision or "").upper(), decision or "—")


def _render_candidate_summary(results: list["PortfolioResult"]) -> list[str]:
    """Render the comparative table for candidate tickers, or empty list if none.

    Pulls structured data from ``trade_decision_structured`` (set by the Risk
    Judge) and the precomputed ``candidate_fit`` (in portfolio_context). Falls
    back to dashes when data is missing — never hides a row.
    """
    candidates = [r for r in results if _is_candidate_result(r)]
    if not candidates:
        return []

    lines: list[str] = ["## Candidate Evaluation"]
    lines.append("")
    lines.append(
        "| Ticker | Decision | Score | Role | Role gap | Sector overlap | "
        "Entry quality | Recommended size |"
    )
    lines.append(
        "|--------|----------|------:|------|----------|----------------|"
        "---------------|------------------|"
    )

    for r in candidates:
        state = r.state or {}
        structured = state.get("trade_decision_structured") or {}
        ctx = state.get("portfolio_context") or {}
        fit = ctx.get("candidate_fit") or {}
        role_gap = fit.get("role_gap") or {}
        overlap = fit.get("sector_overlap") or {}
        cand = structured.get("candidate") or {}

        decision_raw = (structured.get("decision") or r.short_decision() or "").upper()
        decision_label = _candidate_decision_label(decision_raw)
        score = cand.get("score")
        score_str = f"{score:.1f}" if isinstance(score, (int, float)) else "—"
        role = (structured.get("role") or ctx.get("role") or "candidate")

        gap_str = (
            "FILLS" if role_gap.get("has_gap")
            else f"AT/OVER ({role_gap.get('current_weight_pct', 0):.1f}/"
                 f"{role_gap.get('target_weight_pct', 0):.1f}%)"
        )

        ov_level = overlap.get("level") or cand.get("sector_overlap") or "—"
        ov_with = ", ".join(overlap.get("overlapping_tickers") or cand.get("sector_overlap_with") or []) or "—"
        ov_str = f"{ov_level}" + (f" ({ov_with})" if ov_with != "—" else "")

        entry_q = structured.get("entry_quality") or "n/a"

        rec_pct = cand.get("recommended_size_pct") or fit.get("recommended_initial_weight_pct")
        rec_usd = cand.get("recommended_size_usd") or fit.get("recommended_initial_size_usd")
        if rec_pct is not None and rec_usd is not None:
            size_str = f"{rec_pct:.1f}% (${rec_usd:,.0f})"
        elif rec_pct is not None:
            size_str = f"{rec_pct:.1f}%"
        else:
            size_str = "—"

        lines.append(
            f"| {r.ticker} | **{decision_label}** | {score_str} | {role} | "
            f"{gap_str} | {ov_str} | {entry_q} | {size_str} |"
        )

    return lines


def _render_ticker_detail(r: "PortfolioResult") -> list[str]:
    """Expand a ticker's final state into markdown mirroring the JSON log.

    Falls back to a fenced decision block when ``r.state`` is unavailable
    (e.g. in tests with a stubbed state dict).
    """
    state = r.state or {}
    lines: list[str] = []

    has_detail = any(
        state.get(key) for key, _ in _DETAIL_REPORT_SECTIONS
    ) or state.get("investment_debate_state") or state.get("risk_debate_state") or state.get(
        "investment_plan"
    ) or state.get("trader_investment_plan") or state.get("final_trade_decision")

    if not has_detail:
        lines.append("")
        lines.append("```")
        lines.append((r.decision or "").strip())
        lines.append("```")
        return lines

    # Surface the portfolio context that was fed to Trader + Risk Judge so
    # the reader can see what the decision was anchored on.
    pc = state.get("portfolio_context")
    if pc:
        from tradingagents.agents.utils.portfolio_context import (
            format_portfolio_context,
        )

        block = format_portfolio_context(pc, r.ticker)
        if block:
            lines.append("")
            lines.append("#### 💼 Portfolio Context (injected)")
            lines.append("")
            lines.append(block)

    for key, heading in _DETAIL_REPORT_SECTIONS:
        _append_section(lines, heading, state.get(key))

    invest = state.get("investment_debate_state") or {}
    if any(invest.get(k) for k, _ in _DETAIL_INVEST_DEBATE_SECTIONS):
        lines.append("")
        lines.append("#### 🥊 Bull vs Bear Debate")
        for sub_key, sub_heading in _DETAIL_INVEST_DEBATE_SECTIONS:
            _append_section(lines, sub_heading, invest.get(sub_key), level=5)

    _append_section(lines, "🧠 Investment Plan", state.get("investment_plan"))
    _append_section(
        lines, "💼 Trader Investment Decision", state.get("trader_investment_plan")
    )

    risk = state.get("risk_debate_state") or {}
    if any(risk.get(k) for k, _ in _DETAIL_RISK_DEBATE_SECTIONS):
        lines.append("")
        lines.append("#### ⚠ Risk Management Debate")
        for sub_key, sub_heading in _DETAIL_RISK_DEBATE_SECTIONS:
            _append_section(lines, sub_heading, risk.get(sub_key), level=5)

    _append_section(lines, "✅ Final Trade Decision", state.get("final_trade_decision"))

    return lines


def _extract_short_decision(decision: Any) -> str | None:
    text = _coerce_to_text(decision)
    if not text:
        return None
    upper = text.upper()
    for token in ("BUY", "SELL", "HOLD"):
        if token in upper:
            return token
    return (text.strip().splitlines()[0] or "")[:30] or None


@dataclass
class PortfolioResult:
    ticker: str
    decision: str | None
    state: dict[str, Any] | None = field(default=None, repr=False)
    error: str | None = None
    duration_s: float = 0.0

    def __post_init__(self) -> None:
        # Normalise Gemini-shaped content to a plain string so downstream
        # consumers (rich table, markdown, csv, json) can treat it uniformly.
        if self.decision is not None and not isinstance(self.decision, str):
            self.decision = _coerce_to_text(self.decision)
        if self.decision == "":
            self.decision = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.decision is not None

    def short_decision(self) -> str:
        """Extract BUY/SELL/HOLD if present, otherwise truncated raw text."""
        if self.error:
            return "ERROR"
        text = _coerce_to_text(self.decision)
        if not text:
            return "-"
        upper = text.upper()
        for token in ("BUY", "SELL", "HOLD"):
            if token in upper:
                return token
        return (text.strip().splitlines()[0] or "-")[:40]


class PortfolioReporter:
    """Render and persist portfolio-level results."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    def render_table(
        self,
        results: Iterable[PortfolioResult],
        trade_date: str,
        pppc_by_ticker: dict[str, str] | None = None,
    ) -> None:
        results = list(results)
        table = Table(
            title=f"Portfolio Analysis — {trade_date}",
            show_header=True,
            header_style="bold magenta",
        )
        table.add_column("Ticker", style="cyan", no_wrap=True)
        table.add_column("Decision", style="green")
        if pppc_by_ticker:
            table.add_column("PPC (CSV)", style="white", justify="right")
        table.add_column("Duration", style="yellow", justify="right")
        table.add_column("Log", style="white", overflow="fold")
        table.add_column("Error", style="red", overflow="fold")

        for r in results:
            decision = r.short_decision()
            decision_color = {
                "BUY": "[bold green]BUY[/bold green]",
                "SELL": "[bold red]SELL[/bold red]",
                "HOLD": "[bold yellow]HOLD[/bold yellow]",
                "ERROR": "[bold red]ERROR[/bold red]",
            }.get(decision, decision)

            log_path = (
                f"eval_results/{r.ticker}/TradingAgentsStrategy_logs/"
                f"full_states_log_{trade_date}.json"
                if r.ok
                else "-"
            )
            row = [r.ticker, decision_color]
            if pppc_by_ticker:
                row.append(pppc_by_ticker.get(r.ticker, "-"))
            row.extend([f"{r.duration_s:.1f}s", log_path, r.error or ""])
            table.add_row(*row)

        self.console.print(table)
        self.console.print(self._summary_panel(results))

    def _summary_panel(self, results: list[PortfolioResult]) -> Panel:
        total = len(results)
        counter = Counter(r.short_decision() for r in results)
        ok_count = sum(1 for r in results if r.ok)
        errors = total - ok_count

        lines = [f"[bold]Total:[/bold] {total}   [green]OK:[/green] {ok_count}   [red]Errors:[/red] {errors}"]
        for label in ("BUY", "SELL", "HOLD"):
            n = counter.get(label, 0)
            if n:
                pct = 100 * n / ok_count if ok_count else 0
                lines.append(f"  {label}: {n} ({pct:.0f}% of OK)")
        return Panel("\n".join(lines), title="Summary", border_style="blue")

    def save_json(
        self,
        results: Iterable[PortfolioResult],
        trade_date: str,
        out_dir: str | Path = "eval_results/_portfolio",
    ) -> Path:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        file_path = out_path / f"portfolio_report_{trade_date}.json"

        payload = {
            "trade_date": trade_date,
            "results": [
                {
                    "ticker": r.ticker,
                    "decision_short": r.short_decision(),
                    "decision_full": r.decision,
                    "error": r.error,
                    "duration_s": round(r.duration_s, 2),
                    "log_path": (
                        f"eval_results/{r.ticker}/TradingAgentsStrategy_logs/"
                        f"full_states_log_{trade_date}.json"
                        if r.ok
                        else None
                    ),
                }
                for r in results
            ],
        }
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return file_path

    def save_markdown(
        self,
        results: Iterable[PortfolioResult],
        trade_date: str,
        out_dir: str | Path = "reports",
        synthesis: dict[str, Any] | None = None,
    ) -> Path:
        """Write a human-readable Markdown summary with the aggregate table.

        When ``synthesis`` is provided (from
        ``TradingAgentsGraph.synthesize_portfolio``), its ``narrative`` is
        rendered at the top of the report so the Portfolio Manager's verdict
        is the first thing the reader sees, before the per-ticker drill-down.
        """
        results = list(results)
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        file_path = out_path / f"portfolio_{trade_date}.md"

        total = len(results)
        ok = [r for r in results if r.ok]
        errors = [r for r in results if not r.ok]
        counter = Counter(r.short_decision() for r in ok)

        lines: list[str] = []
        lines.append(f"# Portfolio Analysis — {trade_date}")
        lines.append("")
        lines.append(
            f"**Total:** {total}  |  **OK:** {len(ok)}  |  **Errors:** {len(errors)}"
        )
        distribution = "  |  ".join(
            f"**{label}:** {counter.get(label, 0)}"
            for label in ("BUY", "SELL", "HOLD")
            if counter.get(label, 0)
        )
        if distribution:
            lines.append("")
            lines.append(distribution)
        lines.append("")

        if synthesis and synthesis.get("narrative"):
            lines.append("## 🎯 Portfolio Manager — Veredicto Estratégico")
            lines.append("")
            lines.append(str(synthesis["narrative"]))
            lines.append("")
            lines.append("---")
            lines.append("")
        elif synthesis and synthesis.get("error"):
            lines.append(
                f"> ⚠️ Portfolio Manager skipped: {synthesis['error']}"
            )
            lines.append("")

        lines.append("| Ticker | Decision | Duration | Log | Error |")
        lines.append("|--------|----------|---------:|-----|-------|")
        for r in results:
            log_path = (
                f"../eval_results/{r.ticker}/TradingAgentsStrategy_logs/"
                f"full_states_log_{trade_date}.json"
                if r.ok
                else "-"
            )
            log_cell = f"[JSON]({log_path})" if r.ok else "-"
            error_cell = (r.error or "").replace("|", "\\|")
            lines.append(
                f"| {r.ticker} | {r.short_decision()} | {r.duration_s:.1f}s | {log_cell} | {error_cell} |"
            )

        broker_orders = _render_broker_orders(ok)
        if broker_orders:
            lines.append("")
            lines.extend(broker_orders)

        candidate_table = _render_candidate_summary(ok)
        if candidate_table:
            lines.append("")
            lines.extend(candidate_table)

        if ok:
            lines.append("")
            lines.append("## Detailed decisions")
            for r in ok:
                lines.append("")
                lines.append(f"### {r.ticker} — {r.short_decision()}")
                lines.extend(_render_ticker_detail(r))

        file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return file_path

    def save_csv(
        self,
        results: Iterable[PortfolioResult],
        trade_date: str,
        out_dir: str | Path = "reports",
    ) -> Path:
        """Write a flat CSV so the table can be opened in Excel / joined with positions."""
        results = list(results)
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        file_path = out_path / f"portfolio_{trade_date}.csv"

        with file_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "ticker",
                    "decision_short",
                    "decision_full",
                    "error",
                    "duration_s",
                    "log_path",
                ]
            )
            for r in results:
                log_path = (
                    f"eval_results/{r.ticker}/TradingAgentsStrategy_logs/"
                    f"full_states_log_{trade_date}.json"
                    if r.ok
                    else ""
                )
                writer.writerow(
                    [
                        r.ticker,
                        r.short_decision(),
                        (r.decision or "").strip(),
                        r.error or "",
                        f"{r.duration_s:.2f}",
                        log_path,
                    ]
                )
        return file_path
