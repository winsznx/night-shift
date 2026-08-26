# backup-capacity-placement

Version: 1.0.0
Applies to: capacity-broker

## When this applies

An authoritative impact snapshot exists and placement groups need destinations.

## Procedure

1. List qualified destinations. Read `eligible` and `ineligible_reasons` on each — they
   are authoritative and already account for temperature, holds, and existing
   reservations.
2. Never treat free slots alone as availability. A freezer with sixty free slots sitting
   above the ULT ceiling is not a destination; a commit there will be refused later,
   after a responder has already carried material across the building.
3. Place the highest-priority group first, into the destination with the best combination
   of headroom and temperature margin.
4. Reserve per placement group, one reservation per group.
5. On a capacity refusal, read the numbers in the refusal. They are current and real.
   Choose a different destination or split the group. Do not retry the same request.
6. If no eligible destination can take a group, report `all_groups_placed: false` and
   escalate. A partially placed rescue that is reported as complete is worse than one
   that is reported as partial.

## Contention

Another incident may be reserving against the same destination at the same time. The
reservation is transactional, so exactly one of you will win. Losing is a normal
outcome, not an error — re-plan against the numbers in the refusal.

## What this skill does not decide

Whether material actually moves, or whether a destination is still safe at the moment of
receipt. Destination temperature is re-checked at commit time by the Custody Service.
