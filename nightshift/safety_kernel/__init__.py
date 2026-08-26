"""Rescue Safety Kernel.

Pure Python. No model calls. No network. No datastore. No wall clock.

Everything this package exports is a total function over an explicit ``KernelState``
snapshot, so the production domain services and the offline verifier evaluate literally
the same code against the same inputs. Tests never reimplement expected behaviour —
they assert against these functions (PRD §15).
"""

from nightshift.safety_kernel.authority import (
    AGENT_TOOL_DOMAINS,
    TOOL_REGISTRY,
    ToolSpec,
    authorize_tool,
    domains_for,
    is_registered_tool,
)
from nightshift.safety_kernel.config import DEFAULT_CONFIG, KernelConfig
from nightshift.safety_kernel.decision import Decision, Verdict, allow, refuse
from nightshift.safety_kernel.invariants import (
    INVARIANTS,
    InvariantResult,
    check_all_invariants,
    n1_capacity_conservation,
    n2_exactly_once_effects,
    n3_valid_custody_prerequisite,
    n4_fresh_destination_evidence,
    n5_complete_reconciliation,
    n6_no_premature_close,
    n7_least_privilege_effect_authority,
    n8_memory_non_authority,
    n9_duplicate_event_safety,
    n10_revision_qualification,
    n11_fail_closed_on_contradiction,
    n12_failure_attribution,
    n13_containment_integrity,
)
from nightshift.safety_kernel.preconditions import evaluate_action
from nightshift.safety_kernel.transitions import (
    INCIDENT_TRANSITIONS,
    can_transition_incident,
    custody_transition_allowed,
    freezer_transition_allowed,
    reservation_transition_allowed,
)
from nightshift.safety_kernel.world import (
    ActionRequest,
    KernelState,
    ReconciliationSnapshot,
    reconciliation_snapshot,
)

__all__ = [
    "AGENT_TOOL_DOMAINS",
    "DEFAULT_CONFIG",
    "INCIDENT_TRANSITIONS",
    "INVARIANTS",
    "TOOL_REGISTRY",
    "ActionRequest",
    "Decision",
    "InvariantResult",
    "KernelConfig",
    "KernelState",
    "ReconciliationSnapshot",
    "ToolSpec",
    "Verdict",
    "allow",
    "authorize_tool",
    "can_transition_incident",
    "check_all_invariants",
    "custody_transition_allowed",
    "domains_for",
    "evaluate_action",
    "freezer_transition_allowed",
    "is_registered_tool",
    "n1_capacity_conservation",
    "n2_exactly_once_effects",
    "n3_valid_custody_prerequisite",
    "n4_fresh_destination_evidence",
    "n5_complete_reconciliation",
    "n6_no_premature_close",
    "n7_least_privilege_effect_authority",
    "n8_memory_non_authority",
    "n9_duplicate_event_safety",
    "n10_revision_qualification",
    "n11_fail_closed_on_contradiction",
    "n12_failure_attribution",
    "n13_containment_integrity",
    "reconciliation_snapshot",
    "refuse",
    "reservation_transition_allowed",
]
