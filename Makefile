VENV := .venv/bin
PYTHON := $(VENV)/python
PYTEST := $(VENV)/pytest

# Optional overrides for portfolio targets
POSITIONS ?=
TICKERS ?=
DATE ?=
TYPES ?= CEDEARS
# 5 keeps Gemini under its per-minute quota for typical 5-10 ticker portfolios.
# Bump only with a higher-tier key — concurrency=10 has hit 429s in practice.
MAX_CONCURRENCY ?= 5
# Candidate evaluation: tickers to consider INITIATING (not yet held).
# Optional ':role' suffix per ticker, e.g. "NVO:tactical,GOOGL:anchor".
CANDIDATES ?=
# Cash holdings beyond FCI: "MEP=3000,CABLE=1500,ARS=750000". Decimals use '.'.
CASH ?=
# Required only when CASH includes ARS.
ARS_MEP_RATE ?=
ARS_CABLE_RATE ?=
# Broker capabilities override. Comma-separated subset of: gtd, stop_loss, bracket.
# Default in config is "gtd" — set this to override (e.g. "gtd,stop_loss,bracket"
# for brokers with full feature set).
BROKER_FEATURES ?=

.PHONY: cli cli-tab install test test-all portfolio portfolio-positions portfolio-tickers portfolio-example help

## Show available targets
help:
	@grep -E '^## ' -A 1 $(MAKEFILE_LIST) | grep -v -- "^--$$" | sed -E 's/^## /  /; s/^([a-zA-Z_-]+):.*/\1:/'

## Run the interactive CLI (analyze single ticker)
cli:
	$(PYTHON) -m cli.main analyze

## Open the CLI in a new Terminal tab (macOS)
cli-tab:
	osascript -e 'tell application "Terminal" to activate' -e 'tell application "System Events" to keystroke "t" using command down' && sleep 0.3 && osascript -e 'tell application "Terminal" to do script "cd $(CURDIR) && $(PYTHON) -m cli.main analyze" in front window'

## Install dependencies
install:
	$(VENV)/pip install -r requirements.txt

## Run the legacy smoke test (single file)
test:
	$(PYTHON) tests/test.py

## Run the full pytest suite
test-all:
	$(PYTEST) tests/ -v

## Interactive portfolio analysis (prompts for tickers/CSV and date)
portfolio:
	$(PYTHON) -m cli.main portfolio --max-concurrency $(MAX_CONCURRENCY) --types "$(TYPES)"

## Portfolio from a positions CSV (usage: make portfolio-positions POSITIONS=/path/to/file.csv [DATE=YYYY-MM-DD] [CANDIDATES=NVO:tactical,GOOGL:anchor] [CASH=MEP=3000,ARS=750000] [ARS_MEP_RATE=1200])
portfolio-positions:
	@if [ -z "$(POSITIONS)" ]; then echo "Error: POSITIONS=/path/to/file.csv is required"; exit 1; fi
	$(PYTHON) -m cli.main portfolio \
	    --positions "$(POSITIONS)" \
	    --types "$(TYPES)" \
	    --max-concurrency $(MAX_CONCURRENCY) \
	    $(if $(DATE),--date $(DATE),) \
	    $(if $(CANDIDATES),--candidates "$(CANDIDATES)",) \
	    $(if $(CASH),--cash "$(CASH)",) \
	    $(if $(ARS_MEP_RATE),--ars-mep-rate $(ARS_MEP_RATE),) \
	    $(if $(ARS_CABLE_RATE),--ars-cable-rate $(ARS_CABLE_RATE),) \
	    $(if $(BROKER_FEATURES),--broker-features "$(BROKER_FEATURES)",)

## Portfolio from a comma-separated ticker list (usage: make portfolio-tickers TICKERS=NVDA,AMZN [DATE=YYYY-MM-DD])
portfolio-tickers:
	@if [ -z "$(TICKERS)" ]; then echo "Error: TICKERS=NVDA,AMZN is required"; exit 1; fi
	$(PYTHON) -m cli.main portfolio \
	    --tickers "$(TICKERS)" \
	    --max-concurrency $(MAX_CONCURRENCY) \
	    $(if $(DATE),--date $(DATE),) \
	    $(if $(CANDIDATES),--candidates "$(CANDIDATES)",) \
	    $(if $(CASH),--cash "$(CASH)",) \
	    $(if $(ARS_MEP_RATE),--ars-mep-rate $(ARS_MEP_RATE),) \
	    $(if $(ARS_CABLE_RATE),--ars-cable-rate $(ARS_CABLE_RATE),) \
	    $(if $(BROKER_FEATURES),--broker-features "$(BROKER_FEATURES)",)

## Run the main_portfolio.py example script
portfolio-example:
	$(PYTHON) main_portfolio.py
