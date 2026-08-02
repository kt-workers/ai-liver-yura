from __future__ import annotations

import json

import pytest

from app.adapters.prompt import CharacterPromptBuilder, ResponseValidatorPromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.character_response import ActivityExecutionStatus, CharacterResponse, ResponseContext
from app.domain.cognitive_direction import (
    ConversationPhaseSignal,
    ExpectedResponse,
    InputSpeechAct,
    InputTarget,
    InterestChange,
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
    TargetInterestUpdate,
)
from app.ports.llm_roles import ResponseGeneratorRoleAdapter
from app.runtime.cognitive_direction_pipeline import (
    InputMeaningJsonParser,
    InternalDirectiveJsonParser,
    InternalDirectiveValidator,
)


class StubResponseGenerator:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.activities: list[Activity] = []
        self._character_profile = None

    async def generate_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        return self.responses.pop(0)


def meaning_json(
    speech_act: str = "question",
    expected: str = "direct_answer",
    target_id: str | None = "current_desire",
    *,
    intent: str = "ask_agent_internal_state",
    phase: str = "continue",
) -> str:
    return json.dumps(
        {
            "input_speech_act": speech_act,
            "primary_intent": intent,
            "expected_response": expected,
            "target": (
                {"type": "agent_internal_state", "id": target_id}
                if target_id is not None
                else None
            ),
            "entities": [],
            "references": [],
            "information_provided": [],
            "negated": False,
            "hypothetical": False,
            "past_reference": False,
            "conversation_phase_signal": phase,
            "confidence": 0.96,
            "reason": "入力側の意味を分類した",
        },
        ensure_ascii=False,
    )


def directive_json(mode: str = "speak", updates: list[dict[str, object]] | None = None) -> str:
    return json.dumps(
        {
            "response_mode": mode,
            "response_goal": "入力へ自然に応答する",
            "activity_intent": None,
            "initiative_level": 0.8,
            "question_budget": 1,
            "new_direction_budget": 1,
            "self_disclosure_level": 0.8,
            "content_requirements": [],
            "forbidden_claims": [],
            "target_interest_updates": updates or [],
            "state_update_proposals": [],
            "reason": "構造化入力に基づく",
        },
        ensure_ascii=False,
    )


def planning_input(text: str) -> dict[str, object]:
    return {
        "event": {"type": "user_text", "source_event_id": "event-1", "user_text": text},
        "situation": {"current_topic": "現在の気分"},
        "emotion": {"joy": 0.0, "amusement": 0.0, "engagement": 0.94},
        "drive": {"curiosity": 1.0},
        "relationship": {},
        "motivation": {},
        "moral": {},
        "memory": {},
        "conversation_history": [],
        "related_knowledge": [],
        "last_activity_result": None,
        "ongoing_activity": None,
        "available_activities": [],
    }


def legacy_prompt(data: dict[str, object]) -> str:
    return "\n".join(("legacy", "# 判断入力", json.dumps(data, ensure_ascii=False), "# 出力JSONスキーマ", "{}"))


@pytest.mark.asyncio
async def test_runtime_uses_two_roles_and_does_not_reinterpret_raw_text() -> None:
    text = "今は何をしたい気分ですか？"
    generator = StubResponseGenerator([meaning_json(), directive_json()])
    adapter = ResponseGeneratorRoleAdapter(generator)
    activity = Activity(
        ActivityType.BEHAVIOR_PLANNING,
        "意味解析",
        context={
            "plugin_prompt_override": legacy_prompt(planning_input(text)),
            "llm_role": "situation_evaluator",
            "event_id": "event-1",
            "user_input": text,
        },
        source_event_id="event-1",
    )

    payload = json.loads(await adapter.evaluate(activity))

    assert [item.context["llm_role"] for item in generator.activities] == [
        "input_meaning_interpreter",
        "internal_directive_planner",
    ]
    assert payload["speech_act"] == "question"
    validated = payload["constraints"]["_internal_directive"]
    assert validated["internal_directive"]["response_mode"] == "answer"
    assert validated["internal_directive"]["question_budget"] == 0
    assert text not in generator.activities[1].context["plugin_prompt_override"]


@pytest.mark.parametrize(
    ("raw", "act", "expected", "target_id"),
    (
        (meaning_json(), InputSpeechAct.QUESTION, ExpectedResponse.DIRECT_ANSWER, "current_desire"),
        (meaning_json(target_id="anger"), InputSpeechAct.QUESTION, ExpectedResponse.DIRECT_ANSWER, "anger"),
        (meaning_json("answer", "acknowledgement", "しまなみ海道", intent="answer_agent_question"), InputSpeechAct.ANSWER, ExpectedResponse.ACKNOWLEDGEMENT, "しまなみ海道"),
        (meaning_json("acknowledgement", "continue_listening", None, intent="acknowledge"), InputSpeechAct.ACKNOWLEDGEMENT, ExpectedResponse.CONTINUE_LISTENING, None),
        (meaning_json("closing", "acknowledgement", None, intent="close", phase="winding_down"), InputSpeechAct.CLOSING, ExpectedResponse.ACKNOWLEDGEMENT, None),
    ),
)
def test_input_meaning_contract(raw: str, act: InputSpeechAct, expected: ExpectedResponse, target_id: str | None) -> None:
    parsed = InputMeaningJsonParser().parse(raw, source_text="入力")
    assert parsed is not None
    assert parsed.input_speech_act is act
    assert parsed.expected_response is expected
    assert (parsed.target.target_id if parsed.target else None) == target_id


