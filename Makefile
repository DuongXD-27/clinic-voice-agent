PYTHON ?= python
PYTEST_ARGS ?=

.PHONY: install lint format test check

install:
	$(PYTHON) -m pip install -e ".[dev,speech]"

lint:
	$(PYTHON) -m ruff check src tests

format:
	$(PYTHON) -m ruff check --fix src tests
	$(PYTHON) -m ruff format src tests

test:
	$(PYTHON) -m pytest -q $(PYTEST_ARGS)

# Chạy trước khi push: lint + format check + test (giống CI)
check:
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests
	$(PYTHON) -m pytest -q $(PYTEST_ARGS)
