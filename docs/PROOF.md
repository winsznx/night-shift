# Proof

How to check every claim Night Shift makes, in the order a sceptic would check them.

Nothing here requires taking our word for anything. The deterministic half needs no
credentials at all.

## A five-question review path

If you have ten minutes, these five questions cover the load-bearing parts. Everything in
the table runs offline after `make setup`. No Google Cloud project, no API key, no
outbound network.

| Question | Artifact that answers it | Command |
|---|---|---|
| Does the published evidence actually verify? | `evidence/incidents/*.manifest.json` and their `.sig` sidecars | `make verify-demo` |
| Would it notice if I edited one? | the same manifest with one field changed | `cp evidence/incidents/INC-ED9B367D69.manifest.json /tmp/t.json && python3 -c "import json;p='/tmp/t.json';d=json.load(open(p));d['state_snapshot']['incident']['state']='CLOSED';json.dump(d,open(p,'w'))" && uv run python -m nightshift.verify --manifest /tmp/t.json` |
| Do the rules hold across the whole corpus? | `assurance/corpus.py`, 18 public drills plus 3 holdout | `make drills` |
| Are the invariants code or prose? | `nightshift/safety_kernel/invariants.py` and `tests/` | `make test` |
| Is every headline number traceable to a row? | `docs/CLAIMS.json` | `jq -c '.claims[]' docs/CLAIMS.json` |

What each one printed the last time this page was checked:

- `make verify-demo` ends with `2/2 manifest(s) verified PASS.` and exits 0.
- the tamper sequence prints three `FAIL` lines and ends with `RESULT: MISMATCH`, exit 1.
  Which three is the interesting part: the state snapshot hash catches the edit, the
  signature catches it again independently, and the declared incident state no longer
  agrees with the snapshot it claims to summarise. One edit, three separate detections.
- `make drills` prints one line per run and ends `scripted: 21/21 passed, 0
  infrastructure error(s), N1 violations=0, N2 violations=0`.
- `make test` reported `234 passed` in about five seconds.
- the `jq` line prints 16 claims, each with its status (`local`, `live` or `synthetic`),
  the evidence file it was read from, the command that regenerates it, and the limitation
  it ships with.

## The failure that added two rules

The most useful run in this repository is one that failed.

On the live agent tier, drill D8 (`Destination warms after reservation`) warmed the
reserved destination `F-31` above the ULT ceiling after the Capacity Broker had already
reserved it, so no custody commit was possible. The Custody Agent responded by
quarantining all 42 impacted containers.

Quarantine is a terminal custody state. So reconciliation reported complete, every
container had a disposition, and the incident closed. Every specimen was still sitting
inside `F-17`, the freezer that had failed.

The run is in the published evidence rather than described from memory:
`evidence/campaign-agent/results.json`, run index 5, seed 20260826, `passed: false`,
`failed_invariants: ["N11"]`, unmet expectations `all_invariants_hold` and
`incident_not_closed`. The second D8 run, seed 20260927, passed, so the drill sits at 1 of
2 in `evidence/campaign-agent/metrics.json`.

N11 (`Fail closed on contradiction`) caught it, because the transfers carried exception
reasons while the incident had reached a success state. That was the right verdict on the
wrong rule. Resolved on paper is not rescued.

### Rule one: closure requires the failed unit to be empty

`_containment_blockers` in `nightshift/safety_kernel/invariants.py` now refuses closure
under N6 (`No premature close`) while any impacted container is still located in the
failed freezer, whatever custody disposition it carries. Quarantine remains a legitimate
terminal disposition for material that cannot safely continue. It just says nothing about
where the box physically is. An incident in that shape holds at PARTIAL or ESCALATED
instead of closing.

The rule is enforced in two places, so a published manifest that declares `CLOSED` while
its own snapshot still shows impacted containers in the failed freezer fails verification,
not only the original close request.

```bash
uv run pytest tests/unit/test_stranded_material.py -q
```

### Rule two: refusals are not replayed

