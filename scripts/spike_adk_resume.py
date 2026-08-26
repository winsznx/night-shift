"""Phase 0 seam spike: what does ADK actually do to an effectful tool on resume?

PRD §22 calls this the central architecture assumption. The question is narrow and its
answer decides the whole idempotency design:

    A tool commits an effect. The runtime dies before the tool's result is persisted.
    On resume, does ADK call that tool again?

Assuming an answer would be malpractice, so this script provokes three different
failure shapes against a real Gemini-backed ADK run and reports what each one did:

    A. after_tool_callback raises  — the effect committed, the plugin killed the turn
    B. the tool itself raises after committing — "response lost after commit" (D5/D6)
    C. the invocation is cancelled mid-flight — a worker actually dying (D7)

Night Shift must be safe under *all three*, which is why every mutating tool is keyed
on a semantic action ID and returns the existing receipt rather than committing twice.

Run: uv run python scripts/spike_adk_resume.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.apps.app import ResumabilityConfig
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from nightshift.common.canonical import sha256_hex
from nightshift.common.config import get_settings

INSTRUCTION = (
    "You reserve backup freezer capacity. Call reserve_capacity exactly once with "
    "incident_id='INC-SPIKE', destination_freezer_id='F-03', group_id='PG-1'. "
    "Then reply with the reservation_id you received and nothing else."
)


class EffectStore:
    """The same shape as a real domain service: action_id -> receipt."""

    def __init__(self) -> None:
        self.receipts: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []
        self.commits = 0

    def reserve(self, incident_id: str, destination_freezer_id: str, group_id: str) -> dict:
        action_id = sha256_hex("reservation", incident_id, destination_freezer_id, group_id)
        self.calls.append(action_id)
        existing = self.receipts.get(action_id)
        if existing is not None:
            return {**existing, "duplicate_returned": True}
        self.commits += 1
        receipt = {
            "receipt_id": f"RCP-{self.commits}",
            "action_id": action_id,
            "reservation_id": f"RES-{action_id[:8]}",
            "status": "COMMITTED",
            "duplicate_returned": False,
        }
        self.receipts[action_id] = receipt
        return receipt


class CrashAfterToolPlugin(BasePlugin):
    """Variant A: the effect committed, then the turn dies before the result persists."""

    def __init__(self) -> None:
        super().__init__(name="crash-after-tool")
        self.armed = True
        self.fired = False

    async def after_tool_callback(self, *, tool, tool_args, tool_context, result):  # type: ignore[no-untyped-def]
        if self.armed and tool.name == "reserve_capacity":
            self.armed = False
            self.fired = True
            raise RuntimeError("SPIKE: runtime killed after tool commit")
        return None


def build(
    store: EffectStore, plugins: list[BasePlugin], tool
) -> tuple[Runner, InMemorySessionService]:
    settings = get_settings()
    agent = LlmAgent(
        name="spike_broker", model=settings.model_id, instruction=INSTRUCTION, tools=[tool]
    )
    app = App(
        name="nightshift_spike",
        root_agent=agent,
        plugins=plugins,
        resumability_config=ResumabilityConfig(is_resumable=True),
    )
    session_service = InMemorySessionService()
    return (
        Runner(app=app, session_service=session_service, auto_create_session=True),
        session_service,
    )


async def _drain(
    runner: Runner, *, user_id: str, session_id: str, invocation_id: str, text: str | None
) -> str | None:
    msg = types.Content(role="user", parts=[types.Part(text=text)]) if text else None
    try:
        async for _ in runner.run_async(
            user_id=user_id, session_id=session_id, invocation_id=invocation_id, new_message=msg
        ):
            pass
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


async def variant_a() -> dict[str, Any]:
    store = EffectStore()

    def reserve_capacity(incident_id: str, destination_freezer_id: str, group_id: str) -> dict:
        """Reserve backup freezer capacity for a group of containers."""
        return store.reserve(incident_id, destination_freezer_id, group_id)

    plugin = CrashAfterToolPlugin()
    runner, sessions = build(store, [plugin], reserve_capacity)
    await sessions.create_session(app_name="nightshift_spike", user_id="u", session_id="s")

    inv = "e-variant-a"
    err1 = await _drain(
        runner, user_id="u", session_id="s", invocation_id=inv, text="Reserve the capacity now."
    )
    calls_after_crash, commits_after_crash = len(store.calls), store.commits
    err2 = await _drain(runner, user_id="u", session_id="s", invocation_id=inv, text=None)

    return {
        "variant": "A: after_tool_callback raises",
        "fault_injected": plugin.fired,
        "run1_error": err1,
        "resume_error": err2,
        "tool_calls_before_resume": calls_after_crash,
        "tool_calls_after_resume": len(store.calls),
        "tool_reinvoked_on_resume": len(store.calls) > calls_after_crash,
        "committed_effects": store.commits,
        "duplicate_effect": store.commits > 1,
        "commits_before_resume": commits_after_crash,
    }


async def variant_b() -> dict[str, Any]:
    store = EffectStore()
    state = {"armed": True, "fired": False}

    def reserve_capacity(incident_id: str, destination_freezer_id: str, group_id: str) -> dict:
        """Reserve backup freezer capacity for a group of containers."""
        receipt = store.reserve(incident_id, destination_freezer_id, group_id)
        if state["armed"]:
            state["armed"] = False
            state["fired"] = True
            raise RuntimeError("SPIKE: response lost after the effect committed")
        return receipt

    runner, sessions = build(store, [], reserve_capacity)
    await sessions.create_session(app_name="nightshift_spike", user_id="u", session_id="s")

    inv = "e-variant-b"
    err1 = await _drain(
        runner, user_id="u", session_id="s", invocation_id=inv, text="Reserve the capacity now."
    )
    calls_after_crash, commits_after_crash = len(store.calls), store.commits
    err2 = await _drain(runner, user_id="u", session_id="s", invocation_id=inv, text=None)

    return {
        "variant": "B: tool commits then raises (response lost after commit)",
        "fault_injected": state["fired"],
        "run1_error": err1,
        "resume_error": err2,
        "tool_calls_before_resume": calls_after_crash,
        "tool_calls_after_resume": len(store.calls),
        "tool_reinvoked_on_resume": len(store.calls) > calls_after_crash,
        "committed_effects": store.commits,
        "duplicate_effect": store.commits > 1,
        "commits_before_resume": commits_after_crash,
    }


async def variant_c() -> dict[str, Any]:
    """A worker actually dying: cancel the invocation as soon as the effect commits."""
    store = EffectStore()
    committed = asyncio.Event()

    def reserve_capacity(incident_id: str, destination_freezer_id: str, group_id: str) -> dict:
        """Reserve backup freezer capacity for a group of containers."""
        receipt = store.reserve(incident_id, destination_freezer_id, group_id)
        committed.set()
        return receipt

    runner, sessions = build(store, [], reserve_capacity)
    await sessions.create_session(app_name="nightshift_spike", user_id="u", session_id="s")
    inv = "e-variant-c"

    async def run_until_cancelled() -> None:
        async for _ in runner.run_async(
            user_id="u",
            session_id="s",
            invocation_id=inv,
            new_message=types.Content(
                role="user", parts=[types.Part(text="Reserve the capacity now.")]
            ),
        ):
            pass

    task = asyncio.create_task(run_until_cancelled())
    try:
        await asyncio.wait_for(committed.wait(), timeout=120)
    except TimeoutError:
        task.cancel()
        return {"variant": "C: invocation cancelled mid-flight", "error": "tool never committed"}

    task.cancel()
    cancel_error = None
    try:
        await task
    except asyncio.CancelledError:
        cancel_error = "CancelledError"
    except Exception as exc:
        cancel_error = f"{type(exc).__name__}: {exc}"

    calls_after_crash, commits_after_crash = len(store.calls), store.commits
    err2 = await _drain(runner, user_id="u", session_id="s", invocation_id=inv, text=None)

    return {
        "variant": "C: invocation cancelled mid-flight (worker dies)",
        "fault_injected": True,
        "run1_error": cancel_error,
        "resume_error": err2,
        "tool_calls_before_resume": calls_after_crash,
        "tool_calls_after_resume": len(store.calls),
        "tool_reinvoked_on_resume": len(store.calls) > calls_after_crash,
        "committed_effects": store.commits,
        "duplicate_effect": store.commits > 1,
        "commits_before_resume": commits_after_crash,
    }


async def main() -> int:
    settings = get_settings()
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.project_id)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.model_location)
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")

    from google.adk.version import __version__ as adk_version

    variants = []
    for fn in (variant_a, variant_b, variant_c):
        try:
            variants.append(await fn())
        except Exception as exc:
            variants.append(
                {"variant": fn.__name__, "harness_error": f"{type(exc).__name__}: {exc}"}
            )

    reinvoked = [v for v in variants if v.get("tool_reinvoked_on_resume")]
    duplicates = [v for v in variants if v.get("duplicate_effect")]

    out = {
        "adk_version": adk_version,
        "model": settings.model_id,
        "vertex": True,
        "variants": variants,
        "any_variant_reinvoked_tool": bool(reinvoked),
        "any_duplicate_effect": bool(duplicates),
        "conclusion": (
            "At least one interruption shape re-invokes a committed tool on resume, so "
            "semantic action IDs plus receipt replay are load-bearing, not belt-and-braces."
            if reinvoked
            else "No variant re-invoked the tool, but idempotency is still required because "
            "Pub/Sub redelivery and responder retries reach the same services independently."
        ),
        "duplicate_effects_observed": len(duplicates),
    }
    print(json.dumps(out, indent=2))
    return 1 if duplicates else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
