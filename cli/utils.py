import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import questionary

from cli.main import console
from cli.models import AnalystType


# Roles allowed when overriding candidate classification via the CLI.
_VALID_ROLES = ("anchor", "tactical", "speculative")


@dataclass(frozen=True)
class CashHoldings:
    """Cash positions provided via the ``--cash`` flag, beyond FCI liquidity.

    Currencies are stored at face value in their native unit. ARS is NOT
    auto-converted — the caller must pass an FX rate (``--ars-mep-rate`` or
    ``--ars-cable-rate``) for it to count toward USD-deployable liquidity.
    """

    mep_usd: float = 0.0
    cable_usd: float = 0.0
    ars_native: float = 0.0
    ars_to_usd_rate: Optional[float] = None  # MEP rate by default

    def has_ars(self) -> bool:
        return self.ars_native > 0

    def needs_ars_rate(self) -> bool:
        return self.has_ars() and self.ars_to_usd_rate is None

ANALYST_ORDER = [
    ("Market Analyst", AnalystType.MARKET),
    ("Social Media Analyst", AnalystType.SOCIAL),
    ("News Analyst", AnalystType.NEWS),
    ("Fundamentals Analyst", AnalystType.FUNDAMENTALS),
]


def get_ticker() -> str:
    """Prompt the user to enter a ticker symbol."""
    ticker = questionary.text(
        "Enter the ticker symbol to analyze:",
        validate=lambda x: len(x.strip()) > 0 or "Please enter a valid ticker symbol.",
        style=questionary.Style(
            [
                ("text", "fg:green"),
                ("highlighted", "noinherit"),
            ]
        ),
    ).ask()

    if not ticker:
        console.print("\n[red]No ticker symbol provided. Exiting...[/red]")
        exit(1)

    return ticker.strip().upper()


def get_tickers() -> List[str]:
    """Prompt for a list of tickers.

    Accepts either a path to a CSV position report or a comma-separated list.
    """
    raw = questionary.text(
        "Enter tickers (comma-separated) OR path to a positions CSV:",
        validate=lambda x: len(x.strip()) > 0 or "Please enter tickers or a CSV path.",
        style=questionary.Style(
            [
                ("text", "fg:green"),
                ("highlighted", "noinherit"),
            ]
        ),
    ).ask()

    if not raw:
        console.print("\n[red]No tickers provided. Exiting...[/red]")
        exit(1)

    return parse_tickers_input(raw.strip())


def parse_tickers_input(raw: str, types: Optional[List[str]] = None) -> List[str]:
    """Resolve a user-provided string into a ticker list.

    If the string is an existing file path, parse it as a positions CSV.
    Otherwise treat it as a comma-separated ticker list.
    """
    tickers, _ = resolve_positions_input(raw, types=types)
    return tickers


def resolve_positions_input(
    raw: str, types: Optional[List[str]] = None
) -> Tuple[List[str], Dict[str, Dict[str, object]]]:
    """Resolve user input into ``(tickers, holdings)``.

    ``holdings`` is a mapping of ticker → ``portfolio_context`` dict ready to
    be passed to :py:meth:`TradingAgentsGraph.propagate_portfolio`. It is
    populated only when the input is a positions CSV and the rows carry a
    ``pppc_mep`` column; otherwise the dict is empty.
    """
    from tradingagents.dataflows.position_parser import parse_positions_csv

    holdings: Dict[str, Dict[str, object]] = {}

    candidate = Path(raw).expanduser()
    if candidate.exists() and candidate.is_file():
        positions = parse_positions_csv(candidate, types=types)
        tickers = [p.ticker for p in positions]
        for p in positions:
            # Require at least one signal that's actually usable in a prompt.
            if p.pppc is None and p.unrealized_return_pct is None and p.quantity is None:
                continue
            ctx: Dict[str, object] = {
                "currency": "USD",  # pppc_mep is already MEP-USD
                "instrument_type": p.instrument_type,
            }
            if p.pppc is not None:
                ctx["avg_cost"] = p.pppc
            if p.quantity is not None:
                ctx["quantity"] = p.quantity
            if p.unrealized_return_pct is not None:
                # Store as fraction; the prompt formatter renders as %.
                ctx["unrealized_return_pct"] = p.unrealized_return_pct
            if p.role is not None:
                ctx["role"] = p.role
            holdings[p.ticker] = ctx
    else:
        tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]

    # Dedupe preserving order
    seen = set()
    out = []
    for t in tickers:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out, holdings


