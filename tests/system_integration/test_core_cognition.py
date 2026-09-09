"""本番起動から実Ownerの確定まで、通常認知の配送と拒否を検証する。"""

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

import pytest

from app import bootstrap
from app.composition.cognition_configuration import CoreCognitionConfiguration
from app.domain.appraisal import InternalStateReducer
from app.domain.attention import AttentionSchedulingPolicy, AttentionTurnStore
from app.domain.brain_integration import BrainIntegrationModule, BrainWorkStatus
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts import RevisionVector
from app.domain.contracts.common import freeze_json
from app.domain.contracts.preconditions import PreconditionSourceRouter
from app.domain.executive import ExecutiveIntentRequirementsPolicy, ExecutiveRequirementsOwner
from app.domain.input_gateway import InputAdmission, InputAdmissionStatus, InputModality
from app.domain.llm import LLMRoleRequest, LLMRoleResult, StructuredPayload
from app.domain.plugin_registry import PluginRegistryAuthority
from tests.domain.appraisal.test_appraisal_paths import output, policy, result, state
from tests.domain.executive.test_executive import policy as executive_policy
from tests.system_integration.test_core_attention import rules
from tests.system_integration.test_core_executive import Port as ExecutivePort
from tests.system_integration.test_early_boot import SuccessfulPort, work


class Port:
    def __init__(self) -> None:
        self.requests: list[LLMRoleRequest] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self.requests.append(request)
        if request.role_id == "input_meaning":
            return await SuccessfulPort().invoke(request)
        if request.role_id == "subjective_appraisal":
            self.entered.set()
            await self.release.wait()
            assert isinstance(request.input.value, Mapping)
            event = request.input.value["event"]
            assert isinstance(event, Mapping)
            return replace(
                result(
                    request,
                    {
                        **output(cause_ref=str(event["event_id"])),
                        "candidate_id": request.request_id,
                    },
                ),
                started_at=request.created_at,
                completed_at=request.created_at,
            )
        value = await ExecutivePort().invoke(request)
        assert value.output is not None and isinstance(value.output.value, Mapping)
        payload: dict[str, Any] = dict(value.output.value)
        payload.update(
            outcome="wait",
            intents=(),
            goal_transition_intents=(),
            commitment_transition_intents=(),
            rationale_refs=tuple(payload["source_event_ids"]),
        )
        return replace(
            value, output=StructuredPayload(value.output.schema_id, freeze_json(payload))
        )


def application(monkeypatch: pytest.MonkeyPatch, *, fast: bool = False) -> tuple[Any, Port]:
    port = Port()
    descriptors: list[str] = []

    def provider(roles: Any) -> Port:
        descriptors.extend(role.role_id for role in roles)
        return port

    monkeypatch.setattr(bootstrap, "create_openai_port_from_environment", provider)
    requirements = ExecutiveRequirementsOwner(BOUNDS)
    requirements.publish(ExecutiveIntentRequirementsPolicy("test-wait", 1, ()))
    config = CoreCognitionConfiguration(
        policy(),
        executive_policy(),
        InternalStateReducer(replace(state(), source_context_revision=0)),
        AttentionTurnStore(AttentionSchedulingPolicy.production()),
        requirements,
        PluginRegistryAuthority(),
        PreconditionSourceRouter(()),
        (),
        tuple(
            replace(
                rule, proposals=tuple(replace(p, cause_refs=("event-1",)) for p in rule.proposals)
            )
            for rule in rules()
        )
        if fast
        else (),
    )
    app = bootstrap.build_minimum_core(cognition=config)
    assert set(descriptors) == {"input_meaning", "subjective_appraisal", "executive_deliberation"}
    return app, port


def admission(
    app: Any, *, internal: bool = False, event_id: str = "event-1", trace_id: str = "trace-1"
) -> InputAdmission:
    original_payload = work().payload
    assert isinstance(original_payload, bootstrap.InputMeaningBrainWorkPayload)
    original = original_payload.event
    event = replace(
        original,
        envelope=replace(
            original.envelope,
            event_id=event_id,
            trace_id=trace_id,
            occurred_at=datetime.now(timezone.utc),
            revisions=RevisionVector(app.input_context.snapshot().context.source_context_revision),
            event_type="activity.completed" if internal else original.envelope.event_type,
        ),
        modality=InputModality.SUBSYSTEM if internal else original.modality,
    )
    return InputAdmission(InputAdmissionStatus.ACCEPTED, event)


@pytest.mark.asyncio
@pytest.mark.parametrize("internal,fast", [(False, False), (True, False), (True, True)])
async def test_startup_delivers_accepted_event_to_committed_decision(
    monkeypatch: pytest.MonkeyPatch, internal: bool, fast: bool
) -> None:
    app, port = application(monkeypatch, fast=fast)
    await app.start()
    try:
        accepted = app.cognition.submit_input(admission(app, internal=internal))
        assert accepted.accepted
        outcomes = []
        for _ in range(2 if internal else 3):
            outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
            assert outcome.status is BrainWorkStatus.COMPLETED, outcome
            outcomes.append(outcome)
        assert all(o.status is BrainWorkStatus.COMPLETED for o in outcomes), outcomes
        assert outcomes[-1].module is BrainIntegrationModule.EXECUTIVE
        assert outcomes[-1].result.candidate.source_event_ids == ("event-1",)
        trace = app.brain.trace("trace-1")
        assert trace.root_trigger_id == "event-1"
        assert trace.source_event_ids == ("event-1",)
        assert len(port.requests) == (1 if fast else 2 if internal else 3)
    finally:
        await app.stop()


