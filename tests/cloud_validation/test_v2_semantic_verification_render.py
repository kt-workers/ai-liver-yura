from __future__ import annotations

from app.domain.llm import LLMModelClass, LLMReasoningEffort
from cloud_validation import v2_semantic_verification_lab as lab
from cloud_validation.v2_semantic_verification_matrix import EXTRA_PRESETS
from cloud_validation.v2_semantic_verification_render import _gpt56_model_policy


def test_gpt56_minimal_maps_to_provider_none() -> None:
    policies = _gpt56_model_policy("gpt-5.6-sol")

    policy = policies[LLMModelClass.BALANCED]
    assert policy.reasoning_by_effort[LLMReasoningEffort.MINIMAL] == "none"
    assert policy.reasoning_by_effort[LLMReasoningEffort.MEDIUM] == "medium"


def test_render_entrypoint_registers_extended_failure_matrix() -> None:
    assert set(EXTRA_PRESETS).issubset(lab._PRESETS)
