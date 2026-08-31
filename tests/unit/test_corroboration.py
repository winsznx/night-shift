"""Capture evidence may refuse a scan. It may never authorise one.

A custody commit used to rest on a bearer token that was published in plaintext inside
the signed manifest. These tests cover the deterministic half of the replacement: what a
photograph or a voice note is compared against, and what happens when they disagree.

Nothing here calls a model. That is the property under test.
"""

from __future__ import annotations

import pytest

from nightshift.safety_kernel.config import DEFAULT_CONFIG
from nightshift.safety_kernel.corroboration import (
    CorroborationStatus,
    adjudicate,
    corroborate_container_label,
    corroborate_destination_display,
    corroborate_voice_confirmation,
    normalize_container_id,
)


class TestContainerLabel:
    def test_a_matching_label_confirms(self) -> None:
        assert corroborate_container_label("C-0421", "C-0421").status is (
            CorroborationStatus.CONFIRMED
        )

    @pytest.mark.parametrize("observed", ["c-0421", "C 0421", "C0421", " C-0421 ", "c0421"])
    def test_case_spacing_and_punctuation_are_forgiven(self, observed: str) -> None:
        """A camera and a print head change the glyphs, not which box is in the hand."""
        assert corroborate_container_label("C-0421", observed).confirms

    @pytest.mark.parametrize("observed", ["C-0422", "C-0431", "D-0421", "C-042"])
    def test_a_single_wrong_character_is_a_mismatch(self, observed: str) -> None:
        """One wrong digit is a different box, so nothing about it is forgiven."""
        result = corroborate_container_label("C-0421", observed)

        assert result.status is CorroborationStatus.MISMATCH
        assert result.observed == observed
        assert result.expected == "C-0421"

    @pytest.mark.parametrize("observed", ["", "   "])
    def test_an_unreadable_label_is_absent_not_a_failure(self, observed: str) -> None:
        """A dead phone battery must not block a rescue."""
        assert corroborate_container_label("C-0421", observed).status is (
            CorroborationStatus.ABSENT
        )

    def test_normalisation_keeps_every_alphanumeric(self) -> None:
        assert normalize_container_id("cnt-00184") == "CNT00184"


class TestDestinationDisplay:
    def test_agreement_within_tolerance_confirms(self) -> None:
        result = corroborate_destination_display(-79.4, -80.1)

        assert result.confirms

    def test_the_wrong_freezer_is_caught(self) -> None:
        """Standing at a failing unit while the plan names a backup one."""
        result = corroborate_destination_display(-79.4, -55.0)

        assert result.status is CorroborationStatus.MISMATCH
        assert "beyond" in result.detail

    def test_a_display_agreeing_with_an_unsafe_reading_still_refuses(self) -> None:
        """Agreeing with a reading that is itself unsafe corroborates nothing."""
        result = corroborate_destination_display(-58.0, -58.5)

        assert result.status is CorroborationStatus.MISMATCH
        assert str(DEFAULT_CONFIG.destination_temp_ceiling_c) in result.detail

    def test_a_missing_photo_is_absent(self) -> None:
        assert corroborate_destination_display(-79.4, None).status is CorroborationStatus.ABSENT

    def test_missing_telemetry_is_absent_rather_than_a_mismatch(self) -> None:
        """Nothing to compare against is not the same as a disagreement."""
        assert corroborate_destination_display(None, -79.4).status is CorroborationStatus.ABSENT


class TestVoiceConfirmation:
    @pytest.mark.parametrize("said", ["confirmed", "Yes, loaded", "that's correct", "placed"])
    def test_an_affirmative_confirms(self, said: str) -> None:
        assert corroborate_voice_confirmation(said).confirms

    @pytest.mark.parametrize(
        "said",
        ["abort", "no, that is not confirmed", "stop, wrong freezer", "hold on, cancel that"],
    )
    def test_negation_wins_over_an_affirmative_token(self, said: str) -> None:
        """ "No, that is not confirmed" contains "confirm". Reading it as yes would be
        the worst available failure for a spoken control."""
        assert corroborate_voice_confirmation(said).status is CorroborationStatus.MISMATCH

    def test_unrelated_speech_is_absent(self) -> None:
        result = corroborate_voice_confirmation("it's freezing in here")

        assert result.status is CorroborationStatus.ABSENT

    def test_silence_is_absent(self) -> None:
        assert corroborate_voice_confirmation("").status is CorroborationStatus.ABSENT


class TestAdjudication:
    def test_no_captures_is_allowed_and_says_so(self) -> None:
        allowed, reason, sources = adjudicate([])

        assert allowed is True
        assert "task token alone" in reason
        assert sources == []

    def test_all_confirmations_allow_and_record_their_sources(self) -> None:
        allowed, reason, sources = adjudicate(
            [
                corroborate_container_label("C-0421", "C-0421"),
                corroborate_destination_display(-79.4, -80.0),
            ]
        )

        assert allowed is True
        assert "capture:container-label" in sources
        assert "telemetry:destination" in sources

    def test_one_contradiction_refuses_despite_two_confirmations(self) -> None:
        """The right box at the wrong freezer. Averaging this into an approval is how a
        specimen ends up somewhere nobody can find it."""
        allowed, reason, sources = adjudicate(
            [
                corroborate_container_label("C-0421", "C-0421"),
                corroborate_voice_confirmation("confirmed"),
                corroborate_destination_display(-79.4, -50.0),
            ]
        )

        assert allowed is False
        assert reason.startswith("destination_display")
        assert sources == []

    def test_absence_alongside_a_confirmation_still_allows(self) -> None:
        allowed, _, sources = adjudicate(
            [
                corroborate_container_label("C-0421", "C-0421"),
                corroborate_voice_confirmation(""),
            ]
        )

        assert allowed is True
        assert sources == ["capture:container-label"]

    def test_capture_evidence_cannot_grant_authority(self) -> None:
        """The security property. A confirmation returns allowed=True, which is exactly
        what supplying no capture at all returns, so a forged photograph buys nothing
        the task token did not already grant."""
        with_capture, _, _ = adjudicate([corroborate_container_label("C-0421", "C-0421")])
        without_capture, _, _ = adjudicate([])

        assert with_capture == without_capture is True
