import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest

from app.domain.appraisal import (
    OUTPUT_SCHEMA,
    AppraisalDimension,
    AppraisalDimensionKind,
    AppraisalPath,
    DeepAppraisalContext,
    DeepAppraisalFreshnessStamp,
    DeepAppraisalInterpreter,
    DeepAppraisalLiveStatePort,
    DeepAppraisalPolicy,
    DeterministicAppraisalRule,
    FacetRef,
    InternalStateFacet,
    InternalStateReducer,
    InternalStateSnapshot,
    StateDeltaProposal,
    StateFacetKind,
    appraise_event,
    build_deep_request,
    commit_deep_result,
)
from app.domain.contracts import EventEnvelope, RevisionVector
from app.domain.contracts.common import JsonValue
from app.domain.input_meaning import (
    ExpectedResponse,
    MeaningResolution,
    PrimaryIntent,
    SpeechAct,
    StructuredInputMeaning,
    TemporalRelation,
)
from app.domain.llm import (
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)
from tests.helpers.llm import make_execution_policy

NOW = datetime(2026, 8, 24, tzinfo=timezone.utc)
JOY = FacetRef(StateFacetKind.EMOTION, "joy")


def event(event_type: str = "activity.completed") -> EventEnvelope:
    return EventEnvelope(
        "event:1",
        event_type,
        "activity-runtime",
        NOW,
        "trace:1",
        RevisionVector(7),
        {"activity_ref": "activity:1"},
    )


def meaning() -> StructuredInputMeaning:
    return StructuredInputMeaning(
        "event:1",
        7,
        SpeechAct.STATEMENT,
        PrimaryIntent.PROVIDE_INFORMATION,
        ExpectedResponse.ACKNOWLEDGEMENT,
        None,
        (),
        (),
        ("活動が完了した",),
        False,
        False,
        TemporalRelation.PAST,
        0.9,
        (),
        MeaningResolution.RESOLVED,
        "yura.input-meaning.acceptance",
        1,
    )


def state(value: float = 0.2, revision: int = 3) -> InternalStateSnapshot:
    facet = InternalStateFacet(JOY, value, 0.0, value, 0.8, ("event:seed",), NOW)
    return InternalStateSnapshot(revision, 7, (facet,), NOW)


def policy() -> DeepAppraisalPolicy:
    return DeepAppraisalPolicy(
        make_execution_policy(
            LLMModelClass.BALANCED,
            LLMReasoningEffort.MEDIUM,
            10,
            1,
            800,
        )
    )


def output(
    *,
    cause_ref: str = "event:1",
    target_ref: str | None = None,
    delta: float = 0.2,
) -> dict[str, Any]:
    return {
        "candidate_id": "candidate:deep:1",
        "dimensions": [{"kind": "pleasantness", "value": 0.6, "target_ref": target_ref}],
        "proposals": [
            {
                "facet_kind": "emotion",
                "state_key": "joy",
                "target_ref": None,
                "delta": delta,
                "confidence": 0.8,
                "cause_refs": [cause_ref],
            }
        ],
        "salience": 0.7,
        "relevance": 0.8,
        "evidence_refs": [cause_ref],
    }


def result(request: LLMRoleRequest, value: object | None = None) -> LLMRoleResult:
    return LLMRoleResult(
        request.request_id,
        request.role_id,
        LLMRoleStatus.SUCCEEDED,
        request.revisions,
        NOW + timedelta(seconds=2),
        request.trace_id,
        LLMModelClass.BALANCED,
        1,
        LLMTokenUsage(20, 10),
        StructuredPayload(OUTPUT_SCHEMA, cast(JsonValue, output() if value is None else value)),
        started_at=NOW + timedelta(seconds=1),
    )


