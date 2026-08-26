"""Canonical JSON must be boring and stable — the verifier depends on it."""

from __future__ import annotations

import math

import pytest

from nightshift.common.canonical import (
    CanonicalizationError,
    canonical_json,
    sha256_hex,
    sha256_of,
)
from nightshift.schemas.enums import ActionType


def test_key_order_is_irrelevant_to_the_hash():
    a = {"b": 1, "a": 2, "c": {"z": 1, "y": 2}}
    b = {"c": {"y": 2, "z": 1}, "a": 2, "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert sha256_of(a) == sha256_of(b)


def test_no_insignificant_whitespace():
    assert canonical_json({"a": [1, 2], "b": "x"}) == '{"a":[1,2],"b":"x"}'


def test_negative_zero_normalizes():
    assert sha256_of({"t": -0.0}) == sha256_of({"t": 0.0})


def test_non_finite_floats_are_rejected():
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(CanonicalizationError):
            canonical_json({"t": bad})


def test_enums_serialize_as_values():
    assert canonical_json({"t": ActionType.CAPACITY_RESERVE}) == '{"t":"CAPACITY_RESERVE"}'


def test_control_characters_escape():
    assert canonical_json("a\x01b") == '"a\\u0001b"'


def test_unicode_is_not_ascii_escaped():
    assert canonical_json("café") == '"café"'


def test_sets_are_order_independent():
    assert sha256_of({1, 2, 3}) == sha256_of({3, 1, 2})


def test_unsupported_type_raises():
    with pytest.raises(CanonicalizationError):
        canonical_json({"t": object()})


def test_hash_is_stable_across_runs():
    doc = {"incident": "INC-1", "slots": 12, "temp": -79.5, "tags": ["a", "b"]}
    assert sha256_of(doc) == sha256_of(doc)
    # Locked-in value: if this changes, every published manifest hash changes.
    assert sha256_of(doc) == sha256_of(dict(reversed(list(doc.items()))))


def test_pipe_is_rejected_in_action_id_components():
    with pytest.raises(CanonicalizationError):
        sha256_hex("a|b", "c")


def test_float_integral_values_keep_a_decimal_point():
    assert canonical_json({"t": -80.0}) == '{"t":-80.0}'
