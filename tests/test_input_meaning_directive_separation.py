from __future__ import annotations

import json

import pytest

from app.adapters.prompt import CharacterPromptBuilder, ResponseValidatorPromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    ResponseContext,
)
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
from app.prompting.cognitive_direction_prompt_builders import (
    InputMeaningPromptBuilder,
)
from app.runtime.cognitive_direction_pipeline import (
    InputMeaningJsonParser,
    InternalDirectiveJsonParser,
    InternalDirectiveValidator,
)

DESIRE_QUESTION = "\u4eca\u306f\u4f55\u3092\u3057\u305f\u3044\u6c17\u5206\u3067\u3059\u304b\uff1f"
ANGER_QUESTION = "\u4eca\u6012\u3063\u3066\u308b\uff1f"
FUN_QUESTION = "\u697d\u3057\u3044\uff1f"
HUNGER_QUESTION = "\u304a\u8179\u306f\u7a7a\u3044\u3066\u308b\uff1f"
SHIMANAMI = "\u3057\u307e\u306a\u307f\u6d77\u9053"
ACK = "\u4e86\u89e3"
CLOSING = "\u4eca\u65e5\u306f\u3053\u306e\u304f\u3089\u3044\u304b\u306a"
CURRENT_FEELING_QUESTION = "\u4eca\u3069\u3093\u306a\u6c17\u5206\uff1f"


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
    target_type: str = "agent_internal_state",
    intent: str = "ask_agent_internal_state",
    phase: str = "continue",
) -> str:
    return json.dumps(
        {
            "input_speech_act": speech_act,
            "primary_intent": intent,
            "expected_response": expected,
            "target": (
                {"type": target_type, "id": target_id}
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
            "reason": "input meaning classified",
        }
    )


def directive_json(mode: str = "speak") -> str:
    return json.dumps(
        {
            "response_mode": mode,
            "response_goal": "respond naturally",
            "activity_intent": None,
            "initiative_level": 0.8,
            "question_budget": 1,
            "new_direction_budget": 1,
            "self_disclosure_level": 0.8,
            "content_requirements": [],
            "forbidden_claims": [],
            "target_interest_updates": [],
            "state_update_proposals": [],
            "reason": "based on structured input",
        }
    )


def planning_input(text: str) -> dict[str, object]:
    return {
        "event": {
            "type": "user_text",
            "source_event_id": "event-1",
            "user_text": text,
        },
        "situation": {"current_topic": "current mood"},
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
    return "\n".join(
        (
            "legacy",
            "# \u5224\u65ad\u5165\u529b",
            json.dumps(data),
            "# \u51fa\u529bJSON\u30b9\u30ad\u30fc\u30de",
            "{}",
        )
    )


@pytest.mark.asyncio
async def test_runtime_uses_two_roles_without_raw_text_reinterpretation() -> None:
    generator = StubResponseGenerator([meaning_json(), directive_json()])
    adapter = ResponseGeneratorRoleAdapter(generator)
    activity = Activity(
        ActivityType.BEHAVIOR_PLANNING,
        "interpret",
        context={
            "plugin_prompt_override": legacy_prompt(
                planning_input(DESIRE_QUESTION)
            ),
            "llm_role": "situation_evaluator",
            "event_id": "event-1",
            "user_input": DESIRE_QUESTION,
        },
        source_event_id="event-1",
    )

    payload = json.loads(await adapter.evaluate(activity))

    assert [item.context["llm_role"] for item in generator.activities] == [
        "input_meaning_interpreter",
        "internal_directive_planner",
    ]
    validated = payload["constraints"]["_internal_directive"]
    assert payload["speech_act"] == "question"
    assert validated["internal_directive"]["response_mode"] == "answer"
    assert validated["internal_directive"]["question_budget"] == 0
    assert DESIRE_QUESTION not in generator.activities[1].context[
        "plugin_prompt_override"
    ]


def test_input_meaning_prompt_requires_semantic_canonical_targets() -> None:
    prompt = InputMeaningPromptBuilder().build(
        planning_input(CURRENT_FEELING_QUESTION)
    )

    assert "targetは単なるNamed Entityではない" in prompt
    assert "type=internal_state,id=current_feeling" in prompt
    assert "type=internal_state,id=joy" in prompt
    assert "type=internal_state,id=anger" in prompt
    assert "type=internal_state,id=current_desire" in prompt
    assert "文字列照合規則ではなく意味分類例" in prompt
    assert "表現が異なっても" in prompt
    assert "固定フレーズ辞書や正規表現による照合を行わない" in prompt
    assert "question、request、command等で意味上の対象が存在する場合" in prompt
    assert "targetをnullにしてはいけない" in prompt
    assert "曖昧参照はconversation_history" in prompt
    assert "本当に意味上の対象がない場合だけtargetをnull" in prompt


@pytest.mark.parametrize("speech_act", ("question", "request", "command"))
def test_input_meaning_parser_rejects_missing_required_semantic_target(
    speech_act: str,
) -> None:
    raw = meaning_json(
        speech_act=speech_act,
        expected="direct_answer" if speech_act == "question" else "action",
        target_id=None,
    )

    assert InputMeaningJsonParser().parse(raw, source_text="input") is None
    assert InputMeaningJsonParser.has_missing_semantic_target(raw)


@pytest.mark.asyncio
async def test_missing_question_target_is_restructured_then_current_feeling_is_normalized(
) -> None:
    invalid_meaning = meaning_json(
        target_id=None,
        intent="ask_current_feeling",
    )
    corrected_meaning = meaning_json(
        target_id="current_feeling",
        target_type="internal_state",
        intent="ask_current_feeling",
    )
    diagnostic_directive = json.loads(directive_json("answer"))
    diagnostic_directive["response_goal"] = (
        "現在の気分はニュートラルで落ち着いています"
    )
    diagnostic_directive["content_requirements"] = [
        "ニュートラルであることを明示する"
    ]
    generator = StubResponseGenerator(
        [
            invalid_meaning,
            corrected_meaning,
            json.dumps(diagnostic_directive, ensure_ascii=False),
        ]
    )
    adapter = ResponseGeneratorRoleAdapter(generator)
    activity = Activity(
        ActivityType.BEHAVIOR_PLANNING,
        "interpret",
        context={
            "plugin_prompt_override": legacy_prompt(
                planning_input(CURRENT_FEELING_QUESTION)
            ),
            "llm_role": "situation_evaluator",
            "event_id": "event-1",
            "user_input": CURRENT_FEELING_QUESTION,
        },
        source_event_id="event-1",
    )

    payload = json.loads(await adapter.evaluate(activity))
    validated = payload["constraints"]["_internal_directive"]
    meaning = validated["structured_input_meaning"]
    directive_result = validated["internal_directive"]

    assert [item.context["llm_role"] for item in generator.activities] == [
        "input_meaning_interpreter",
        "input_meaning_interpreter",
        "internal_directive_planner",
    ]
    assert "# Contract Repair" in generator.activities[1].context[
        "plugin_prompt_override"
    ]
    assert meaning["target"] == {
        "type": "internal_state",
        "id": "current_feeling",
    }
    assert "internal_state_guidance_normalized" in validated["validation_notes"]
    assert directive_result["response_goal"] == (
        "ユーザーが尋ねた内的状態について、現在の状態に沿って自然に直接答える"
    )
    assert "ニュートラル" not in "\n".join(
        directive_result["content_requirements"]
    )


@pytest.mark.parametrize(
    ("raw", "act", "expected", "target_id"),
    (
        (
            meaning_json(),
            InputSpeechAct.QUESTION,
            ExpectedResponse.DIRECT_ANSWER,
            "current_desire",
        ),
        (
            meaning_json(target_id="anger"),
            InputSpeechAct.QUESTION,
            ExpectedResponse.DIRECT_ANSWER,
            "anger",
        ),
        (
            meaning_json(
                "answer",
                "acknowledgement",
                SHIMANAMI,
                target_type="place",
                intent="answer_agent_question",
            ),
            InputSpeechAct.ANSWER,
            ExpectedResponse.ACKNOWLEDGEMENT,
            SHIMANAMI,
        ),
        (
            meaning_json(
                "acknowledgement",
                "continue_listening",
                None,
                intent="acknowledge",
            ),
            InputSpeechAct.ACKNOWLEDGEMENT,
            ExpectedResponse.CONTINUE_LISTENING,
            None,
        ),
        (
            meaning_json(
                "closing",
                "acknowledgement",
                None,
                intent="close",
                phase="winding_down",
            ),
            InputSpeechAct.CLOSING,
            ExpectedResponse.ACKNOWLEDGEMENT,
            None,
        ),
    ),
)
def test_input_meaning_contract(
    raw: str,
    act: InputSpeechAct,
    expected: ExpectedResponse,
    target_id: str | None,
) -> None:
    parsed = InputMeaningJsonParser().parse(raw, source_text="input")
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


def directive(
    mode: ResponseMode,
    updates: tuple[TargetInterestUpdate, ...] = (),
) -> InternalDirective:
    return InternalDirective(
        response_mode=mode,
        response_goal="respond",
        activity_intent=None,
        initiative_level=0.9,
        question_budget=1,
        new_direction_budget=1,
        self_disclosure_level=0.5,
        target_interest_updates=updates,
    )


def validate(
    meaning: StructuredInputMeaning,
    command: InternalDirective,
    text: str = "input",
    profile: dict[str, object] | None = None,
):
    return InternalDirectiveValidator().validate(
        meaning,
        command,
        planning_input(text),
        character_profile=profile or {},
    )


def test_direct_question_acknowledgement_and_closing_force_budgets() -> None:
    question = validate(
        structured(
            InputSpeechAct.QUESTION,
            expected=ExpectedResponse.DIRECT_ANSWER,
            target=InputTarget("agent_internal_state", "current_desire"),
        ),
        directive(ResponseMode.ASK),
    )
    acknowledgement = validate(
        structured(InputSpeechAct.ACKNOWLEDGEMENT),
        directive(ResponseMode.SPEAK),
        ACK,
    )
    closing = validate(
        structured(
            InputSpeechAct.CLOSING,
            phase=ConversationPhaseSignal.WINDING_DOWN,
        ),
        directive(ResponseMode.ASK),
        CLOSING,
    )

    assert question.directive.response_mode is ResponseMode.ANSWER
    for plan in (question, acknowledgement, closing):
        assert plan.directive.question_budget == 0
        assert plan.directive.new_direction_budget == 0
    assert acknowledgement.directive.response_mode in {
        ResponseMode.LISTEN,
        ResponseMode.REACT,
    }
    assert closing.directive.response_mode in {
        ResponseMode.LISTEN,
        ResponseMode.REACT,
    }


def test_curiosity_requires_target_interest_and_knowledge_gap() -> None:
    global_only = validate(
        structured(InputSpeechAct.STATEMENT),
        directive(ResponseMode.ASK),
    )
    update = TargetInterestUpdate(
        target_type="place",
        target_id=SHIMANAMI,
        interest_change=InterestChange.SLIGHTLY_INCREASE,
        new_knowledge_gaps=("visit time",),
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
        structured(
            InputSpeechAct.QUESTION,
            expected=ExpectedResponse.DIRECT_ANSWER,
            target=InputTarget("agent_internal_state", "joy"),
        ),
        directive(ResponseMode.ANSWER),
        FUN_QUESTION,
    )
    hunger = validate(
        structured(
            InputSpeechAct.QUESTION,
            expected=ExpectedResponse.DIRECT_ANSWER,
            target=InputTarget("agent_internal_state", "physical_hunger"),
        ),
        directive(ResponseMode.ANSWER),
        HUNGER_QUESTION,
        {
            "existence": {
                "physical_capabilities": [
                    "\u7269\u7406\u7684\u306a\u8eab\u4f53\u3092\u6301\u305f\u306a\u3044"
                ]
            }
        },
    )

    joy_requirements = "\n".join(joy.directive.content_requirements)
    assert "joy=0.0" not in joy_requirements
    assert "engagement=0.94" not in joy_requirements
    assert "engagement\u3084curiosity" in "\n".join(
        joy.directive.forbidden_claims
    )
    human_body_claim = (
        "\u4eba\u9593\u3068\u540c\u3058\u7269\u7406\u7684\u8eab\u4f53\u611f\u899a"
        "\u306f\u6301\u305f\u306a\u3044"
    )
    assert human_body_claim in "\n".join(hunger.directive.content_requirements)
    assert "\u4eca\u306f\u7a7a\u8179\u3067\u306a\u3044\u3060\u3051" in "\n".join(
        hunger.directive.forbidden_claims
    )


def test_strict_parser_and_validated_directive_prompt_transport() -> None:
    malformed = json.loads(directive_json())
    malformed["question_budget"] = 0.5
    assert InternalDirectiveJsonParser().parse(json.dumps(malformed)) is None

    directive_context = {
        "internal_directive": {
            "response_mode": "answer",
            "response_goal": "respect existence boundary",
            "question_budget": 0,
            "new_direction_budget": 0,
            "content_requirements": ["no physical body"],
            "forbidden_claims": ["ordinary human hunger"],
        },
        "character_profile": {"name": "yura"},
        "existence_boundaries": ["no physical body"],
    }
    context = ResponseContext(
        user_input=HUNGER_QUESTION,
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="continue conversation",
        allowed_claims=(),
        forbidden_claims=(),
        activity_goal="answer question",
        constraints={"_internal_directive": directive_context},
    )
    character_prompt = CharacterPromptBuilder().build(
        context,
        character_profile=None,
        correction=None,
    )
    validator_prompt = ResponseValidatorPromptBuilder().build(
        context,
        CharacterResponse(speech="not hungry"),
    )

    assert "Validated Internal Directive" in character_prompt
    assert "existence_boundaries" in character_prompt
    assert "Character Profile / Existence Boundaries" in validator_prompt
    assert "accepted=false" in validator_prompt
