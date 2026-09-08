"""注意・評価の本体所有者から実際の判断確定までを検証する。"""

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, cast

import pytest

from app.composition.executive import CoreExecutiveBinding, CoreExecutiveEvidence
from app.domain.attention import AttentionSource
from app.domain.contracts import CapabilityAvailability
from app.domain.contracts.common import JsonValue
from app.domain.contracts.finalization import FinalizationError
from app.domain.executive import (
    AuthoritativeIntentRequirements,
    ExecutiveDecisionAuthority,
    ExecutiveDecisionCandidate,
    ExecutiveSourceEvent,
)
from app.domain.llm import LLMRoleRequest, LLMRoleResult, StructuredPayload
from app.runtime.kernel import CancellationToken
from tests.domain.executive.test_executive import (
    candidate_json,
    live_state,
    policy,
    snapshot,
    success,
)
from tests.helpers.executive_requirements import SPEECH_OWNER, make_authority
from tests.system_integration.test_core_appraisal import setup
from tests.system_integration.test_core_attention import connect, offer_user, rules


class Reader:
    def __init__(self, source: AttentionSource) -> None:
        values = snapshot()
        self.value = CoreExecutiveEvidence(
            source,
            (ExecutiveSourceEvent("event:1", source.occurred_at, True),),
            None,
            values.facts,
            values.capabilities,
            values.preconditions,
        )
        self.requirements = live_state().requirements
        self.reads = 0

    async def read(self, source: AttentionSource) -> CoreExecutiveEvidence:
        self.reads += 1
        return self.value

    async def requirements_for(
        self,
        candidate: ExecutiveDecisionCandidate,
    ) -> tuple[AuthoritativeIntentRequirements, ...]:
        return self.requirements


class Port:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.requests: list[LLMRoleRequest] = []

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self.requests.append(request)
        self.started.set()
        await self.release.wait()
        context = cast(Mapping[str, Any], request.input.value)
        output = candidate_json(context["trigger_id"])
        for name in (
            "source_event_ids",
            "source_context_revision",
            "goal_revision",
            "attention_revision",
        ):
            output[name] = context[name]
        return replace(
            success(request),
            started_at=request.created_at,
            completed_at=request.created_at,
            output=StructuredPayload("executive.candidate.v1", cast(JsonValue, output)),
        )


def wired(port: Port | None = None) -> Any:
    from types import SimpleNamespace

    core = setup()
    attention, attention_owner = connect(core)
    core.connection.appraise_fast(core.event, rules(), candidate_id="fast")
    attention.offer_appraisal()
    dispatch = attention.claim_next()
    assert dispatch is not None
    reader = Reader(dispatch.selected_source)
    llm = Port() if port is None else port
    authority = make_authority()
    binding = CoreExecutiveBinding(attention, reader, llm, policy(), authority, core.clock)
    return SimpleNamespace(
        core=core,
        attention=attention,
        attention_owner=attention_owner,
        dispatch=dispatch,
        reader=reader,
        llm=llm,
        authority=authority,
        binding=binding,
    )


async def deliberate(value: Any, request_id: str = "request") -> Any:
    return await value.binding.deliberate(
        value.dispatch,
        request_id=request_id,
        trace_id="trace",
        decision_id=request_id,
        cancellation=CancellationToken(),
    )


@pytest.mark.asyncio
async def test_current_sources_reach_decision_and_duplicate_trigger_is_rejected() -> None:
    value = wired()
    result = await deliberate(value)
    assert value.binding.latest_decision() is result
    assert value.authority.has_committed(value.dispatch.trigger.trigger_id)
    assert value.reader.reads == 2
    context = value.llm.requests[0].input.value
    assert context["internal_state"]["revision"] == value.core.owner.snapshot().revision
    assert context["goal_revision"] == value.core.goals.snapshot().revision
    assert context["attention_revision"] == value.attention_owner.snapshot().revision
    with pytest.raises(FinalizationError, match="TARGET_ALREADY_FINALIZED"):
        await deliberate(value, "duplicate")
    assert value.binding.latest_decision() is result


@pytest.mark.parametrize(
    "change", ["attention", "state", "evidence", "capability", "precondition", "requirements"]
)
@pytest.mark.asyncio
async def test_live_changes_reject_decision_without_marking_trigger_committed(change: str) -> None:
    value = wired()
    value.llm.release.clear()
    task = asyncio.create_task(deliberate(value))
    await asyncio.wait_for(value.llm.started.wait(), 1)
    data = value.reader.value
    if change == "attention":
        offer_user(value.attention_owner, value.core)
    elif change == "state":
        value.core.connection.appraise_fast(value.core.event, rules(), candidate_id="next")
    elif change == "evidence":
        value.reader.value = replace(data, facts=data.facts[:-1])
    elif change == "capability":
        value.reader.value = replace(
            data,
            capabilities=(
                replace(data.capabilities[0], availability=CapabilityAvailability.UNAVAILABLE),
            ),
        )
    elif change == "precondition":
        value.reader.value = replace(
            data, preconditions=(replace(data.preconditions[0], actual="unavailable"),)
        )
    else:
        value.reader.requirements = ()
    value.llm.release.set()
    with pytest.raises(ValueError):
        await task
    assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)
    assert value.binding.latest_decision() is None


