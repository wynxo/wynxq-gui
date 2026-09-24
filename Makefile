# Wynxq — a local AI workbench for Linux
.PHONY: help install test lint format type-check clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install in development mode
	python3 -m venv .venv
	.venv/bin/pip install -e . pytest
	.venv/bin/pip install ruff mypy pre-commit
	.venv/bin/pre-commit install

test: ## Run tests
	QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q

test-all: ## Run all tests including dock controller
	QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q

lint: ## Lint with ruff
	.venv/bin/ruff check wynxq install.py

format: ## Format with ruff
	.venv/bin/ruff format wynxq install.py

format-check: ## Check formatting
	.venv/bin/ruff format --check wynxq install.py

type-check: ## Type check with mypy
	.venv/bin/mypy wynxq --ignore-missing-imports

smoke-test: ## Run GUI smoke test
	QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software .venv/bin/python -m wynxq --smoke-test

screenshots: ## Render demo screenshots
	QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
		.venv/bin/python -m wynxq --snapshot docs/screenshots

clean: ## Clean build artifacts
	rm -rf .venv build dist *.egg-info
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
