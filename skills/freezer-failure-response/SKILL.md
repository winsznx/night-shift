# freezer-failure-response

Version: 1.0.0
Applies to: signal-investigator, incident-commander

## When this applies

A ULT freezer has reported temperature above its alarm threshold, or a sustained upward
trend, and it is not yet established whether this is a real equipment failure.

## Procedure

1. Pull the temperature window covering at least twice the confirm window. A short
   window cannot distinguish a spike from a trend.
2. Pull door events over the same span.
3. Compare the timing, not just the presence, of door events:
   - a door opening that closes *before* warming begins does not explain warming that
     continues afterwards
   - a warming curve that peaks shortly after a door closes and then recovers toward
     setpoint is a door excursion
   - warming that continues climbing with the door closed is equipment
4. Pull equipment history. A unit with a recent compressor service and a repeat of the
   same signature is a stronger failure signal than a first-time excursion.
5. Classify. Prefer INCONCLUSIVE with a short re-observation window over a confident
   wrong answer — the cost of looking again in ten minutes is far below the cost of
   either an unnecessary full rescue or a missed failure.

## Severity guidance

- SEV1: sustained warming confirmed and the unit holds priority-class-1 material
- SEV2: sustained warming confirmed
- SEV3: elevated but not yet sustained, or explained by a door event that is recovering
- INFO: recovered without intervention

## What this skill does not decide

Whether the incident may advance state, whether capacity exists, or whether material may
move. Those are deterministic decisions made by the Incident Control, Capacity, and
Custody services. This skill guides interpretation only.
