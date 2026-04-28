# TradingAgents/graph/trading_graph.py

import asyncio
import copy
import json
import os
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI

from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.agents.utils.memory import FinancialSituationMemory
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.agents.utils.portfolio_aggregate import (
    compute_portfolio_aggregate,
)
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.previous_decision import load_previous_decision

# Import the new abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    get_stock_data,
    get_indicators,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_insider_sentiment,
    get_insider_transactions,
    get_global_news
)

from .conditional_logic import ConditionalLogic
from .setup import GraphSetup
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor


def _augment_portfolio_context(
    base_ctx: Optional[Dict[str, Any]],
    ticker: str,
    trade_date: str,
    portfolio_aggregate: Optional[Dict[str, Any]],
    *,
    reports_dir: str = "reports",
) -> Optional[Dict[str, Any]]:
    """Inject portfolio-level fields into a per-ticker context dict.

    Adds ``portfolio_aggregate`` (the same precomputed dict for every ticker)
    and ``previous_decision`` (per-ticker, read from disk). Returns the
    augmented dict, or ``None`` if there's nothing to inject and ``base_ctx``
    was also ``None``.
    """
    augmented: Dict[str, Any] = dict(base_ctx) if base_ctx else {}
    if portfolio_aggregate is not None:
        # Deep-copy so concurrent ticker runs can't accidentally corrupt the
        # shared aggregate by mutating nested dicts/lists in-place.
        augmented["portfolio_aggregate"] = copy.deepcopy(portfolio_aggregate)
    prev = load_previous_decision(ticker, trade_date, reports_dir=reports_dir)
    if prev is not None:
        augmented["previous_decision"] = prev.to_dict()
    return augmented if augmented else None


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=["market", "social", "news", "fundamentals"],
        debug=False,
        config: Dict[str, Any] = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(
            os.path.join(self.config["project_dir"], "dataflows/data_cache"),
            exist_ok=True,
        )

        # Initialize LLMs. ``analyst_llm`` and ``mechanical_llm`` are optional
        # lighter-weight tiers; if a config doesn't define them they fall back
        # to ``quick_think_llm`` so legacy configs keep working unchanged.
        analyst_model = self.config.get("analyst_llm") or self.config["quick_think_llm"]
        mechanical_model = self.config.get("mechanical_llm") or self.config["quick_think_llm"]

        provider = self.config["llm_provider"].lower()
        if provider in ("openai", "ollama", "openrouter"):
            base_url = self.config["backend_url"]
            self.deep_thinking_llm = ChatOpenAI(model=self.config["deep_think_llm"], base_url=base_url)
            self.quick_thinking_llm = ChatOpenAI(model=self.config["quick_think_llm"], base_url=base_url)
            self.analyst_llm = ChatOpenAI(model=analyst_model, base_url=base_url)
            self.mechanical_llm = ChatOpenAI(model=mechanical_model, base_url=base_url)
        elif provider == "anthropic":
            base_url = self.config["backend_url"]
            self.deep_thinking_llm = ChatAnthropic(model=self.config["deep_think_llm"], base_url=base_url)
            self.quick_thinking_llm = ChatAnthropic(model=self.config["quick_think_llm"], base_url=base_url)
            self.analyst_llm = ChatAnthropic(model=analyst_model, base_url=base_url)
            self.mechanical_llm = ChatAnthropic(model=mechanical_model, base_url=base_url)
        elif provider == "google":
            self.deep_thinking_llm = ChatGoogleGenerativeAI(model=self.config["deep_think_llm"])
            self.quick_thinking_llm = ChatGoogleGenerativeAI(model=self.config["quick_think_llm"])
            self.analyst_llm = ChatGoogleGenerativeAI(model=analyst_model)
            self.mechanical_llm = ChatGoogleGenerativeAI(model=mechanical_model)
        else:
            raise ValueError(f"Unsupported LLM provider: {self.config['llm_provider']}")
        
        # Initialize memories
        self.bull_memory = FinancialSituationMemory("bull_memory", self.config)
        self.bear_memory = FinancialSituationMemory("bear_memory", self.config)
        self.trader_memory = FinancialSituationMemory("trader_memory", self.config)
        self.invest_judge_memory = FinancialSituationMemory("invest_judge_memory", self.config)
        self.risk_manager_memory = FinancialSituationMemory("risk_manager_memory", self.config)

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic()
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.bull_memory,
            self.bear_memory,
            self.trader_memory,
            self.invest_judge_memory,
            self.risk_manager_memory,
            self.conditional_logic,
            analyst_llm=self.analyst_llm,
        )

        self.propagator = Propagator()
        # Reflector + SignalProcessor are pure pattern extraction; the lighter
        # mechanical_llm is enough and keeps Flash quota for the actual agents.
        self.reflector = Reflector(self.mechanical_llm)
        self.signal_processor = SignalProcessor(self.mechanical_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph
        self.graph = self.graph_setup.setup_graph(selected_analysts)

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": ToolNode(
                [
                    # Core stock data tools
                    get_stock_data,
                    # Technical indicators
                    get_indicators,
                ]
            ),
            "social": ToolNode(
                [
                    # News tools for social media analysis
                    get_news,
                ]
            ),
            "news": ToolNode(
                [
                    # News and insider information
                    get_news,
                    get_global_news,
                    get_insider_sentiment,
                    get_insider_transactions,
                ]
            ),
            "fundamentals": ToolNode(
                [
                    # Fundamental analysis tools
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                ]
            ),
        }

    def propagate(self, company_name, trade_date, portfolio_context=None):
        """Run the trading agents graph for a company on a specific date.

        ``portfolio_context`` is an optional dict with the caller's current
        holding for this ticker (e.g. ``{"avg_cost": 42.5, "currency": "USD"}``).
        When provided, the Trader and Risk Judge receive it in their prompts
        so the decision is anchored on the existing position. Analysts and
        Researchers do not see it, to keep their reports unbiased.
        """
        self.ticker = company_name
        init_agent_state = self.propagator.create_initial_state(
            company_name, trade_date, portfolio_context=portfolio_context
        )
        args = self.propagator.get_graph_args()

        if self.debug:
            trace = []
            for chunk in self.graph.stream(init_agent_state, **args):
                if len(chunk["messages"]) == 0:
                    pass
                else:
                    chunk["messages"][-1].pretty_print()
                    trace.append(chunk)
            final_state = trace[-1]
        else:
            final_state = self.graph.invoke(init_agent_state, **args)

        self.curr_state = final_state
        self._log_state(company_name, trade_date, final_state)

        return final_state, self.process_signal(final_state["final_trade_decision"])

    async def propagate_async(
        self, company_name, trade_date, on_node=None, portfolio_context=None
    ):
        """Async variant that does not mutate instance state — safe for parallel use.

        If ``on_node`` is provided, it is called with each node name as the
        graph streams updates — enabling live progress dashboards. Final state
        is captured from the ``values`` stream so we do not need to invoke the
        graph twice.

        ``portfolio_context`` — see :meth:`propagate`.
        """
        init_agent_state = self.propagator.create_initial_state(
            company_name, trade_date, portfolio_context=portfolio_context
        )
        args = self.propagator.get_graph_args()

        if on_node is None:
            final_state = await self.graph.ainvoke(init_agent_state, **args)
        else:
            # get_graph_args() already sets stream_mode; replace it with the
            # dual mode we need for progress tracking + final state capture.
            stream_args = {k: v for k, v in args.items() if k != "stream_mode"}
            final_state = None
            async for mode, event in self.graph.astream(
                init_agent_state,
                stream_mode=["updates", "values"],
                **stream_args,
            ):
                if mode == "updates":
                    for node_name in event.keys():
                        try:
                            on_node(node_name)
                        except Exception:
                            pass  # never let UI callbacks break the pipeline
                elif mode == "values":
                    final_state = event
            if final_state is None:
                raise RuntimeError(
                    f"Graph streaming for {company_name} ended without a final state"
                )

        self._log_state(company_name, trade_date, final_state)
        return final_state, self.process_signal(final_state["final_trade_decision"])

    async def propagate_portfolio(
        self,
        tickers,
        trade_date,
        max_concurrency: int = 10,
        progress=None,
        holdings: Dict[str, Dict[str, Any]] | None = None,
    ):
        """Run the pipeline for several tickers concurrently.

        Returns a list of ``PortfolioResult`` in the same order as ``tickers``.
        Individual ticker failures are captured in the result's ``error`` field
        rather than raising, so partial success is always reported.

        ``progress`` can be a ``PortfolioProgress`` instance — if provided,
        per-ticker start / node / finish events are forwarded so callers can
        render a live dashboard.

        ``holdings`` maps ticker → portfolio_context dict (e.g.
        ``{"NVDA": {"avg_cost": 123.4, "currency": "USD"}}``). The context for
        each ticker is threaded into the Trader and Risk Judge prompts only.
        Tickers missing from ``holdings`` simply run with no portfolio context.
        """
        from .portfolio import PortfolioResult  # local import to avoid cycle

        semaphore = asyncio.Semaphore(max_concurrency)

        # Compute portfolio-level aggregates ONCE per run, so every ticker's
        # Risk Judge sees the same whole-book view. None when holdings lack
        # qty + avg_cost (e.g. ticker-list mode without positions CSV).
        portfolio_agg = compute_portfolio_aggregate(holdings)
        agg_dict = portfolio_agg.to_dict() if portfolio_agg is not None else None

        async def run_one(ticker: str) -> "PortfolioResult":
            start = time.perf_counter()
            async with semaphore:
                if progress is not None:
                    progress.start(ticker)
                on_node = (
                    (lambda n, t=ticker: progress.on_node(t, n))
                    if progress is not None
                    else None
                )
                base_ctx = holdings.get(ticker) if holdings else None
                ctx = _augment_portfolio_context(
                    base_ctx, ticker, trade_date, agg_dict
                )
                try:
                    state, decision = await self.propagate_async(
                        ticker, trade_date, on_node=on_node, portfolio_context=ctx
                    )
                    if progress is not None:
                        progress.finish(ticker, decision=decision)
                    return PortfolioResult(
                        ticker=ticker,
                        decision=decision,
                        state=state,
                        error=None,
                        duration_s=time.perf_counter() - start,
                    )
                except Exception as exc:  # noqa: BLE001 — fail-soft per ticker
                    err = f"{type(exc).__name__}: {exc}"
                    if progress is not None:
                        progress.finish(ticker, error=err)
                    return PortfolioResult(
                        ticker=ticker,
                        decision=None,
                        state=None,
                        error=err,
                        duration_s=time.perf_counter() - start,
                    )

        return await asyncio.gather(*(run_one(t) for t in tickers))

    def _log_state(self, ticker, trade_date, final_state):
        """Persist the final state to a per-ticker JSON file."""
        log_entry = {
            str(trade_date): {
                "company_of_interest": final_state["company_of_interest"],
                "trade_date": final_state["trade_date"],
                "market_report": final_state["market_report"],
                "sentiment_report": final_state["sentiment_report"],
                "news_report": final_state["news_report"],
                "fundamentals_report": final_state["fundamentals_report"],
                "investment_debate_state": {
                    "bull_history": final_state["investment_debate_state"]["bull_history"],
                    "bear_history": final_state["investment_debate_state"]["bear_history"],
                    "history": final_state["investment_debate_state"]["history"],
                    "current_response": final_state["investment_debate_state"][
                        "current_response"
                    ],
                    "judge_decision": final_state["investment_debate_state"][
                        "judge_decision"
                    ],
                },
                "trader_investment_decision": final_state["trader_investment_plan"],
                "risk_debate_state": {
                    "risky_history": final_state["risk_debate_state"]["risky_history"],
                    "safe_history": final_state["risk_debate_state"]["safe_history"],
                    "neutral_history": final_state["risk_debate_state"][
                        "neutral_history"
                    ],
                    "history": final_state["risk_debate_state"]["history"],
                    "judge_decision": final_state["risk_debate_state"]["judge_decision"],
                },
                "investment_plan": final_state["investment_plan"],
                "final_trade_decision": final_state["final_trade_decision"],
                "portfolio_context": final_state.get("portfolio_context"),
                "trade_decision_structured": final_state.get(
                    "trade_decision_structured"
                ),
            }
        }
        self.log_states_dict.setdefault(ticker, {}).update(log_entry)

        directory = Path(f"eval_results/{ticker}/TradingAgentsStrategy_logs/")
        directory.mkdir(parents=True, exist_ok=True)

        with open(
            directory / f"full_states_log_{trade_date}.json",
            "w",
        ) as f:
            # default=str so Decimal / date / numpy scalars from caller-supplied
            # holdings dicts don't crash the dump and orphan the entire run.
            json.dump(log_entry, f, indent=4, default=str)

    def reflect_and_remember(self, returns_losses, state=None):
        """Reflect on decisions and update memory based on returns.

        ``state`` can be passed explicitly (required when using the async /
        portfolio path). If omitted, falls back to ``self.curr_state`` for
        backward compatibility with single-ticker sync callers.
        """
        target_state = state if state is not None else self.curr_state
        if target_state is None:
            raise ValueError(
                "No state available for reflection. Pass state= explicitly "
                "or run propagate() first."
            )

        self.reflector.reflect_bull_researcher(
            target_state, returns_losses, self.bull_memory
        )
        self.reflector.reflect_bear_researcher(
            target_state, returns_losses, self.bear_memory
        )
        self.reflector.reflect_trader(
            target_state, returns_losses, self.trader_memory
        )
        self.reflector.reflect_invest_judge(
            target_state, returns_losses, self.invest_judge_memory
        )
        self.reflector.reflect_risk_manager(
            target_state, returns_losses, self.risk_manager_memory
        )

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal)
