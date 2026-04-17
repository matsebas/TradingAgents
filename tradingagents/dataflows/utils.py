import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Annotated

import pandas as pd


_DATE_RE = re.compile(r"(\d{4}-\d{1,2}-\d{1,2})")


def normalize_date(value: str, *, field_name: str = "date") -> str:
    """Return a clean ``YYYY-MM-DD`` string, tolerating common LLM mistakes.

    LLM tool calls sometimes mangle arguments (e.g. concatenating the next
    kwarg into the date value: ``"2026-04-17,indicator:macd"``). Rather than
    letting the raw ``strptime`` blow up and bubbling a cryptic error through
    the vendor fallback chain, this helper extracts the first valid
    ``YYYY-MM-DD`` substring and validates it. Callers that hold a clean
    string pay no cost beyond the regex match.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if not isinstance(value, str):
        raise TypeError(
            f"{field_name} must be a string or date, got {type(value).__name__}"
        )

    stripped = value.strip()
    match = _DATE_RE.search(stripped)
    if match is None:
        raise ValueError(f"{field_name} has no YYYY-MM-DD component: {value!r}")

    candidate = match.group(1)
    # Re-parse to validate calendar correctness (catches 2026-13-40 etc.).
    try:
        parsed = datetime.strptime(candidate, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(
            f"{field_name} is not a valid calendar date: {candidate!r}"
        ) from exc
    return parsed.strftime("%Y-%m-%d")


def parse_date(value: str, *, field_name: str = "date") -> datetime:
    """Normalise + parse in one shot. Returns a naive ``datetime``."""
    return datetime.strptime(normalize_date(value, field_name=field_name), "%Y-%m-%d")


SavePathType = Annotated[str, "File path to save data. If None, data is not saved."]

def save_output(data: pd.DataFrame, tag: str, save_path: SavePathType = None) -> None:
    if save_path:
        data.to_csv(save_path)
        print(f"{tag} saved to {save_path}")


def get_current_date():
    return date.today().strftime("%Y-%m-%d")


def decorate_all_methods(decorator):
    def class_decorator(cls):
        for attr_name, attr_value in cls.__dict__.items():
            if callable(attr_value):
                setattr(cls, attr_name, decorator(attr_value))
        return cls

    return class_decorator


def get_next_weekday(d):
    if not isinstance(d, datetime):
        d = parse_date(d)

    if d.weekday() >= 5:
        days_to_add = 7 - d.weekday()
        return d + timedelta(days=days_to_add)
    return d
