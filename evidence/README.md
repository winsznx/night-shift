# Evidence

Raw artifacts behind every measured claim Night Shift makes. Method, controls, scoring and
known gaps are in [`methodology.md`](methodology.md).

## The curated bundle

| Path | What it is, and what it proves |
|---|---|
| `campaign/results.json`, `results.csv`, `metrics.json` | the deterministic tier: provenance and every raw row, the same rows flat, and the derived numbers the README and `docs/CLAIMS.json` read from. Failures and refusals are retained |
| `campaign-agent/` | the same three files for the live Gemini fleet, 18 runs across 9 drills. Holds the one run that failed, which is the most useful row in here |
| `incidents/INC-*.manifest.json` and `.manifest.json.sig` | three signed incident manifests with detached signature sidecars. Each shows the recorded verdict follows from the recorded state, and that the body was signed by the published Cloud KMS key. Check all three with `make verify-demo` |
| `incidents/verification-report.txt` | the verifier's own output, captured, so a disagreement with your run is visible rather than a matter of trust |
| `qualification.json` | which agent and skill revisions were cleared for operational traffic, on which drills, at which commit |
| `content-screening.json` | per-payload, per-layer verdicts for nine disclosed injection payloads across three screening layers, misses included |
| `iam-denial.json` | one forbidden identity refused with HTTP 403 by Cloud Run's edge, contrasted with two permitted identities on the same routes |
| `traces.json` | Night Shift's own spans, read back out of the Cloud Trace API rather than assumed |
| `agent-recovery.json` | retry and backoff when a worker fails without deciding anything, including the classification bug that let a routine Vertex 503 abort a rescue |

`incidents/*.pub.pem` exists locally but is gitignored, and nothing needs it. The verifier
pins its trusted public keys in `nightshift/verify/trusted_keys.py` rather than trusting a
key shipped next to the artifact it verifies. `scratch/` is gitignored too, and holds the
output of `make drills`.

## Provenance

Most artifacts carry a `source_commit` naming the tree that produced them. Three do not,
and read `"source_commit": "unknown"`: `campaign/results.json`,
`campaign-agent/results.json`, and `iam-denial.json`.

The field was read from the `NIGHTSHIFT_COMMIT` environment variable with a literal
fallback, and those runs were launched without it set. The rows are as real as any other.
What is missing is the chain from a row back to the code that produced it. `Settings` now
falls back to `git rev-parse --short HEAD`, so artifacts generated from here on carry a
commit, but those three predate the fix and keep reading `unknown` until regenerated.

Both manifests, `qualification.json` and `content-screening.json` all name a commit.
`metrics.json` and `results.csv` carry no provenance block by design, because they are
derived views of the `results.json` beside them. The manifests were re-signed once, after
a history rewrite left their commit anchors pointing at nothing, which `docs/PROOF.md`
explains under "Why the manifests were re-signed".

## Start here

Read [`../docs/PROOF.md`](../docs/PROOF.md), and its five-question review path before
anything else in this repository.

Then read "The failure that added two rules". On the live agent tier, drill D8 warmed the
reserved destination, the Custody Agent quarantined all 42 containers in place,
reconciliation reported complete, and the incident closed with every specimen still inside
the failed freezer. N11 caught it, and two safety rules came out of it. The failing run is
run index 5 in `campaign-agent/results.json`, and it was left there.
