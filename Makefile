.PHONY: format lint check

format:
	uv run ruff format src
	uv run ruff check --fix src

lint:
	uv run ruff check src
	uv run mypy src

check: format lint