@pytest.mark.asyncio
async def test_wrong_evidence_source_is_rejected_before_llm() -> None:
    value = wired()
    value.reader.value = replace(
        value.reader.value, source=replace(value.reader.value.source, source_ref="wrong")
    )
    with pytest.raises(ValueError, match="供給元"):
        await deliberate(value)
    assert not value.llm.requests


@pytest.mark.asyncio
async def test_requirement_read_failure_is_not_replaced_with_empty_requirements() -> None:
    value = wired()

    class FailedReader(Reader):
        async def requirements_for(
            self, candidate: ExecutiveDecisionCandidate
        ) -> tuple[AuthoritativeIntentRequirements, ...]:
            raise RuntimeError("必須要件を取得できません")

    reader = FailedReader(value.dispatch.selected_source)
    value.binding = CoreExecutiveBinding(
        value.attention, reader, value.llm, policy(), value.authority, value.core.clock
    )
    with pytest.raises(RuntimeError, match="必須要件"):
        await deliberate(value)
    assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)


@pytest.mark.asyncio
async def test_cancellation_and_recancellation_reap_suppressed_provider_without_commit() -> None:
    caught, finish = asyncio.Event(), asyncio.Event()

    class SuppressingPort(Port):
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            try:
                return await super().invoke(request)
            except asyncio.CancelledError:
                caught.set()
                await finish.wait()
                self.release.set()
                return await super().invoke(request)

    value = wired(SuppressingPort())
    value.llm.release.clear()
    before = asyncio.all_tasks()
    task = asyncio.create_task(deliberate(value))
    await asyncio.wait_for(value.llm.started.wait(), 1)
    task.cancel()
    await asyncio.wait_for(caught.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)
    assert value.binding.latest_decision() is None
    assert not (asyncio.all_tasks() - before)


@pytest.mark.asyncio
async def test_change_during_requirements_read_is_rechecked() -> None:
    value = wired()

    class UpdatingReader(Reader):
        async def requirements_for(
            self, candidate: ExecutiveDecisionCandidate
        ) -> tuple[AuthoritativeIntentRequirements, ...]:
            offer_user(value.attention_owner, value.core)
            return self.requirements

    reader = UpdatingReader(value.dispatch.selected_source)
    value.binding = CoreExecutiveBinding(
        value.attention, reader, value.llm, policy(), value.authority, value.core.clock
    )
    with pytest.raises(ValueError, match="現在の状態"):
        await deliberate(value)
    assert not value.authority.has_committed(value.dispatch.trigger.trigger_id)


@pytest.mark.asyncio
async def test_matching_source_header_cannot_hide_wrong_event_lineage() -> None:
    value = wired()
    value.reader.value = replace(
        value.reader.value,
        source_events=(replace(value.reader.value.source_events[0], event_id="wrong-event"),),
    )
    with pytest.raises(ValueError, match="元イベント"):
        await deliberate(value)
    assert not value.llm.requests


@pytest.mark.asyncio
async def test_already_cancelled_request_does_not_read_or_invoke() -> None:
    from app.runtime.kernel.contracts import CancellationRecord

    value = wired()
    token = CancellationToken()
    token.cancel(CancellationRecord("request", "取消済み", value.core.clock.now()))
    with pytest.raises(asyncio.CancelledError):
        await value.binding.deliberate(
            value.dispatch,
            request_id="request",
            trace_id="trace",
            decision_id="decision",
            cancellation=token,
        )
    assert not value.llm.requests
    assert value.reader.reads == 0


@pytest.mark.asyncio
async def test_cancellation_after_commit_preserves_committed_decision() -> None:
    from app.domain.executive import CommittedExecutiveDecision

    value = wired()
    caller = asyncio.current_task()
    assert caller is not None
    cancel_caller = caller.cancel

    class AfterCommitAuthority(ExecutiveDecisionAuthority):
        def commit(self, *args: Any, **kwargs: Any) -> CommittedExecutiveDecision:
            committed = super().commit(*args, **kwargs)
            asyncio.get_running_loop().call_soon(cancel_caller)
            return committed

    authority = AfterCommitAuthority(SPEECH_OWNER)
    value.binding = CoreExecutiveBinding(
        value.attention,
        value.reader,
        value.llm,
        policy(),
        authority,
        value.core.clock,
    )
    with pytest.raises(asyncio.CancelledError):
        await deliberate(value)
    assert authority.has_committed(value.dispatch.trigger.trigger_id)
    assert value.binding.latest_decision() is not None
