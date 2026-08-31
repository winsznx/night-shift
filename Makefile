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

# `make setup` used to install the web app in the same recipe, so the first command the
# README hands a judge died with "pnpm: command not found" (error 127) on any machine
# without pnpm, before a single dependency on the credential-free path was installed.
# The web app is not on that path, so it gets its own target.

.PHONY: setup
setup: setup-python setup-web ## Install Python and web dependencies

.PHONY: setup-python
setup-python: ## Install Python dependencies (the whole credential-free path)
	uv python install 3.12
	uv sync --all-groups
	@echo
	@echo "make setup-python is the whole credential-free path. Nothing below needs"
	@echo "pnpm, a Google Cloud project, or a key:"
	@echo "  make test          run every offline test"
	@echo "  make verify-demo   verify the published reference manifest"
	@echo "  make drills        run the full drill corpus"
	@echo
	@echo "The web app is separate and needs pnpm:  make setup-web"

.PHONY: setup-web
setup-web: ## Install web dependencies (needs pnpm)
	cd apps/web && pnpm install

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

# test-all, not test: the adversarial suite is where the drill corpus lives, so gating a
# PR on `test` alone let all 33 drill-corpus tests go unrun on the way to green.
.PHONY: check
check: lint typecheck test-all secret-scan ## Everything a PR should pass

# --- running -------------------------------------------------------------------------

.PHONY: run-local
run-local: ## Run the BFF and the web app locally against the in-memory store
	@# A port already in use is the normal case when a previous run is still alive, and
	@# the raw failure for that is a uvicorn traceback plus a Node EADDRINUSE stack --
	@# neither of which says "you already have this running".
	@busy=""; \
	 lsof -ti:$(API_PORT) >/dev/null 2>&1 && busy="$$busy $(API_PORT)"; \
	 lsof -ti:3000 >/dev/null 2>&1 && busy="$$busy 3000"; \
	 if [ -n "$$busy" ]; then \
	   echo "Port(s) already in use:$$busy"; \
	   echo; \
	   echo "  Night Shift may already be running: http://127.0.0.1:3000"; \
	   echo "  To take them over:  kill $$(lsof -ti:$(API_PORT) -ti:3000 | tr '\n' ' ')&& make run-local"; \
	   exit 1; \
	 fi
	@echo "API  http://127.0.0.1:$(API_PORT)"
	@echo "Web  http://127.0.0.1:3000"
	@trap 'kill 0' EXIT INT TERM; \
	 NIGHTSHIFT_STORE=memory $(PY) python -m uvicorn apps.api.main:app --port $(API_PORT) & \
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

.PHONY: corpus
corpus: ## Re-export the drill corpus to corpus/ as YAML
	@# `python -m assurance.corpus` prints a runpy RuntimeWarning over the output, because
	@# assurance/__init__ has already imported this module. Call main() directly instead.
	$(PY) python -c "from assurance.corpus import main; raise SystemExit(main())" --out corpus

# --- evidence ------------------------------------------------------------------------

# NIGHTSHIFT_COMMIT is passed explicitly because an artifact that cannot name the tree it
# came from cannot be reproduced from it. Four published artifacts already carry
# "source_commit": "unknown" because nothing set this.

.PHONY: evidence
evidence: ## Run the measurement campaign and publish raw results
	NIGHTSHIFT_COMMIT=$$(git rev-parse --short HEAD) \
		$(PY) python -m assurance.campaign --seeds 6 --drivers scripted --out evidence/campaign

.PHONY: evidence-agent
evidence-agent: ## Run the live-agent tier of the campaign (slow)
	NIGHTSHIFT_COMMIT=$$(git rev-parse --short HEAD) \
		$(PY) python -m assurance.campaign --seeds 2 --drivers agent \
		--drills D1,D2,D3,D5,D8,D9,D10,D13,D16 --no-holdout --out evidence/campaign-agent

.PHONY: evidence-recovery
evidence-recovery: ## Record how the fleet recovers from a worker that fails without deciding
	NIGHTSHIFT_COMMIT=$$(git rev-parse --short HEAD) \
		$(PY) python scripts/measure_agent_recovery.py

.PHONY: evidence-screening
evidence-screening: ## Measure every content-screening layer against the disclosed payloads
	NIGHTSHIFT_COMMIT=$$(git rev-parse --short HEAD) \
		$(PY) python scripts/measure_content_screening.py

.PHONY: evidence-iam
evidence-iam: ## Prove a forbidden call is denied by Cloud Run IAM (needs deployed services)
	set -a && . infra/deploy/urls.env && set +a && $(PY) python scripts/prove_iam_denial.py

.PHONY: evidence-traces
evidence-traces: ## Read Night Shift spans back out of Cloud Trace and record what was found
	$(PY) python scripts/verify_traces.py --hours 3

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

.PHONY: schedule
schedule: ## Create the Cloud Run Job and Cloud Scheduler jobs that keep the fleet running
	./infra/deploy/schedule_operations.sh $(PROJECT) $(REGION)

.PHONY: deploy-web
deploy-web: ## Build and deploy the web app to Cloud Run
	./infra/deploy/deploy_web.sh $(PROJECT) $(REGION)

.PHONY: qualify
ablation: ## Run the corpus with the Safety Kernel removed, and compare
	$(PY) python -m assurance.ablation --seeds 6

.PHONY: qualify
qualify: ## Run the qualification gate (refuses unqualified revisions)
	$(PY) python scripts/check_qualification.py
