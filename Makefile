# Common tasks. Run `make help` for the list.
PY ?= .venv/bin/python
WEB = Code/webapp
ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: help setup seed run test test-ui check package reset screenshots docker-up docker-down

help:            ## Show this help
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup:           ## Create .venv (Python 3.12) and install everything, including Chromium for the UI tests
	python3.12 -m venv .venv || python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -r requirements-dev.txt
	$(PY) -m playwright install chromium

seed:            ## Analyse every sample invoice (they appear in History)
	$(PY) -m docintel seed

run:             ## Start the web app on http://localhost:8000
	cd $(WEB) && ../../$(PY) manage.py runserver 0.0.0.0:8000

test:            ## Core tests and web tests
	$(PY) -m pytest Code/core -q
	cd $(WEB) && ../../$(PY) manage.py test

test-ui:         ## UI tests (Playwright, headless Chromium) and deployment script tests
	$(PY) -m pytest qa/tests -q

check:           ## Script and JSON checks (bash -n, shellcheck, JSON syntax, Markdown links)
	for f in Deployment/scripts/*.sh; do bash -n "$$f"; done
	shellcheck Deployment/scripts/*.sh
	$(PY) qa/check_repo.py

package:         ## Build build/webapp.zip with every Python library included
	PYTHON=$(PY) Deployment/scripts/package.sh --vendor

screenshots:     ## Retake imgs/screenshot-*.png from local mode
	$(PY) qa/take_screenshots.py

reset:           ## Delete all local data
	$(PY) -m docintel reset

docker-up:       ## Run the web app with the Azurite storage emulator in Docker
	docker compose up --build -d

docker-down:     ## Stop Docker services
	docker compose down
