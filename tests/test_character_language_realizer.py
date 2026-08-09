from __future__ import annotations

import json

import pytest

from app.adapters.prompt.character_language_realizer_prompt_builder import (
    CharacterLanguageRealizerPromptBuilder,
)
from app.domain.activities import Activity, ActivityType
from app.domain.character import CharacterProfile
from app.domain.character_response import (
    ActivityExecutionStatus,
    ResponseClaim,
    ResponseContext,
)
from app.domain.semantic_utterance import (
    SemanticProposition,
    SemanticTarget,
    SemanticUtterancePlan,
)
from app.runtime.character_language_realizer_service import (
    CharacterLanguageRealizerService,
)


class _RecordingCharacterModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.activities: list[Activity] = []

    async def generate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return self.response


def _profile(*, style: str = "やわらかく穏やかな話し方") -> CharacterProfile:
    return CharacterProfile(
        name="ゆら",
        personality="穏やかで好奇心を持つが、相手の意図を優先する",
        speaking_style=style,
        streaming_style="会話相手へ自然に反応する",
    )


def _semantic_plan() -> SemanticUtterancePlan:
    return SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "joy"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="joy",
                state="absent",
                certainty="high",
                evidence_refs=("emotion.current.reactive.joy",),
            ),
        ),
        forbidden_additions=(
            "substitute_non_target_state",
            "unsupported_new_self_state",
        ),
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )


def _context(*, include_semantic_plan: bool = True) -> ResponseContext:
    memory: dict[str, object] = {}
    if include_semantic_plan:
        memory["semantic_utterance_plan"] = _semantic_plan().as_context()
    return ResponseContext(
        user_input="楽しい？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の内部状態へ直接答える",
        speech_act="question",
        emotion={
            "current": {
                "reactive": {
                    "joy": 0.0,
                    "amusement": 0.0,
                    "calm": 0.58,
                }
            }
        },
        drive={"curiosity": 0.82, "engagement": 0.78},
        memory=memory,
    )


def test_language_realizer_prompt_exposes_semantics_not_raw_internal_state() -> None:
    prompt = CharacterLanguageRealizerPromptBuilder().build(
        _context(),
        character_profile=_profile(),
        correction=None,
    )

    assert "# Semantic Utterance Plan for Character" in prompt
    assert '"predicate": "joy"' in prompt
    assert '"state": "absent"' in prompt
    assert '"name": "ゆら"' in prompt
    assert "emotion.current.reactive.joy" not in prompt
    assert "evidence_refs" not in prompt
    assert "0.82" not in prompt
    assert "0.58" not in prompt
    assert "楽しい？" not in prompt


def test_same_semantic_plan_keeps_facts_while_character_profile_changes_style_context() -> None:
    builder = CharacterLanguageRealizerPromptBuilder()
    gentle = builder.build(
        _context(),
        character_profile=_profile(style="やわらかく穏やかな話し方"),
        correction=None,
    )
    concise = builder.build(
        _context(),
        character_profile=_profile(style="短く率直な話し方"),
        correction=None,
    )

    assert '"predicate": "joy"' in gentle
    assert '"state": "absent"' in gentle
    assert '"predicate": "joy"' in concise
    assert '"state": "absent"' in concise
    assert "やわらかく穏やかな話し方" in gentle
    assert "短く率直な話し方" in concise


def test_character_utterance_schema_has_no_acoustic_parameters() -> None:
    raw = json.dumps(
        {
            "speech": "今は、そこまで楽しいって感じじゃないかな。",
            "linguistic_performance": {
                "phrasing": ["今は、", "そこまで楽しいって感じじゃないかな。"],
                "emphasis": ["そこまで"],
                "delivery_tags": ["gentle"],
            },
            "semantic_realizations": ["proposition:0:joy"],
        },
        ensure_ascii=False,
    )

    parsed = CharacterLanguageRealizerService.parse(raw)

    assert parsed is not None
    assert parsed.speech == "今は、そこまで楽しいって感じじゃないかな。"
    assert parsed.expression == "neutral"
    assert parsed.gesture is None
    assert parsed.pause_after_seconds == 0.0
    assert parsed.voice_intent.style == "neutral"
    assert parsed.voice_intent.speed == 1.0
    assert parsed.claims == (ResponseClaim.CONVERSATION_ONLY,)


@pytest.mark.asyncio
async def test_model_invocation_does_not_receive_raw_response_context_or_user_input() -> None:
    model = _RecordingCharacterModel(
        json.dumps(
            {
                "speech": "今はそこまで楽しいって感じじゃないかな。",
                "linguistic_performance": {
                    "phrasing": ["今は", "そこまで楽しいって感じじゃないかな。"],
                    "emphasis": [],
                    "delivery_tags": ["gentle"],
                },
                "semantic_realizations": ["proposition:0:joy"],
            },
            ensure_ascii=False,
        )
    )
    service = CharacterLanguageRealizerService(
        model,
        CharacterLanguageRealizerPromptBuilder(),
        _profile(),
    )
    source = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ答える",
        source_event_id="test-event",
    )

    response = await service.generate(source, _context())

    assert response.speech.startswith("今は")
    assert len(model.activities) == 1
    activity = model.activities[0]
    assert activity.context["llm_role"] == "character_language_realizer"
    assert activity.context["semantic_boundary"] is True
    for forbidden_key in (
        "user_input",
        "response_context",
        "event_payload",
        "activity_execution_result",
        "ongoing_activity",
    ):
        assert forbidden_key not in activity.context
    prompt = str(activity.context["plugin_prompt_override"])
    assert "0.82" not in prompt
    assert "0.58" not in prompt
    assert "emotion.current.reactive.joy" not in prompt


@pytest.mark.asyncio
async def test_non_semantic_case_keeps_legacy_character_path_temporarily() -> None:
    model = _RecordingCharacterModel(
        json.dumps(
            {
                "speech": "うん。",
                "expression": "soft_smile",
                "gesture": None,
                "voice_intent": {"style": "calm"},
                "pause_after_seconds": 0.0,
                "reaction_segments": None,
                "claims": ["conversation_only"],
            },
            ensure_ascii=False,
        )
    )
    service = CharacterLanguageRealizerService(
        model,
        CharacterLanguageRealizerPromptBuilder(),
        _profile(),
    )
    source = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="通常会話を続ける",
    )

    response = await service.generate(source, _context(include_semantic_plan=False))

    assert response.speech == "うん。"
    assert len(model.activities) == 1
    activity = model.activities[0]
    assert activity.context["llm_role"] == "character"
    assert "response_context" in activity.context
    assert "user_input" in activity.context
