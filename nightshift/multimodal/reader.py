"""Gemini reads what is in a photograph or a voice note, and nothing else.

This module is the only place a model touches responder capture. It returns strings and
numbers describing what it saw or heard. It never decides whether a pickup may proceed,
never sees a token, and never writes state. That decision belongs to
``nightshift.safety_kernel.corroboration``, which is pure arithmetic over the values
returned here and over telemetry this system already holds.

Keeping the split hard is what makes the capture usable as evidence at all. A model that
misreads a label produces a MISMATCH and a refusal, which is a correct outcome. A model
that were allowed to *conclude* anything would produce a commit, which is not.

Every reader fails to ``None`` rather than raising. A responder standing in a cold room
with a bad connection must still be able to move specimens on the task token alone, and
the receipt records that no capture corroborated it.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

MAX_CAPTURE_BYTES = 4_000_000
"""Largest single capture accepted, before base64 expansion.

A phone photo is well under this. The cap exists so an unauthenticated route cannot be
used to push arbitrarily large bodies into a model call that costs money.
"""

_LABEL_PROMPT = (
    "This is a photograph of a laboratory specimen container label. Read the container "
    "identifier printed on it. Container identifiers look like C-0421 or CNT-00184. "
    "Reply with the identifier only, nothing else. If you cannot read an identifier "
    "with confidence, reply exactly UNREADABLE."
)

_DISPLAY_PROMPT = (
    "This is a photograph of an ultra-low-temperature freezer's front display. Read the "
    "current temperature it shows, in degrees Celsius. These units run between -95 and "
    "-50 degrees. Reply with the number only, including the minus sign, for example "
    "-79.4. If you cannot read a temperature with confidence, reply exactly UNREADABLE."
)

_VOICE_PROMPT = (
    "Transcribe this short voice note from a laboratory responder wearing cryogenic "
    "gloves. Reply with the transcript only. If there is no intelligible speech, reply "
    "exactly UNREADABLE."
)

_UNREADABLE = "UNREADABLE"
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


@dataclass
class CaptureReader:
    """Reads responder captures with Gemini through Vertex AI.

    ``model`` defaults to the same Gemini the fleet runs on. There is no separate
    multimodal model to configure or a second endpoint to reason about.
    """

    model: str
    project: str = ""
    location: str = "global"
    timeout_s: float = 20.0

    def _generate(self, prompt: str, data: bytes, mime_type: str) -> str | None:
        if not data or len(data) > MAX_CAPTURE_BYTES:
            return None
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(
                vertexai=True, project=self.project or None, location=self.location
            )
            response = client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(data=data, mime_type=mime_type),
                    types.Part(text=prompt),
                ],
                config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=64),
            )
            text = (response.text or "").strip()
        except Exception as exc:
            log.warning("capture reading unavailable (%s); continuing without it", exc)
            return None
        if not text or text.upper().startswith(_UNREADABLE):
            return None
        return text

    def read_container_label(self, image: bytes, mime_type: str = "image/jpeg") -> str | None:
        """The container identifier printed on a photographed label, or ``None``."""
        return self._generate(_LABEL_PROMPT, image, mime_type)

    def read_freezer_display(self, image: bytes, mime_type: str = "image/jpeg") -> float | None:
        """The temperature shown on a photographed freezer display, or ``None``.

        Parsed out of the reply rather than trusted as a bare float, because a model
        asked for a number sometimes returns "-79.4 C". A value outside the range an ULT
        freezer can physically occupy is discarded: that is a misread, and passing it on
        would let the corroboration step compare against nonsense.
        """
        text = self._generate(_DISPLAY_PROMPT, image, mime_type)
        if text is None:
            return None
        match = _NUMBER.search(text)
        if match is None:
            return None
        try:
            celsius = float(match.group())
        except ValueError:
            return None
        if not (-120.0 <= celsius <= 20.0):
            return None
        return celsius

    def transcribe_confirmation(self, audio: bytes, mime_type: str = "audio/webm") -> str | None:
        """What the responder said, or ``None``."""
        return self._generate(_VOICE_PROMPT, audio, mime_type)


def capture_mime(value: str | None, fallback: str) -> str:
    """The MIME type the browser stamped on a data URL, or ``fallback``.

    Worth reading rather than assuming. Safari's ``MediaRecorder`` produces mp4 while
    Chrome and Firefox produce webm, so hardcoding one label means the model is handed
    bytes that contradict their declared type on whichever browser lost the coin toss.
    That degrades to an unreadable capture, which is safe but is also a capability
    silently missing on an entire browser.
    """
    if not value or not value.startswith("data:"):
        return fallback
    header = value.split(",", 1)[0]
    mime = header[5:].split(";", 1)[0].strip()
    return mime or fallback


def decode_capture(value: str | None) -> bytes | None:
    """Decode a base64 capture from an untrusted request body.

    Accepts a bare base64 payload or a full ``data:`` URL, because a browser's
    ``canvas.toDataURL`` and ``FileReader`` produce the latter and making every caller
    strip the prefix is an invitation to get it wrong. Anything that does not decode is
    treated as absent rather than as an error: a malformed capture must degrade to
    token-only authority, not fail a rescue.
    """
    if not value:
        return None
    payload = value.split(",", 1)[1] if value.startswith("data:") else value
    try:
        data = base64.b64decode(payload, validate=True)
    except Exception:
        return None
    if not data or len(data) > MAX_CAPTURE_BYTES:
        return None
    return data


def build_reader(settings: Any) -> CaptureReader:
    return CaptureReader(
        model=settings.model_id,
        project=settings.project_id,
        location=settings.model_location,
    )