def test_deterministic_appraisal_uses_typed_event_not_raw_text() -> None:
    rule = DeterministicAppraisalRule(
        "rule:activity-completed",
        "activity.completed",
        (AppraisalDimension(AppraisalDimensionKind.GOAL_CONGRUENCE, 0.7),),
        (StateDeltaProposal(JOY, 0.2, 0.9, ("event:1",)),),
        0.7,
        0.8,
    )
    candidate = appraise_event(
        event(), state(), (rule,), candidate_id="candidate:fast:1", created_at=NOW
    )
    assert candidate is not None
    assert candidate.path is AppraisalPath.FAST_DETERMINISTIC
    assert candidate.proposals[0].cause_refs == ("event:1", "rule:activity-completed")
    assert (
        appraise_event(
            event("activity.failed"),
            state(),
            (rule,),
            candidate_id="candidate:none",
            created_at=NOW,
        )
        is None
    )


def test_deep_request_contains_current_state_and_revision_without_provider_types() -> None:
    request = build_deep_request(
        event(),
        None,
        state(),
        DeepAppraisalContext(("goal:1",)),
        request_id="request:1",
        trace_id="trace:1",
        created_at=NOW,
        policy=policy(),
    )
    value = cast(dict[str, Any], request.input.to_dict()["value"])
    assert value["state"]["revision"] == 3
    assert request.revisions.source_context_revision == 7
    assert request.role_id == "subjective_appraisal"


def test_same_event_with_different_current_state_produces_different_request_snapshot() -> None:
    first = build_deep_request(
        event(),
        None,
        state(0.2),
        DeepAppraisalContext(),
        request_id="request:1",
        trace_id="trace:1",
        created_at=NOW,
        policy=policy(),
    )
    second = build_deep_request(
        event(),
        None,
        state(0.8),
        DeepAppraisalContext(),
        request_id="request:2",
        trace_id="trace:2",
        created_at=NOW,
        policy=policy(),
    )
    first_value = cast(dict[str, Any], first.input.to_dict()["value"])
    second_value = cast(dict[str, Any], second.input.to_dict()["value"])
    assert first_value["state"] != second_value["state"]


def test_natural_language_appraisal_uses_meaning_without_exposing_raw_text() -> None:
    language_event = EventEnvelope(
        "event:1",
        "input.text.utterance",
        "chat",
        NOW,
        "trace:1",
        RevisionVector(7),
        {"content": {"text": "raw text must not be reinterpreted"}},
    )
    with pytest.raises(ValueError, match="requires StructuredInputMeaning"):
        build_deep_request(
            language_event,
            None,
            state(),
            DeepAppraisalContext(),
            request_id="request:1",
            trace_id="trace:1",
            created_at=NOW,
            policy=policy(),
        )
    request = build_deep_request(
        language_event,
        meaning(),
        state(),
        DeepAppraisalContext(),
        request_id="request:1",
        trace_id="trace:1",
        created_at=NOW,
        policy=policy(),
    )
    value = cast(dict[str, Any], request.input.to_dict()["value"])
    assert "payload" not in value["event"]
    assert value["meaning"]["primary_intent"] == "provide_information"


def test_deep_candidate_schema_and_bounded_evidence_are_validated() -> None:
    context = DeepAppraisalContext(("goal:1",))
    request = build_deep_request(
        event(),
        None,
        state(),
        context,
        request_id="request:1",
        trace_id="trace:1",
        created_at=NOW,
        policy=policy(),
    )
    candidate = commit_deep_result(
        request,
        result(request),
        event=event(),
        snapshot=state(),
        context=context,
        current_source_context_revision=7,
        current_state_revision=3,
        policy=policy(),
    )
    assert candidate.path is AppraisalPath.DEEP_LLM
    with pytest.raises(ValueError, match="outside bounded context"):
        commit_deep_result(
            request,
            result(request, output(cause_ref="invented:1")),
            event=event(),
            snapshot=state(),
            context=context,
            current_source_context_revision=7,
            current_state_revision=3,
            policy=policy(),
        )


