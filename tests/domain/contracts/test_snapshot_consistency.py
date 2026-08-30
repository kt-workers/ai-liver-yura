from __future__ import annotations

import asyncio

import pytest

from app.domain.contracts.snapshots import (
    DEFAULT_SNAPSHOT_STABILIZATION_POLICY,
    SnapshotGenerationSample,
    SnapshotIncoherentError,
    SnapshotInvariantError,
    SnapshotReadCycle,
    SnapshotStabilizationPolicy,
    stabilize_snapshot,
    stabilize_snapshot_async,
)


def _sample(
    revision: int,
    *,
    fingerprint: str = "payload-a",
    generation: int = 1,
) -> SnapshotGenerationSample:
    return SnapshotGenerationSample(
        owner_id="owner-a",
        revision=revision,
        payload_fingerprint=fingerprint,
        generation_refs=(("model_revision", generation),),
    )


def _cycle(
    value: str,
    before: SnapshotGenerationSample,
    after: SnapshotGenerationSample,
    *,
    policy: SnapshotStabilizationPolicy = DEFAULT_SNAPSHOT_STABILIZATION_POLICY,
) -> SnapshotReadCycle[str]:
    return SnapshotReadCycle(
        value=value,
        before=(before,),
        after=(after,),
        policy_id=policy.policy_id,
        policy_revision=policy.policy_revision,
    )


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_policy_rejects_invalid_max_attempts(value: object) -> None:
    with pytest.raises(ValueError):
        SnapshotStabilizationPolicy(
            policy_id="policy",
            policy_revision=1,
            max_attempts=value,  # type: ignore[arg-type]
            allow_event_loop_yield_between_attempts=True,
        )


def test_policy_rejects_non_bool_yield_flag() -> None:
    with pytest.raises(ValueError):
        SnapshotStabilizationPolicy(
            policy_id="policy",
            policy_revision=1,
            max_attempts=1,
            allow_event_loop_yield_between_attempts=1,  # type: ignore[arg-type]
        )


def test_first_attempt_stable_returns_value() -> None:
    result = stabilize_snapshot(
        DEFAULT_SNAPSHOT_STABILIZATION_POLICY,
        lambda: _cycle("stable", _sample(1), _sample(1)),
    )

    assert result == "stable"


def test_unstable_then_stable_retries_without_fallback() -> None:
    cycles = iter(
        (
            _cycle("old", _sample(1), _sample(2)),
            _cycle("current", _sample(2), _sample(2)),
        )
    )

    result = stabilize_snapshot(
        DEFAULT_SNAPSHOT_STABILIZATION_POLICY,
        lambda: next(cycles),
    )

    assert result == "current"


def test_all_attempts_unstable_fail_closed() -> None:
    attempts = 0

    def read_cycle() -> SnapshotReadCycle[str]:
        nonlocal attempts
        attempts += 1
        return _cycle("partial", _sample(attempts), _sample(attempts + 1))

    with pytest.raises(SnapshotIncoherentError, match="SNAPSHOT_INCOHERENT"):
        stabilize_snapshot(DEFAULT_SNAPSHOT_STABILIZATION_POLICY, read_cycle)

    assert attempts == 3


def test_policy_revision_change_invalidates_attempt() -> None:
    old_cycle = SnapshotReadCycle(
        value="old",
        before=(_sample(1),),
        after=(_sample(1),),
        policy_id=DEFAULT_SNAPSHOT_STABILIZATION_POLICY.policy_id,
        policy_revision=0,
    )
    stable_cycle = _cycle("current", _sample(1), _sample(1))
    cycles = iter((old_cycle, stable_cycle))

    assert (
        stabilize_snapshot(
            DEFAULT_SNAPSHOT_STABILIZATION_POLICY,
            lambda: next(cycles),
        )
        == "current"
    )


def test_same_revision_different_payload_is_invariant_violation() -> None:
    cycle = _cycle(
        "invalid",
        _sample(1, fingerprint="payload-a"),
        _sample(1, fingerprint="payload-b"),
    )

    with pytest.raises(SnapshotInvariantError, match="without revision"):
        stabilize_snapshot(DEFAULT_SNAPSHOT_STABILIZATION_POLICY, lambda: cycle)


@pytest.mark.asyncio
async def test_async_retry_yields_without_starving_unrelated_work() -> None:
    attempts = 0
    heartbeat = asyncio.Event()

    async def unrelated() -> None:
        heartbeat.set()

    async def read_cycle() -> SnapshotReadCycle[str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return _cycle("old", _sample(1), _sample(2))
        assert heartbeat.is_set()
        return _cycle("current", _sample(2), _sample(2))

    task = asyncio.create_task(unrelated())
    result = await stabilize_snapshot_async(
        DEFAULT_SNAPSHOT_STABILIZATION_POLICY,
        read_cycle,
    )
    await task

    assert result == "current"


@pytest.mark.asyncio
async def test_async_policy_can_disable_cooperative_yield() -> None:
    policy = SnapshotStabilizationPolicy(
        policy_id="no-yield",
        policy_revision=1,
        max_attempts=2,
        allow_event_loop_yield_between_attempts=False,
    )
    attempts = 0

    async def read_cycle() -> SnapshotReadCycle[str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return _cycle("old", _sample(1), _sample(2), policy=policy)
        return _cycle("current", _sample(2), _sample(2), policy=policy)

    assert await stabilize_snapshot_async(policy, read_cycle) == "current"
