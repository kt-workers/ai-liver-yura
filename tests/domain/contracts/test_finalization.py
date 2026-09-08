"""世代公開・最終確定と具体所有者の競合を決定論的に検証する。"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from threading import Barrier, Event

import pytest

from app.domain.contracts.finalization import (
    AuthorityFinalizationFence,
    AuthorityFinalizationParticipant,
    AuthorityFinalizationRequest,
    AuthorityGenerationToken,
    FinalizationError,
    FinalizationFailure,
)
from app.domain.executive import ExecutiveDecisionAuthority
from app.domain.executive.authority import ExecutiveFinalizationInput
from tests.domain.executive.test_executive import candidate, live_state, snapshot
from tests.domain.goal_planning.test_goal_planning import NOW
from tests.domain.goal_planning.test_goal_planning import candidate as plan_candidate
from tests.domain.goal_planning.test_goal_planning import context as plan_context
from tests.domain.goal_planning.test_goal_planning import current as plan_current
from tests.domain.goal_planning.test_plan_replacement import seeded
from tests.domain.plan_execution.test_progression import setup


class Target:
    """同期区間の観測だけを行う試験用の登録済み所有者。"""

    def __init__(self, *, rank: int = 70) -> None:
        self.participant = AuthorityFinalizationParticipant(self, "test_target", rank)
        self.calls = 0
        self.action: Callable[[], None] | None = None
        self.operation = self.participant.register_operation(self, "commit", self.commit)

    def commit(self, value: int, now: datetime) -> int:
        self.calls += 1
        if self.action is not None:
            self.action()
        return value

    def request(self, *tokens: AuthorityGenerationToken) -> AuthorityFinalizationRequest[int, int]:
        return AuthorityFinalizationRequest(tokens, self.participant, self.operation, 7)


def test_replacement_rejects_old_plan_but_keeps_history() -> None:
    owner, plan = seeded()
    published = owner.current_plan_publication(plan.candidate.goal_id)
    new = owner.commit(
        replace(plan_candidate(), candidate_id="replacement"),
        replace(plan_context(), previous_plan=plan),
        replace(plan_current(), previous_plan=plan),
        plan_id="replacement",
        committed_at=NOW + timedelta(seconds=1),
    )
    target = Target()
    result = AuthorityFinalizationFence().finalize(target.request(*published.tokens))
    assert result.failure is FinalizationFailure.GENERATION_MISMATCH
    assert target.calls == 0
    assert owner.snapshot(plan.plan_id) == plan
    assert owner.current_plan(plan.candidate.goal_id) == new


def test_fence_blocks_replacement_only_until_final_commit_release() -> None:
    owner, plan = seeded()
    token = owner.current_plan_publication(plan.candidate.goal_id).tokens
    entered, attempted, finished = Event(), Event(), Event()
    target = Target()

    def during_commit() -> None:
        entered.set()
        assert attempted.wait(5)
        assert not finished.is_set()
        assert owner.current_plan(plan.candidate.goal_id) == plan

    def replace_plan() -> None:
        assert entered.wait(5)
        attempted.set()
        owner.commit(
            replace(plan_candidate(), candidate_id="replacement"),
            replace(plan_context(), previous_plan=plan),
            replace(plan_current(), previous_plan=plan),
            plan_id="replacement",
            committed_at=NOW + timedelta(seconds=1),
        )
        finished.set()

    target.action = during_commit
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(replace_plan)
        result = AuthorityFinalizationFence().finalize(target.request(*token))
        future.result(timeout=5)
    assert result.value == 7 and finished.is_set()


def test_write_attempt_invalidates_even_validation_failure_and_preserves_product() -> None:
    owner, plan = seeded()
    token = owner.finalization_participant.token()
    with pytest.raises(ValueError):
        owner.commit(
            plan_candidate(), plan_context(), plan_current(), plan_id="original", committed_at=NOW
        )
    target = Target()
    assert (
        AuthorityFinalizationFence().finalize(target.request(token)).failure
        is FinalizationFailure.GENERATION_MISMATCH
    )
    assert owner.current_plan(plan.candidate.goal_id) == plan
    current_token = owner.finalization_participant.token()
    owner.current_plan(plan.candidate.goal_id)
    assert current_token == owner.finalization_participant.token()


@pytest.mark.parametrize(
    "operation",
    ["progress", "stop", "retire", "activate", "reserve", "prepare", "assessment", "finish"],
)
def test_plan_execution_mutations_invalidate_composite_publication(operation: str) -> None:
    state = setup()
    published = state.owner.observation_publication(state.scope_id)
    assert len(published.tokens) == 4
    if operation == "progress":
        state.owner.progress(state.scope_id)
    elif operation == "stop":
        state.owner.stop(state.scope_id)
    elif operation == "retire":
        state.owner.stop(state.scope_id)
        published = state.owner.observation_publication(state.scope_id)
        state.owner.retire(state.scope_id)
    elif operation == "activate":
        state.owner.activate(published.value.authorization, NOW)
    elif operation == "reserve":
        state.owner.reserve_ready(state.scope_id, state.current, NOW)
    elif operation == "prepare":
        scope = published.value.authorization.scope
        with pytest.raises(ValueError):
            state.owner.prepare_scope(
                scope.plan,
                scope.bindings,
                state.current.argument_facts,
                captured_at=NOW,
                deadline_at=scope.deadline_at,
            )
    elif operation == "assessment":
        with pytest.raises(ValueError):
            state.owner.apply_assessment(None)  # type: ignore[arg-type]
    else:
        invocation = state.owner.reserve_ready(state.scope_id, state.current, NOW).invocations[0]
        published = state.owner.observation_publication(state.scope_id)
        state.owner._finish_dispatch(invocation)
    target = Target()
    result = AuthorityFinalizationFence().finalize(target.request(*published.tokens))
    assert result.failure is FinalizationFailure.GENERATION_MISMATCH
    assert target.calls == 0


def test_composite_publication_cannot_omit_activity_and_activity_failure_invalidates() -> None:
    state = setup()
    published = state.owner.observation_publication(state.scope_id)
    target = Target()
    omitted = tuple(
        t for t in published.tokens if t._participant is not state.activity.finalization_participant
    )
    fence = AuthorityFinalizationFence()
    assert (
        fence.finalize(target.request(*omitted)).failure
        is FinalizationFailure.INVALID_LOCK_CONFIGURATION
    )
    with pytest.raises(ValueError):
        state.activity.supersede("missing", NOW)
    assert (
        fence.finalize(target.request(*published.tokens)).failure
        is FinalizationFailure.GENERATION_MISMATCH
    )


def test_busy_releases_earlier_participants_and_unrelated_owner_advances() -> None:
    first, second, target = Target(rank=10), Target(rank=20), Target()
    request = target.request(first.participant.token(), second.participant.token())
    held, release = Event(), Event()

    def hold() -> None:
        with second.participant:
            held.set()
            assert release.wait(5)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(hold)
        assert held.wait(5)
        try:
            assert (
                AuthorityFinalizationFence().finalize(request).failure
                is FinalizationFailure.PARTICIPANT_BUSY
            )
            independent = Target(rank=80)
            assert (
                AuthorityFinalizationFence()
                .finalize(independent.request(first.participant.token()))
                .value
                == 7
            )
        finally:
            release.set()
            future.result(timeout=5)
    assert target.calls == 0


def test_opposite_input_order_has_no_deadlock_and_all_locks_are_released() -> None:
    a, b = Target(rank=10), Target(rank=20)
    barrier = Barrier(2)

    def run(reverse: bool) -> FinalizationFailure | None:
        target = Target()
        tokens = (a.participant.token(), b.participant.token())
        barrier.wait(timeout=5)
        result = AuthorityFinalizationFence().finalize(
            target.request(*(tokens[::-1] if reverse else tokens))
        )
        return result.failure

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, value) for value in (False, True)]
        results = [f.result(timeout=5) for f in futures]
    assert all(r in (None, FinalizationFailure.PARTICIPANT_BUSY) for r in results)
    with a.participant.mutation(), b.participant.mutation():
        pass


def test_duplicate_normalization_and_conflicting_generations() -> None:
    source, target = Target(rank=10), Target()
    old = source.participant.token()
    fence = AuthorityFinalizationFence()
    assert fence.finalize(target.request(old, old)).value == 7
    with source.participant.mutation():
        pass
    new = source.participant.token()
    assert (
        fence.finalize(target.request(old, new)).failure is FinalizationFailure.INVALID_PARTICIPANT
    )


def test_forged_and_restarted_token_cannot_be_promoted() -> None:
    source, target = Target(rank=10), Target()
    token = source.participant.token()
    other = Target(rank=10)
    fence = AuthorityFinalizationFence()
    forged = replace(token, _participant=other.participant)
    assert fence.finalize(target.request(forged)).failure is FinalizationFailure.INVALID_PARTICIPANT
    with pytest.raises(ValueError):
        replace(token, generation=True)
    with source.participant.mutation():
        pass
    forged = replace(token, generation=source.participant.token().generation)
    assert fence.finalize(target.request(forged)).failure is FinalizationFailure.INVALID_PARTICIPANT
    source.participant.retire()
    assert (
        fence.finalize(target.request(token)).failure is FinalizationFailure.PARTICIPANT_UNAVAILABLE
    )
    assert other.participant.token().owner_instance_key != token.owner_instance_key


def test_duplicate_registration_and_lock_configuration_rejected() -> None:
    source = Target(rank=10)
    with pytest.raises(FinalizationError):
        AuthorityFinalizationParticipant(source, "duplicate", 10)
    another = Target(rank=20)
    with pytest.raises(FinalizationError):
        AuthorityFinalizationParticipant(
            another, "duplicate", 10, owner_instance_key=source.participant.order_key[1]
        )
    with pytest.raises(FinalizationError):
        source.participant.configure_dependencies((source.participant,))
    target = Target()
    with pytest.raises(FinalizationError):
        target.participant.register_operation(target, "callback", lambda value, now: value)
    assert (
        AuthorityFinalizationFence(max_participants=1)
        .finalize(target.request(source.participant.token()))
        .failure
        is FinalizationFailure.INVALID_LOCK_CONFIGURATION
    )


def test_cancellation_before_acquisition_and_after_commit() -> None:
    source, target = Target(rank=10), Target()
    signal = Event()
    signal.set()
    fence = AuthorityFinalizationFence()
    request = target.request(source.participant.token())
    assert fence.finalize(request, cancellation=signal).failure is FinalizationFailure.CANCELLED
    assert target.calls == 0
    signal.clear()
    target.action = signal.set
    result = fence.finalize(request, cancellation=signal)
    assert result.value == 7 and result.failure is None and signal.is_set()
    assert result.source_tokens == request.expected_tokens
    assert result.target_token is not None


@pytest.mark.parametrize(
    "failure", [FinalizationFailure.TARGET_REJECTED, FinalizationFailure.TARGET_ALREADY_FINALIZED]
)
def test_typed_rejection_releases_and_keeps_target_available(failure: FinalizationFailure) -> None:
    source, target = Target(rank=10), Target()

    def reject() -> None:
        raise FinalizationError(failure)

    target.action = reject
    result = AuthorityFinalizationFence().finalize(target.request(source.participant.token()))
    assert result.failure is failure
    target.participant.token()
    with source.participant.mutation():
        pass


def test_fault_preserves_published_state_and_disables_target_without_raw_text() -> None:
    source, target = Target(rank=10), Target()

    def fault() -> None:
        raise RuntimeError("PRIVATE_SENTINEL")

    target.action = fault
    result = AuthorityFinalizationFence().finalize(target.request(source.participant.token()))
    assert result.failure is FinalizationFailure.TARGET_COMMIT_FAULT
    assert target.calls == 1
    assert "PRIVATE_SENTINEL" not in repr(result)
    with pytest.raises(FinalizationError) as caught:
        target.participant.token()
    assert caught.value.failure is FinalizationFailure.PARTICIPANT_UNAVAILABLE
    with source.participant.mutation():
        pass


def test_source_write_and_undeclared_acquisition_are_rejected() -> None:
    source, target, unknown = Target(rank=10), Target(), Target(rank=80)

    def write_source() -> None:
        with source.participant.mutation():
            pytest.fail("出典を変更できてはなりません")

    token = source.participant.token()
    target.action = write_source
    assert (
        AuthorityFinalizationFence().finalize(target.request(token)).failure
        is FinalizationFailure.INVALID_LOCK_CONFIGURATION
    )
    assert source.participant.token() == token
    second = Target()

    def read_unknown() -> None:
        unknown.participant.token()

    second.action = read_unknown
    assert (
        AuthorityFinalizationFence().finalize(second.request(token)).failure
        is FinalizationFailure.INVALID_LOCK_CONFIGURATION
    )


def test_nested_fence_is_rejected_without_affecting_outer_commit() -> None:
    source, target, nested = Target(rank=10), Target(), Target(rank=80)
    request = nested.request(source.participant.token())

    def nested_call() -> None:
        assert (
            AuthorityFinalizationFence().finalize(request).failure
            is FinalizationFailure.INVALID_LOCK_CONFIGURATION
        )

    target.action = nested_call
    assert (
        AuthorityFinalizationFence().finalize(target.request(source.participant.token())).value == 7
    )


def test_real_executive_target_uses_fence_clock_and_existing_duplicate_semantics() -> None:
    source, target = Target(rank=10), ExecutiveDecisionAuthority()
    request = AuthorityFinalizationRequest(
        (source.participant.token(),),
        target.finalization_participant,
        target.finalization_operation,
        ExecutiveFinalizationInput(candidate(), snapshot(), live_state(), "fenced-decision"),
    )
    result = AuthorityFinalizationFence().finalize(request)
    assert result.failure is None and result.value is not None
    assert result.value.decision_id == "fenced-decision"
    assert result.value.committed_at > NOW
    assert (
        AuthorityFinalizationFence().finalize(request).failure
        is FinalizationFailure.TARGET_ALREADY_FINALIZED
    )


@pytest.mark.parametrize("index", [0, 1, 2])
def test_cancellation_during_acquisition_and_after_all_acquired(
    index: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second, target = Target(rank=10), Target(rank=20), Target()
    signal = Event()
    selected = (first.participant, second.participant, target.participant)[index]
    original = selected._acquire

    def acquire(*, blocking: bool) -> bool:
        result = original(blocking=blocking)
        signal.set()
        return result

    request = target.request(first.participant.token(), second.participant.token())
    monkeypatch.setattr(selected, "_acquire", acquire)
    result = AuthorityFinalizationFence().finalize(request, cancellation=signal)
    assert result.failure is FinalizationFailure.CANCELLED and target.calls == 0
    monkeypatch.undo()
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert (
            pool.submit(lambda: AuthorityFinalizationFence().finalize(request).value).result(5) == 7
        )


def test_activity_report_changes_composite_currentness() -> None:
    import asyncio

    from app.domain.activity_execution import ExecutionAdapterReport
    from app.domain.contracts import ExecutionStatus
    from tests.domain.plan_execution.test_progression import Preflight

    state = setup()
    invocation = state.owner.reserve_ready(state.scope_id, state.current, NOW).invocations[0]
    state.activity.admit(invocation, asyncio.run(Preflight(state).current_for(invocation)))
    state.activity.start(
        invocation.command.command_id,
        asyncio.run(Preflight(state).current_for(invocation)),
        NOW,
        "dispatch",
    )
    before = state.owner.observation_publication(state.scope_id)
    direct = state.activity.snapshot_publication(invocation.command.command_id)
    record = before.value.observations[0].record
    assert direct.value == record
    assert record.dispatch_id is not None
    state.activity.apply_report(
        ExecutionAdapterReport(
            invocation.command.command_id,
            invocation.invocation_id,
            record.dispatch_id,
            ExecutionStatus.COMPLETED,
            NOW,
            {},
        )
    )
    after = state.owner.observation_publication(state.scope_id)
    assert state.activity.snapshot_publication(invocation.command.command_id).value != direct.value
    assert before.value != after.value
    target = Target()
    assert (
        AuthorityFinalizationFence().finalize(target.request(*before.tokens)).failure
        is FinalizationFailure.GENERATION_MISMATCH
    )


def test_retired_scope_reregistration_does_not_revive_old_token() -> None:
    state = setup()
    scope = state.owner.scope_publication(state.scope_id).value
    state.owner.stop(state.scope_id)
    old = state.owner.observation_publication(state.scope_id)
    state.owner.retire(state.scope_id)
    replacement = state.owner.prepare_scope(
        scope.plan,
        scope.bindings,
        state.current.argument_facts,
        captured_at=NOW,
        deadline_at=scope.deadline_at,
    )
    assert replacement.scope_id != scope.scope_id
    target = Target()
    assert (
        AuthorityFinalizationFence().finalize(target.request(*old.tokens)).failure
        is FinalizationFailure.GENERATION_MISMATCH
    )


def test_goal_and_attention_share_read_and_write_generation_boundaries() -> None:
    from tests.domain.attention.test_attention_turn_store import attention_store, signal

    state = setup()
    goal = state.goals.snapshot_publication()
    with pytest.raises(ValueError):
        state.goals.apply(None)  # type: ignore[arg-type]
    assert state.goals.snapshot() == goal.value
    target = Target()
    assert (
        AuthorityFinalizationFence().finalize(target.request(*goal.tokens)).failure
        is FinalizationFailure.GENERATION_MISMATCH
    )
    attention = attention_store()
    before = attention.snapshot_publication()
    attention.offer(signal("input"))
    assert attention.snapshot() != before.value
    assert (
        AuthorityFinalizationFence().finalize(target.request(*before.tokens)).failure
        is FinalizationFailure.GENERATION_MISMATCH
    )
    token = attention.finalization_participant.token()
    assert attention.policy is not None
    attention.snapshot()
    assert attention.finalization_participant.token() == token


def test_target_as_source_locks_once_and_advances_only_mechanical_generation() -> None:
    target = Target()
    before = target.participant.token()
    result = AuthorityFinalizationFence().finalize(target.request(before, before))
    assert result.value == 7 and target.calls == 1
    assert result.target_token is not None and result.target_token.generation > before.generation
    assert (
        AuthorityFinalizationFence().finalize(target.request(before)).failure
        is FinalizationFailure.GENERATION_MISMATCH
    )


@pytest.mark.asyncio
async def test_slow_role_does_not_hold_fence_or_block_foreground_and_speech_work() -> None:
    import asyncio

    source, background, foreground = Target(rank=10), Target(), Target(rank=80)
    request = background.request(source.participant.token())
    started, finish = asyncio.Event(), asyncio.Event()
    progressed: list[str] = []

    async def slow_role() -> None:
        started.set()
        await finish.wait()
        assert AuthorityFinalizationFence().finalize(request).value == 7

    async def independent(name: str) -> None:
        await started.wait()
        progressed.append(name)

    task = asyncio.create_task(slow_role())
    await started.wait()
    await asyncio.gather(independent("body"), independent("speech"))
    assert (
        AuthorityFinalizationFence().finalize(foreground.request(source.participant.token())).value
        == 7
    )
    assert progressed == ["body", "speech"]
    finish.set()
    await task


def test_cancellation_after_token_validation_still_prevents_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target = Target(rank=10), Target()
    signal = Event()
    original = source.participant._validate

    def validate(token: AuthorityGenerationToken) -> FinalizationFailure | None:
        result = original(token)
        signal.set()
        return result

    monkeypatch.setattr(source.participant, "_validate", validate)
    result = AuthorityFinalizationFence().finalize(
        target.request(source.participant.token()), cancellation=signal
    )
    assert result.failure is FinalizationFailure.CANCELLED and target.calls == 0


def test_base_exception_during_commit_disables_target_and_releases_sources() -> None:
    import asyncio

    source, target = Target(rank=10), Target()

    def fault() -> None:
        raise asyncio.CancelledError()

    target.action = fault
    result = AuthorityFinalizationFence().finalize(target.request(source.participant.token()))
    assert result.failure is FinalizationFailure.TARGET_COMMIT_FAULT
    with source.participant.mutation():
        pass
    with pytest.raises(FinalizationError):
        target.participant.token()


def test_unregistered_operation_and_malformed_seal_are_rejected() -> None:
    source, target = Target(rank=10), Target()
    request = target.request(source.participant.token())
    forged = replace(request.operation, operation_identity="unknown")
    assert (
        AuthorityFinalizationFence().finalize(replace(request, operation=forged)).failure
        is FinalizationFailure.INVALID_PARTICIPANT
    )
    token = replace(source.participant.token(), _seal=object())  # type: ignore[arg-type]
    assert (
        AuthorityFinalizationFence().finalize(target.request(token)).failure
        is FinalizationFailure.INVALID_PARTICIPANT
    )


def test_unparticipating_goal_port_cannot_supply_finalization_tokens() -> None:
    from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
    from app.domain.goals import GoalCommitmentSnapshot
    from app.domain.plan_execution.contracts import PlanExecutionPolicy
    from app.domain.plan_execution.owner import PlanExecutionOwner

    state = setup()

    class GoalPort:
        def snapshot(self) -> GoalCommitmentSnapshot:
            return state.goals.snapshot()

    owner = PlanExecutionOwner(
        state.planning,
        GoalPort(),
        state.activity,
        PlanExecutionPolicy("execution", 1, 2, 2, 4, 256),
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    )
    with pytest.raises(FinalizationError) as caught:
        owner.finalization_participant.token()
    assert caught.value.failure is FinalizationFailure.PARTICIPANT_UNSUPPORTED


def test_duplicate_normalization_never_hides_invalid_issuance() -> None:
    source, target = Target(rank=10), Target()
    token = source.participant.token()
    invalid = replace(token, _seal=object())  # type: ignore[arg-type]
    result = AuthorityFinalizationFence().finalize(target.request(invalid, token))
    assert result.failure is FinalizationFailure.INVALID_PARTICIPANT and target.calls == 0


def test_distinct_owner_cannot_register_existing_order_key() -> None:
    source = Target(rank=10)

    class Owner:
        pass

    owner = Owner()
    with pytest.raises(FinalizationError) as caught:
        AuthorityFinalizationParticipant(
            owner, "different_owner", 10, owner_instance_key=source.participant.order_key[1],
        )
    assert caught.value.failure is FinalizationFailure.INVALID_PARTICIPANT
