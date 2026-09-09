"""独立レビューで指摘された連続認知と早期受付を検証する。"""

import asyncio

import pytest

from app.domain.attention import AttentionSourceKind
from app.domain.brain_integration import BrainWorkStatus
from tests.system_integration.test_core_cognition import admission, application


@pytest.mark.asyncio
@pytest.mark.parametrize("internal", [True, False])
async def test_sequential_inputs_retire_only_obsolete_appraisals(
    monkeypatch: pytest.MonkeyPatch, internal: bool
) -> None:
    app, _ = application(monkeypatch)
    await app.start()
    try:
        for index in range(4):
            assert app.cognition.submit_input(
                admission(
                    app, internal=internal, event_id=f"event-{index}", trace_id=f"trace-{index}"
                )
            ).accepted
            for _ in range(2 if internal else 3):
                outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
                assert outcome.status is BrainWorkStatus.COMPLETED, outcome
            current = app.cognition.appraisal.current_commit()
            sources = app.cognition._attention_owner.snapshot().sources
            assert [s.source_ref for s in sources if s.kind is AttentionSourceKind.APPRAISAL] == [
                current.candidate.candidate_id
            ]
            if not internal:
                assert (
                    sum(s.kind is AttentionSourceKind.USER_INTERACTION for s in sources)
                    == index + 1
                )
    finally:
        await app.stop()


@pytest.mark.asyncio
async def test_early_user_source_is_reaped_on_runtime_cancel_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, port = application(monkeypatch)
    await app.start()
    try:
        accepted = app.cognition.submit_input(admission(app))
        assert accepted.accepted
        assert any(
            s.kind is AttentionSourceKind.USER_INTERACTION
            for s in app.cognition._attention_owner.snapshot().sources
        )
        assert not port.requests
        assert app.brain.cancel(accepted.work_id, "開始前取消")
        outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
        assert outcome.status is BrainWorkStatus.CANCELLED
        assert not port.requests
        assert not app.cognition._attention_owner.snapshot().sources
    finally:
        await app.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("consume", [False, True])
