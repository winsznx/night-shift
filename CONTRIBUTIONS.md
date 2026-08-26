# Contributions

## What this build found in Google ADK

Night Shift's dominant mechanism — idempotent effects behind semantic action IDs —
depends entirely on knowing what ADK does to a tool that has already committed when a run
resumes. PRD §22 required proving that rather than assuming it, and the proof turned up
something worth writing down.

### Resume behaviour is not uniform across interruption shapes

**Reproduction:** [`scripts/spike_adk_resume.py`](scripts/spike_adk_resume.py) · run with
`make spike`

**Versions:** `google-adk` 2.7.1, `google-genai` 2.20.0, Python 3.12.14, Gemini 3.5 Flash
on Vertex AI, `InMemorySessionService`,
`App(resumability_config=ResumabilityConfig(is_resumable=True))`.

The spike commits a real effect inside `reserve_capacity`, interrupts the run three
different ways, then resumes the same `invocation_id`:

| Variant | How the run is interrupted | Tool re-invoked on resume? |
|---|---|---|
| A | `BasePlugin.after_tool_callback` raises after the tool returns | no |
| B | the tool function itself raises after committing | no |
| C | the invocation is cancelled mid-flight (`task.cancel()`) | **yes** |

Only variant C — a worker actually dying, which is the realistic case — re-invokes the
committed tool. Variants A and B terminate the invocation in a way that resume treats as
complete.

**Why this matters to anyone building effectful ADK agents.** If you test resume safety
by raising from a plugin or from your tool, you will observe no re-invocation and may
conclude that idempotency is unnecessary. Then a pod eviction or a scale-down in
production produces variant C, the tool runs a second time, and you have booked the
freezer twice.

Observed output from the run recorded in `docs/SPIKE_RESULTS.md`:

```json
{
  "variant": "C: invocation cancelled mid-flight (worker dies)",
  "tool_calls_before_resume": 1,
  "tool_calls_after_resume": 2,
  "tool_reinvoked_on_resume": true,
  "committed_effects": 1,
  "duplicate_effect": false
}
```

Night Shift produced one committed effect from two calls because the semantic action ID
was identical and the second call replayed the first call's receipt. Without that, it
would have been two reservations.

**What we would suggest upstream.** This is a documentation and test-coverage gap rather
than a bug — the behaviour is defensible, and arguably correct for each shape in
isolation. What is missing is a statement in the resumability documentation that tool
re-invocation on resume depends on *how* the invocation ended, together with the guidance
that follows from it: any tool with a side effect must be idempotent on a key the caller
controls, because the framework cannot know which effects were durable.

A minimal reproduction suitable for an upstream issue is the spike script itself, which is
self-contained apart from Vertex credentials.

### Status

At the time of writing this has **not** been filed upstream. It is reproduced, recorded,
and published here with a runnable script and exact versions. Filing it requires an
account interaction outside this build, and manufacturing a token contribution to be able
to claim one would be worse than saying plainly that it is ready to file and has not been.

## Smaller observations, not worth an issue

- `LlmAgent` cannot combine `output_schema` with `tools`. That is a reasonable constraint,
  but it means a tool-using agent's structured output has to be validated by the caller.
  Night Shift embeds the JSON Schema in the instruction and validates the final message
  with Pydantic. An earlier attempt used a compact field listing instead, and the model
  invented plausible-but-wrong names for nested objects — `{"specialist":
  "impact-assessment", "reason": …}` instead of `{"specialist": "impact-analyst",
  "objective": …}`. Full JSON Schema plus one worked example fixed it.
- `ResumabilityConfig` emits an `[EXPERIMENTAL]` warning on every `App` construction, which
  is noisy when building six agents per incident. Not a defect, just loud.

## Contributing to Night Shift

```bash
make setup
make check     # lint + typecheck + tests + secret scan
```

Two rules matter more than style:

1. **Never weaken a drill to make it pass.** If a drill fails, either the system is wrong
   or the expectation encoded an assumption that was never true. Both are fine outcomes;
   deleting the assertion is not. Where an expectation was genuinely wrong, correct it and
   record the reasoning in the drill's own description — see H2 in
   [`assurance/corpus.py`](assurance/corpus.py) for the pattern.
2. **Tests assert against the kernel, not against a second implementation.** If a test
   needs to know what should happen, it calls the same invariant function production
   calls. A parallel reimplementation of "what N1 should say" is how the two drift apart.
