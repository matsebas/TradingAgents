"""Example: run the TradingAgents pipeline for a whole portfolio in parallel.

Usage variants:
    # Hard-coded tickers
    python main_portfolio.py

    # From the CLI instead:
    python -m cli.main portfolio --positions /path/to/positions.csv
    python -m cli.main portfolio --tickers NVDA,AMZN,SPY
    python -m cli.main portfolio   # interactive prompt
"""

import asyncio
import contextlib
import datetime
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.portfolio import PortfolioProgress, PortfolioReporter
from tradingagents.graph.trading_graph import TradingAgentsGraph


load_dotenv()


async def main() -> None:
    tickers = ["NVDA", "AMZN", "SPY", "IBIT", "SMH"]
    trade_date = datetime.date.today().isoformat()

    config = DEFAULT_CONFIG.copy()
    # Use Gemini flash for both quick and deep thinking — keeps cost/latency low
    # across N parallel tickers.
    config["quick_think_llm"] = "gemini-3-flash-preview"
    config["deep_think_llm"] = "gemini-3-flash-preview"
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1

    ta = TradingAgentsGraph(config=config, debug=False)

    log_dir = Path("eval_results/_portfolio")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"portfolio_{trade_date}.log"
    dashboard_console = Console(file=sys.stdout)

    with log_file.open("w", encoding="utf-8") as log_fh, contextlib.redirect_stdout(log_fh):
        with PortfolioProgress(tickers, console=dashboard_console) as progress:
            results = await ta.propagate_portfolio(
                tickers, trade_date, max_concurrency=10, progress=progress
            )

    reporter = PortfolioReporter(console=dashboard_console)
    dashboard_console.print()
    reporter.render_table(results, trade_date)
    json_path = reporter.save_json(results, trade_date)
    md_path = reporter.save_markdown(results, trade_date)
    csv_path = reporter.save_csv(results, trade_date)
    dashboard_console.print(
        f"\n[dim]Aggregated reports saved:\n"
        f"  JSON:     {json_path}\n"
        f"  Markdown: {md_path}\n"
        f"  CSV:      {csv_path}\n"
        f"  Run log:  {log_file}[/dim]"
    )


if __name__ == "__main__":
    asyncio.run(main())