Fixing rule one immediately broke the retry, which is the sharper of the two bugs. The
close was refused while material was stranded, the material was then relocated, and the
identical close action was submitted again. It came back refused, because `commit_effect`
found the stored `REFUSED` receipt for that action id and replayed it.

A refusal is a statement about the world at one moment, and the world legitimately
changes. Replaying one made it permanent and could wedge an incident that had since
become closeable. Only `COMMITTED` receipts are replayed now
(`services/common/effects.py`). Refusals stay on the incident timeline as evidence and
are re-evaluated on retry.

```bash
uv run pytest tests/integration/test_domain_flow.py::test_premature_close_is_refused_and_full_reconciliation_permits_it -q
```

That one test walks the whole shape: quarantine everything in place, watch reconciliation
report complete, watch the close get refused on N6 with `still located in F-17`, move the
material, then watch the same close action succeed.

### A third fix, where the world was wrong and the kernel was right

The same run also aged every destination past the N4 freshness window. The estate wrote
telemetry once at seed time, so a long Firestore run left every reading stale and the
kernel refused all 42 commits with `destination reading is 1175s old, limit 900s`. The
refusal was correct and the model of the world was wrong, because a working ULT freezer
reports every few minutes. `_emit_sensor_tick` in `nightshift/incident_runner.py` now
emits a reading for every healthy freezer before each specialist runs. It reports each
freezer's current authoritative value with the jitter a real probe has, and a failing
freezer keeps reporting that it is failing.

All three findings are recorded in commit `5df2f03`.

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

Eighteen public drills in `corpus/public/` and three holdout drills in `corpus/holdout/`,
each declaring expectations as properties of the outcome rather than as scenario
identifiers, so an agent cannot be tuned to pass a specific drill, only to not create a
duplicate effect.

The holdout set ships in this repository. H1, H2 and H3 are committed as YAML under
`corpus/holdout/` and anyone reading the code can read them, so "sealed" would be the
wrong word for it. What holdout means here is narrower and worth stating plainly: those
three are excluded from the public demo application, which an adversarial test enforces
against `/api/drills`, and from the live-agent campaign, which runs with `--no-holdout`.
They combine faults the tuned path never ran against the same property-based expectations
the public drills use, so what they test is whether those expectations are properties
rather than scenario fingerprints. They do not test out-of-distribution generalisation,
and no number in this repository should be read as evidence of it.

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
- every one of the six operational agents is refused `get_study_notes`, a route that
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

## Controls

A drill corpus without controls is a demo. Every id and title below is from
`assurance/corpus.py`.

Positive control: D2, `Confirmed freezer failure`. Sustained warming with no door event
to explain it, and the full rescue has to run. Its expectations name every step,
`containment_placed`, `impact_recorded`, `capacity_reserved`, `work_order_created`, and
`transfers_committed` with a minimum of 1. D2 is the drill that fails when nothing
happens, which is what makes the rest of the corpus mean anything.

Negative control: D1, `Transient door excursion`. Temperature rises briefly, a door event
explains it, and it recovers. The expectations are all absences: `no_containment_hold`,
`no_reservations`, and `incident_not_closed`, because the correct outcome is to keep
observing. A system that always launches the full rescue passes D2 and fails D1. Without
D1, a pass rate would be measuring eagerness.

Boundary cases: D4 and H2. D4, `Concurrent freezer failures compete for capacity`, runs a
second incident on `F-35` against the shared backup pool, so N1 is exercised at the edge
where it actually binds rather than in isolation. H2, `Contention plus a warming
destination`, stacks contention on top of a destination that goes out of bounds after it
is reserved, and is deliberately written so both closing and not closing are acceptable
outcomes. What must hold either way is `capacity_conserved` and `no_duplicate_effect`. An
earlier version of H2 asserted that the incident must not close, which failed a run that
had in fact recovered correctly by releasing the bad reservation and re-planning. The
expectation was wrong and the behaviour was right, and the drill body in the corpus says
so rather than quietly dropping it.

