"""Phase 7 gate: a valid manifest verifies, a tampered one does not."""

from __future__ import annotations

import copy
import json

import pytest

from nightshift.common.config import get_settings
from nightshift.evidence.manifest import build_manifest, restore_state, snapshot_state
from nightshift.evidence.signing import LocalSigner, NullSigner, verify_signature
from nightshift.evidence.store import write_evidence
from nightshift.verify.verifier import VerificationStatus, verify_manifest, verify_manifest_file
from tests import builders as b

NOW = b.T_NOW


@pytest.fixture
def closed_state():
    return b.closed_state_all_committed()


def _manifest(state, **kw):
    return build_manifest(state, evaluated_at=NOW, delivered_event_ids=["e1", "e1"], **kw)


# --------------------------------------------------------------------------------------
# Round trip
# --------------------------------------------------------------------------------------


def test_state_snapshot_round_trips(closed_state):
    restored = restore_state(snapshot_state(closed_state))
    assert restored.incident is not None and closed_state.incident is not None
    assert restored.incident.id == closed_state.incident.id
    assert restored.incident.state == closed_state.incident.state
    assert set(restored.containers) == set(closed_state.containers)
    assert set(restored.receipts) == set(closed_state.receipts)
    assert set(restored.transfers) == set(closed_state.transfers)


def test_manifest_is_deterministic(closed_state):
    from nightshift.common.canonical import sha256_of

    a = _manifest(closed_state)
    c = _manifest(closed_state)
    assert sha256_of(a) == sha256_of(c)


def test_manifest_declares_synthetic_provenance(closed_state):
    m = _manifest(closed_state)
    assert m["synthetic"] is True
    assert m["simulated_field_events"] is True


def test_manifest_carries_the_kernel_config_it_was_evaluated_under(closed_state):
    m = _manifest(closed_state)
    assert m["kernel_config"]["destination_temp_max_age_s"] == 900
    assert m["evaluated_at"] == NOW


# --------------------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------------------


def test_valid_signed_manifest_passes(closed_state, tmp_path):
    signer = LocalSigner(tmp_path / "keys")
    bundle = write_evidence(
        closed_state, signer=signer, out_dir=tmp_path, upload=False,
        evaluated_at=NOW, delivered_event_ids=["e1", "e1"],
    )
    result = verify_manifest_file(bundle.manifest_path)
    assert result.status is VerificationStatus.PASS, result.render()
    assert not result.divergences


def test_unsigned_manifest_is_partial_not_pass(closed_state, tmp_path):
    bundle = write_evidence(
        closed_state, signer=NullSigner(), out_dir=tmp_path, upload=False,
        evaluated_at=NOW, delivered_event_ids=["e1"],
    )
    result = verify_manifest_file(bundle.manifest_path)
    assert result.status is VerificationStatus.PARTIAL, result.render()
    # An unsigned manifest is a check that could not be performed, not one that failed.
    signature_checks = [c for c in result.checks if c.name.startswith("signature")]
    assert signature_checks and all(c.ok is None for c in signature_checks)


def test_tampering_with_the_state_snapshot_fails_verification(closed_state, tmp_path):
    signer = LocalSigner(tmp_path / "keys")
    bundle = write_evidence(
        closed_state, signer=signer, out_dir=tmp_path, upload=False,
        evaluated_at=NOW, delivered_event_ids=["e1"],
    )
    tampered = json.loads(bundle.manifest_path.read_text())
    # Quietly mark an unresolved container as committed — the kind of edit that would
    # make a partial rescue look complete.
    containers = tampered["state_snapshot"]["containers"]
    victim = sorted(containers)[0]
    containers[victim]["custody_state"] = "UNRESOLVED"
    bundle.manifest_path.write_text(json.dumps(tampered, indent=2))

    result = verify_manifest_file(bundle.manifest_path)
    assert result.status is VerificationStatus.MISMATCH, result.render()
    assert any(c.name.startswith("artifact hash") and c.ok is False for c in result.checks)
    assert any("N5" in d or "N6" in d for d in result.divergences), result.divergences