def parse_candidates_input(
    raw: Optional[str], default_role: str = "tactical"
) -> Dict[str, Dict[str, object]]:
    """Parse the ``--candidates`` flag into a ``{ticker: ctx}`` mapping.

    Accepts a comma-separated list with optional ``:role`` suffix per ticker:

        ``"NVO"`` → tactical (default)
        ``"NVO:anchor"`` → anchor
        ``"NVO:tactical,GOOGL:speculative"`` → both, distinct roles

    Each candidate's ``ctx`` is shaped so the existing portfolio_context
    plumbing accepts it: ``role`` set, ``is_candidate=True``, and zero
    ``quantity``/``avg_cost`` so it's excluded from cost-basis aggregates.
    """
    if not raw:
        return {}
    if default_role not in _VALID_ROLES:
        raise ValueError(
            f"Invalid default_role '{default_role}'; expected one of {_VALID_ROLES}"
        )
    out: Dict[str, Dict[str, object]] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            ticker, role = chunk.split(":", 1)
            ticker = ticker.strip().upper()
            role = role.strip().lower()
            if role not in _VALID_ROLES:
                raise ValueError(
                    f"Invalid role '{role}' for candidate '{ticker}'; "
                    f"expected one of {_VALID_ROLES}"
                )
        else:
            ticker = chunk.strip().upper()
            role = default_role
        if not ticker:
            continue
        out[ticker] = {
            "role": role,
            "is_candidate": True,
            "quantity": 0,
            "avg_cost": 0,
            "currency": "USD",
        }
    return out


def parse_cash_input(raw: Optional[str]) -> CashHoldings:
    """Parse the ``--cash`` flag into a ``CashHoldings`` snapshot.

    Format: ``"MEP=3000,CABLE=1500,ARS=750000"``. Keys are case-insensitive;
    only ``MEP``, ``CABLE``, ``ARS`` are recognised. Comma is reserved as
    the entry separator — decimals MUST use period (e.g. ``MEP=3000.50``).
    """
    if not raw:
        return CashHoldings()

    mep = 0.0
    cable = 0.0
    ars = 0.0
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ValueError(
                f"Invalid --cash entry '{chunk}'; expected format KEY=VALUE."
            )
        key, value = chunk.split("=", 1)
        key = key.strip().upper()
        value = value.strip()
        try:
            amount = float(value)
        except ValueError as e:
            raise ValueError(
                f"Invalid amount '{value}' for currency '{key}'."
            ) from e
        if amount < 0:
            raise ValueError(f"Negative cash amount '{value}' for {key}.")
        if key == "MEP":
            mep = amount
        elif key == "CABLE":
            cable = amount
        elif key == "ARS":
            ars = amount
        else:
            raise ValueError(
                f"Unknown currency '{key}' in --cash; expected MEP, CABLE, or ARS."
            )
    return CashHoldings(mep_usd=mep, cable_usd=cable, ars_native=ars)


