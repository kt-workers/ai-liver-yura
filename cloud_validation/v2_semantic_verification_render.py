from __future__ import annotations

from app.adapters.llm.openai_responses import OpenAIResponsesModelPolicy
from app.domain.llm import LLMModelClass, LLMReasoningEffort
from cloud_validation import v2_semantic_verification_lab as lab
from cloud_validation.v2_semantic_verification_matrix import EXTRA_PRESETS


def _gpt56_model_policy(model: str) -> dict[LLMModelClass, OpenAIResponsesModelPolicy]:
    efforts = {
        LLMReasoningEffort.MINIMAL: "none",
        LLMReasoningEffort.LOW: "low",
        LLMReasoningEffort.MEDIUM: "medium",
        LLMReasoningEffort.HIGH: "high",
    }
    return {
        model_class: OpenAIResponsesModelPolicy(model, efforts)
        for model_class in (
            LLMModelClass.FAST,
            LLMModelClass.BALANCED,
            LLMModelClass.DEEP_REASONING,
        )
    }


lab._model_policy = _gpt56_model_policy
lab._PRESETS.update(EXTRA_PRESETS)
app = lab.app

__all__ = ["app"]
