from __future__ import annotations

import json

import pytest

from app.adapters.prompt.character_realization_observer_prompt_builder import (
    CharacterRealizationObserverPromptBuilder,
)
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
from app.runtime.character_realization_validator import CharacterRealizationValidator


_DEFAULT_OBSERVED_STATES = {
    "proposition:0:joy": "high",
    "proposition:0:sadness": "unknown",
    "proposition:0:current_feeling": "overview",
    "proposition:1:joy": "high",
    "proposition:2:anger": "moderate",
    "proposition:3:calm": "low",
    "proposition:4:amusement": "absent",
}
_OBSERVER_EVIDENCE = {
    "proposition:0:joy": "楽しい",
    "proposition:0:sadness": "悲しい",
    "proposition:0:current_feeling": "気分",
    "proposition:1:joy": "うれし",
    "proposition:2:anger": "腹立たし",
    "proposition:3:calm": "穏やか",
    "proposition:4:amusement": "面白",
}


class _RecordingValidationModel:
    def __init__(
        self,
        payload: dict[str, object],
        *,
        observer_overrides: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.payload = payload
        self.observer_overrides = observer_overrides or {}
        self.activities: list[Activity] = []

    async def validate_character_response(self, activity: Activity) -> str:
        self.activities.append(activity)
        if activity.context.get("llm_role") == "character_realization_observer":
            prompt = str(activity.context.get("plugin_prompt_override") or "")
            lines = prompt.splitlines()
            marker = lines.index("# Candidate Predicate IDs")
            candidates = json.loads(lines[marker + 1])
            observations: list[dict[str, object]] = []
            for candidate in candidates:
                realization_id = str(candidate["realization_id"])
                override = self.observer_overrides.get(realization_id, {})
                evidence = _OBSERVER_EVIDENCE.get(realization_id, "気分")
                observations.append(
                    {
                        "realization_id": realization_id,
                        "predicate_realized": override.get("predicate_realized", True),
                        "observed_state": override.get(
                            "observed_state", _DEFAULT_OBSERVED_STATES[realization_id]
                        ),
                        "observed_certainty": override.get(
                            "observed_certainty", "high"
                        ),
                        "predicate_evidence_spans": override.get(
                            "predicate_evidence_spans", [evidence]
                        ),
                        "state_evidence_spans": override.get(
                            "state_evidence_spans", [evidence]
                        ),
                        "certainty_evidence_spans": override.get(
                            "certainty_evidence_spans", []
                        ),
                    }
                )
            return json.dumps({"observations": observations}, ensure_ascii=False)
        return json.dumps(self.payload, ensure_ascii=False)


def _context(
    *,
    user_input: str,
    target_id: str,
    propositions: tuple[SemanticProposition, ...],
) -> ResponseContext:
    plan = SemanticUtterancePlan(
        speech_act="direct_answer",
        target=SemanticTarget("internal_state", target_id),
        propositions=propositions,
        response_length="short",
        self_disclosure="brief",
        question_budget=0,
        new_direction_budget=0,
    )
    return ResponseContext(
        user_input=user_input,
        activity_type="conversation",
        operation="discuss",
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(ResponseClaim.CONVERSATION_ONLY,),
        forbidden_claims=(),
        activity_goal="内部状態へ直接答える",
        speech_act="question",
        constraints={
            "_internal_directive": {
                "existence_boundaries": ["存在種別はAI VTuberである"],
            }
        },
        memory={
            "semantic_utterance_plan": plan.as_context(),
            "semantic_validation": {
                "accepted": True,
                "reason": "semantic_plan_consistent",
                "differences": [],
            },
        },
    )


def _response(speech: str, realizations: tuple[str, ...]) -> CharacterResponse:
    return CharacterResponse(
        speech=speech,
        expression="neutral",
        claims=(ResponseClaim.CONVERSATION_ONLY,),
        linguistic_performance=LinguisticPerformance(
            phrasing=(speech,),
            delivery_tags=("gentle",),
        ),
        semantic_realizations=realizations,
    )


def _post_observation_check(realization_id: str) -> dict[str, object]:
    evidence = _OBSERVER_EVIDENCE.get(realization_id, "気分")
    return {
        "realization_id": realization_id,
        "predicate_preserved": True,
        "predicate_evidence_spans": [evidence],
        "concept_preserved": True,
        "concept_evidence_spans": [],
    }


def _accepted_payload(checks: list[dict[str, object]]) -> dict[str, object]:
    return {
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
        "realized_proposition_checks": checks,
    }


def _source() -> Activity:
    return Activity(
        activity_type=ActivityType.CONVERSATION_WITH_USER,
        goal="質問へ答える",
        source_event_id="state-fidelity-test",
    )


def _joy_high_context() -> ResponseContext:
    return _context(
        user_input="楽しい？",
        target_id="joy",
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="joy",
                state="high",
                certainty="high",
                concept=None,
            ),
        ),
    )