def structured(
    act: InputSpeechAct,
    *,
    expected: ExpectedResponse = ExpectedResponse.ACKNOWLEDGEMENT,
    target: InputTarget | None = None,
    phase: ConversationPhaseSignal = ConversationPhaseSignal.CONTINUE,
) -> StructuredInputMeaning:
    return StructuredInputMeaning(
        input_speech_act=act,
        primary_intent="ask_agent_internal_state" if target else "conversation",
        expected_response=expected,
        target=target,
        conversation_phase_signal=phase,
        confidence=0.95,
    )


def directive(mode: ResponseMode, updates: tuple[TargetInterestUpdate, ...] = ()) -> InternalDirective:
    return InternalDirective(
        response_mode=mode,
        response_goal="応答する",
        activity_intent=None,
        initiative_level=0.9,
        question_budget=1,
        new_direction_budget=1,
        self_disclosure_level=0.5,
        target_interest_updates=updates,
    )


def validate(meaning: StructuredInputMeaning, command: InternalDirective, text: str = "入力", profile: dict[str, object] | None = None):
    return InternalDirectiveValidator().validate(
        meaning,
        command,
        planning_input(text),
        character_profile=profile or {},
    )


def test_direct_question_acknowledgement_and_closing_force_budgets() -> None:
    question = validate(
        structured(InputSpeechAct.QUESTION, expected=ExpectedResponse.DIRECT_ANSWER, target=InputTarget("agent_internal_state", "current_desire")),
        directive(ResponseMode.ASK),
    )
    acknowledgement = validate(structured(InputSpeechAct.ACKNOWLEDGEMENT), directive(ResponseMode.SPEAK), "了解")
    closing = validate(
        structured(InputSpeechAct.CLOSING, phase=ConversationPhaseSignal.WINDING_DOWN),
        directive(ResponseMode.ASK),
        "今日はこのくらいかな",
    )

    assert question.directive.response_mode is ResponseMode.ANSWER
    for plan in (question, acknowledgement, closing):
        assert plan.directive.question_budget == 0
        assert plan.directive.new_direction_budget == 0
    assert acknowledgement.directive.response_mode in {ResponseMode.LISTEN, ResponseMode.REACT}
    assert closing.directive.response_mode in {ResponseMode.LISTEN, ResponseMode.REACT}


def test_curiosity_requires_target_interest_and_knowledge_gap() -> None:
    global_only = validate(structured(InputSpeechAct.STATEMENT), directive(ResponseMode.ASK))
    update = TargetInterestUpdate(
        target_type="place",
        target_id="しまなみ海道",
        interest_change=InterestChange.SLIGHTLY_INCREASE,
        new_knowledge_gaps=("訪れた時間帯",),
    )
    targeted = validate(
        structured(InputSpeechAct.STATEMENT),
        directive(ResponseMode.ASK, (update,)),
    )

    assert global_only.directive.response_mode is ResponseMode.LISTEN
    assert global_only.directive.question_budget == 0
    assert targeted.directive.response_mode is ResponseMode.ASK
    assert targeted.directive.question_budget == 1


def test_internal_state_and_existence_boundaries_are_enforced() -> None:
    joy = validate(
        structured(InputSpeechAct.QUESTION, expected=ExpectedResponse.DIRECT_ANSWER, target=InputTarget("agent_internal_state", "joy")),
        directive(ResponseMode.ANSWER),
        "楽しい？",
    )
    hunger = validate(
        structured(InputSpeechAct.QUESTION, expected=ExpectedResponse.DIRECT_ANSWER, target=InputTarget("agent_internal_state", "physical_hunger")),
        directive(ResponseMode.ANSWER),
        "お腹は空いてる？",
        {"existence": {"physical_capabilities": ["物理的な身体を持たない"]}},
    )

    joy_requirements = "\n".join(joy.directive.content_requirements)
    assert "joy=0.0" in joy_requirements and "engagement=0.94" in joy_requirements
    assert "楽しいと断定" in "\n".join(joy.directive.forbidden_claims)
    assert "人間と同じ物理的身体感覚は持たない" in "\n".join(hunger.directive.content_requirements)
    assert "今は空腹でないだけ" in "\n".join(hunger.directive.forbidden_claims)


def test_parsers_are_strict_and_prompts_receive_validated_directive() -> None:
    malformed = json.loads(directive_json())
    malformed["question_budget"] = 0.5
    assert InternalDirectiveJsonParser().parse(json.dumps(malformed)) is None

    directive_context = {
        "internal_directive": {
            "response_mode": "answer",
            "response_goal": "存在設定に沿って答える",
            "question_budget": 0,
            "new_direction_budget": 0,
            "content_requirements": ["物理的身体を持たないことを明示する"],
            "forbidden_claims": ["今はお腹が空いていないだけと答える"],
        },
        "character_profile": {"name": "ゆら"},
        "existence_boundaries": ["物理的な身体を持たない"],
    }
    context = ResponseContext(
        user_input="お腹は空いてる？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="会話を継続する",
        allowed_claims=(),
        forbidden_claims=(),
        activity_goal="質問へ答える",
        constraints={"_internal_directive": directive_context},
    )
    character_prompt = CharacterPromptBuilder().build(context, character_profile=None, correction=None)
    validator_prompt = ResponseValidatorPromptBuilder().build(context, CharacterResponse(speech="今は空いてないよ。"))

    assert "Validated Internal Directive" in character_prompt
    assert "existence_boundaries" in character_prompt
    assert "Character Profile / Existence Boundaries" in validator_prompt
    assert "accepted=false" in validator_prompt
