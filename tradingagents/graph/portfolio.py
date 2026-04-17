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
    ) -> Path:
        """Write a human-readable Markdown summary with the aggregate table."""
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

        if ok:
            lines.append("")
            lines.append("## Detailed decisions")
            for r in ok:
                lines.append("")
                lines.append(f"### {r.ticker} — {r.short_decision()}")
                lines.append("")
                lines.append("```")
                lines.append((r.decision or "").strip())
                lines.append("```")

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