def _sadness_unknown_context(*, certainty: str = "high") -> ResponseContext:
    return _context(
        user_input="悲しい？",
        target_id="sadness",
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="sadness",
                state="unknown",
                certainty=certainty,
                concept=None,
            ),
        ),
    )


def _mixed_context() -> ResponseContext:
    return _context(
        user_input="今どんな気分？",
        target_id="current_feeling",
        propositions=(
            SemanticProposition(
                kind="self_state",
                predicate="current_feeling",
                state="overview",
                certainty="high",
                concept=None,
            ),
            SemanticProposition(
                kind="self_state_dimension",
                predicate="joy",
                state="high",
                certainty="high",
                concept=None,
            ),
            SemanticProposition(
                kind="self_state_dimension",
                predicate="anger",
                state="moderate",
                certainty="high",
                concept=None,
            ),
            SemanticProposition(
                kind="self_state_dimension",
                predicate="calm",
                state="low",
                certainty="high",
                concept=None,
            ),
            SemanticProposition(
                kind="self_state_dimension",
                predicate="amusement",
                state="absent",
                certainty="high",
                concept=None,
            ),
        ),
    )


def test_state_fidelity_and_unknown_are_observer_responsibility_not_downstream() -> None:
    mixed = _mixed_context()
    mixed_response = _response(
        "今の気分は、うれしさと腹立たしさもある。",
        (
            "proposition:0:current_feeling",
            "proposition:1:joy",
            "proposition:2:anger",
        ),
    )
    post_prompt = CharacterRealizationValidatorPromptBuilder().build(
        mixed, mixed_response
    )
    observer_prompt = CharacterRealizationObserverPromptBuilder().build(
        mixed,
        mixed_response,
        SemanticUtterancePlan.from_context(mixed.memory["semantic_utterance_plan"]),
    )

    assert '"realization_policy": "optional_but_complete_if_realized"' in post_prompt
    assert "state/polarity/intensity/certaintyはこの工程で判定しない" in post_prompt
    assert "state_fidelity" not in post_prompt
    assert "presence_only_counterfactual_equivalent" not in post_prompt
    assert "low/moderate/high/very_highはpresentとは異なり" in observer_prompt
    assert "unknownは対象の存在・不在・強度・値を現時点で確定していない" in observer_prompt
    assert "特定polarityへcommitしたspeechをunknownにしない" in observer_prompt


@pytest.mark.asyncio
async def test_acceptance_without_realized_proposition_checks_fails_closed() -> None:
    payload = _accepted_payload([_post_observation_check("proposition:0:joy")])
    payload.pop("realized_proposition_checks")
    model = _RecordingValidationModel(payload)
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )

    result = await validator.validate(
        _source(),
        _joy_high_context(),
        _response("とても楽しいよ。", ("proposition:0:joy",)),
    )

    assert result.accepted is False
    assert result.reason == "realization_validator_schema_invalid"


