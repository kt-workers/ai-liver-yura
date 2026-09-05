import asyncio
import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts import CapabilityAvailability, RevisionVector
from app.domain.contracts.common import JsonValue
from app.domain.input_gateway import (
    InputAdmissionLedger,
    InputModality,
    InputNormalizer,
    InputObservation,
    InputPermission,
    InputSessionRegistry,
    InputSourceState,
    NormalizedInputEvent,
)
from app.domain.input_meaning import (
    OUTPUT_SCHEMA,
    ExpectedResponse,
    InputMeaningAcceptancePolicy,
    InputMeaningBoundaryFailure,
    InputMeaningFreshnessStamp,
    InputMeaningInterpretationResult,
    InputMeaningInterpreter,
    InputMeaningLiveContextPort,
    InputMeaningPolicy,
    MeaningResolution,
    PrimaryIntent,
    ReferenceContext,
    ReferenceContextEntry,
    ReferenceContextKind,
    build_request,
    commit_result,
)
from app.domain.llm import (
    LLMFailureCode,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleFailure,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)
from tests.helpers.llm import make_execution_policy

NOW = datetime(2026, 8, 19, tzinfo=timezone.utc)


def policy() -> InputMeaningPolicy:
    required_fields: dict[PrimaryIntent, tuple[str, ...]] = {
        intent: ("references",) for intent in PrimaryIntent
    }
    for intent in (
        PrimaryIntent.REQUEST_ACTION,
        PrimaryIntent.START_ACTIVITY,
        PrimaryIntent.STOP_ACTIVITY,
    ):
        required_fields[intent] = ("target_ref", "references")
    return InputMeaningPolicy(
        make_execution_policy(LLMModelClass.BALANCED, LLMReasoningEffort.MEDIUM, 10, 1, 800),
        InputMeaningAcceptancePolicy("yura.input-meaning.acceptance", 1, 0.7, required_fields),
    )


def freshness_stamp(
    revision: int = 4, acceptance: InputMeaningAcceptancePolicy | None = None
) -> InputMeaningFreshnessStamp:
    value = policy().acceptance if acceptance is None else acceptance
    return InputMeaningFreshnessStamp(revision, value.policy_id, value.policy_revision)


def event(
    text: str = "それをもう一度説明して",
    modality: InputModality = InputModality.TEXT,
) -> NormalizedInputEvent:
    observation = InputObservation(
        "obs-1",
        InputSourceState("chat", "user", CapabilityAvailability.AVAILABLE, InputPermission.GRANTED),
        modality,
        "utterance",
        NOW,
        "trace-1",
        RevisionVector(4),
        {"text": text},
    )
    admission = InputNormalizer(
        InputAdmissionLedger(),
        InputSessionRegistry(),
        bounds_policy=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    ).normalize(observation)
    assert admission.event is not None
    return admission.event


def context(revision: int = 4) -> ReferenceContext:
    return ReferenceContext(
        revision,
        (
            ReferenceContextEntry(
                "speech-1", ReferenceContextKind.RECENT_SPEECH, "presentation:42", 3
            ),
        ),
    )


def output(
    *,
    confidence: float = 0.9,
    unresolved: tuple[str, ...] = (),
    reference: str | None = "presentation:42",
    negated: bool = False,
    hypothetical: bool = False,
) -> dict[str, Any]:
    return {
        "speech_act": "request",
        "primary_intent": "request_information",
        "expected_response": "answer",
        "target_ref": "presentation:42",
        "entities": [],
        "references": [{"mention_id": "それ", "resolved_ref": reference}],
        "information": ["説明の再提示"],
        "negated": negated,
        "hypothetical": hypothetical,
        "temporal_relation": "relative",
        "confidence": confidence,
        "unresolved_fields": list(unresolved),
    }


