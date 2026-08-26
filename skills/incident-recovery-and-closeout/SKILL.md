# incident-recovery-and-closeout

Version: 1.0.0
Applies to: incident-commander

## When this applies

Transfers are complete or exhausted and the incident is heading toward closure.

## Procedure

1. Read the reconciliation before doing anything else. It reports committed,
   quarantined, unresolved, and in-flight counts and whether the set is complete.
2. If anything is unresolved or in flight, the incident does not close. Say what is
   outstanding and keep working — or escalate if it cannot be resolved.
3. Containment hold release requires demonstrated recovery: a continuous validation
   window at setpoint, not a repair claim. A freezer that has been fixed but has not
   yet held temperature for the validation window keeps its hold.
4. Request closure only once reconciliation reports complete.

## What "complete" means

Every impacted container is in exactly one terminal custody state: COMMITTED or
QUARANTINED. Containers still AT_SOURCE, PICKED_UP, IN_TRANSIT, RECEIVED, or UNRESOLVED
are not resolved.

## Partial outcomes

A partial rescue is not a success and must never be presented as one. The honest
outcomes are PARTIAL or ESCALATED, both of which keep the incident visible. Closing an
incident that still has unaccounted material is the worst failure this system can have,
which is why the closure guard is deterministic and not persuadable.
