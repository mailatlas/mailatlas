.DEFAULT_GOAL := help

PYTHON ?= python
PIP := $(PYTHON) -m pip

.PHONY: help verify-python bootstrap bootstrap-python test check smoke-release doctor

help:
	@echo "Targets:"
	@echo "  bootstrap         Install the editable Python dev environment"
	@echo "  bootstrap-python  Install the editable Python dev environment"
	@echo "  test              Run the Python test suite"
	@echo "  check             Run the Python test suite"
	@echo "  smoke-release     Build package artifacts and run the release smoke test"
	@echo "  doctor            Run the built-in MailAtlas self-check"

bootstrap: bootstrap-python

verify-python:
	$(PYTHON) -c "import sys; sys.exit('MailAtlas requires Python 3.11+ for bootstrap-python. Activate a 3.12 venv first or pass PYTHON=python3.12.' if sys.version_info < (3, 11) else 0)"

bootstrap-python: verify-python
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

test:
	$(PYTHON) -m unittest discover -s tests -v

check: test

smoke-release:
	$(PYTHON) -m build
	$(PYTHON) scripts/smoke_release.py

doctor:
	$(PYTHON) -m mailatlas doctor
