# Convenience targets for Poppet development.
#
# This file uses tab indentation (Makefiles require it).

PY ?= .venv/Scripts/python.exe

.PHONY: help install dev test lint format build smoke probe clean release-test release-prod

help:
	@echo "Common targets:"
	@echo "  make install        — pip install -e ."
	@echo "  make dev            — pip install -e .[dev]"
	@echo "  make test           — run pytest"
	@echo "  make lint           — ruff check"
	@echo "  make format         — ruff format + check --fix"
	@echo "  make build          — python -m build (wheel + sdist)"
	@echo "  make smoke          — scripts/mcp_smoke_test.py (stdio MCP handshake)"
	@echo "  make probe          — ping Cascadeur's script server (needs it running)"
	@echo "  make clean          — wipe build/, dist/, *.egg-info"

install:
	$(PY) -m pip install -e .

dev:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest tests/ -v -p no:cacheprovider

lint:
	$(PY) -m ruff check src/ tests/ scripts/

format:
	$(PY) -m ruff format src/ tests/ scripts/
	$(PY) -m ruff check --fix src/ tests/ scripts/

build:
	$(PY) -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('build', 'dist')]"
	$(PY) -m build --wheel --sdist
	$(PY) -m twine check dist/*

smoke:
	$(PY) scripts/mcp_smoke_test.py

probe:
	$(PY) -m poppet_mcp.cascadeur_connection

clean:
	$(PY) -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('build', 'dist', '.pytest_cache', '.ruff_cache')]"

release-test:
	bash scripts/publish.sh test

release-prod:
	bash scripts/publish.sh prod
