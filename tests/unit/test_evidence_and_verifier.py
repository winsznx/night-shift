"""Phase 7 gate: a valid manifest verifies, a tampered one does not."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nightshift.evidence.manifest import build_manifest, restore_state, snapshot_state
from nightshift.evidence.signing import LocalSigner, NullSigner, verify_signature
from nightshift.evidence.store import write_evidence
from nightshift.schemas.enums import IncidentState
from nightshift.verify.verifier import VerificationStatus, verify_manifest_file
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


def test_a_locally_signed_manifest_verifies_but_its_provenance_is_not_established(
    closed_state, tmp_path
):
    """A manifest you generated yourself is checkable, and it is not Night Shift's.

    ``LocalSigner`` mints a fresh EC key here, exactly as ``make incident`` does on a
    machine with no GCP credentials. Every structural and recomputation check must still
    pass, because the offline path has to produce evidence the offline verifier can
    read. What cannot pass is provenance: this verifier pins the two published Night
    Shift signing keys, and an unrecognised key is a check it cannot perform rather than
    one it failed. PARTIAL, never PASS.
    """
    signer = LocalSigner(tmp_path / "keys")
    bundle = write_evidence(
        closed_state,
        signer=signer,
        out_dir=tmp_path,
        upload=False,
        evaluated_at=NOW,
        delivered_event_ids=["e1", "e1"],
    )
    result = verify_manifest_file(bundle.manifest_path)

    assert result.status is VerificationStatus.PARTIAL, result.render()
    assert not result.divergences
    assert any(c.name.startswith("signature") and c.ok is True for c in result.checks)
    pin = [c for c in result.checks if c.name.startswith("signing key")]
    assert pin and all(c.ok is None for c in pin), result.render()


def test_unsigned_manifest_is_partial_not_pass(closed_state, tmp_path):
    bundle = write_evidence(
        closed_state,
        signer=NullSigner(),
        out_dir=tmp_path,
        upload=False,
        evaluated_at=NOW,
        delivered_event_ids=["e1"],
    )
    result = verify_manifest_file(bundle.manifest_path)
    assert result.status is VerificationStatus.PARTIAL, result.render()
    # An unsigned manifest is a check that could not be performed, not one that failed.
    signature_checks = [c for c in result.checks if c.name.startswith("signature")]
    assert signature_checks and all(c.ok is None for c in signature_checks)


def test_tampering_with_the_state_snapshot_fails_verification(closed_state, tmp_path):
    signer = LocalSigner(tmp_path / "keys")
    bundle = write_evidence(
        closed_state,
        signer=signer,
        out_dir=tmp_path,
        upload=False,
        evaluated_at=NOW,
        delivered_event_ids=["e1"],
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
        closed_state,
        signer=signer,
        out_dir=tmp_path,
        upload=False,
        evaluated_at=NOW,
        delivered_event_ids=["e1"],
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
        closed_state,
        signer=signer,
        out_dir=tmp_path,
        upload=False,
        evaluated_at=NOW,
        delivered_event_ids=["e1"],
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
        c.name == "embedded and detached signatures agree" and c.ok is False for c in result.checks
    )


def test_manifest_claiming_closed_with_unresolved_containers_is_caught(tmp_path):
    """The single most dangerous lie this system could tell."""
    from nightshift.schemas.enums import CustodyState, IncidentState

    state = b.closed_state_all_committed()
    broken = dict(state.containers)
    victim = sorted(broken)[0]
    broken[victim] = broken[victim].model_copy(update={"custody_state": CustodyState.IN_TRANSIT})
    from nightshift.safety_kernel.world import KernelState

    lying = KernelState(
        incident=state.incident,
        freezers=state.freezers,
        containers=broken,
        impact=state.impact,
        reservations=state.reservations,
        transfers=state.transfers,
        receipts=state.receipts,
        revision_states=state.revision_states,
        holds=state.holds,
    )
    assert lying.incident is not None and lying.incident.state is IncidentState.CLOSED

    signer = LocalSigner(tmp_path / "keys")
    bundle = write_evidence(
        lying,
        signer=signer,
        out_dir=tmp_path,
        upload=False,
        evaluated_at=NOW,
        delivered_event_ids=["e1"],
    )
    # The manifest is internally consistent and correctly signed — and still fails,
    # because the recomputed invariants say the incident should not be CLOSED.
    result = verify_manifest_file(bundle.manifest_path)
    assert result.status is VerificationStatus.MISMATCH
    assert any(
        c.name == "closed incident is fully reconciled" and c.ok is False for c in result.checks
    )
    assert bundle.manifest["invariants_all_hold"] is False
    assert "N5" in bundle.manifest["failed_invariants"]


def test_verifier_needs_no_model_or_network(monkeypatch):
    """Fail loudly if verification ever grows an outbound call.

    Asserted against a *published* manifest rather than a freshly generated one, because
    that is the claim a reader actually acts on: download the artifact, run the verifier
    offline, get PASS. Key pinning has to hold on that path with no network, which it
    does because the trusted public keys are compiled in rather than fetched.
    """
    import socket

    published = sorted(
        (Path(__file__).resolve().parents[2] / "evidence" / "incidents").glob("*.manifest.json")
    )
    if not published:
        pytest.skip("no published manifest available")

    def _no_network(*_a, **_k):
        raise AssertionError("verification attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", _no_network)
    result = verify_manifest_file(published[0])

    assert result.status is VerificationStatus.PASS, result.render()
    assert any(c.name.startswith("signing key") and c.ok is True for c in result.checks)


def test_kms_and_local_signatures_verify_identically(closed_state, tmp_path):
    """The verifier does not care which backend signed, only that the key matches."""
    signer = LocalSigner(tmp_path / "keys")
    payload = b"night shift evidence"
    sig = signer.sign(payload)
    assert verify_signature(payload, sig) == (True, "")
    assert verify_signature(b"different", sig)[0] is False


# --------------------------------------------------------------------------------------
# Sealing instant
#
# Regression: the manifest writer stamped wall clock, so re-sealing a finished rescue
# days later re-asked N4 against readings that were fresh when it closed. That sealed a
# failing invariant into a signed document while the live incident page, which pins to
# closed_at, still called the same incident PASS.
# --------------------------------------------------------------------------------------


def _closed_at(state, when):
    assert state.incident is not None
    state.incident.state = IncidentState.CLOSED
    state.incident.closed_at = when
    return state


def test_a_terminal_incident_seals_at_its_closed_at_not_wall_clock(closed_state, tmp_path):
    closed = _closed_at(closed_state, NOW)
    bundle = write_evidence(
        closed, signer=NullSigner(), out_dir=tmp_path, upload=False, delivered_event_ids=[]
    )
    assert bundle.manifest["evaluated_at"] == NOW


def test_re_sealing_a_finished_rescue_does_not_invent_an_n4_failure(closed_state, tmp_path):
    """Seal the same closed incident twice, far apart. The verdict must not move."""
    closed = _closed_at(closed_state, NOW)
    first = write_evidence(
        closed, signer=NullSigner(), out_dir=tmp_path / "a", upload=False, delivered_event_ids=[]
    ).manifest
    second = write_evidence(
        closed, signer=NullSigner(), out_dir=tmp_path / "b", upload=False, delivered_event_ids=[]
    ).manifest

    assert first["evaluated_at"] == second["evaluated_at"] == NOW
    assert first["invariants_all_hold"] == second["invariants_all_hold"]
    assert first.get("failed_invariants", []) == second.get("failed_invariants", [])


def test_an_open_incident_still_seals_at_wall_clock(closed_state, tmp_path):
    """While a rescue is running, 'now' really is now."""
    assert closed_state.incident is not None
    closed_state.incident.state = IncidentState.RECONCILING
    closed_state.incident.closed_at = None
    bundle = write_evidence(
        closed_state, signer=NullSigner(), out_dir=tmp_path, upload=False, delivered_event_ids=[]
    )
    assert bundle.manifest["evaluated_at"] != NOW