def get_portfolio_date() -> str:
    """Prompt for an analysis date; defaults to today."""
    today = datetime.date.today().isoformat()
    import re

    def validate_date(s: str) -> bool:
        if not s:
            return True
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return False
        try:
            datetime.datetime.strptime(s, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    date = questionary.text(
        f"Analysis date (YYYY-MM-DD, blank = today {today}):",
        validate=lambda x: validate_date(x.strip())
        or "Please enter a valid date in YYYY-MM-DD format.",
    ).ask()

    if date is None:
        console.print("\n[red]No date provided. Exiting...[/red]")
        exit(1)

    return date.strip() or today


def get_analysis_date() -> str:
    """Prompt the user to enter a date in YYYY-MM-DD format."""
    import re
    from datetime import datetime

    def validate_date(date_str: str) -> bool:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return False
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    date = questionary.text(
        "Enter the analysis date (YYYY-MM-DD):",
        validate=lambda x: validate_date(x.strip())
        or "Please enter a valid date in YYYY-MM-DD format.",
        style=questionary.Style(
            [
                ("text", "fg:green"),
                ("highlighted", "noinherit"),
            ]
        ),
    ).ask()

    if not date:
        console.print("\n[red]No date provided. Exiting...[/red]")
        exit(1)

    return date.strip()


def select_analysts() -> List[AnalystType]:
    """Select analysts using an interactive checkbox."""
    choices = questionary.checkbox(
        "Select Your [Analysts Team]:",
        choices=[
            questionary.Choice(display, value=value) for display, value in ANALYST_ORDER
        ],
        instruction="\n- Press Space to select/unselect analysts\n- Press 'a' to select/unselect all\n- Press Enter when done",
        validate=lambda x: len(x) > 0 or "You must select at least one analyst.",
        style=questionary.Style(
            [
                ("checkbox-selected", "fg:green"),
                ("selected", "fg:green noinherit"),
                ("highlighted", "noinherit"),
                ("pointer", "noinherit"),
            ]
        ),
    ).ask()

    if not choices:
        console.print("\n[red]No analysts selected. Exiting...[/red]")
        exit(1)

    return choices


def select_research_depth() -> int:
    """Select research depth using an interactive selection."""

    # Define research depth options with their corresponding values
    DEPTH_OPTIONS = [
        ("Shallow - Quick research, few debate and strategy discussion rounds", 1),
        ("Medium - Middle ground, moderate debate rounds and strategy discussion", 3),
        ("Deep - Comprehensive research, in depth debate and strategy discussion", 5),
    ]

    choice = questionary.select(
        "Select Your [Research Depth]:",
        choices=[
            questionary.Choice(display, value=value) for display, value in DEPTH_OPTIONS
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
        style=questionary.Style(
            [
                ("selected", "fg:yellow noinherit"),
                ("highlighted", "fg:yellow noinherit"),
                ("pointer", "fg:yellow noinherit"),
            ]
        ),
    ).ask()

    if choice is None:
        console.print("\n[red]No research depth selected. Exiting...[/red]")
        exit(1)

    return choice


def select_shallow_thinking_agent(provider) -> str:
    """Select shallow thinking llm engine using an interactive selection."""

    # Define shallow thinking llm engine options with their corresponding model names
    SHALLOW_AGENT_OPTIONS = {
        "openai": [
            ("GPT-4o-mini - Fast and efficient for quick tasks", "gpt-4o-mini"),
            ("GPT-4.1-nano - Ultra-lightweight model for basic operations", "gpt-4.1-nano"),
            ("GPT-4.1-mini - Compact model with good performance", "gpt-4.1-mini"),
            ("GPT-4o - Standard model with solid capabilities", "gpt-4o"),
        ],
        "anthropic": [
            ("Claude Haiku 3.5 - Fast inference and standard capabilities", "claude-3-5-haiku-latest"),
            ("Claude Sonnet 3.5 - Highly capable standard model", "claude-3-5-sonnet-latest"),
            ("Claude Sonnet 3.7 - Exceptional hybrid reasoning and agentic capabilities", "claude-3-7-sonnet-latest"),
            ("Claude Sonnet 4 - High performance and excellent reasoning", "claude-sonnet-4-0"),
        ],
        "google": [
            ("Gemini 3.0 Flash Preview - Latest fast model (recommended)", "gemini-3-flash-preview"),
            ("Gemini 2.0 Flash-Lite - Cost efficiency and low latency", "gemini-2.0-flash-lite"),
            ("Gemini 2.0 Flash - Next generation features, speed, and thinking", "gemini-2.0-flash"),
            ("Gemini 2.5 Flash - Adaptive thinking, cost efficiency", "gemini-2.5-flash-preview-05-20"),
        ],
        "openrouter": [
            ("Meta: Llama 4 Scout", "meta-llama/llama-4-scout:free"),
            ("Meta: Llama 3.3 8B Instruct - A lightweight and ultra-fast variant of Llama 3.3 70B", "meta-llama/llama-3.3-8b-instruct:free"),
            ("google/gemini-2.0-flash-exp:free - Gemini Flash 2.0 offers a significantly faster time to first token", "google/gemini-2.0-flash-exp:free"),
        ],
        "ollama": [
            ("llama3.1 local", "llama3.1"),
            ("llama3.2 local", "llama3.2"),
        ]
    }

    choice = questionary.select(
        "Select Your [Quick-Thinking LLM Engine]:",
        choices=[
            questionary.Choice(display, value=value)
            for display, value in SHALLOW_AGENT_OPTIONS[provider.lower()]
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
        style=questionary.Style(
            [
                ("selected", "fg:magenta noinherit"),
                ("highlighted", "fg:magenta noinherit"),
                ("pointer", "fg:magenta noinherit"),
            ]
        ),
    ).ask()

    if choice is None:
        console.print(
            "\n[red]No shallow thinking llm engine selected. Exiting...[/red]"
        )
        exit(1)

    return choice


def select_deep_thinking_agent(provider) -> str:
    """Select deep thinking llm engine using an interactive selection."""

    # Define deep thinking llm engine options with their corresponding model names
    DEEP_AGENT_OPTIONS = {
        "openai": [
            ("GPT-4.1-nano - Ultra-lightweight model for basic operations", "gpt-4.1-nano"),
            ("GPT-4.1-mini - Compact model with good performance", "gpt-4.1-mini"),
            ("GPT-4o - Standard model with solid capabilities", "gpt-4o"),
            ("o4-mini - Specialized reasoning model (compact)", "o4-mini"),
            ("o3-mini - Advanced reasoning model (lightweight)", "o3-mini"),
            ("o3 - Full advanced reasoning model", "o3"),
            ("o1 - Premier reasoning and problem-solving model", "o1"),
        ],
        "anthropic": [
            ("Claude Haiku 3.5 - Fast inference and standard capabilities", "claude-3-5-haiku-latest"),
            ("Claude Sonnet 3.5 - Highly capable standard model", "claude-3-5-sonnet-latest"),
            ("Claude Sonnet 3.7 - Exceptional hybrid reasoning and agentic capabilities", "claude-3-7-sonnet-latest"),
            ("Claude Sonnet 4 - High performance and excellent reasoning", "claude-sonnet-4-0"),
            ("Claude Opus 4 - Most powerful Anthropic model", "	claude-opus-4-0"),
        ],
        "google": [
            ("Gemini 3.0 Flash Preview - Latest fast model (recommended)", "gemini-3-flash-preview"),
            ("Gemini 2.5 Flash - Adaptive thinking, cost efficiency", "gemini-2.5-flash-preview-05-20"),
            ("Gemini 3.1 Pro Preview", "gemini-3.1-pro-preview"),
            ("Gemini 2.5 Pro", "gemini-2.5-pro-preview-06-05"),
        ],
        "openrouter": [
            ("DeepSeek V3 - a 685B-parameter, mixture-of-experts model", "deepseek/deepseek-chat-v3-0324:free"),
            ("Deepseek - latest iteration of the flagship chat model family from the DeepSeek team.", "deepseek/deepseek-chat-v3-0324:free"),
        ],
        "ollama": [
            ("llama3.1 local", "llama3.1"),
            ("qwen3", "qwen3"),
        ]
    }
    
    choice = questionary.select(
        "Select Your [Deep-Thinking LLM Engine]:",
        choices=[
            questionary.Choice(display, value=value)
            for display, value in DEEP_AGENT_OPTIONS[provider.lower()]
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
        style=questionary.Style(
            [
                ("selected", "fg:magenta noinherit"),
                ("highlighted", "fg:magenta noinherit"),
                ("pointer", "fg:magenta noinherit"),
            ]
        ),
    ).ask()

    if choice is None:
        console.print("\n[red]No deep thinking llm engine selected. Exiting...[/red]")
        exit(1)

    return choice

def select_llm_provider() -> tuple[str, str]:
    """Select the LLM Provider using interactive selection."""
    BASE_URLS = [
        ("Google", "https://generativelanguage.googleapis.com/v1"),
        ("OpenAI", "https://api.openai.com/v1"),
        ("Anthropic", "https://api.anthropic.com/"),
        ("Openrouter", "https://openrouter.ai/api/v1"),
        ("Ollama", "http://localhost:11434/v1"),
    ]
    
    choice = questionary.select(
        "Select your LLM Provider:",
        choices=[
            questionary.Choice(display, value=(display, value))
            for display, value in BASE_URLS
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
        style=questionary.Style(
            [
                ("selected", "fg:magenta noinherit"),
                ("highlighted", "fg:magenta noinherit"),
                ("pointer", "fg:magenta noinherit"),
            ]
        ),
    ).ask()
    
    if choice is None:
        console.print("\n[red]no LLM Provider selected. Exiting...[/red]")
        exit(1)
    
    display_name, url = choice
    print(f"You selected: {display_name}\tURL: {url}")
    
    return display_name, url
