# impact-assessment

Version: 1.0.0
Applies to: impact-analyst

## When this applies

An incident has been confirmed and a containment hold is in place. The impact set must
be established before any capacity is reserved.

## Procedure

1. Enumerate every container in the failed freezer. Check the `enumeration_complete`
   flag on the response — a partial read is the single most dangerous input to this
   whole workflow.
2. If enumeration is incomplete, stop. Report `inventory_complete: false` and say what
   was unreadable. An incident that closes against a partial impact set leaves real
   material unaccounted for.
3. Group by handling requirement: priority class and required temperature. Material
   from the same study at the same temperature should stay together so it remains
   findable after the move.
4. Rank priority groups. Priority class 1 moves first.

## Priority guidance

- class 1: irreplaceable or actively enrolled study material
- class 2: replaceable with significant cost or delay
- class 3: method development, replicates, and other reproducible material

## What this skill does not decide

Where material goes, whether capacity exists, or when it moves. The impact snapshot is
an observation, not a plan.
