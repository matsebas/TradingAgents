VENV := .venv/bin
PYTHON := $(VENV)/python
PYTEST := $(VENV)/pytest

# Optional overrides for portfolio targets
POSITIONS ?=
TICKERS ?=
DATE ?=
TYPES ?= CEDEARS
MAX_CONCURRENCY ?= 10

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

## Portfolio from a positions CSV (usage: make portfolio-positions POSITIONS=/path/to/file.csv [DATE=YYYY-MM-DD])
portfolio-positions:
	@if [ -z "$(POSITIONS)" ]; then echo "Error: POSITIONS=/path/to/file.csv is required"; exit 1; fi
	$(PYTHON) -m cli.main portfolio \
	    --positions "$(POSITIONS)" \
	    --types "$(TYPES)" \
	    --max-concurrency $(MAX_CONCURRENCY) \
	    $(if $(DATE),--date $(DATE),)

## Portfolio from a comma-separated ticker list (usage: make portfolio-tickers TICKERS=NVDA,AMZN [DATE=YYYY-MM-DD])
portfolio-tickers:
	@if [ -z "$(TICKERS)" ]; then echo "Error: TICKERS=NVDA,AMZN is required"; exit 1; fi
	$(PYTHON) -m cli.main portfolio \
	    --tickers "$(TICKERS)" \
	    --max-concurrency $(MAX_CONCURRENCY) \
	    $(if $(DATE),--date $(DATE),)

## Run the main_portfolio.py example script
portfolio-example:
	$(PYTHON) main_portfolio.py
