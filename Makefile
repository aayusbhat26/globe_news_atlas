PYTHON ?= python
PIPELINE_RUN = $(PYTHON) -m pipeline.orchestration.flows

.PHONY: install pipeline dev run build test up down logs

install:
	$(PYTHON) -m pip install -r pipeline/requirements.txt -r backend/requirements.txt
	cd frontend && npm ci

pipeline:
	$(PIPELINE_RUN)

dev:
	$(PYTHON) run.py --dev

run: build
	$(PYTHON) run.py

build:
	cd frontend && npm run build

test:
	PYTHONPATH=backend $(PYTHON) -m pytest backend/tests -v

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f
