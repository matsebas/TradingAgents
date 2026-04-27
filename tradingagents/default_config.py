import os

DEFAULT_CONFIG = {
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", "./results"),
    "data_dir": "./data",
    "data_cache_dir": os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "dataflows/data_cache",
    ),
    # LLM settings
    "llm_provider": "google",
    "deep_think_llm": "gemini-3-flash-preview",
    "quick_think_llm": "gemini-3-flash-preview",
    # Lighter models for tasks that don't need full Flash:
    # - analyst_llm: the 4 analysts (Market/Social/News/Fundamentals) which
    #   mostly summarise tool output.
    # - mechanical_llm: signal processor + reflector — pure pattern extraction.
    # If unset, both fall back to quick_think_llm.
    "analyst_llm": "gemini-3.1-flash-lite-preview",
    "mechanical_llm": "gemini-3.1-flash-lite-preview",
    "backend_url": "https://api.openai.com/v1",  # Not used for Google provider
    # Gemini settings
    "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
    "gemini_model": "gemini-3-flash-preview",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: yfinance, alpha_vantage, local
        "technical_indicators": "yfinance",  # Options: yfinance, alpha_vantage, local
        "fundamental_data": "yfinance",      # Options: yfinance, gemini, openai, alpha_vantage, local
        "news_data": "google",               # Options: google, gemini, openai, alpha_vantage, local
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
        # Example: "get_news": "openai",               # Override category default
    },
}
