# specimen-transfer-procedure

Version: 1.0.0
Applies to: custody-agent

## When this applies

A responder is moving containers from a failed freezer to a reserved destination.

## Procedure per container

1. Confirm the container is in this incident's scope.
2. Confirm an active reservation covers the intended destination.
3. Confirm a source scan exists.
4. Confirm a destination scan exists.
5. Read destination temperature. `fresh_and_in_bounds: false` means a commit will be
   refused — do not attempt it. WAIT_FOR_EVIDENCE and let the destination be re-read,
   or escalate to the Capacity Broker for a re-plan if the destination has genuinely
   gone bad.
6. Commit. Read the receipt. `COMMITTED` is the only success.

## Exceptions

- **Scanned somewhere unplanned.** This is a contradiction, not a new plan. Flag
  UNRESOLVED with the observed and expected locations. Never update the plan to match
  the scan — that converts a lost container into a clean-looking record.
- **Destination warmed after reservation.** Do not commit. Escalate for a re-plan; the
  reservation can be released and the material placed elsewhere.
- **Container cannot safely continue.** QUARANTINED is a real terminal disposition. It
  keeps the container accounted for without pretending it reached its destination.
- **Duplicate scan.** The second scan of the same event is absorbed. A receipt with
  `duplicate_returned: true` is success.

## What this skill does not decide

Whether the incident may close. Reconciliation completeness is computed deterministically
and closure is refused while anything is unresolved or in flight.
