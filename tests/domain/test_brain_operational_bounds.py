from dataclasses import replace

import pytest

from app.domain.brain_operational_bounds import (
    V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    InputBounds,
)


@pytest.mark.parametrize(
    "field_name",
    (
        "max_text_codepoints",
        "max_payload_json_bytes",
        "max_session_metadata_json_bytes",
        "max_active_sessions_per_source",
    ),
)
def test_input_bounds_reject_bool_zero_and_negative(field_name: str) -> None:
    values = dict(
        max_text_codepoints=1,
        max_payload_json_bytes=1,
        max_session_metadata_json_bytes=1,
        max_active_sessions_per_source=1,
    )
    for invalid in (True, 0, -1):
        with pytest.raises(ValueError):
            InputBounds(**{**values, field_name: invalid})


def test_shared_policy_rejects_cross_owner_capacity_mismatch() -> None:
    with pytest.raises(ValueError):
        replace(
            V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
            semantic_verification=replace(
                V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.semantic_verification,
                max_proposition_relations=(
                    V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.speech_semantics.max_propositions - 1
                ),
            ),
        )

    with pytest.raises(ValueError):
        replace(
            V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
            planning=replace(
                V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.planning,
                max_capability_descriptors=(
                    V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.executive.max_capability_descriptors + 1
                ),
            ),
        )


def test_v2_baseline_policy_has_canonical_identity_and_input_values() -> None:
    policy = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
    assert policy.policy_id == "v2.brain-operational-bounds.default"
    assert policy.policy_revision == 1
    assert policy.input.max_text_codepoints == 32768
    assert policy.input.max_payload_json_bytes == 262144
    assert policy.input.max_session_metadata_json_bytes == 32768
    assert policy.input.max_active_sessions_per_source == 64
