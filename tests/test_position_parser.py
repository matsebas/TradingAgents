"""Tests for the position CSV parser used by the portfolio feature."""

import os
import sys
import tempfile
import textwrap

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tradingagents.dataflows.position_parser import (
    ParsedPosition,
    parse_positions_csv,
)


SAMPLE_CSV = textwrap.dedent(
    """\
    descripcion_comitente_completa;descripcion_tipo_especie;abreviatura_instrumento;descripcion_instrumento;pppc_mep
    11854 - FOO;CEDEARS;AMZN;CEDEAR AMAZON.COM, INC;1.5291283721191364
    11854 - FOO;CEDEARS;NVDA;CEDEAR NVIDIA CORPORATION;7.7248440614058710
    11854 - FOO;CEDEARS;IBIT.BA;CEDEAR ISHARES BITCOIN TR;3.9636149454763130
    11854 - FOO;CEDEARS;NVDA;CEDEAR NVIDIA CORPORATION;7.7248440614058710
    11854 - FOO;Fondos;25518;MAX RENTA FIJA DOLARES FCI Clase C Cable;1.0971586270283110
    11854 - FOO;Bonos;AL30;BONO AL30;0.0
    """
)


@pytest.fixture
def sample_csv_path():
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        f.write(SAMPLE_CSV)
        path = f.name
    yield path
    os.unlink(path)


def test_parses_cedears_by_default(sample_csv_path):
    positions = parse_positions_csv(sample_csv_path)
    tickers = [p.ticker for p in positions]
    assert tickers == ["AMZN", "NVDA", "IBIT"]


def test_dedupes_preserving_first_occurrence(sample_csv_path):
    positions = parse_positions_csv(sample_csv_path)
    assert len(positions) == 3
    assert [p.ticker for p in positions].count("NVDA") == 1


def test_strips_ba_suffix(sample_csv_path):
    positions = parse_positions_csv(sample_csv_path)
    tickers = [p.ticker for p in positions]
    assert "IBIT" in tickers
    assert "IBIT.BA" not in tickers


def test_filters_out_fondos_by_default(sample_csv_path):
    positions = parse_positions_csv(sample_csv_path)
    tickers = [p.ticker for p in positions]
    assert "25518" not in tickers
    assert "AL30" not in tickers


def test_custom_types_filter(sample_csv_path):
    positions = parse_positions_csv(sample_csv_path, types=["Bonos"])
    tickers = [p.ticker for p in positions]
    assert tickers == ["AL30"]


def test_multiple_types(sample_csv_path):
    positions = parse_positions_csv(sample_csv_path, types=["CEDEARS", "Bonos"])
    tickers = [p.ticker for p in positions]
    assert set(tickers) == {"AMZN", "NVDA", "IBIT", "AL30"}


def test_returns_parsed_position_with_type(sample_csv_path):
    positions = parse_positions_csv(sample_csv_path)
    assert all(isinstance(p, ParsedPosition) for p in positions)
    assert positions[0].instrument_type == "CEDEARS"


def test_case_insensitive_type_matching(sample_csv_path):
    positions = parse_positions_csv(sample_csv_path, types=["cedears"])
    assert len(positions) == 3


def test_raises_on_missing_file():
    with pytest.raises(FileNotFoundError):
        parse_positions_csv("/nonexistent/path.csv")


def test_raises_on_missing_ticker_column(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("col_a;col_b\n1;2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="abreviatura_instrumento"):
        parse_positions_csv(str(bad))


def test_supports_comma_separator(tmp_path):
    csv = tmp_path / "comma.csv"
    csv.write_text(
        "descripcion_tipo_especie,abreviatura_instrumento\nCEDEARS,AAPL\nCEDEARS,MSFT\n",
        encoding="utf-8",
    )
    positions = parse_positions_csv(str(csv))
    assert [p.ticker for p in positions] == ["AAPL", "MSFT"]


def test_parses_pppc_column_when_present(sample_csv_path):
    positions = parse_positions_csv(sample_csv_path)
    by_ticker = {p.ticker: p for p in positions}
    # AMZN has pppc 1.5291... — positive, so we keep it.
    assert by_ticker["AMZN"].pppc is not None
    assert abs(by_ticker["AMZN"].pppc - 1.5291283721191364) < 1e-9
    assert abs(by_ticker["NVDA"].pppc - 7.7248440614058710) < 1e-9


def test_pppc_is_none_when_column_missing(tmp_path):
    csv = tmp_path / "no_pppc.csv"
    csv.write_text(
        "descripcion_tipo_especie;abreviatura_instrumento\nCEDEARS;AAPL\n",
        encoding="utf-8",
    )
    positions = parse_positions_csv(str(csv))
    assert positions[0].pppc is None


def test_pppc_zero_or_malformed_is_treated_as_unknown(tmp_path):
    csv = tmp_path / "bad_pppc.csv"
    csv.write_text(
        "descripcion_tipo_especie;abreviatura_instrumento;pppc_mep\n"
        "CEDEARS;AAPL;0.0\n"
        "CEDEARS;MSFT;not-a-number\n"
        "CEDEARS;GOOGL;\n",
        encoding="utf-8",
    )
    positions = parse_positions_csv(str(csv))
    assert all(p.pppc is None for p in positions)


def test_parses_quantity_and_unrealized_return_pct(tmp_path):
    csv = tmp_path / "full.csv"
    csv.write_text(
        "descripcion_tipo_especie;abreviatura_instrumento;total;pppc_mep;rendimiento_pct_mep\n"
        "CEDEARS;SMH;263,0;8.12;0.2190\n"
        "CEDEARS;AMZN;1,0;1.53;0.1987\n"
        "CEDEARS;SPY;66,0;33.72;0.0941\n",
        encoding="utf-8",
    )
    by_ticker = {p.ticker: p for p in parse_positions_csv(str(csv))}
    assert by_ticker["SMH"].quantity == 263.0
    assert by_ticker["AMZN"].quantity == 1.0
    assert abs(by_ticker["SMH"].unrealized_return_pct - 0.219) < 1e-9
    assert abs(by_ticker["SPY"].unrealized_return_pct - 0.0941) < 1e-9


def test_quantity_and_return_pct_default_to_none_when_columns_missing(tmp_path):
    csv = tmp_path / "narrow.csv"
    csv.write_text(
        "descripcion_tipo_especie;abreviatura_instrumento\nCEDEARS;AAPL\n",
        encoding="utf-8",
    )
    p = parse_positions_csv(str(csv))[0]
    assert p.quantity is None
    assert p.unrealized_return_pct is None
