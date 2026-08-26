# Security

Night Shift is a system where an agent's mistake can move irreplaceable material to the
wrong freezer, or lose track of it entirely. The security model is built around that,
not around keeping a chatbot polite.

Every claim here states what is enforced and under which assumptions. Where a control is
probabilistic, it says so, and it names the deterministic control standing behind it.

## Threat model

| Threat | Defence | Enforced by |
|---|---|---|
| Prompt injection in vendor or document content | Model Armor screening, semantic policy, least privilege, deterministic egress filter | Model Armor (live) + kernel authority table + regex egress filter |
| Compromised specialist agent | Per-agent identity and tool restrictions, applied at four layers | Toolset construction, broker, service route guard, Cloud Run IAM |
| Commander compromise | The Commander holds no mutation authority of any kind | `AGENT_TOOL_DOMAINS` + `_ACTION_REQUIRED_IDENTITY` (N7) |
| Duplicate Pub/Sub delivery | Incident dedupe key derived from the real-world condition, not the message id | `dedupe_key(site, freezer, window)` |
| Resume re-executes a committed tool | Stable semantic action IDs and receipt replay | `services/common/effects.py` steps 3–4 |
| Concurrent capacity allocation | Capacity read and reservation write in one transaction | Firestore transaction + N1 |
| Stale Memory Bank | Authoritative re-read required; memory can never be the sole evidence | N8 |
| Stale telemetry | Freshness precondition re-checked at commit time, not only at reservation | N4 |
| Forged responder event | Unguessable per-dispatch task token; body bound to the token by HMAC | `opaque_token()` + `responder_task_signature()` |
| Duplicate responder scan | Scan idempotency on `(incident, container, phase)` | N2 + custody state machine |
| Partial evidence | Fail closed to an explicit non-success state | N11 |
| Ledger and effect disagreement | Verifier reports the mismatch rather than trusting either | N2 orphan checks |
| Blocked revision used | Missing qualification is treated as unqualified | N10 |
| Agent loops | Tool-call cap, wall-clock cap, per-drill model budget | broker budget + orchestrator |
| Worker crash | Idempotent tools make repeat invocation safe | proven by the Phase 0 spike |
| Secret leakage | No secrets in the repo; `.env` gitignored; identity via service accounts | `make secret-scan` |
| Demo abuse | Namespace isolation, rate limit, concurrency cap, scripted-only public drills | `apps/api/main.py` |

## Authority, four layers deep

The §11.3 permission matrix is applied independently at four points. Skipping any one
changes only *where* the refusal happens, never whether it happens.

1. **Toolset construction** — an agent's tools are derived from its authority domains, so
   a forbidden tool never appears in the schema the model sees.
2. **Tool broker** — deny by default. Unregistered tools are unreachable; the calling
   identity must hold the tool's domain.
3. **Domain service route guard** — the same kernel table, re-checked server-side.
4. **Cloud Run IAM** — each agent runs as its own service account, and an identity with
   no business calling a service is not a `run.invoker` on it.

Layer 4 means the Dispatch Agent's attempt to read specimen inventory is refused by
Google's infrastructure before it reaches any of our code.

### Read the matrix by its gaps

| Agent | Telemetry | Inventory | Capacity | Facilities | Custody |
|---|---|---|---|---|---|
| incident-commander | summary | — | — | — | — |
| signal-investigator | read, equipment | — | — | — | — |
| impact-analyst | summary | scoped read | — | — | — |
| capacity-broker | backup read | placement view | read, **write** | — | — |
| dispatch-agent | equipment | — | — | read, **write** | — |
| custody-agent | destination | incident read | read | — | read, **write** |

The Commander cannot move anything. The Dispatch Agent has no inventory access whatsoever.
The Capacity Broker cannot commit custody. The Custody Agent cannot create reservations or
work orders. Exactly one agent holds each write domain.

## The sensitive route exists on purpose

`GET /v1/study-notes/{container_id}` returns real study metadata and is gated behind
`inventory.write` — a domain no operational agent holds. It exists so the forbidden-tool
drill targets a route that genuinely returns something worth having. A denial against a
stub proves nothing.

## Handling untrusted content

Vendor replies, repair notes, and uploaded documents are untrusted. The broker screens
tool output that can carry externally authored text before it reaches the model's
context; numeric telemetry is not screened, because doing so would burn budget without
reducing risk.

The published injection payload family is in
[`assurance/controller.py`](assurance/controller.py) — instruction override combined with
a data-exfiltration request. Model Armor matched it at HIGH confidence. That result is
published as an observation about one payload family, not as a general detection
guarantee.

Where Model Armor is unavailable, the deterministic layers are unchanged and the
degradation is recorded. Night Shift never claims Model Armor alone secures it.

## Outbound egress

The vendor message route applies a deterministic filter before anything leaves: container
identifiers, study identifiers, specimen references, patient references, and study owner
references are blocked, and the block is written to the incident timeline as a security
event. This is the layer that still holds when every probabilistic layer above it misses.

## What the demo deliberately does not do

- No real patient data, PHI, PII, or confidential research data exists anywhere in the
  fixture. Names on the responder roster are invented.
- The Cloud Storage retention policy is versioned but **not locked**. Locking is
  irreversible and PRD §28 requires explicit approval first.
- The local agent principal token is an HMAC over a shared secret. On Cloud Run, transport
  identity is a Google-issued OIDC ID token; the HMAC assertion carries the *Night Shift*
  principal, which the transport layer alone cannot distinguish. Both layers are enforced.

## What is not claimed

- No HIPAA, GxP, FDA, GLP, or CLIA compliance. None of that was assessed.
- No claim that the agents make good operational judgements. The claim is narrower: the
  deterministic rules held regardless of what the agents decided.
- No claim of security against an attacker with write access to Firestore or the ability
  to sign with the KMS key. The evidence chain proves the state was signed by the key
  holder, not that the key holder was honest.

## Reporting

This is a hackathon artifact on a synthetic estate. If you find something interesting,
open an issue on the repository.
