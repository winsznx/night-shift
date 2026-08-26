.DEFAULT_GOAL := help
SHELL := /bin/bash
PY := uv run
PROJECT ?= $(shell gcloud config get-value project 2>/dev/null)
REGION ?= us-central1
API_PORT ?= 8081

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-18s\033[0m %s\n", $$1, $$2}'

# --- setup ---------------------------------------------------------------------------

.PHONY: setup
setup: ## Install Python and web dependencies
	uv python install 3.12
	uv sync --all-groups
	cd apps/web && pnpm install
	@echo
	@echo "Setup complete. Deterministic work needs no credentials:"
	@echo "  make test          run every offline test"
	@echo "  make verify-demo   verify the published reference manifest"
	@echo "  make drills        run the full drill corpus"

# --- quality -------------------------------------------------------------------------

.PHONY: test
test: ## Run unit, property, and integration tests (no credentials needed)
	$(PY) pytest tests/unit tests/property tests/integration -q

.PHONY: test-all
test-all: ## Run every test including adversarial
	$(PY) pytest tests -q

.PHONY: lint
lint: ## Lint Python
	$(PY) ruff check nightshift services agents assurance fixtures scripts tests
	$(PY) ruff format --check nightshift services agents assurance fixtures

.PHONY: fmt
fmt: ## Format Python
	$(PY) ruff format nightshift services agents assurance fixtures scripts tests
	$(PY) ruff check --fix nightshift services agents assurance fixtures scripts tests

.PHONY: typecheck
typecheck: ## Typecheck Python and TypeScript
	$(PY) mypy
	cd apps/web && npx tsc --noEmit

.PHONY: build
build: ## Build the web app
	cd apps/web && pnpm build

.PHONY: secret-scan
secret-scan: ## Fail if anything that looks like a credential is tracked
	@$(PY) python scripts/secret_scan.py

.PHONY: check
check: lint typecheck test secret-scan ## Everything a PR should pass

# --- running -------------------------------------------------------------------------

.PHONY: run-local
run-local: ## Run the BFF and the web app locally against the in-memory store
	@echo "API  http://127.0.0.1:$(API_PORT)"
	@echo "Web  http://127.0.0.1:3000"
	@NIGHTSHIFT_STORE=memory $(PY) python -m uvicorn apps.api.main:app --port $(API_PORT) & \
	 cd apps/web && NIGHTSHIFT_API_URL=http://127.0.0.1:$(API_PORT) pnpm dev

.PHONY: api
api: ## Run just the BFF
	NIGHTSHIFT_STORE=memory $(PY) python -m uvicorn apps.api.main:app --port $(API_PORT) --reload

.PHONY: incident
incident: ## Run one live incident with the real agent fleet
	$(PY) python scripts/run_incident.py --rounds 8

.PHONY: drills
drills: ## Run the full drill corpus (deterministic tier, seconds)
	$(PY) python -m assurance.campaign --seeds 1 --drivers scripted --out evidence/scratch

# --- evidence ------------------------------------------------------------------------

.PHONY: evidence
evidence: ## Run the measurement campaign and publish raw results
	$(PY) python -m assurance.campaign --seeds 6 --drivers scripted --out evidence/campaign

.PHONY: evidence-agent
evidence-agent: ## Run the live-agent tier of the campaign (slow)
	$(PY) python -m assurance.campaign --seeds 2 --drivers agent \
		--drills D1,D2,D3,D5,D8,D9,D10,D13,D16 --no-holdout --out evidence/campaign-agent

.PHONY: verify-demo
verify-demo: ## Verify every published manifest (no credentials needed)
	@$(PY) python scripts/verify_all.py

.PHONY: seed-demo
seed-demo: ## Run a real incident and publish its signed evidence
	$(PY) python scripts/seed_demo.py --rounds 8

.PHONY: spike
spike: ## Re-run the ADK resume seam spike
	$(PY) python scripts/spike_adk_resume.py

# --- cloud ---------------------------------------------------------------------------

.PHONY: bootstrap
bootstrap: ## Enable APIs and provision GCP resources
	./infra/bootstrap/enable_apis.sh $(PROJECT)
	./infra/bootstrap/provision.sh $(PROJECT) $(REGION)

.PHONY: deploy
deploy: ## Build the image and deploy every Cloud Run service
	./infra/deploy/deploy_services.sh $(PROJECT) $(REGION)

.PHONY: smoke-live
smoke-live: ## Check the deployed public API
	@$(PY) python scripts/smoke_live.py

.PHONY: e2e
e2e: ## Run the Playwright judge-path suite
	cd apps/web && npx playwright test

.PHONY: clean-room
clean-room: ## Reproduce from a clean clone in a temp directory
	@./scripts/clean_room.sh

.PHONY: deploy-web
deploy-web: ## Build and deploy the web app to Cloud Run
	./infra/deploy/deploy_web.sh $(PROJECT) $(REGION)
