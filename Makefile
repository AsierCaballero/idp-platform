.PHONY: install test lint clean

install:
	pip install -e ".[dev]"

test:
	pytest -v

lint:
	ruff check idp/
	mypy idp/

clean:
	rm -rf .pytest_cache/ __pycache__/
	rm -rf *.egg-info/
	rm -rf .coverage htmlcov/