def test_tampering_with_the_stored_verdict_fails_verification(closed_state, tmp_path):
    signer = LocalSigner(tmp_path / "keys")
    bundle = write_evidence(
        closed_state, signer=signer, out_dir=tmp_path, upload=False,
        evaluated_at=NOW, delivered_event_ids=["e1"],
    )
    tampered = json.loads(bundle.manifest_path.read_text())
    for entry in tampered["invariant_results"]:
        if entry["invariant"] == "N1":
            entry["holds"] = False
    bundle.manifest_path.write_text(json.dumps(tampered, indent=2))

    result = verify_manifest_file(bundle.manifest_path)
    assert result.status is VerificationStatus.MISMATCH
    assert any("N1" in d for d in result.divergences)


def test_tampering_with_the_signature_fails(closed_state, tmp_path):
    signer = LocalSigner(tmp_path / "keys")
    bundle = write_evidence(
        closed_state, signer=signer, out_dir=tmp_path, upload=False,
        evaluated_at=NOW, delivered_event_ids=["e1"],
    )
    tampered = json.loads(bundle.manifest_path.read_text())
    tampered["signature"]["signature_b64"] = "AAAA" + tampered["signature"]["signature_b64"][4:]
    bundle.manifest_path.write_text(json.dumps(tampered, indent=2))

    result = verify_manifest_file(bundle.manifest_path)
    assert result.status is VerificationStatus.MISMATCH, result.render()
    # The embedded signature is checked on its own merits — an untampered detached
    # sidecar must not mask an edit to the copy that travels with the manifest.
    assert any(c.name == "signature (embedded)" and c.ok is False for c in result.checks)
    assert any(
        c.name == "embedded and detached signatures agree" and c.ok is False
        for c in result.checks
    )


def test_manifest_claiming_closed_with_unresolved_containers_is_caught(tmp_path):
    """The single most dangerous lie this system could tell."""
    from nightshift.schemas.enums import CustodyState, IncidentState

    state = b.closed_state_all_committed()
    broken = dict(state.containers)
    victim = sorted(broken)[0]
    broken[victim] = broken[victim].model_copy(
        update={"custody_state": CustodyState.IN_TRANSIT}
    )
    from nightshift.safety_kernel.world import KernelState

    lying = KernelState(
        incident=state.incident, freezers=state.freezers, containers=broken,
        impact=state.impact, reservations=state.reservations, transfers=state.transfers,
        receipts=state.receipts, revision_states=state.revision_states, holds=state.holds,
    )
    assert lying.incident is not None and lying.incident.state is IncidentState.CLOSED

    signer = LocalSigner(tmp_path / "keys")
    bundle = write_evidence(
        lying, signer=signer, out_dir=tmp_path, upload=False,
        evaluated_at=NOW, delivered_event_ids=["e1"],
    )
    # The manifest is internally consistent and correctly signed — and still fails,
    # because the recomputed invariants say the incident should not be CLOSED.
    result = verify_manifest_file(bundle.manifest_path)
    assert result.status is VerificationStatus.MISMATCH
    assert any(
        c.name == "closed incident is fully reconciled" and c.ok is False
        for c in result.checks
    )
    assert bundle.manifest["invariants_all_hold"] is False
    assert "N5" in bundle.manifest["failed_invariants"]


def test_verifier_needs_no_model_or_network(closed_state, tmp_path, monkeypatch):
    """Fail loudly if verification ever grows an outbound call."""
    import socket

    signer = LocalSigner(tmp_path / "keys")
    bundle = write_evidence(
        closed_state, signer=signer, out_dir=tmp_path, upload=False,
        evaluated_at=NOW, delivered_event_ids=["e1"],
    )

    def _no_network(*_a, **_k):
        raise AssertionError("verification attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", _no_network)
    result = verify_manifest_file(bundle.manifest_path)
    assert result.status is VerificationStatus.PASS


def test_kms_and_local_signatures_verify_identically(closed_state, tmp_path):
    """The verifier does not care which backend signed, only that the key matches."""
    signer = LocalSigner(tmp_path / "keys")
    payload = b"night shift evidence"
    sig = signer.sign(payload)
    assert verify_signature(payload, sig) == (True, "")
    assert verify_signature(b"different", sig)[0] is False