@pytest.mark.asyncio
async def test_primary_high_weakened_to_presence_is_rejected_by_observer() -> None:
    model = _RecordingValidationModel(
        _accepted_payload([_post_observation_check("proposition:0:joy")]),
        observer_overrides={
            "proposition:0:joy": {
                "observed_state": "present",
                "state_evidence_spans": ["楽しい"],
            }
        },
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )

    result = await validator.validate(
        _source(),
        _joy_high_context(),
        _response("うん、楽しいよ。", ("proposition:0:joy",)),
    )

    assert result.accepted is False
    assert result.reason == "observed_semantic_state_fidelity_mismatch"
    assert (
        "proposition:0:joy:observed_state_mismatch:expected=high:observed=present"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_unknown_committed_to_present_is_rejected_by_observer() -> None:
    model = _RecordingValidationModel(
        _accepted_payload([_post_observation_check("proposition:0:sadness")]),
        observer_overrides={
            "proposition:0:sadness": {
                "observed_state": "present",
                "observed_certainty": "high",
                "state_evidence_spans": ["悲しい"],
            }
        },
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )

    result = await validator.validate(
        _source(),
        _sadness_unknown_context(),
        _response("うん、悲しいよ。", ("proposition:0:sadness",)),
    )

    assert result.accepted is False
    assert result.reason == "observed_semantic_state_fidelity_mismatch"
    assert (
        "proposition:0:sadness:observed_state_mismatch:expected=unknown:observed=present"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_supporting_bare_presence_is_rejected_by_independent_observation() -> None:
    realizations = (
        "proposition:0:current_feeling",
        "proposition:1:joy",
        "proposition:2:anger",
        "proposition:3:calm",
    )
    model = _RecordingValidationModel(
        _accepted_payload(
            [_post_observation_check(realization_id) for realization_id in realizations]
        ),
        observer_overrides={
            "proposition:1:joy": {"observed_state": "present"},
            "proposition:3:calm": {"observed_state": "present"},
        },
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )

    result = await validator.validate(
        _source(),
        _mixed_context(),
        _response(
            "今の気分は、穏やかで、うれしさがありつつ、腹立たしさもあります。",
            realizations,
        ),
    )

    assert result.accepted is False
    assert result.reason == "observed_semantic_state_fidelity_mismatch"
    assert (
        "proposition:1:joy:observed_state_mismatch:expected=high:observed=present"
        in result.claim_differences
    )
    assert (
        "proposition:3:calm:observed_state_mismatch:expected=low:observed=present"
        in result.claim_differences
    )


@pytest.mark.asyncio
async def test_missing_or_duplicate_post_observation_check_fails_closed() -> None:
    realizations = (
        "proposition:0:current_feeling",
        "proposition:1:joy",
    )
    response = _response("今の気分は、うれしさが強くある。", realizations)

    missing_model = _RecordingValidationModel(
        _accepted_payload([_post_observation_check("proposition:0:current_feeling")])
    )
    missing_result = await CharacterRealizationValidator(
        model=missing_model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    ).validate(_source(), _mixed_context(), response)
    assert missing_result.accepted is False
    assert missing_result.reason == "realization_validator_schema_invalid"

    duplicate_model = _RecordingValidationModel(
        _accepted_payload(
            [
                _post_observation_check("proposition:0:current_feeling"),
                _post_observation_check("proposition:1:joy"),
                _post_observation_check("proposition:1:joy"),
            ]
        )
    )
    duplicate_result = await CharacterRealizationValidator(
        model=duplicate_model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    ).validate(_source(), _mixed_context(), response)
    assert duplicate_result.accepted is False
    assert duplicate_result.reason == "realization_validator_schema_invalid"


@pytest.mark.asyncio
async def test_unplanned_character_realization_is_rejected_before_model_call() -> None:
    model = _RecordingValidationModel(
        _accepted_payload([_post_observation_check("proposition:0:joy")])
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )

    result = await validator.validate(
        _source(),
        _joy_high_context(),
        _response(
            "とても楽しいし、悲しくもあるよ。",
            ("proposition:0:joy", "proposition:9:sadness"),
        ),
    )

    assert result.accepted is False
    assert result.reason == "unknown_semantic_realization"
    assert result.claim_differences == ("proposition:9:sadness",)
    assert model.activities == []


@pytest.mark.asyncio
async def test_all_realized_observations_and_post_checks_consistent_accepts() -> None:
    realizations = (
        "proposition:0:current_feeling",
        "proposition:1:joy",
        "proposition:2:anger",
    )
    model = _RecordingValidationModel(
        _accepted_payload(
            [_post_observation_check(realization_id) for realization_id in realizations]
        ),
        observer_overrides={
            "proposition:0:current_feeling": {
                "state_evidence_spans": ["今の気分"],
            },
            "proposition:1:joy": {
                "state_evidence_spans": ["かなりうれしく"],
            },
            "proposition:2:anger": {
                "state_evidence_spans": ["腹立たしさもある"],
            },
        },
    )
    validator = CharacterRealizationValidator(
        model=model,
        prompt_builder=CharacterRealizationValidatorPromptBuilder(),
    )

    result = await validator.validate(
        _source(),
        _mixed_context(),
        _response(
            "今の気分は、かなりうれしくて、腹立たしさもある。",
            realizations,
        ),
    )

    assert result.accepted is True
    assert result.reason == "post_observation_semantic_contract_consistent"