def result(request: LLMRoleRequest, value: object | None = None) -> LLMRoleResult:
    return LLMRoleResult(
        request.request_id,
        request.role_id,
        LLMRoleStatus.SUCCEEDED,
        request.revisions,
        NOW + timedelta(seconds=1),
        request.trace_id,
        LLMModelClass.BALANCED,
        1,
        LLMTokenUsage(20, 10),
        StructuredPayload(OUTPUT_SCHEMA, cast(JsonValue, output() if value is None else value)),
        started_at=NOW,
    )


def test_text_and_stt_use_same_role_schema_and_reference_context() -> None:
    text_request = build_request(
        event(), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    speech_request = build_request(
        event(modality=InputModality.SPEECH),
        context(),
        request_id="r2",
        trace_id="t2",
        created_at=NOW,
        policy=policy(),
    )
    assert text_request.role_id == speech_request.role_id == "input_meaning"
    assert text_request.input.schema_id == speech_request.input.schema_id
    request_value = cast(dict[str, Any], text_request.input.to_dict()["value"])
    assert request_value["reference_context"]["entries"][0]["reference_id"] == "speech-1"


@pytest.mark.parametrize("surface", ["それをもう一度説明して", "先ほどの内容を再度教えて"])
def test_paraphrase_provider_candidates_commit_to_same_typed_meaning(surface: str) -> None:
    request = build_request(
        event(surface), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    meaning = commit_result(
        request,
        result(request),
        reference_context=context(),
        freshness_stamp=freshness_stamp(),
        policy=policy(),
    )
    assert meaning.primary_intent is PrimaryIntent.REQUEST_INFORMATION
    assert meaning.expected_response is ExpectedResponse.ANSWER
    assert meaning.references[0].resolved_ref == "presentation:42"
    assert "text" not in meaning.to_dict()
    json.dumps(meaning.to_dict(), allow_nan=False)


def test_low_confidence_and_unresolved_reference_fail_closed_to_clarification() -> None:
    request = build_request(
        event(), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    meaning = commit_result(
        request,
        result(request, output(confidence=0.2, reference=None)),
        reference_context=context(),
        freshness_stamp=freshness_stamp(),
        policy=policy(),
    )
    assert meaning.resolution is MeaningResolution.CLARIFICATION_REQUIRED
    assert set(meaning.unresolved_fields) == {"confidence", "references"}


def test_acceptance_policy_controls_threshold_required_resolution_and_provenance() -> None:
    request = build_request(
        event(), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    at_threshold = commit_result(
        request,
        result(request, output(confidence=0.7)),
        reference_context=context(),
        freshness_stamp=freshness_stamp(),
        policy=policy(),
    )
    assert at_threshold.resolution is MeaningResolution.RESOLVED
    assert at_threshold.acceptance_policy_id == "yura.input-meaning.acceptance"
    assert at_threshold.acceptance_policy_revision == 1

    action = output()
    action["primary_intent"] = PrimaryIntent.REQUEST_ACTION.value
    action["target_ref"] = None
    clarification = commit_result(
        request,
        result(request, action),
        reference_context=context(),
        freshness_stamp=freshness_stamp(),
        policy=policy(),
    )
    assert clarification.resolution is MeaningResolution.CLARIFICATION_REQUIRED
    assert "target_ref" in clarification.unresolved_fields


def test_acceptance_policy_requires_closed_full_intent_mapping() -> None:
    full_mapping: dict[PrimaryIntent, tuple[str, ...]] = {intent: () for intent in PrimaryIntent}
    with pytest.raises(ValueError, match="全primary intent"):
        InputMeaningAcceptancePolicy("policy", 1, 0.7, {})
    full_mapping[PrimaryIntent.REQUEST_ACTION] = ("unknown",)
    with pytest.raises(ValueError, match="不正"):
        InputMeaningAcceptancePolicy("policy", 1, 0.7, full_mapping)


@pytest.mark.parametrize(
    "intent",
    ["request_action", "start_activity", "stop_activity"],
)
def test_action_intents_without_target_require_clarification(intent: str) -> None:
    request = build_request(
        event(), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    value = output()
    value["primary_intent"] = intent
    value["target_ref"] = None
    meaning = commit_result(
        request,
        result(request, value),
        reference_context=context(),
        freshness_stamp=freshness_stamp(),
        policy=policy(),
    )
    assert meaning.resolution is MeaningResolution.CLARIFICATION_REQUIRED
    assert "target_ref" in meaning.unresolved_fields


def test_negation_and_hypothetical_are_typed_without_surface_matching() -> None:
    request = build_request(
        event("仮に始めるとしても今は始めない"),
        context(),
        request_id="r1",
        trace_id="t1",
        created_at=NOW,
        policy=policy(),
    )
    meaning = commit_result(
        request,
        result(request, output(negated=True, hypothetical=True)),
        reference_context=context(),
        freshness_stamp=freshness_stamp(),
        policy=policy(),
    )
    assert meaning.negated is True and meaning.hypothetical is True


def test_non_language_stale_and_extra_output_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="only text or speech"):
        build_request(
            event(modality=InputModality.VISION),
            context(),
            request_id="r",
            trace_id="t",
            created_at=NOW,
            policy=policy(),
        )
    request = build_request(
        event(), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    with pytest.raises(ValueError, match="古くなっています"):
        commit_result(
            request,
            result(request),
            reference_context=context(),
            freshness_stamp=freshness_stamp(5),
            policy=policy(),
        )
    invalid = output()
    invalid["appraisal"] = "happy"
    with pytest.raises(ValueError, match="fields do not match schema"):
        commit_result(
            request,
            result(request, invalid),
            reference_context=context(),
            freshness_stamp=freshness_stamp(),
            policy=policy(),
        )


def test_reference_outside_bounded_context_is_rejected() -> None:
    request = build_request(
        event(), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    with pytest.raises(ValueError, match="範囲外"):
        commit_result(
            request,
            result(request, output(reference="made-up:999")),
            reference_context=context(),
            freshness_stamp=freshness_stamp(),
            policy=policy(),
        )


def test_wrapper_modality_cannot_relabel_vision_envelope_as_text() -> None:
    vision = event(modality=InputModality.VISION)
    disguised = replace(vision, modality=InputModality.TEXT)
    with pytest.raises(ValueError, match="event_type does not match"):
        build_request(
            disguised,
            context(),
            request_id="r1",
            trace_id="t1",
            created_at=NOW,
            policy=policy(),
        )


def test_reference_context_is_bounded_unique_and_not_from_future() -> None:
    entry = ReferenceContextEntry("r", ReferenceContextKind.CURRENT_TOPIC, "topic:1", 4)
    with pytest.raises(ValueError, match="max_entries"):
        ReferenceContext(4, (entry,), max_entries=0)
    with pytest.raises(ValueError, match="unique"):
        ReferenceContext(4, (entry, entry))
    with pytest.raises(ValueError, match="newer"):
        ReferenceContext(3, (entry,))


def test_slow_meaning_port_does_not_block_unrelated_task() -> None:
    observed: list[str] = []

    class SlowPort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            await asyncio.sleep(0.02)
            return result(request)

    class LiveContext:
        async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
            return freshness_stamp()

    async def scenario() -> None:
        task = asyncio.create_task(
            InputMeaningInterpreter(SlowPort(), LiveContext(), policy()).interpret(
                event(),
                context(),
                request_id="r1",
                trace_id="t1",
                created_at=NOW,
            )
        )
        await asyncio.sleep(0)
        observed.append("unrelated")
        await task

    asyncio.run(scenario())
    assert observed == ["unrelated"]


def test_interpret_rejects_result_when_live_context_advances_during_provider_wait() -> None:
    class AdvancingPort:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            self.started.set()
            await self.release.wait()
            return result(request)

    class LiveContext:
        revision = 4

        async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
            return freshness_stamp(self.revision)

    async def scenario() -> None:
        provider = AdvancingPort()
        live_context = LiveContext()
        task = asyncio.create_task(
            InputMeaningInterpreter(provider, live_context, policy()).interpret(
                event(), context(), request_id="r1", trace_id="t1", created_at=NOW
            )
        )
        await provider.started.wait()
        live_context.revision = 5
        provider.release.set()
        outcome = await task
        assert outcome.boundary_failure is not None
        assert outcome.boundary_failure.code is LLMFailureCode.STALE
        assert outcome.meaning is None

    asyncio.run(scenario())


def test_interpret_rejects_result_when_live_acceptance_policy_advances() -> None:
    class ImmediatePort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return result(request)

    class LiveContext:
        async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
            return InputMeaningFreshnessStamp(4, "yura.input-meaning.acceptance", 2)

    outcome = asyncio.run(
        InputMeaningInterpreter(ImmediatePort(), LiveContext(), policy()).interpret(
            event(), context(), request_id="r1", trace_id="t1", created_at=NOW
        )
    )
    assert outcome.boundary_failure is not None
    assert outcome.boundary_failure.code is LLMFailureCode.STALE
    assert outcome.meaning is None


def test_interpret_preserves_request_revision_after_post_await_live_read() -> None:
    class ImmediatePort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return result(request)

    class LiveContext:
        async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
            return freshness_stamp()

    meaning = asyncio.run(
        InputMeaningInterpreter(ImmediatePort(), LiveContext(), policy()).interpret(
            event(), context(), request_id="r1", trace_id="t1", created_at=NOW
        )
    )
    assert meaning.meaning is not None
    assert meaning.meaning.source_context_revision == 4


def test_interpret_fails_closed_when_live_context_read_fails() -> None:
    class ImmediatePort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return result(request)

    class FailingLiveContext:
        async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
            raise RuntimeError("live context unavailable")

    outcome = asyncio.run(
        InputMeaningInterpreter(ImmediatePort(), FailingLiveContext(), policy()).interpret(
            event(), context(), request_id="r1", trace_id="t1", created_at=NOW
        )
    )
    assert outcome.boundary_failure is not None
    assert outcome.boundary_failure.code is LLMFailureCode.REJECTED
    assert "live context unavailable" not in outcome.boundary_failure.message
    assert outcome.meaning is None


def test_live_context_port_is_read_only_protocol() -> None:
    class LiveContext:
        async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
            return freshness_stamp()

    port: InputMeaningLiveContextPort = LiveContext()
    assert asyncio.run(port.current_freshness_stamp()) == freshness_stamp()


def test_old_result_cannot_be_reused_with_new_reference_context() -> None:
    request = build_request(
        event(), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    with pytest.raises(ValueError, match="要求時の固定内容と一致しません"):
        commit_result(
            request,
            result(request),
            reference_context=context(5),
            freshness_stamp=freshness_stamp(),
            policy=policy(),
        )


ROLE_FAILURES = [
    (LLMRoleStatus.FAILED, LLMFailureCode.PROVIDER_UNAVAILABLE),
    (LLMRoleStatus.FAILED, LLMFailureCode.PROVIDER_ERROR),
    (LLMRoleStatus.FAILED, LLMFailureCode.SCHEMA_INVALID),
    (LLMRoleStatus.FAILED, LLMFailureCode.POLICY_VIOLATION),
    (LLMRoleStatus.TIMED_OUT, LLMFailureCode.TIMEOUT),
    (LLMRoleStatus.CANCELLED, LLMFailureCode.CANCELLED),
    (LLMRoleStatus.STALE, LLMFailureCode.STALE),
    (LLMRoleStatus.SUPERSEDED, LLMFailureCode.SUPERSEDED),
    (LLMRoleStatus.REJECTED, LLMFailureCode.REJECTED),
]


class RecordingLiveContext:
    def __init__(self, stamp: InputMeaningFreshnessStamp | None = None) -> None:
        self.calls = 0
        self.stamp = freshness_stamp() if stamp is None else stamp

    async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
        self.calls += 1
        return self.stamp


@pytest.mark.parametrize(("status", "code"), ROLE_FAILURES)
@pytest.mark.parametrize("retryable", [False, True])
def test_interpret_preserves_role_failure_without_live_read(
    status: LLMRoleStatus, code: LLMFailureCode, retryable: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = LLMRoleFailure(code, "提供サービスから通知された失敗", retryable)
    live = RecordingLiveContext(freshness_stamp(5))

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return replace(result(request), status=status, output=None, failure=failure)

    def forbidden_commit(*args: object, **kwargs: object) -> None:
        pytest.fail("非成功で意味の採用処理を呼んではなりません")

    monkeypatch.setattr("app.domain.input_meaning.interpreter.commit_result", forbidden_commit)
    outcome = asyncio.run(
        InputMeaningInterpreter(Port(), live, policy()).interpret(
            event(), context(), request_id="r1", trace_id="t1", created_at=NOW
        )
    )
    assert outcome.role_status is status
    assert outcome.role_failure is failure
    assert outcome.meaning is None
    assert outcome.boundary_failure is None
    assert live.calls == 0
    encoded = json.loads(json.dumps(outcome.to_dict(), allow_nan=False))
    assert encoded["role_failure"] == failure.to_dict()
    assert encoded["source_context_revision"] == 4
    with pytest.raises(FrozenInstanceError):
        cast(Any, outcome).role_status = LLMRoleStatus.SUCCEEDED


@pytest.mark.parametrize(
    "field", ["request_id", "role_id", "trace_id", "revisions", "completed_at"]
)
@pytest.mark.parametrize("failed", [False, True])
def test_exchange_rejection_precedes_failure_and_live_read(field: str, failed: bool) -> None:
    live = RecordingLiveContext()

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            response = result(request)
            if failed:
                response = replace(
                    response,
                    status=LLMRoleStatus.FAILED,
                    output=None,
                    failure=LLMRoleFailure(LLMFailureCode.PROVIDER_UNAVAILABLE, "利用できません"),
                )
            changes: dict[str, Any] = {field: "別の識別子"}
            if field == "revisions":
                changes[field] = RevisionVector(9)
            if field == "completed_at":
                changes[field] = NOW - timedelta(seconds=1)
                changes["started_at"] = NOW - timedelta(seconds=2)
            return replace(response, **changes)

    outcome = asyncio.run(
        InputMeaningInterpreter(Port(), live, policy()).interpret(
            event(), context(), request_id="r1", trace_id="t1", created_at=NOW
        )
    )
    assert outcome.role_status is None
    assert outcome.role_failure is None
    assert outcome.meaning is None
    assert outcome.boundary_failure is not None
    assert outcome.boundary_failure.code is LLMFailureCode.POLICY_VIOLATION
    assert not outcome.boundary_failure.retryable
    assert (outcome.request_id, outcome.trace_id, outcome.source_context_revision) == (
        "r1",
        "t1",
        4,
    )
    assert live.calls == 0


@pytest.mark.parametrize("case", ["schema_id", "fields", "enum", "reference"])
def test_success_candidate_rejection_is_typed(case: str) -> None:
    live = RecordingLiveContext()

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            candidate = output()
            if case == "fields":
                candidate.pop("speech_act")
            elif case == "enum":
                candidate["speech_act"] = {"不正": "値"}
            elif case == "reference":
                candidate = output(reference="範囲外")
            response = result(request, candidate)
            if case == "schema_id":
                return replace(response, output=StructuredPayload("別の構造", candidate))
            return response

    outcome = asyncio.run(
        InputMeaningInterpreter(Port(), live, policy()).interpret(
            event(), context(), request_id="r1", trace_id="t1", created_at=NOW
        )
    )
    assert outcome.meaning is None
    assert outcome.role_failure is None
    assert outcome.boundary_failure is not None
    expected = (
        LLMFailureCode.POLICY_VIOLATION if case == "reference" else LLMFailureCode.SCHEMA_INVALID
    )
    assert outcome.boundary_failure.code is expected
    assert not outcome.boundary_failure.retryable
    assert live.calls == (0 if case == "schema_id" else 1)
    assert outcome.role_status is (None if case == "schema_id" else LLMRoleStatus.SUCCEEDED)


@pytest.mark.parametrize("modality", [InputModality.TEXT, InputModality.SPEECH])
@pytest.mark.parametrize("confidence", [0.6, 0.7, 0.9])
def test_public_success_matches_pure_commit_and_reads_live_once(
    modality: InputModality, confidence: float
) -> None:
    live = RecordingLiveContext()
    request = build_request(
        event(modality=modality),
        context(),
        request_id="r1",
        trace_id="t1",
        created_at=NOW,
        policy=policy(),
    )
    response = result(request, output(confidence=confidence))

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return response

    outcome = asyncio.run(
        InputMeaningInterpreter(Port(), live, policy()).interpret(
            event(modality=modality), context(), request_id="r1", trace_id="t1", created_at=NOW
        )
    )
    assert outcome.meaning == commit_result(
        request,
        response,
        reference_context=context(),
        freshness_stamp=freshness_stamp(),
        policy=policy(),
    )
    assert outcome.role_status is LLMRoleStatus.SUCCEEDED
    assert outcome.role_failure is None
    assert outcome.boundary_failure is None
    assert live.calls == 1
    json.dumps(outcome.to_dict(), allow_nan=False)


@pytest.mark.parametrize("phase", ["provider", "live"])
def test_external_cancellation_propagates(phase: str) -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        reaped = asyncio.Event()

        async def wait_for_cancellation() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                reaped.set()

        class Port:
            async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
                if phase == "provider":
                    await wait_for_cancellation()
                return result(request)

        class Live:
            async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
                await wait_for_cancellation()
                return freshness_stamp()

        task = asyncio.create_task(
            InputMeaningInterpreter(Port(), Live(), policy()).interpret(
                event(), context(), request_id="r1", trace_id="t1", created_at=NOW
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled() and reaped.is_set()

    asyncio.run(scenario())


def test_public_result_rejects_invalid_variants_and_preserves_json() -> None:
    failure = LLMRoleFailure(LLMFailureCode.PROVIDER_ERROR, "処理できません", True)
    valid = InputMeaningInterpretationResult(
        "r", "t", "e", 0, LLMRoleStatus.FAILED, role_failure=failure
    )
    boundary = InputMeaningBoundaryFailure(LLMFailureCode.REJECTED, "現在世代を取得できません")
    invalid: list[dict[str, Any]] = [
        {"role_failure": None},
        {"boundary_failure": boundary},
        {"role_status": None},
        {"role_status": LLMRoleStatus.SUCCEEDED},
        {"role_status": LLMRoleStatus.TIMED_OUT},
        {"source_context_revision": True},
        {"request_id": ""},
        {"role_failure": "失敗"},
        {"role_failure": replace(failure, retryable=cast(bool, 1))},
    ]
    for changes in invalid:
        with pytest.raises(ValueError):
            replace(valid, **changes)
    rejected = replace(valid, role_failure=None, role_status=None, boundary_failure=boundary)
    assert (
        json.loads(json.dumps(rejected.to_dict(), allow_nan=False))["boundary_failure"]
        == boundary.to_dict()
    )
    with pytest.raises(FrozenInstanceError):
        cast(Any, boundary).retryable = True
    with pytest.raises(ValueError):
        InputMeaningBoundaryFailure(LLMFailureCode.STALE, "古い結果", cast(bool, 1))


def test_invalid_request_remains_programming_error() -> None:
    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            pytest.fail("不正な要求を提供サービスへ送ってはなりません")

    live = RecordingLiveContext()
    with pytest.raises(ValueError):
        asyncio.run(
            InputMeaningInterpreter(Port(), live, policy()).interpret(
                event(), context(5), request_id="r1", trace_id="t1", created_at=NOW
            )
        )
    assert live.calls == 0
