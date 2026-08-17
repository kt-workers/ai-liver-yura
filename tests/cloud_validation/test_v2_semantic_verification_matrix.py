from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cloud_validation.v2_semantic_verification_lab import (
    SemanticVerificationLabRequest,
    build_validation_fixture,
)
from cloud_validation.v2_semantic_verification_matrix import EXTRA_PRESETS

NOW = datetime(2026, 8, 17, 14, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("name", sorted(EXTRA_PRESETS))
def test_extra_preset_can_build_through_production_authorities(name: str) -> None:
    request = SemanticVerificationLabRequest.model_validate(EXTRA_PRESETS[name])

    fixture = build_validation_fixture(request, now=NOW)

    assert fixture.semantic_plan.candidate.propositions
    assert fixture.utterance.candidate.segments
    assert fixture.snapshot.semantic_plan is fixture.semantic_plan
    assert fixture.snapshot.utterance is fixture.utterance


def test_matrix_contains_both_accept_and_reject_expectations() -> None:
    expectations = {
        SemanticVerificationLabRequest.model_validate(item).expected_acceptance
        for item in EXTRA_PRESETS.values()
    }

    assert expectations == {"accepted", "rejected"}
