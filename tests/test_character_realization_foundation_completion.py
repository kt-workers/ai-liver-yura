from __future__ import annotations

import json

import pytest

from app.adapters.prompt.character_language_realizer_prompt_builder import (
    CharacterLanguageRealizerPromptBuilder,
)
from app.adapters.prompt.character_realization_validator_prompt_builder import (
    CharacterRealizationValidatorPromptBuilder,
)
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ResponseClaim,
    ResponseContext,
)
from app.domain.character_utterance import LinguisticPerformance
from app.domain.semantic_utterance import (
    SemanticProposition,
    SemanticTarget,
    SemanticUtterancePlan,
)
from app.domain.semantic_validation import RealizedSemanticObservation
from app.runtime.character_language_realizer_service import CharacterLanguageRealizerService
from app.runtime.character_realization_validator import CharacterRealizationValidator


def _source() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="確定済み意味を自然に表現する",
        source_event_id="foundation-completion",
        context={
            "event_id": "foundation-completion",
            "trace_context": {"trace_id": "trace-foundation"},
            "activity_turn_id": "turn-foundation",
        },
    )


def _internal_state_context() -> ResponseContext:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "energy"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="energy",
                state="low",
                certainty="high",
                concept=None,
            ),
        ),
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )
    return ResponseContext(
        user_input="今の元気はどんな感じ？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在のenergyへ直接答える",
        speech_act="question",
        memory={
            "semantic_utterance_plan": plan.as_context(),
            "semantic_validation": {
                "accepted": True,
                "reason": "semantic_plan_consistent",
                "differences": [],
            },
        },
    )


class _CharacterModel:
    def __init__(self, speech: str) -> None:
        self.speech = speech
        self.activities: list[Activity] = []

    async def generate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return json.dumps(
            {
                "speech": self.speech,
                "linguistic_performance": {
                    "phrasing": [self.speech],
                    "emphasis": [],
                    "delivery_tags": [],
                },
                "semantic_realizations": ["proposition:0:energy"],
            },
            ensure_ascii=False,
        )


class _ValidationModel:
    def __init__(self, speech: str, state_span: str) -> None:
        self.speech = speech
        self.state_span = state_span

    async def validate_character_response(self, activity: Activity) -> str:
        if activity.context.get("llm_role") == "character_realization_observer":
            return json.dumps(
                {
                    "observations": [
                        {
                            "realization_id": "proposition:0:energy",
                            "predicate_realized": True,
                            "observed_state": "low",
                            "observed_certainty": "high",
                            "predicate_evidence_spans": ["元気"],
                            "state_evidence_spans": [self.state_span],
                            "certainty_evidence_spans": [],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "accepted": True,
                "reason": "post_observation_semantic_contract_consistent",
                "differences": [],
                "semantic_checks": {
                    "required_content_preserved": True,
                    "forbidden_additions_absent": True,
                    "unsupported_new_fact_absent": True,
                    "existence_boundary_preserved": True,
                    "budget_preserved": True,
                },
                "realized_proposition_checks": [
                    {
                        "realization_id": "proposition:0:energy",
                        "predicate_preserved": True,
                        "predicate_evidence_spans": ["元気"],
                        "concept_preserved": True,
                        "concept_evidence_spans": [],
                    }
                ],
            },
            ensure_ascii=False,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "speech", "state_span"),
    (
        (
            CharacterProfile(
                name="ゆら",
                personality="穏やか",
                speaking_style="やわらかく余韻のある話し方",
                streaming_style="落ち着いて応答する",
            ),
            "元気は控えめな感じだよ。",
            "控えめな感じ",
        ),
        (
            CharacterProfile(
                name="ゆら",
                personality="穏やか",
                speaking_style="短く簡潔な話し方",
                streaming_style="簡潔に応答する",
            ),
            "今は元気、あまり強くないよ。",
            "あまり強くない",
        ),
    ),
)
async def test_character_profile_surface_variation_preserves_same_semantic_plan(
    profile: CharacterProfile,
    speech: str,
    state_span: str,
) -> None:
    context = _internal_state_context()
    character_model = _CharacterModel(speech)
    response = await CharacterLanguageRealizerService(
        character_model,
        CharacterLanguageRealizerPromptBuilder(),
        profile,
    ).generate(_source(), context)

    validation = await CharacterRealizationValidator(
        model=_ValidationModel(speech, state_span),
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    ).validate(_source(), context, response)

    assert response.speech == speech
    assert validation.accepted is True
    assert validation.reason == "post_observation_semantic_contract_consistent"
    prompt = str(character_model.activities[0].context["plugin_prompt_override"])
    assert profile.speaking_style in prompt
    assert '"predicate": "energy"' in prompt
    assert '"state": "low"' in prompt


def _knowledge_plan() -> SemanticUtterancePlan:
    return SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("knowledge", "deep_sea_pressure_adaptation"),
        propositions=(
            SemanticProposition(
                kind="knowledge_fact",
                predicate="pressure_adaptation",
                state="present",
                certainty="high",
                concept="flexible_cell_membrane",
                evidence_refs=("memory.semantic_fact.deep_sea_pressure",),
            ),
        ),
        required_content=("pressure_adaptation",),
        forbidden_additions=("unsupported_external_fact",),
        response_length="short",
        self_disclosure="none",
        question_budget=0,
        new_direction_budget=0,
    )


def _knowledge_response() -> CharacterResponse:
    speech = "深海生物は柔軟な細胞膜で高い圧力に適応するよ。"
    return CharacterResponse(
        speech=speech,
        expression="neutral",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=LinguisticPerformance(phrasing=(speech,)),
        semantic_realizations=("proposition:0:pressure_adaptation",),
    )


def test_memory_knowledge_fixture_uses_same_typed_observation_comparison_contract() -> None:
    plan = _knowledge_plan()
    response = _knowledge_response()
    exact = RealizedSemanticObservation(
        realization_id="proposition:0:pressure_adaptation",
        predicate_realized=True,
        observed_state="present",
        observed_certainty="high",
        predicate_evidence_spans=("高い圧力に適応",),
        state_evidence_spans=("適応する",),
        certainty_evidence_spans=(),
    )

    assert CharacterRealizationValidator._observation_differences(
        plan,
        response,
        (exact,),
    ) == []

    changed = RealizedSemanticObservation(
        realization_id=exact.realization_id,
        predicate_realized=True,
        observed_state="unknown",
        observed_certainty="high",
        predicate_evidence_spans=exact.predicate_evidence_spans,
        state_evidence_spans=exact.state_evidence_spans,
        certainty_evidence_spans=(),
    )
    differences = CharacterRealizationValidator._observation_differences(
        plan,
        response,
        (changed,),
    )
    assert (
        "proposition:0:pressure_adaptation:observed_state_mismatch:"
        "expected=present:observed=unknown"
        in differences
    )


def test_memory_knowledge_fixture_does_not_expand_current_production_routing() -> None:
    plan = _knowledge_plan()
    context = ResponseContext(
        user_input="深海生物はどう高圧に適応するの？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="Knowledgeへ答える",
        memory={
            "semantic_utterance_plan": plan.as_context(),
            "semantic_validation": {
                "accepted": True,
                "reason": "semantic_plan_consistent",
                "differences": [],
            },
        },
    )

    assert CharacterLanguageRealizerService._uses_language_realizer(context) is False
    assert CharacterRealizationValidator._uses_realization_validation(context, plan) is False
