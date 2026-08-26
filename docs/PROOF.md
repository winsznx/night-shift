# Proof

How to check every claim Night Shift makes, in the order a sceptic would check them.

Nothing here requires taking our word for anything. The deterministic half needs no
credentials at all.

---

## 1. The invariants are real code, not prose

```bash
make setup
uv run pytest tests/unit/test_invariants.py -q
```

Every reference model case from PRD §15.2 is covered: zero capacity, the exact capacity
boundary, concurrent reservations exceeding capacity, duplicate semantic reservations
with new request IDs, an effect committed but the response lost, a duplicate barcode
scan, stale destination temperature, a destination that warms after reservation, partial
transfer, conflicting scans, a worker dying after work-order creation, closure requested
with one unresolved container, a blocked revision attempting an action, stale memory
contradicting current state, an agent reporting success with no effect in the store, and
an effect with no corresponding receipt.

The tests assert against the kernel's own functions. There is no second implementation of
"what N1 should say" that could drift.

## 2. The properties hold for arbitrary inputs

```bash
uv run pytest tests/property -q
```

Hypothesis generates arbitrary reservation mixes, retry counts, custody state
combinations, and identifier strings, then checks that an ALLOW never overbooks, that
action IDs are stable across any retry count and collide only on identical semantics,
that reconciliation partitions every container exactly once, and that canonical JSON
hashes are order-independent.

## 3. Concurrency actually refuses the loser

```bash
uv run pytest tests/integration/test_domain_flow.py::test_concurrent_reservations_cannot_overbook -q
```

Two threads race for four slots each on a freezer with six free. One commits, one is
refused on N1, and the total reserved never exceeds what was verified available. This
runs through the real FastAPI routes and the real effect commit sequence.

## 4. Idempotency under real interruption

```bash
make spike
```

Provokes three different interruption shapes against a live Gemini-backed ADK run. The
cancellation variant re-invokes an already-committed tool on resume: 2 tool calls, 1
committed effect. Full results and versions in [SPIKE_RESULTS.md](SPIKE_RESULTS.md).

## 5. The drill corpus

```bash
make drills
```

Eighteen public drills plus a holdout set, each declaring expectations as properties of
the outcome rather than as scenario identifiers — so an agent cannot be tuned to pass a
specific drill, only to not create a duplicate effect.

Idempotency drills carry a `fault_actually_fired` expectation, because a drill that was
supposed to inject a commit loss and did not proves nothing, and would otherwise pass as
the loudest possible false green.

## 6. The measurement campaign

```bash
make evidence          # deterministic tier, wide
make evidence-agent    # live Gemini tier, narrow and slow
```

Writes `evidence/campaign/results.json`, `results.csv`, and `metrics.json`. Every headline
number in the README and in `docs/CLAIMS.json` is derived from those rows by
`scripts/generate_readme.py` and `scripts/generate_claims.py`. None is typed.

Failures and refusals are retained, not deleted. A run that failed is in the CSV with its
unmet expectations and failed invariants named.

## 7. Tampering is detected

```bash
uv run pytest tests/unit/test_evidence_and_verifier.py -q
```

Four distinct tamper cases, each producing a distinct signal:

| Tamper | Result |
|---|---|
| edit the state snapshot | artifact hash fails **and** the recomputed verdict diverges |
| edit the stored verdict | verdict divergence alone |
| edit the embedded signature | signature verification fails, and the embedded/detached mismatch is reported |
| leave the manifest unsigned | `PARTIAL`, never `PASS` |

One test is worth reading specifically:
`test_manifest_claiming_closed_with_unresolved_containers_is_caught`. It builds a manifest
that is internally consistent and correctly signed, and describes an incident marked
`CLOSED` while a container is still `IN_TRANSIT`. It still fails, because the recomputed
invariants say the incident should not be closed. That is the single most dangerous lie
this system could tell, and the verifier catches it without needing to trust the signer.

## 8. Verify a published manifest

```bash
make verify-demo
# or
python -m nightshift.verify --manifest evidence/incidents/<id>.manifest.json
```

Exit code 0 for `PASS`, 1 for `MISMATCH`, 2 for `PARTIAL`. No model, no network beyond
fetching the manifest, no Google Cloud credentials.

A test asserts this by monkeypatching `socket.connect` to raise: if verification ever
grows an outbound call, that test fails.

## 9. Authority is enforced where it is claimed

```bash
uv run pytest tests/integration/test_domain_flow.py -q -k "forbidden or study_notes or unauthenticated or forged"
```

- the Dispatch Agent reaching for `list_impacted_containers` gets a 403 naming N7 and the
  required domain
- every one of the six operational agents is refused `get_study_notes` — a route that
  returns real metadata, so the denial is worth something
- an unauthenticated call holds no authority
- a forged principal token is rejected

On Cloud Run there is a fourth layer: each agent runs as its own service account, and an
identity that should not reach a service is not a `run.invoker` on it. That denial happens
at Google's edge before any Night Shift code runs.

## 10. The live deployment

```bash
make smoke-live
curl -s $NIGHTSHIFT_API_URL/api/meta | jq
```

`/api/meta` reports the model, store backend, signer backend, region, and commit of what
is actually running. An authenticated domain service returns 404 to an unauthenticated
caller.

## 11. Clean-room reproduction

```bash
make clean-room
```

Clones the repository into a temporary directory, follows `SETUP.md` and nothing else,
and runs the deterministic path end to end. Zero undocumented setup steps, or it fails.

---

## What none of this proves

The verifier proves the stored verdict follows from the stored state, and that the state
was signed by the holder of the published key. It does not prove the state describes the
physical world — the estate is synthetic and responder movements are simulated.

It also says nothing about whether the agents made good decisions. The claim is narrower
and deliberately so: **the deterministic rules held regardless of what the agents
decided.** That is the property worth having, because it is the one that survives the
model being wrong.
