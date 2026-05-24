# Convenience targets for Poppet development.
#
# This file uses tab indentation (Makefiles require it).

PY ?= .venv/Scripts/python.exe

.PHONY: help install dev test lint format build smoke clean release-test release-prod

help:
	@echo "Common targets:"
	@echo "  make install        — pip install -e ."
	@echo "  make dev            — pip install -e .[dev]"
	@echo "  make test           — run pytest"
	@echo "  make lint           — ruff check"
	@echo "  make format         — ruff format + check --fix"
	@echo "  make build          — python -m build (wheel + sdist)"
	@echo "  make smoke          — scripts/mcp_smoke_test.py"
	@echo "  make clean          — wipe build/, dist/, *.egg-info"
	@echo "  make release-test   — build + upload to TestPyPI"
	@echo "  make release-prod   — build + upload to PyPI"

install:
	$(PY) -m pip install -e .

dev:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest tests/ -v

lint:
	$(PY) -m ruff check src/ cascadeur_side/ tests/ scripts/

format:
	$(PY) -m ruff format src/ cascadeur_side/ tests/ scripts/
	$(PY) -m ruff check --fix src/ cascadeur_side/ tests/ scripts/

build:
	rm -rf build dist *.egg-info
	$(PY) -m build --wheel --sdist
	$(PY) -m twine check dist/*

smoke:
	$(PY) scripts/mcp_smoke_test.py

clean:
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -exec rm -rf {} +

release-test:
	bash scripts/publish.sh test

release-prod:
	bash scripts/publish.sh prod
