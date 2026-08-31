"""The ablation disables the Safety Kernel, so it must never reach a real deployment."""

from __future__ import annotations

from typing import cast

import pytest

import services.common.effects as effects
from assurance import ablation
from nightshift.safety_kernel import ActionRequest, KernelState, evaluate_action


def test_the_kernel_is_bound_to_the_real_implementation_at_import():
    """A leaked monkeypatch from a previous arm would silently disarm production."""
    assert effects.evaluate_action is evaluate_action


def test_the_guard_refuses_a_non_memory_store(monkeypatch):
    class Settings:
        store_backend = "firestore"
        deployment_env = "local"

    monkeypatch.setattr(ablation, "get_settings", lambda: Settings())
    with pytest.raises(SystemExit):
        ablation._guard()


def test_the_guard_refuses_cloud_run_even_on_memory(monkeypatch):
    class Settings:
        store_backend = "memory"
        deployment_env = "cloud-run"

    monkeypatch.setattr(ablation, "get_settings", lambda: Settings())
    with pytest.raises(SystemExit):
        ablation._guard()


def test_the_ablated_kernel_allows_what_the_real_one_would_weigh():
    """Signature-compatible with evaluate_action, and unconditionally permissive."""
    # The ablated kernel ignores both arguments by construction; it exists to say yes.
    decision = ablation._allow_everything(cast(KernelState, None), cast(ActionRequest, None))
    assert decision.verdict.value == "ALLOW"
    assert "ABLATED" in decision.reason