def test_deep_target_and_schema_extra_fields_are_rejected() -> None:
    context = DeepAppraisalContext(("person:user",))
    request = build_deep_request(
        event(),
        None,
        state(),
        context,
        request_id="request:1",
        trace_id="trace:1",
        created_at=NOW,
        policy=policy(),
    )
    with pytest.raises(ValueError, match="target is outside bounded"):
        commit_deep_result(
            request,
            result(request, output(target_ref="person:invented")),
            event=event(),
            snapshot=state(),
            context=context,
            current_source_context_revision=7,
            current_state_revision=3,
            policy=policy(),
        )
    invalid = output()
    invalid["goal"] = "adopt"
    with pytest.raises(ValueError, match="fields do not match schema"):
        commit_deep_result(
            request,
            result(request, invalid),
            event=event(),
            snapshot=state(),
            context=context,
            current_source_context_revision=7,
            current_state_revision=3,
            policy=policy(),
        )
    with pytest.raises(ValueError, match="between"):
        commit_deep_result(
            request,
            result(request, output(delta=2.0)),
            event=event(),
            snapshot=state(),
            context=context,
            current_source_context_revision=7,
            current_state_revision=3,
            policy=policy(),
        )


@pytest.mark.parametrize(("context_revision", "state_revision"), [(8, 3), (7, 4)])
def test_stale_deep_appraisal_never_commits(context_revision: int, state_revision: int) -> None:
    context = DeepAppraisalContext()
    request = build_deep_request(
        event(),
        None,
        state(),
        context,
        request_id="request:1",
        trace_id="trace:1",
        created_at=NOW,
        policy=policy(),
    )
    with pytest.raises(ValueError, match="stale"):
        commit_deep_result(
            request,
            result(request),
            event=event(),
            snapshot=state(),
            context=context,
            current_source_context_revision=context_revision,
            current_state_revision=state_revision,
            policy=policy(),
        )


def test_slow_deep_appraisal_does_not_block_unrelated_task() -> None:
    observed: list[str] = []

    class SlowPort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            await asyncio.sleep(0.02)
            return result(request)

    class LiveState:
        async def freshness_stamp(self) -> DeepAppraisalFreshnessStamp:
            return DeepAppraisalFreshnessStamp(7, 3)

    async def scenario() -> None:
        task = asyncio.create_task(
            DeepAppraisalInterpreter(SlowPort(), LiveState(), policy()).appraise(
                event(),
                None,
                state(),
                DeepAppraisalContext(),
                request_id="request:1",
                trace_id="trace:1",
                created_at=NOW,
            )
        )
        await asyncio.sleep(0)
        observed.append("unrelated")
        await task

    asyncio.run(scenario())
    assert observed == ["unrelated"]


@pytest.mark.parametrize(
    "advanced_stamp",
    [DeepAppraisalFreshnessStamp(8, 3), DeepAppraisalFreshnessStamp(7, 4)],
)
def test_interpret_rejects_stale_post_await_live_freshness(
    advanced_stamp: DeepAppraisalFreshnessStamp,
) -> None:
    class ControlledPort:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            self.started.set()
            await self.release.wait()
            return result(request)

    class LiveState:
        stamp = DeepAppraisalFreshnessStamp(7, 3)

        async def freshness_stamp(self) -> DeepAppraisalFreshnessStamp:
            return self.stamp

    async def scenario() -> None:
        provider = ControlledPort()
        live_state = LiveState()
        task = asyncio.create_task(
            DeepAppraisalInterpreter(provider, live_state, policy()).appraise(
                event(),
                None,
                state(),
                DeepAppraisalContext(),
                request_id="request:1",
                trace_id="trace:1",
                created_at=NOW,
            )
        )
        await provider.started.wait()
        live_state.stamp = advanced_stamp
        provider.release.set()
        with pytest.raises(ValueError, match="stale"):
            await task

    asyncio.run(scenario())


