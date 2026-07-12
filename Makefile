PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: install test lint format monitor dry-run dashboard validate-sources lock

install:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.lock
	$(BIN)/pip install -e . --no-deps

test:
	$(BIN)/pytest

lint:
	$(BIN)/ruff check job_monitor tests
	$(BIN)/ruff format --check job_monitor tests

format:
	$(BIN)/ruff format job_monitor tests
	$(BIN)/ruff check --fix job_monitor tests

monitor:
	$(BIN)/python -m job_monitor

dry-run:
	$(BIN)/python -m job_monitor --dry-run

validate-sources:
	$(BIN)/python -m job_monitor validate-sources

dashboard:
	@echo "Serving dashboard at http://localhost:8000/"
	cd docs && $(PYTHON) -m http.server 8000

lock:
	$(BIN)/pip freeze --exclude-editable > requirements.lock
