SHELL := /bin/bash

CLUSTER_NAME := agentic-devops
IMAGE_NAME := checkout-service:latest
PYTHON := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: setup test build deploy validate-slo simulate-failure rollback clean

setup:
	python -m venv .venv
	$(PIP) install -r app/requirements.txt

test:
	PYTHONPATH=. $(PYTHON) -m pytest tests/

build:
	docker build -t $(IMAGE_NAME) -f Dockerfile .

deploy:
	./deploy-local.sh

validate-slo:
	PYTHONPATH=. $(PYTHON) -c 'from agents.slo_agent import run; run({})'

simulate-failure:
	./simulate-failure.sh

rollback:
	PYTHONPATH=. $(PYTHON) -c 'from agents.rollback_agent import run; run({"agent_outputs": {"slo": {"status": "failed"}}})'

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache
	kind delete cluster --name $(CLUSTER_NAME) || true