def test_interpret_preserves_request_revisions_after_live_freshness_gate() -> None:
    class ImmediatePort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return result(request)

    class LiveState:
        async def freshness_stamp(self) -> DeepAppraisalFreshnessStamp:
            return DeepAppraisalFreshnessStamp(7, 3)

    candidate = asyncio.run(
        DeepAppraisalInterpreter(ImmediatePort(), LiveState(), policy()).appraise(
            event(),
            None,
            state(),
            DeepAppraisalContext(),
            request_id="request:1",
            trace_id="trace:1",
            created_at=NOW,
        )
    )
    assert candidate.source_context_revision == 7
    assert candidate.base_state_revision == 3


@pytest.mark.parametrize(
    "error", [RuntimeError("live state unavailable"), ValueError("no stable pair")]
)
def test_interpret_fails_closed_when_live_freshness_read_cannot_succeed(error: Exception) -> None:
    class ImmediatePort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return result(request)

    class FailingLiveState:
        async def freshness_stamp(self) -> DeepAppraisalFreshnessStamp:
            raise error

    with pytest.raises(type(error), match=str(error)):
        asyncio.run(
            DeepAppraisalInterpreter(ImmediatePort(), FailingLiveState(), policy()).appraise(
                event(),
                None,
                state(),
                DeepAppraisalContext(),
                request_id="request:1",
                trace_id="trace:1",
                created_at=NOW,
            )
        )


def test_old_deep_result_cannot_be_reused_with_new_snapshot_or_context() -> None:
    request = build_deep_request(
        event(),
        None,
        state(),
        DeepAppraisalContext(),
        request_id="request:1",
        trace_id="trace:1",
        created_at=NOW,
        policy=policy(),
    )
    with pytest.raises(ValueError, match="state does not match request snapshot"):
        commit_deep_result(
            request,
            result(request),
            event=event(),
            snapshot=state(value=0.8),
            context=DeepAppraisalContext(),
            current_source_context_revision=7,
            current_state_revision=3,
            policy=policy(),
        )
    with pytest.raises(ValueError, match="context does not match request snapshot"):
        commit_deep_result(
            request,
            result(request),
            event=event(),
            snapshot=state(),
            context=DeepAppraisalContext(("goal:1",)),
            current_source_context_revision=7,
            current_state_revision=3,
            policy=policy(),
        )


def test_live_state_port_returns_one_typed_freshness_stamp() -> None:
    class LiveState:
        async def freshness_stamp(self) -> DeepAppraisalFreshnessStamp:
            return DeepAppraisalFreshnessStamp(7, 3)

    port: DeepAppraisalLiveStatePort = LiveState()
    assert asyncio.run(port.freshness_stamp()) == DeepAppraisalFreshnessStamp(7, 3)


def test_reducer_rejects_conflict_that_occurs_after_live_freshness_gate() -> None:
    class ImmediatePort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return result(request)

    class LiveState:
        async def freshness_stamp(self) -> DeepAppraisalFreshnessStamp:
            return DeepAppraisalFreshnessStamp(7, 3)

    live_gated = asyncio.run(
        DeepAppraisalInterpreter(ImmediatePort(), LiveState(), policy()).appraise(
            event(),
            None,
            state(),
            DeepAppraisalContext(),
            request_id="request:1",
            trace_id="trace:1",
            created_at=NOW,
        )
    )
    competing_request = build_deep_request(
        event(),
        None,
        state(),
        DeepAppraisalContext(),
        request_id="request:2",
        trace_id="trace:2",
        created_at=NOW,
        policy=policy(),
    )
    competing = commit_deep_result(
        competing_request,
        result(competing_request),
        event=event(),
        snapshot=state(),
        context=DeepAppraisalContext(),
        current_source_context_revision=7,
        current_state_revision=3,
        policy=policy(),
    )
    reducer = InternalStateReducer(state())
    reducer.commit(
        competing,
        current_source_context_revision=7,
        committed_at=NOW + timedelta(seconds=3),
    )
    with pytest.raises(ValueError, match="stale for current state"):
        reducer.commit(
            live_gated,
            current_source_context_revision=7,
            committed_at=NOW + timedelta(seconds=4),
        )
