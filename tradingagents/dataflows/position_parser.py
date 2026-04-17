"""Parse broker position reports (CSV) into tickers ready for analysis.

Designed around the column layout used by local LATAM brokers that export
CEDEAR positions (separator ``;``), but works with plain comma-separated
files as well.

Only rows whose ``descripcion_tipo_especie`` matches the configured types
(default: ``CEDEARS``) are returned. Tickers with a ``.BA`` suffix are
normalised to their US equivalent so that downstream data vendors hit the
correct security.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_TYPES = ("CEDEARS",)
TICKER_COLUMN = "abreviatura_instrumento"
TYPE_COLUMN = "descripcion_tipo_especie"


@dataclass(frozen=True)
class ParsedPosition:
    ticker: str
    instrument_type: str


def _detect_separator(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        return dialect.delimiter
    except csv.Error:
        return ";" if sample.count(";") >= sample.count(",") else ","


def _normalise_ticker(raw: str) -> str:
    ticker = raw.strip().upper()
    if ticker.endswith(".BA"):
        ticker = ticker[:-3]
    return ticker


def parse_positions_csv(
    path: str | Path,
    types: Iterable[str] | None = None,
) -> list[ParsedPosition]:
    """Return deduplicated positions whose instrument type matches ``types``.

    Order is preserved based on first occurrence in the file.
    """
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Positions file not found: {csv_path}")

    allowed = {t.strip().lower() for t in (types or DEFAULT_TYPES)}

    with csv_path.open("r", encoding="utf-8") as f:
        sample = f.read(4096)
        f.seek(0)
        sep = _detect_separator(sample)
        reader = csv.DictReader(f, delimiter=sep)

        if reader.fieldnames is None or TICKER_COLUMN not in reader.fieldnames:
            raise ValueError(
                f"CSV is missing required column '{TICKER_COLUMN}'. "
                f"Found columns: {reader.fieldnames}"
            )
        has_type_column = TYPE_COLUMN in reader.fieldnames

        seen: set[str] = set()
        out: list[ParsedPosition] = []
        for row in reader:
            instrument_type = (row.get(TYPE_COLUMN, "") or "").strip() if has_type_column else ""
            if has_type_column and instrument_type.lower() not in allowed:
                continue

            raw_ticker = row.get(TICKER_COLUMN, "") or ""
            ticker = _normalise_ticker(raw_ticker)
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            out.append(ParsedPosition(ticker=ticker, instrument_type=instrument_type))

    return out
