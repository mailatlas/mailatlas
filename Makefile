.DEFAULT_GOAL := help

PYTHON ?= python
PIP := $(PYTHON) -m pip
NPM ?= npm

.PHONY: help verify-python bootstrap bootstrap-python bootstrap-docs test docs check smoke-release demo-cli demo-parser doctor

help:
	@echo "Targets:"
	@echo "  bootstrap         Install Python and docs dependencies"
	@echo "  bootstrap-python  Install the editable Python dev environment"
	@echo "  bootstrap-docs    Install docs-site dependencies"
	@echo "  test              Run the Python test suite"
	@echo "  docs              Build the docs site"
	@echo "  check             Run tests and docs build"
	@echo "  smoke-release     Build package artifacts and run the release smoke test"
	@echo "  demo-cli          Run the CLI demo against a synthetic fixture"
	@echo "  demo-parser       Run the parser demo against a synthetic fixture"
	@echo "  doctor            Run the built-in MailAtlas self-check"

bootstrap: bootstrap-python bootstrap-docs

verify-python:
	$(PYTHON) -c "import sys; sys.exit('MailAtlas requires Python 3.11+ for bootstrap-python. Activate a 3.12 venv first or pass PYTHON=python3.12.' if sys.version_info < (3, 11) else 0)"

bootstrap-python: verify-python
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

bootstrap-docs:
	cd site && $(NPM) ci

test:
	$(PYTHON) -m unittest discover -s tests -v

docs:
	cd site && $(NPM) run build

check: test docs

smoke-release:
	$(PYTHON) -m build
	$(PYTHON) scripts/smoke_release.py

demo-cli:
	./scripts/demo_cli.sh

demo-parser:
	./scripts/demo_parser_api.sh

doctor:
	$(PYTHON) -m mailatlas doctor
