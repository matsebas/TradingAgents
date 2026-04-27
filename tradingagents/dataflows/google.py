from typing import Annotated

from .googlenews_utils import getNewsData
from .utils import normalize_date


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