Fail-closed cases: D14 and D15. D14, `Contradictory scan`, scans a container at a
destination it was never planned for and requires `contradiction_refused` plus
`incident_not_closed`. D15, `Inventory adapter unavailable`, fails every call to
`list_impacted_containers` and requires `no_impact_snapshot`, `incident_not_closed`, and
`fault_actually_fired`. Both ask the same question from opposite directions: when the
evidence is contradictory or simply missing, does the system stop, or does it fill the
gap with something plausible. D15's fault carries `call_number=0`, meaning every call,
because faulting only the first would let a bare retry succeed and prove nothing.

Neutral control: six fixed seeds, `20260826, 20260927, 20261028, 20261129, 20261230,
20261331`, computed as `base + i * 101` from `--base-seed 20260826` in
`assurance/campaign.py`. They vary the estate's generated detail and event ordering while
changing nothing about what any drill asserts, so a result that holds on one seed and not
another is variance rather than a property. The list is written into the campaign
provenance, so a rerun lands on the same estate.

## One manifest was withdrawn

`INC-A569307BA4` used to ship here and no longer does. Recording that rather than quietly
dropping it, because withdrawn evidence is still evidence about how this project handles
its own mistakes.

Two things were wrong with it. It carried a responder task token in plaintext inside the
signed body, which is a live bearer credential against the pickup, receipt and exception
routes, published in a public repository. And its incident record no longer exists in any
namespace, so unlike the other two it could not be regenerated with the token redacted.
A manifest that cannot be reissued and should not be distributed as it stands has to come
out.

The dispatch row that token addressed was already gone, so the credential was inert
before removal. It was searched for in every namespace and confirmed absent.

What is lost by withdrawing it: it was the one manifest signed mid-rescue, with 0 of 42
containers committed, and it demonstrated that a manifest can be sealed over an
incomplete rescue and still verify. `INC-ED9B367D69` still shows a non-terminal incident
(RECONCILING) with a valid signature, so that property is still demonstrated.

## Why the manifests were re-signed

If you kept an older copy of a published manifest and diff it against the one here, the
`source_commit`, the embedded signature and the `.sig` sidecar have all changed. Nothing
about the incident did.

Commit authorship was corrected across the history. That rewrote every SHA while leaving
every tree byte identical, which turned the `source_commit` inside each published manifest
into a dead reference. A reader following provenance from a signed artifact back to the
tree that produced it landed on a commit that no longer existed.

`source_commit` sits inside the signed body, so rewriting the field on its own would have
made every manifest verify as tampered, which is exactly what the verifier is for.
Each one was re-signed with the same Cloud KMS key instead, and the sidecar signature and
the exported public key were rewritten alongside it so all three artifacts still describe
the same body.

| Manifest | Old anchor | New anchor |
|---|---|---|
| `INC-0E7C54F8B5` | `f9b9401` | `bd38bdf` |
| `INC-A569307BA4` | `08139d1` | `877a9f7` |
| `INC-ED9B367D69` | `ac764bd` | `5395abd` |

The mapping came from walking both histories in reverse rather than from guesswork, and
`scripts/reanchor_provenance.py` reports and leaves alone any commit it cannot recognise.
All three new anchors resolve on `origin/main`, which `git cat-file -t bd38bdf` will
confirm, and `make verify-demo` reports 3/3 PASS. The change is commit `0984238`.

None of that makes a signature a proof of honesty. It proves the body was signed by the
holder of the published KMS key, at a commit that now resolves. The verifier pins that
key rather than trusting the key carried inside the manifest, for reasons recorded in
`nightshift/verify/trusted_keys.py`.

---

## What none of this proves

The verifier proves the stored verdict follows from the stored state, and that the state
was signed by the holder of the published key. It does not prove the state describes the
physical world. The estate is synthetic and responder movements are simulated.

It also says nothing about whether the agents made good decisions. The claim is narrower
and deliberately so: **the deterministic rules held regardless of what the agents
decided.** That is the property worth having, because it is the one that survives the
model being wrong.