@pytest.mark.asyncio
async def test_cancel_during_appraisal_never_dispatches_executive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, port = application(monkeypatch)
    port.release.clear()
    await app.start()
    try:
        accepted = app.cognition.submit_input(admission(app, internal=True))
        await asyncio.wait_for(port.entered.wait(), 2)
        app.brain.cancel(accepted.work_id, "試験取消")
        outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
        assert outcome.status is BrainWorkStatus.CANCELLED
        assert [r.role_id for r in port.requests] == ["subjective_appraisal"]
    finally:
        await app.stop()


@pytest.mark.asyncio
async def test_goal_update_during_appraisal_rejects_old_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.executive import GoalTransitionOperation
    from tests.domain.goals.test_goal_commitment_store import apply_goal

    app, port = application(monkeypatch)
    port.release.clear()
    await app.start()
    try:
        app.cognition.submit_input(admission(app, internal=True))
        await asyncio.wait_for(port.entered.wait(), 2)
        apply_goal(app.goals, GoalTransitionOperation.CREATE, 0)
        port.release.set()
        outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
        assert outcome.status is BrainWorkStatus.FAILED
        assert app.cognition.appraisal.current_commit() is None
        assert len(port.requests) == 1
    finally:
        await app.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("supersede", [False, True])
async def test_trace_cancellation_reaches_work_after_input_completed(
    monkeypatch: pytest.MonkeyPatch, supersede: bool
) -> None:
    app, port = application(monkeypatch)
    port.release.clear()
    await app.start()
    try:
        app.cognition.submit_input(admission(app))
        await asyncio.wait_for(port.entered.wait(), 2)
        first = await asyncio.wait_for(app.brain.next_outcome(), 2)
        assert first.module is BrainIntegrationModule.INPUT_MEANING
        assert app.cognition.cancel_trace("trace-1", "入力置換", supersede=supersede) == 1
        outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
        assert outcome.status is (
            BrainWorkStatus.SUPERSEDED if supersede else BrainWorkStatus.CANCELLED
        )
        assert len(port.requests) == 2
    finally:
        await app.stop()


@pytest.mark.asyncio
async def test_shutdown_reaps_pending_appraisal(monkeypatch: pytest.MonkeyPatch) -> None:
    app, port = application(monkeypatch)
    port.release.clear()
    await app.start()
    app.cognition.submit_input(admission(app, internal=True))
    await asyncio.wait_for(port.entered.wait(), 2)
    await asyncio.wait_for(app.stop(), 3)
    assert app.cognition.appraisal.current_commit() is None
    assert len(port.requests) == 1


@pytest.mark.asyncio
async def test_next_queue_rejection_is_not_reported_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.brain_integration import BrainWorkAdmission, BrainWorkAdmissionStatus

    app, port = application(monkeypatch)
    await app.start()
    submit = app.brain.submit

    def reject_executive(value: Any) -> Any:
        if value.module is BrainIntegrationModule.EXECUTIVE:
            return BrainWorkAdmission(BrainWorkAdmissionStatus.REJECTED, value.work_id)
        return submit(value)

    monkeypatch.setattr(app.brain, "submit", reject_executive)
    try:
        app.cognition.submit_input(admission(app, internal=True))
        outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
        assert outcome.status is BrainWorkStatus.FAILED
        assert not app.cognition.latest_delivery.admission.accepted
        assert len(port.requests) == 1
    finally:
        await app.stop()


def test_unregistered_requirements_cannot_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domain.executive import RequirementsRejected

    app, _ = application(monkeypatch)
    # 初期値を補うことなく、未登録の実Ownerを拒否する。
    with pytest.raises(RequirementsRejected):
        CoreCognitionConfiguration(
            policy(),
            executive_policy(),
            InternalStateReducer(state()),
            AttentionTurnStore(AttentionSchedulingPolicy.production()),
            ExecutiveRequirementsOwner(BOUNDS),
            PluginRegistryAuthority(),
            PreconditionSourceRouter(()),
            (),
            (),
        )
    assert app.cognition is not None


@pytest.mark.asyncio
async def test_same_trace_cannot_replace_root_or_accept_stale_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _ = application(monkeypatch)
    await app.start()
    try:
        accepted = admission(app, internal=True)
        app.cognition.submit_input(accepted)
        assert accepted.event is not None
        changed = replace(
            accepted,
            event=replace(
                accepted.event, envelope=replace(accepted.event.envelope, event_id="other")
            ),
        )
        with pytest.raises(ValueError, match="root trigger"):
            app.cognition.submit_input(changed)
        stale = replace(
            accepted,
            event=replace(
                accepted.event,
                envelope=replace(accepted.event.envelope, revisions=RevisionVector(0)),
            ),
        )
        with pytest.raises(ValueError, match="現在"):
            app.cognition.submit_input(stale)
    finally:
        await app.stop()
