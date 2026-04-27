"""
Gemini data vendor implementation using Google's Generative AI.

Updated to use google.genai (the new official library).

All public functions wrap the SDK call in a tenacity retry that fires only
on transient ``RESOURCE_EXHAUSTED`` (429) errors. The SDK does NOT retry
automatically. Daily-quota exhaustion is unrecoverable — those errors will
still propagate after the retry window.
"""

from google import genai
from google.genai import types
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)
import logging

from .config import get_config


_logger = logging.getLogger(__name__)


def _is_rate_limited(exc: BaseException) -> bool:
    """Return True for transient 429 errors so tenacity retries them."""
    msg = str(exc)
    return "429" in msg or "RESOURCE_EXHAUSTED" in msg


# Retry policy applied to every Gemini call below. 4 attempts, exponential
# backoff with jitter starting at 4s and capped at 30s. Only retries on
# 429/RESOURCE_EXHAUSTED — other errors fail fast so the router falls back
# to the next vendor.
_gemini_retry = retry(
    retry=retry_if_exception(_is_rate_limited),
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=4, max=30, jitter=2),
    before_sleep=before_sleep_log(_logger, logging.WARNING),
    reraise=True,
)


@_gemini_retry
def get_stock_news_gemini(query, start_date, end_date):
    """Get stock news from Gemini with Google Search grounding."""
    config = get_config()
    client = genai.Client(api_key=config.get("gemini_api_key"))

    prompt = f"Can you search Social Media for {query} from {start_date} to {end_date}? Make sure you only get the data posted during that period."

    response = client.models.generate_content(
        model=config.get("gemini_model", "gemini-3-flash-preview"),
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=1.0,
            max_output_tokens=4096,
            top_p=1.0,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )
    )

    return response.text


@_gemini_retry
def get_global_news_gemini(curr_date, look_back_days=7, limit=5):
    """Get global news from Gemini with Google Search grounding."""
    config = get_config()
    client = genai.Client(api_key=config.get("gemini_api_key"))

    prompt = f"Can you search global or macroeconomics news from {look_back_days} days before {curr_date} to {curr_date} that would be informative for trading purposes? Make sure you only get the data posted during that period. Limit the results to {limit} articles."

    response = client.models.generate_content(
        model=config.get("gemini_model", "gemini-3-flash-preview"),
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=1.0,
            max_output_tokens=4096,
            top_p=1.0,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )
    )

    return response.text


@_gemini_retry
def get_fundamentals_gemini(ticker, curr_date):
    """Get fundamental data from Gemini with Google Search grounding."""
    config = get_config()
    client = genai.Client(api_key=config.get("gemini_api_key"))

    prompt = f"Can you search Fundamental for discussions on {ticker} during of the month before {curr_date} to the month of {curr_date}. Make sure you only get the data posted during that period. List as a table, with PE/PS/Cash flow/ etc"

    response = client.models.generate_content(
        model=config.get("gemini_model", "gemini-3-flash-preview"),
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=1.0,
            max_output_tokens=4096,
            top_p=1.0,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )
    )

    return response.text