@pytest.mark.parametrize(
    "path",
    [
        "queue_cancel",
        "task_cancel",
        "running_cancel",
        "supersede",
        "deadline",
        "stale",
        "unavailable",
        "failed",
        "success",
        "stop_queued",
        "stop_running",
    ],
)
async def test_terminal_observer_reclaims_early_user_without_competing_consumer(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    consume: bool,
) -> None:
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone

    from app.adapters.llm.production import UnavailableLLMRolePort
    from app.domain.input_meaning.interpreter import descriptor
    from app.domain.llm import LLMRoleRequest, LLMRoleResult

    app, port = application(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    invoke = port.invoke

    async def slow_meaning(request: LLMRoleRequest) -> LLMRoleResult:
        if request.role_id == "input_meaning":
            entered.set()
            await release.wait()
            if path == "unavailable":
                return await UnavailableLLMRolePort(
                    (descriptor(app.config.input_meaning_policy),)
                ).invoke(request)
            if path == "failed":
                raise ValueError("提供先の故障")
        return await invoke(request)

    monkeypatch.setattr(port, "invoke", slow_meaning)
    if path == "stale":
        monkeypatch.setattr(app.bridge, "is_fresh", lambda work: False)
    await app.start()
    source = admission(app)
    deadline = None
    if path == "deadline":
        assert source.event is not None
        source = replace(
            source,
            event=replace(
                source.event,
                envelope=replace(
                    source.event.envelope,
                    occurred_at=datetime.now(timezone.utc) - timedelta(seconds=2),
                ),
            ),
        )
        deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
    try:
        accepted = app.cognition.submit_input(source, deadline_at=deadline)
        assert accepted.accepted
        assert not entered.is_set()
        assert [s.source_ref for s in app.cognition._attention_owner.snapshot().sources] == [
            "event-1"
        ]
        if path == "task_cancel":
            await asyncio.sleep(0)
            assert not entered.is_set()
            assert app.brain.cancel(accepted.work_id, "task開始前")
        elif path == "queue_cancel":
            assert app.brain.cancel(accepted.work_id, "queue取消")
        elif path == "supersede":
            assert app.brain.supersede(accepted.work_id, "置換")
        elif path == "stop_queued":
            await app.stop()
        elif path not in ("deadline", "stale"):
            await asyncio.wait_for(entered.wait(), 2)
            assert app.cognition._attention_owner.snapshot().sources
            if path == "running_cancel":
                assert app.brain.cancel(accepted.work_id, "実行中取消")
            elif path == "stop_running":
                await app.stop()
            else:
                release.set()
        if consume:
            outcome = await asyncio.wait_for(app.brain.next_outcome(), 2)
            status = outcome.status
        else:
            for _ in range(1000):
                interval = app.brain.trace("trace-1").intervals[0]
                if interval.completed_at is not None:
                    break
                await asyncio.sleep(0)
            assert interval.completed_at is not None
            status = interval.status
        expected = {
            "supersede": BrainWorkStatus.SUPERSEDED,
            "deadline": BrainWorkStatus.TIMED_OUT,
            "stale": BrainWorkStatus.STALE,
            "unavailable": BrainWorkStatus.COMPLETED,
            "failed": BrainWorkStatus.FAILED,
            "success": BrainWorkStatus.COMPLETED,
        }.get(path, BrainWorkStatus.CANCELLED)
        assert status is expected
        users = [
            s
            for s in app.cognition._attention_owner.snapshot().sources
            if s.kind is AttentionSourceKind.USER_INTERACTION
        ]
        assert bool(users) == (path == "success")
        assert not app.cognition._pending_users
    finally:
        await app.stop()
        await app.stop()
    assert app.brain._pump_task.done()
    assert app.brain._runtime.diagnostics().owned_task_count == 0


@pytest.mark.asyncio
async def test_real_runtime_admission_rejection_reclaims_only_new_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from app import bootstrap
    from app.config.minimum_brain import MinimumBrainProductionConfig, load_minimum_brain_config

    def small(data: bytes) -> MinimumBrainProductionConfig:
        config = load_minimum_brain_config(data)
        return replace(
            config,
            integration_policy=replace(
                config.integration_policy,
                lane_policies=tuple(
                    replace(p, queue_capacity=1) for p in config.integration_policy.lane_policies
                ),
            ),
        )

    monkeypatch.setattr(bootstrap, "load_minimum_brain_config", small)
    app, _ = application(monkeypatch)
    await app.start()
    try:
        assert app.cognition.submit_input(admission(app)).accepted
        rejected = app.cognition.submit_input(
            admission(app, event_id="event-2", trace_id="trace-2")
        )
        assert not rejected.accepted
        assert [s.source_ref for s in app.cognition._attention_owner.snapshot().sources] == [
            "event-1"
        ]
    finally:
        await app.stop()
    assert not app.cognition._attention_owner.snapshot().sources


@pytest.mark.asyncio
async def test_runtime_cancel_does_not_withdraw_unrelated_successful_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _ = application(monkeypatch)
    await app.start()
    try:
        first = app.cognition.submit_input(admission(app))
        assert app.cognition.submit_input(
            admission(app, event_id="event-2", trace_id="trace-2")
        ).accepted
        assert app.brain.cancel(first.work_id, "最初だけ取消")
        outcomes = [await asyncio.wait_for(app.brain.next_outcome(), 2) for _ in range(4)]
        assert sum(o.status is BrainWorkStatus.CANCELLED for o in outcomes) == 1
        assert all(
            o.status is BrainWorkStatus.COMPLETED for o in outcomes if o.trace_id == "trace-2"
        )
        assert [
            s.source_ref
            for s in app.cognition._attention_owner.snapshot().sources
            if s.kind is AttentionSourceKind.USER_INTERACTION
        ] == ["event-2"]
    finally:
        await app.stop()


@pytest.mark.asyncio
async def test_pending_meaning_cannot_be_used_as_executive_semantic_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.brain_integration import BrainIntegrationModule
    from app.domain.llm import LLMRoleRequest, LLMRoleResult

    app, port = application(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    original = port.invoke

    async def blocked(request: LLMRoleRequest) -> LLMRoleResult:
        if request.role_id == "input_meaning":
            entered.set()
            await release.wait()
        return await original(request)

    monkeypatch.setattr(port, "invoke", blocked)
    await app.start()
    try:
        app.cognition.submit_input(admission(app))
        await entered.wait()
        app.cognition.submit_input(
            admission(app, internal=True, event_id="internal", trace_id="internal")
        )
        rejected = await asyncio.wait_for(app.brain.next_outcome(), 2)
        assert rejected.module is BrainIntegrationModule.APPRAISAL
        assert rejected.status is BrainWorkStatus.FAILED
        assert not any(r.role_id == "executive_deliberation" for r in port.requests)
        release.set()
        for _ in range(3):
            assert (
                await asyncio.wait_for(app.brain.next_outcome(), 2)
            ).status is BrainWorkStatus.COMPLETED
    finally:
        await app.stop()
