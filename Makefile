.PHONY: help install install-dev test lint format clean run-api run-watch poetry-install poetry-run poetry-shell

help:
	@echo "FarmCalc - Available commands:"
	@echo ""
	@echo "  make poetry-install    - Install dependencies with Poetry"
	@echo "  make poetry-shell      - Activate Poetry shell"
	@echo "  make install           - Install package in editable mode (pip)"
	@echo "  make install-dev       - Install with dev dependencies (pip)"
	@echo "  make test              - Run tests"
	@echo "  make lint              - Run linter (ruff)"
	@echo "  make format            - Format code (black)"
	@echo "  make clean             - Clean build artifacts"
	@echo "  make run-api           - Run FastAPI server (uvicorn)"
	@echo "  make run-watch         - Run watcher in foreground"
	@echo ""
	@echo "Poetry commands:"
	@echo "  poetry install         - Install dependencies"
	@echo "  poetry run farmcalc    - Run CLI command"
	@echo "  poetry run uvicorn farmcalc.api:app --reload  - Run API with auto-reload"

# Poetry commands
poetry-install:
	poetry install

poetry-shell:
	poetry shell

# Pip installation (alternative)
install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"

# Testing
test:
	pytest tests/ -v

# Linting and formatting
lint:
	ruff check farmcalc/ tests/

format:
	black farmcalc/ tests/

# Cleanup
clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	find . -type d -name __pycache__ -exec rm -r {} +
	find . -type f -name "*.pyc" -delete

# Run API server
run-api:
	uvicorn farmcalc.api:app --host 0.0.0.0 --port 8000 --reload

# Run watcher
run-watch:
	python -m farmcalc watch --interval 5 --top 25
