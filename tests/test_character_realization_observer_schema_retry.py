from __future__ import annotations

import json

import pytest

from app.adapters.prompt.character_realization_validator_prompt_builder import (
    CharacterRealizationValidatorPromptBuilder,
)
from app.domain.activities import Activity, ActivityType
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
from app.runtime.character_realization_validator_schema_retry import (
    CharacterRealizationValidator,
)


class _SequenceObserverModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.activities: list[Activity] = []

    async def validate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        if not self.responses:
            raise AssertionError("unexpected observer model call")
        return self.responses.pop(0)


def _plan() -> SemanticUtterancePlan:
    return SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", "energy"),
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="energy",
                state="low",
                certainty="high",
            ),
        ),
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )


def _context(plan: SemanticUtterancePlan) -> ResponseContext:
    return ResponseContext(
        user_input="今の元気はどんな感じ？",
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="現在の状態へ直接答える",
        speech_act="question",
        memory={"semantic_utterance_plan": plan.as_context()},
    )


def _response() -> CharacterResponse:
    speech = "元気は控えめだよ。"
    return CharacterResponse(
        speech=speech,
        expression="neutral",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=LinguisticPerformance(phrasing=(speech,)),
        semantic_realizations=("proposition:0:energy",),
    )


def _valid_observation(*, predicate_realized: object = True) -> dict[str, object]:
    return {
        "realization_id": "proposition:0:energy",
        "predicate_realized": predicate_realized,
        "observed_state": "low",
        "observed_certainty": "high",
        "predicate_evidence_spans": ["元気"],
        "state_evidence_spans": ["控えめ"],
        "certainty_evidence_spans": [],
    }


def _payload(*, predicate_realized: object = True) -> str:
    return json.dumps(
        {"observations": [_valid_observation(predicate_realized=predicate_realized)]},
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_observer_schema_invalid_gets_one_contract_retry_without_expected_values() -> None:
    model = _SequenceObserverModel(
        [
            _payload(predicate_realized="no"),
            _payload(predicate_realized=True),
        ]
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    plan = _plan()
    source = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ答える",
        source_event_id="schema-retry-test",
    )

    observations = await validator._observe_realized_semantics(
        source,
        _context(plan),
        _response(),
        plan,
        attempt=1,
    )

    assert observations is not None
    assert len(observations) == 1
    assert observations[0].predicate_realized is True
    assert observations[0].observed_state == "low"
    assert len(model.activities) == 2
    first, second = model.activities
    assert first.context["llm_role"] == "character_realization_observer"
    assert second.context["llm_role"] == "character_realization_observer"
    assert first.context["observer_contract_attempt"] == 1
    assert second.context["observer_contract_attempt"] == 2
    assert "# Observer Output Contract Retry" not in first.context["plugin_prompt_override"]
    retry_prompt = second.context["plugin_prompt_override"]
    assert "# Observer Output Contract Retry" in retry_prompt
    assert "predicate_realizedはJSON booleanのtrueまたはfalseだけ" in retry_prompt
    assert '"state": "low"' not in retry_prompt
    assert '"certainty": "high"' not in retry_prompt
    assert '"concept":' not in retry_prompt
    assert '"predicate_realized": "no"' not in retry_prompt


@pytest.mark.asyncio
async def test_observer_schema_invalid_twice_still_fails_closed() -> None:
    model = _SequenceObserverModel(
        [
            _payload(predicate_realized="no"),
            _payload(predicate_realized="omitted"),
        ]
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )
    plan = _plan()
    source = Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ答える",
        source_event_id="schema-retry-test",
    )

    observations = await validator._observe_realized_semantics(
        source,
        _context(plan),
        _response(),
        plan,
        attempt=1,
    )

    assert observations is None
    assert len(model.activities) == 2


def test_observer_parser_keeps_list_envelope_normalization_structural_only() -> None:
    raw = json.dumps([_valid_observation()], ensure_ascii=False)

    observations = CharacterRealizationValidator._parse_observer_payload(raw)

    assert observations is not None
    assert len(observations) == 1
    assert observations[0].predicate_realized is True
    assert observations[0].observed_state == "low"


def test_observer_parser_does_not_coerce_string_predicate_realized() -> None:
    raw = _payload(predicate_realized="no")

    observations = CharacterRealizationValidator._parse_observer_payload(raw)

    assert observations is None
