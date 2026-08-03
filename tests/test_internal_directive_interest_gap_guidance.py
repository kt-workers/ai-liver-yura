from __future__ import annotations

from app.domain.cognitive_direction import (
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    StructuredInputMeaning,
)
from app.prompting.cognitive_direction_prompt_builders import (
    InternalDirectivePromptBuilder,
)


def _meaning() -> StructuredInputMeaning:
    return StructuredInputMeaning(
        input_speech_act=InputSpeechAct.QUESTION,
        primary_intent="ask_physical_experience",
        expected_response=ExpectedResponse.DIRECT_ANSWER,
        target=InputTarget("character_experience", "yesterday_outing"),
        past_reference=True,
        confidence=0.98,
    )


def _planning_input() -> dict[str, object]:
    return {
        "emotion": {"calm": 0.73},
        "drive": {"curiosity": 0.28},
        "relationship": {},
        "motivation": {},
        "moral": {"honesty": 0.98},
        "situation": {"current_topic": "ゆらの昨日の外出経験"},
        "memory": {},
        "related_knowledge": [],
        "last_activity_result": None,
        "ongoing_activity": None,
        "available_activities": [],
    }


def _profile() -> dict[str, object]:
    return {
        "name": "ゆら",
        "existence": {
            "physical_capabilities": ["物理的な身体を持たない"],
            "experience_boundaries": [
                "根拠のない現実空間での実体験を語らない"
            ],
        },
    }


def test_prompt_only_resolves_existing_knowledge_gaps() -> None:
    prompt = InternalDirectivePromptBuilder().build(
        _meaning(),
        _planning_input(),
        character_profile=_profile(),
    )

    assert '"related_knowledge": []' in prompt
    assert '"memory": {}' in prompt
    assert "既存のKnowledge Gapとして" in prompt
    assert "存在しない場合は空配列" in prompt
    assert "解決済みGapとして新規作成してはいけない" in prompt


def test_prompt_requires_evidence_before_interest_change() -> None:
    prompt = InternalDirectivePromptBuilder().build(
        _meaning(),
        _planning_input(),
        character_profile=_profile(),
    )

    assert "増減の明確な根拠" in prompt
    assert "回答したこと" in prompt
    assert "根拠がなければunchanged" in prompt


def test_prompt_rejects_narrative_state_update_proposals() -> None:
    prompt = InternalDirectivePromptBuilder().build(
        _meaning(),
        _planning_input(),
        character_profile=_profile(),
    )

    assert "実際に値を変更すべき状態だけ" in prompt
    assert "応答行為の記録" in prompt
    assert "current_topicへ『直接回答』" in prompt
    assert "変更がなければ空配列" in prompt
