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
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_TYPES = ("CEDEARS",)
TICKER_COLUMN = "abreviatura_instrumento"
TYPE_COLUMN = "descripcion_tipo_especie"
PPPC_COLUMN = "pppc_mep"  # weighted-average cost in MEP (USD equivalent)
QUANTITY_COLUMN = "total"  # number of units held (CEDEARs / shares / etc.)
# Unrealized return as a fraction (e.g. 0.2190 = +21.90%). Ratio-invariant,
# so reliable even when PPPC is expressed in CEDEAR units.
RETURN_PCT_COLUMN = "rendimiento_pct_mep"


@dataclass(frozen=True)
class ParsedPosition:
    ticker: str
    instrument_type: str
    pppc: float | None = None  # weighted-average purchase price (in row currency)
    quantity: float | None = None
    unrealized_return_pct: float | None = None  # fraction, not percent points


def _parse_number(raw: str | None) -> float | None:
    """Parse a number that may use ``,`` or ``.`` as the decimal separator."""
    if raw is None:
        return None
    text = raw.strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_pppc(raw: str | None) -> float | None:
    value = _parse_number(raw)
    # Treat 0 (missing cost) as "unknown" so downstream code can skip it.
    return value if value and value > 0 else None


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
        fieldnames = reader.fieldnames or ()
        has_pppc_column = PPPC_COLUMN in fieldnames
        has_qty_column = QUANTITY_COLUMN in fieldnames
        has_return_column = RETURN_PCT_COLUMN in fieldnames

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
            pppc = _parse_pppc(row.get(PPPC_COLUMN)) if has_pppc_column else None
            qty = _parse_number(row.get(QUANTITY_COLUMN)) if has_qty_column else None
            if qty is not None and qty <= 0:
                qty = None
            ret_pct = _parse_number(row.get(RETURN_PCT_COLUMN)) if has_return_column else None
            out.append(
                ParsedPosition(
                    ticker=ticker,
                    instrument_type=instrument_type,
                    pppc=pppc,
                    quantity=qty,
                    unrealized_return_pct=ret_pct,
                )
            )

    return out


def summarize_positions_csv(path: str | Path) -> dict:
    """Return diagnostics about a positions CSV without applying the type filter.

    Used by the CLI to produce a helpful error when ``parse_positions_csv``
    returns nothing (e.g. the file only contains ``Fondos`` but the user
    passed ``--types CEDEARS``). Result schema::

        {
            "total_rows": int,
            "rows_by_type": {type_label: count, ...},
            "has_type_column": bool,
        }
    """
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Positions file not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8") as f:
        sample = f.read(4096)
        f.seek(0)
        sep = _detect_separator(sample)
        reader = csv.DictReader(f, delimiter=sep)

        fieldnames = reader.fieldnames or ()
        has_type_column = TYPE_COLUMN in fieldnames

        counts: Counter[str] = Counter()
        total = 0
        for row in reader:
            total += 1
            if has_type_column:
                t = (row.get(TYPE_COLUMN, "") or "").strip() or "(blank)"
                counts[t] += 1

    return {
        "total_rows": total,
        "rows_by_type": dict(counts),
        "has_type_column": has_type_column,
    }
