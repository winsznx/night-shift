"""Does a responder's captured evidence corroborate what they claim to have done?

A custody commit used to rest entirely on a bearer token. Anyone holding that string
could post a pickup or a receipt for any container in the batch, and the token was
published in plaintext inside the signed manifest, so it was not even a secret. The
token still authenticates the *session*. What it can no longer do on its own is assert
that a physical box moved.

The division of labour is the same one the rest of the system runs on. A model reads
pixels and audio and returns what it thinks it saw. Nothing here calls a model, imports
one, or trusts one. These functions take a reading that already happened and decide,
arithmetically, whether it agrees with authoritative state. A model that hallucinates a
container id produces a MISMATCH, not a commit.

Deliberately not a confidence threshold. "The model was 0.83 sure" is not evidence about
a freezer. Either the string it read equals the container the responder claims to be
holding or it does not, and either the temperature it read agrees with the telemetry
this system already holds or it does not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from nightshift.safety_kernel.config import DEFAULT_CONFIG, KernelConfig

DISPLAY_AGREEMENT_C = 2.0
"""How far a photographed freezer display may sit from the telemetry reading.

A door-mounted display and the probe the telemetry stream comes from are not the same
instrument and never read identically. Two degrees is wide enough that honest
instrument disagreement does not block a rescue, and narrow enough that a photo of the
wrong freezer fails: the estate's backup units sit near -80C and a failing one is above
-60C, so a mixed-up unit misses by far more than two.
"""


class CorroborationStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    """The capture agrees with authoritative state."""

    MISMATCH = "MISMATCH"
    """The capture disagrees. This is a refusal, and it is the interesting outcome."""

    ABSENT = "ABSENT"
    """No capture was supplied, or the reader could not reach a verdict.

    Never an error. A responder in a cold room with a dead phone battery still has to be
    able to move specimens, so absence degrades to token-only authority and is recorded
    as having done so rather than blocking the rescue.
    """


@dataclass(frozen=True)
class CorroborationResult:
    status: CorroborationStatus
    kind: str
    detail: str
    observed: str = ""
    expected: str = ""
    evidence_sources: list[str] = field(default_factory=list)

    @property
    def confirms(self) -> bool:
        return self.status is CorroborationStatus.CONFIRMED

    @property
    def contradicts(self) -> bool:
        return self.status is CorroborationStatus.MISMATCH

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "kind": self.kind,
            "detail": self.detail,
            "observed": self.observed,
            "expected": self.expected,
            "evidence_sources": list(self.evidence_sources),
        }


_ID_NOISE = re.compile(r"[^A-Z0-9]")


def normalize_container_id(raw: str) -> str:
    """Compare label text the way a scanner would, not the way a printer laid it out.

    A photographed label carries whatever the camera and the model made of the glyphs:
    lowercase, a stray space, a hyphen the print head skipped. None of that changes
    which box is in the responder's hands, so it is normalised away before comparison.
    Nothing beyond case, spacing and punctuation is forgiven, because a single wrong
    digit is a different box.
    """
    return _ID_NOISE.sub("", raw.upper())


def corroborate_container_label(
    claimed_container_id: str, observed_text: str
) -> CorroborationResult:
    """Does the photographed label name the container the responder says they hold?"""
    if not observed_text.strip():
        return CorroborationResult(
            status=CorroborationStatus.ABSENT,
            kind="container_label",
            detail="no label photo was supplied, or no identifier could be read from it",
            expected=claimed_container_id,
        )

    observed = normalize_container_id(observed_text)
    expected = normalize_container_id(claimed_container_id)
    if observed == expected:
        return CorroborationResult(
            status=CorroborationStatus.CONFIRMED,
            kind="container_label",
            detail="the label in the photograph names the container being scanned",
            observed=observed_text.strip(),
            expected=claimed_container_id,
            evidence_sources=["capture:container-label"],
        )
    return CorroborationResult(
        status=CorroborationStatus.MISMATCH,
        kind="container_label",
        detail=(
            "the label in the photograph names a different container than the one being scanned"
        ),
        observed=observed_text.strip(),
        expected=claimed_container_id,
        evidence_sources=["capture:container-label"],
    )


def corroborate_destination_display(
    telemetry_celsius: float | None,
    observed_celsius: float | None,
    *,
    tolerance_c: float = DISPLAY_AGREEMENT_C,
    config: KernelConfig = DEFAULT_CONFIG,
) -> CorroborationResult:
    """Does the photographed freezer display agree with the telemetry we hold?

    Two independent failures are worth separating and both are caught here. The
    responder is standing at the wrong freezer, in which case the display disagrees with
    the telemetry for the freezer the plan names. Or the telemetry stream is lying,
    which the same disagreement also surfaces, from the opposite direction.

    A display that is inside tolerance but above the N4 ceiling still fails, because
    agreeing with a reading that is itself unsafe is not corroboration of anything worth
    committing.
    """
    if observed_celsius is None:
        return CorroborationResult(
            status=CorroborationStatus.ABSENT,
            kind="destination_display",
            detail="no destination display photo was supplied, or no reading could be made out",
            expected="" if telemetry_celsius is None else f"{telemetry_celsius:.1f}C",
        )
    if telemetry_celsius is None:
        return CorroborationResult(
            status=CorroborationStatus.ABSENT,
            kind="destination_display",
            detail="no telemetry reading exists for this destination to compare against",
            observed=f"{observed_celsius:.1f}C",
        )

    gap = abs(observed_celsius - telemetry_celsius)
    observed = f"{observed_celsius:.1f}C"
    expected = f"{telemetry_celsius:.1f}C"

    if gap > tolerance_c:
        return CorroborationResult(
            status=CorroborationStatus.MISMATCH,
            kind="destination_display",
            detail=(
                f"the photographed display and the telemetry reading differ by "
                f"{gap:.1f}C, beyond the {tolerance_c:.1f}C agreement window"
            ),
            observed=observed,
            expected=expected,
            evidence_sources=["capture:destination-display", "telemetry:destination"],
        )
    if observed_celsius > config.destination_temp_ceiling_c:
        return CorroborationResult(
            status=CorroborationStatus.MISMATCH,
            kind="destination_display",
            detail=(
                f"the photographed display reads {observed}, above the "
                f"{config.destination_temp_ceiling_c:.1f}C ceiling a destination must hold"
            ),
            observed=observed,
            expected=expected,
            evidence_sources=["capture:destination-display", "telemetry:destination"],
        )
    return CorroborationResult(
        status=CorroborationStatus.CONFIRMED,
        kind="destination_display",
        detail=(
            f"the photographed display agrees with telemetry to within {gap:.1f}C and "
            "is below the destination ceiling"
        ),
        observed=observed,
        expected=expected,
        evidence_sources=["capture:destination-display", "telemetry:destination"],
    )


_AFFIRMATIVE = ("confirm", "confirmed", "yes", "correct", "affirmative", "loaded", "placed", "done")
_NEGATIVE = ("abort", "stop", "cancel", "no", "wrong", "negative", "hold")


def corroborate_voice_confirmation(transcript: str) -> CorroborationResult:
    """Did the responder say the thing out loud?

    A responder in cryogenic gloves cannot reliably operate a touchscreen, which is the
    friction this exists to remove. It is a second channel and never an authority: a
    confirmed transcript with a mismatched label still refuses, because words are the
    weakest evidence in the room.

    Negation is checked before affirmation on purpose. "No, that is not confirmed"
    contains an affirmative token, and reading it as a yes would be the worst possible
    failure mode for a spoken control.
    """
    text = transcript.strip().lower()
    if not text:
        return CorroborationResult(
            status=CorroborationStatus.ABSENT,
            kind="voice_confirmation",
            detail="no voice confirmation was supplied, or nothing could be transcribed",
        )
    if any(word in text for word in _NEGATIVE):
        return CorroborationResult(
            status=CorroborationStatus.MISMATCH,
            kind="voice_confirmation",
            detail="the spoken confirmation withholds or countermands consent",
            observed=transcript.strip()[:200],
            evidence_sources=["capture:voice"],
        )
    if any(word in text for word in _AFFIRMATIVE):
        return CorroborationResult(
            status=CorroborationStatus.CONFIRMED,
            kind="voice_confirmation",
            detail="the responder spoke an affirmative confirmation",
            observed=transcript.strip()[:200],
            evidence_sources=["capture:voice"],
        )
    return CorroborationResult(
        status=CorroborationStatus.ABSENT,
        kind="voice_confirmation",
        detail="the transcript carries neither a confirmation nor a refusal",
        observed=transcript.strip()[:200],
        evidence_sources=["capture:voice"],
    )


def adjudicate(results: list[CorroborationResult]) -> tuple[bool, str, list[str]]:
    """Turn a set of corroboration results into one allow-or-refuse decision.

    Returns ``(allowed, reason, evidence_sources)``.

    Any single contradiction refuses. That asymmetry is the point: two confirmations and
    one mismatch describes a responder holding the right box at the wrong freezer, and
    averaging that into an approval is how a specimen ends up somewhere nobody can find
    it. Nothing here can raise authority above what the token already grants, so a
    forged capture buys an attacker no access they did not already have.

    All-absent is allowed and reported as such, so the receipt records that the commit
    rested on the token alone.
    """
    contradictions = [r for r in results if r.contradicts]
    if contradictions:
        first = contradictions[0]
        return False, f"{first.kind}: {first.detail}", []

    confirmations = [r for r in results if r.confirms]
    sources = sorted({s for r in confirmations for s in r.evidence_sources})
    if not confirmations:
        return True, "no capture evidence supplied; authorised by task token alone", []
    return True, f"corroborated by {', '.join(r.kind for r in confirmations)}", sources
