from __future__ import annotations

from dataclasses import replace

from app.domain.character_response import ResponseContext
from app.domain.semantic_utterance import SemanticUtterancePlan


def project_semantic_discourse_context(
    context: ResponseContext,
    semantic_plan: SemanticUtterancePlan,
) -> SemanticUtterancePlan:
    """ResponseContext由来の有限な談話制約をSemantic Planへ投影する。"""

    if context.constraints.get("avoid_repetition") is not True:
        return semantic_plan

    recent_speech = context.recent_speech_summary.strip()
    if not recent_speech:
        return semantic_plan

    discourse_context = dict(semantic_plan.discourse_context)
    discourse_context["recent_speech_summary"] = recent_speech
    discourse_context["repetition_policy"] = "avoid_semantic_and_phrasal_repeat"
    return replace(semantic_plan, discourse_context=discourse_context)
