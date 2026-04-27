from datetime import timedelta
from typing import Annotated

from .googlenews_utils import getNewsData
from .utils import normalize_date, parse_date


def get_google_news(
    query: Annotated[str, "Query to search with"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Scrape Google News for ``query`` between ``start_date`` and ``end_date``.

    Signature matches every other ``get_news`` vendor so the central router
    in :mod:`tradingagents.dataflows.interface` can call them all with the
    same positional args.
    """
    query = query.replace(" ", "+")
    start_date = normalize_date(start_date, field_name="start_date")
    end_date = normalize_date(end_date, field_name="end_date")

    news_results = getNewsData(query, start_date, end_date)

    if not news_results:
        return ""

    news_str = "".join(
        f"### {n['title']} (source: {n['source']}) \n\n{n['snippet']}\n\n"
        for n in news_results
    )
    return (
        f"## {query} Google News, from {start_date} to {end_date}:\n\n{news_str}"
    )


# Generic query used for the global-news call. Broad enough to surface
# market-moving macro headlines across asset classes.
_GLOBAL_NEWS_QUERY = "global markets macroeconomics financial news"


def get_global_news_google(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int, "Number of days to look back"] = 7,
    limit: Annotated[int, "Maximum number of articles to return"] = 5,
) -> str:
    """Scrape Google News for global macro headlines in the last ``look_back_days``.

    Signature mirrors :func:`get_global_news_gemini` /
    :func:`get_global_news_openai` so the router can swap them.
    """
    end_date = normalize_date(curr_date, field_name="curr_date")
    start = parse_date(end_date) - timedelta(days=int(look_back_days))
    start_date = start.strftime("%Y-%m-%d")

    news_results = getNewsData(
        _GLOBAL_NEWS_QUERY.replace(" ", "+"), start_date, end_date
    )
    if not news_results:
        return ""

    selected = news_results[: int(limit)]
    body = "".join(
        f"### {n['title']} (source: {n['source']}) \n\n{n['snippet']}\n\n"
        for n in selected
    )
    return (
        f"## Global Markets News, from {start_date} to {end_date}:\n\n{body}"
    )