"""
Gemini data vendor implementation using Google's Generative AI.

Updated to use google.genai (the new official library).
"""

from google import genai
from google.genai import types
from .config import get_config


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

