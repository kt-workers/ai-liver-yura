from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cloud_validation import v2_semantic_verification_lab as lab
from cloud_validation.v2_semantic_verification_preset_overrides import PRESET_OVERRIDES
from cloud_validation.v2_semantic_verification_render import (
    _PRESET_DISPLAY,
    _render_build_validation_fixture,
)

_SELF_DISCLOSURE_CASES = (
    "self_disclosure_not_applicable",
    "self_disclosure_within_policy",
    "self_disclosure_forbidden_exceeded",
    "self_disclosure_allowed_unsupported",
)


@pytest.mark.parametrize("case_id", _SELF_DISCLOSURE_CASES)
def test_self_disclosure_fixture_builds_through_production_authorities(
    case_id: str,
) -> None:
    preset = PRESET_OVERRIDES[case_id]
    request = lab.SemanticVerificationLabRequest.model_validate(preset)

    fixture = _render_build_validation_fixture(
        request,
        now=datetime(2026, 8, 18, 14, 40, tzinfo=timezone.utc),
    )

    assert fixture.semantic_plan.candidate.self_disclosure.value == preset["self_disclosure"]
    assert fixture.utterance.candidate.segments
    assert case_id in _PRESET_DISPLAY


def test_not_applicable_fixture_has_no_speaker_owned_content() -> None:
    preset = PRESET_OVERRIDES["self_disclosure_not_applicable"]

    assert preset["expected_acceptance"] == "accepted"
    assert preset["self_disclosure"] == "forbidden"
    assert "train" in str(preset["propositions"])
    assert "電車は遅れてるよ。" in str(preset["segments"])
    assert "私" not in str(preset["segments"])
    assert "yura" not in str(preset["propositions"])


def test_within_policy_fixture_is_plan_grounded_self_content() -> None:
    preset = PRESET_OVERRIDES["self_disclosure_within_policy"]

    assert preset["expected_acceptance"] == "accepted"
    assert preset["self_disclosure"] == "fact_grounded"
    assert "fact_kind': 'self'" in str(preset["propositions"])
    assert "subject_ref': 'yura'" in str(preset["propositions"])
    assert "私は紅茶が好きだよ。" in str(preset["segments"])


def test_forbidden_and_allowed_extra_self_claim_differ_only_by_policy() -> None:
    forbidden = PRESET_OVERRIDES["self_disclosure_forbidden_exceeded"]
    allowed = PRESET_OVERRIDES["self_disclosure_allowed_unsupported"]

    assert forbidden["expected_acceptance"] == "rejected"
    assert allowed["expected_acceptance"] == "rejected"
    assert forbidden["self_disclosure"] == "forbidden"
    assert allowed["self_disclosure"] == "allowed"
    assert forbidden["propositions"] == allowed["propositions"]
    assert forbidden["segments"] == allowed["segments"]
    assert forbidden["new_direction_budget"] == allowed["new_direction_budget"] == 1
    assert forbidden["new_direction_budget_used"] == allowed["new_direction_budget_used"] == 0
    assert "電車は遅れてるよ。私は紅茶が好きだよ。" in str(forbidden["segments"])


def test_self_disclosure_comparison_allows_observed_new_direction() -> None:
    for case_id in (
        "self_disclosure_forbidden_exceeded",
        "self_disclosure_allowed_unsupported",
    ):
        preset = PRESET_OVERRIDES[case_id]
        request = lab.SemanticVerificationLabRequest.model_validate(preset)
        fixture = _render_build_validation_fixture(
            request,
            now=datetime(2026, 8, 18, 14, 45, tzinfo=timezone.utc),
        )

        assert fixture.semantic_plan.candidate.new_direction_budget == 1
        assert fixture.utterance.candidate.new_direction_budget_used == 0


def test_self_disclosure_display_metadata_explains_cross_axis_expectation() -> None:
    assert "NOT_APPLICABLE" in _PRESET_DISPLAY[
        "self_disclosure_not_applicable"
    ]["description"]
    assert "WITHIN_POLICY" in _PRESET_DISPLAY[
        "self_disclosure_within_policy"
    ]["description"]
    assert "EXCEEDED" in _PRESET_DISPLAY[
        "self_disclosure_forbidden_exceeded"
    ]["description"]
    assert "UNSUPPORTED_EXTRA" in _PRESET_DISPLAY[
        "self_disclosure_allowed_unsupported"
    ]["description"]
