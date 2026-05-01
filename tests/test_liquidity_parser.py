"""Tests for the FCI / cash-equivalent parser."""

import os
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.dataflows.liquidity_parser import (
    Liquidity,
    LiquidityItem,
    merge_with_cash,
    parse_liquidity_csv,
)


_HEADER = (
    "descripcion_comitente_completa;descripcion_tipo_especie;abreviatura_instrumento;"
    "descripcion_instrumento;total;valoracion_pesificada_mep;pppc_pesificado_mep;"
    "rendimiento_pct_pesificada_mep;valoracion_mep;pppc_mep;rendimiento_pct_mep"
)


def _row(tipo, ticker, descripcion, valoracion_mep):
    return f"X;{tipo};{ticker};{descripcion};1,0;0;0;0;{valoracion_mep};1.0;0"


def _write_csv(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "positions.csv"
    path.write_text("\n".join([_HEADER, *rows]), encoding="utf-8")
    return path


# --- parse_liquidity_csv -------------------------------------------------


def test_returns_empty_when_no_fondos(tmp_path: Path):
    path = _write_csv(tmp_path, [_row("CEDEARS", "NVDA", "NVIDIA CORP", "1000")])
    liquidity = parse_liquidity_csv(path)
    assert liquidity.items == ()
    assert liquidity.total_money_market_usd == 0
    assert liquidity.total_fixed_income_usd == 0


def test_classifies_money_market_by_description(tmp_path: Path):
    path = _write_csv(
        tmp_path,
        [
            _row("Fondos", "27751", "MAX MONEY MARKET DOLARES Clase A", "6002,18"),
        ],
    )
    liquidity = parse_liquidity_csv(path)
    assert len(liquidity.items) == 1
    item = liquidity.items[0]
    assert item.ticker == "27751"
    assert item.is_money_market is True
    assert abs(item.valoracion_mep_usd - 6002.18) < 0.01
    assert abs(liquidity.total_money_market_usd - 6002.18) < 0.01
    assert liquidity.total_fixed_income_usd == 0


def test_classifies_fixed_income_when_not_money_market(tmp_path: Path):
    path = _write_csv(
        tmp_path,
        [
            _row(
                "Fondos",
                "25516",
                "MAX RENTA FIJA DOLARES FCI Clase A MEP",
                "12696,03",
            ),
        ],
    )
    liquidity = parse_liquidity_csv(path)
    assert liquidity.items[0].is_money_market is False
    assert abs(liquidity.total_fixed_income_usd - 12696.03) < 0.01
    assert liquidity.total_money_market_usd == 0


def test_aggregates_real_csv_shape(tmp_path: Path):
    """Mirror of the user's actual CSV layout (3 FCIs, 1 MM + 2 RF)."""
    path = _write_csv(
        tmp_path,
        [
            _row("CEDEARS", "SMH", "VAN ECK SEMICONDUCTORS", "2136,39"),
            _row("Fondos", "25518", "MAX RENTA FIJA DOLARES Clase C Cable", "10429,77"),
            _row("Fondos", "27751", "MAX MONEY MARKET DOLARES Clase A", "6002,18"),
            _row("Fondos", "25516", "MAX RENTA FIJA DOLARES Clase A MEP", "12696,03"),
        ],
    )
    liquidity = parse_liquidity_csv(path)
    assert len(liquidity.items) == 3  # CEDEAR row excluded
    assert abs(liquidity.total_money_market_usd - 6002.18) < 0.01
    assert abs(liquidity.total_fixed_income_usd - (10429.77 + 12696.03)) < 0.01
    # Without cash, total deployable equals FCI sum
    assert (
        abs(liquidity.total_deployable_usd - (6002.18 + 10429.77 + 12696.03)) < 0.01
    )


def test_skips_rows_with_zero_or_missing_value(tmp_path: Path):
    path = _write_csv(
        tmp_path,
        [
            _row("Fondos", "12345", "MAX MONEY MARKET DOLARES", "0"),
            _row("Fondos", "67890", "MAX MONEY MARKET DOLARES", ""),
        ],
    )
    liquidity = parse_liquidity_csv(path)
    assert liquidity.items == ()


def test_raises_for_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        parse_liquidity_csv(tmp_path / "nope.csv")


# --- merge_with_cash -----------------------------------------------------


def test_merge_layers_cash_on_top():
    base = Liquidity(
        items=(),
        total_money_market_usd=6000.0,
        total_fixed_income_usd=12000.0,
    )
    out = merge_with_cash(
        base,
        cash_mep_usd=3000,
        cash_cable_usd=1500,
        cash_ars_native=600000,
        cash_ars_to_usd_rate=1200,
    )
    # FCI totals preserved
    assert out.total_money_market_usd == 6000.0
    assert out.total_fixed_income_usd == 12000.0
    # Cash exposed
    assert out.cash_mep_usd == 3000
    assert out.cash_cable_usd == 1500
    assert out.cash_ars_native == 600000
    assert out.cash_ars_to_usd_rate == 1200
    # Total = 6k + 12k + 3k + 1.5k + 600k/1200 = 6k+12k+3k+1.5k+500 = 23000
    assert abs(out.total_deployable_usd - 23000.0) < 0.01


def test_merge_excludes_ars_when_rate_missing():
    base = Liquidity(items=(), total_money_market_usd=1000.0)
    out = merge_with_cash(base, cash_ars_native=600000, cash_ars_to_usd_rate=None)
    # ARS stored but not converted into total_deployable
    assert out.cash_ars_native == 600000
    assert out.cash_ars_to_usd_rate is None
    assert out.total_deployable_usd == 1000.0


# --- to_dict -------------------------------------------------------------


def test_to_dict_is_json_friendly():
    import json

    base = Liquidity(
        items=(
            LiquidityItem(
                ticker="27751",
                description="MAX MONEY MARKET DOLARES Clase A",
                valoracion_mep_usd=6002.18,
                is_money_market=True,
            ),
        ),
        total_money_market_usd=6002.18,
        total_fixed_income_usd=0.0,
    )
    json.dumps(base.to_dict())


def test_to_dict_includes_total_deployable_usd():
    base = Liquidity(items=(), total_money_market_usd=1000.0)
    out = merge_with_cash(base, cash_mep_usd=500)
    d = out.to_dict()
    assert d["total_deployable_usd"] == 1500.0
