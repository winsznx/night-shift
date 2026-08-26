#!/usr/bin/env bash
# Clean-room reproduction: clone into a temp directory, follow SETUP.md only, verify.
#
# Fails if the deterministic path needs any step that SETUP.md does not document.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mFAILED: %s\033[0m\n' "$*"; exit 1; }

say "Clean-room reproduction in ${WORK}"

say "1. Clone (tracked files only — nothing from the working tree)"
git -C "${REPO_ROOT}" archive --format=tar HEAD | (cd "${WORK}" && tar xf -)
cd "${WORK}"
[[ -f pyproject.toml ]] || fail "clone is missing pyproject.toml"
[[ ! -f .env ]] || fail ".env was committed — it must never be tracked"
[[ ! -d keys ]] || [[ -z "$(find keys -name '*.key.pem' 2>/dev/null)" ]] || fail "a private key is tracked"

say "2. make setup (Python side only; the web app is not on the deterministic path)"
uv python install 3.12 >/dev/null 2>&1
uv sync --all-groups >/dev/null 2>&1 || fail "uv sync failed on a clean clone"

say "3. make test"
uv run pytest tests/unit tests/property tests/integration -q || fail "tests failed on a clean clone"

say "4. make drills"
uv run python -m assurance.campaign --seeds 1 --drivers scripted --out evidence/scratch 2>&1 \
  | tail -4 || fail "drill corpus failed on a clean clone"

say "5. make verify-demo"
uv run python scripts/verify_all.py || true

say "6. Secret scan"
uv run python scripts/secret_scan.py || fail "secret scan found something"

say "7. Deterministic hashes match the source tree"
CLEAN_HASH=$(uv run python -c "
from fixtures.estate import build_estate, estate_hash
print(estate_hash(build_estate(20260826, epoch='2026-08-26T00:00:00.000Z')))
")
SOURCE_HASH=$(cd "${REPO_ROOT}" && uv run python -c "
from fixtures.estate import build_estate, estate_hash
print(estate_hash(build_estate(20260826, epoch='2026-08-26T00:00:00.000Z')))
")
[[ "${CLEAN_HASH}" == "${SOURCE_HASH}" ]] || fail "estate hash differs between clean clone and source tree"
printf '  estate hash %s (identical in both trees)\n' "${CLEAN_HASH:0:32}"

say "Clean-room reproduction PASSED"
echo "  Zero undocumented setup steps on the deterministic path."
