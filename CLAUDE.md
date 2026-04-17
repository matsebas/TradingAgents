# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt
# or with uv
uv sync

# Run the interactive CLI
python -m cli.main

# Run a single analysis (example script)
python main.py

# Run a test
python tests/test.py
```

Python 3.10+ is required (project targets 3.13, see `.python-version`).

## Environment Setup

Copy `.env.example` and populate. The default config uses **Google Gemini** — only one key is needed:

```bash
GEMINI_API_KEY=...
GOOGLE_API_KEY=...   # same key, both are read
```

For OpenAI + Alpha Vantage instead, set `OPENAI_API_KEY` and `ALPHA_VANTAGE_API_KEY`, then change `llm_provider` to `"openai"` in `tradingagents/default_config.py`.

## Architecture

### Execution Flow

`TradingAgentsGraph` in `tradingagents/graph/trading_graph.py` is the top-level entry point. Calling `.propagate(ticker, date)` runs the full agent pipeline and returns `(final_state, decision)`.

The pipeline is a **LangGraph StateGraph** compiled in `tradingagents/graph/setup.py`:

```
Analysts (parallel reports) → Bull/Bear Researcher Debate → Research Manager
→ Trader → Risk Analysts Debate (Risky/Safe/Neutral) → Risk Judge → END
```

Analysts run sequentially in the order given to `selected_analysts`. Each analyst node has a paired tool node and a message-clearing node (to avoid context bloat between phases). The number of debate rounds is controlled by `max_debate_rounds` and `max_risk_discuss_rounds` in config.

### State

Three TypedDicts in `tradingagents/agents/utils/agent_states.py`:
- `AgentState` (extends `MessagesState`) — top-level graph state carrying reports from each analyst, debate states, and the final decision
- `InvestDebateState` — tracks the bull/bear researcher debate
- `RiskDebateState` — tracks the risk analysts debate

### Vendor Routing

All data access goes through `tradingagents/dataflows/interface.py` → `route_to_vendor()`. Agent tools (defined in `tradingagents/agents/utils/`) call `route_to_vendor(method_name, *args)`. The router:
1. Looks up the method's category (`core_stock_apis`, `technical_indicators`, `fundamental_data`, `news_data`)
2. Reads the configured vendor from `data_vendors` or `tool_vendors` in config
3. Calls the vendor-specific implementation, with automatic fallback to other vendors on failure

**Adding a new data source**: add an implementation module to `tradingagents/dataflows/`, register it in `VENDOR_METHODS` in `interface.py`.

**Vendor options per category** (see `default_config.py`):
- `core_stock_apis`: `yfinance`, `alpha_vantage`, `local`
- `technical_indicators`: `yfinance`, `alpha_vantage`, `local`
- `fundamental_data`: `gemini`, `openai`, `alpha_vantage`, `local`
- `news_data`: `gemini`, `openai`, `google`, `alpha_vantage`, `local`

### Memory

`FinancialSituationMemory` in `tradingagents/agents/utils/memory.py` uses **ChromaDB** (persistent, stored in `./chroma_db/`) with embeddings from Gemini (`gemini-embedding-001`) or OpenAI (`text-embedding-3-small`). Five separate collections are maintained — one per role (bull, bear, trader, invest_judge, risk_manager). After a trade, call `ta.reflect_and_remember(returns)` to write back lessons learned.

### LLM Providers

Supported providers (`llm_provider` in config): `google`, `openai`, `anthropic`, `openrouter`, `ollama`. Each provider has a `deep_think_llm` and a `quick_think_llm` — analysts and researchers use the quick model; research manager and risk judge use the deep model.

### Configuration

Everything flows through `tradingagents/default_config.py` → `DEFAULT_CONFIG`. The global singleton in `tradingagents/dataflows/config.py` is updated via `set_config()` when `TradingAgentsGraph` is initialized. Always pass `config=DEFAULT_CONFIG.copy()` and mutate the copy to avoid cross-instance contamination.

### CLI

`cli/main.py` + `cli/utils.py` implement an interactive terminal UI using `questionary` (prompts) and `rich` (display). `cli/models.py` defines the `AnalystType` enum.

### Results & Logs

Each `.propagate()` call writes a JSON log to `eval_results/{ticker}/TradingAgentsStrategy_logs/full_states_log_{date}.json`.