from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from .common import require_identifier

T = TypeVar("T")


def _require_revision(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative int")
    return value


@dataclass(frozen=True, slots=True)
class SnapshotStabilizationPolicy:
    policy_id: str
    policy_revision: int
    max_attempts: int
    allow_event_loop_yield_between_attempts: bool

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        _require_revision(self.policy_revision, "policy_revision")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts must be a positive int")
        if type(self.allow_event_loop_yield_between_attempts) is not bool:
            raise ValueError(
                "allow_event_loop_yield_between_attempts must be a bool"
            )


DEFAULT_SNAPSHOT_STABILIZATION_POLICY = SnapshotStabilizationPolicy(
    policy_id="v2.snapshot-stabilization.default",
    policy_revision=1,
    max_attempts=3,
    allow_event_loop_yield_between_attempts=True,
)


@dataclass(frozen=True, slots=True)
class SnapshotGenerationSample:
    owner_id: str
    revision: int
    payload_fingerprint: str
    generation_refs: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.owner_id, "owner_id")
        _require_revision(self.revision, "revision")
        require_identifier(self.payload_fingerprint, "payload_fingerprint")

        normalized: list[tuple[str, int]] = []
        seen: set[str] = set()
        for name, revision in self.generation_refs:
            require_identifier(name, "generation_ref name")
            _require_revision(revision, f"generation_ref {name}")
            if name in seen:
                raise ValueError("generation_ref names must be unique")
            seen.add(name)
            normalized.append((name, revision))
        object.__setattr__(self, "generation_refs", tuple(normalized))


@dataclass(frozen=True, slots=True)
class SnapshotReadCycle(Generic[T]):
    value: T
    before: tuple[SnapshotGenerationSample, ...]
    after: tuple[SnapshotGenerationSample, ...]
    policy_id: str
    policy_revision: int

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        _require_revision(self.policy_revision, "policy_revision")
        object.__setattr__(self, "before", tuple(self.before))
        object.__setattr__(self, "after", tuple(self.after))


class SnapshotIncoherentError(RuntimeError):
    pass


class SnapshotInvariantError(RuntimeError):
    pass


def snapshot_cycle_is_stable(
    cycle: SnapshotReadCycle[T],
    policy: SnapshotStabilizationPolicy,
) -> bool:
    if cycle.policy_id != policy.policy_id:
        return False
    if cycle.policy_revision != policy.policy_revision:
        return False
    if len(cycle.before) != len(cycle.after):
        return False

    before_by_owner = {sample.owner_id: sample for sample in cycle.before}
    after_by_owner = {sample.owner_id: sample for sample in cycle.after}
    if len(before_by_owner) != len(cycle.before):
        raise SnapshotInvariantError("duplicate owner_id in before samples")
    if len(after_by_owner) != len(cycle.after):
        raise SnapshotInvariantError("duplicate owner_id in after samples")
    if before_by_owner.keys() != after_by_owner.keys():
        return False

    for owner_id, before in before_by_owner.items():
        after = after_by_owner[owner_id]
        if before.revision == after.revision:
            if before.payload_fingerprint != after.payload_fingerprint:
                raise SnapshotInvariantError(
                    f"owner {owner_id} changed payload without revision"
                )
            if before.generation_refs != after.generation_refs:
                raise SnapshotInvariantError(
                    f"owner {owner_id} changed generation refs without revision"
                )
        if before.revision != after.revision:
            return False
        if before.generation_refs != after.generation_refs:
            return False
    return True


def stabilize_snapshot(
    policy: SnapshotStabilizationPolicy,
    read_cycle: Callable[[], SnapshotReadCycle[T]],
) -> T:
    for _attempt in range(policy.max_attempts):
        cycle = read_cycle()
        if snapshot_cycle_is_stable(cycle, policy):
            return cycle.value
    raise SnapshotIncoherentError("SNAPSHOT_INCOHERENT")


async def stabilize_snapshot_async(
    policy: SnapshotStabilizationPolicy,
    read_cycle: Callable[[], Awaitable[SnapshotReadCycle[T]]],
) -> T:
    for attempt in range(policy.max_attempts):
        cycle = await read_cycle()
        if snapshot_cycle_is_stable(cycle, policy):
            return cycle.value
        if (
            attempt + 1 < policy.max_attempts
            and policy.allow_event_loop_yield_between_attempts
        ):
            await asyncio.sleep(0)
    raise SnapshotIncoherentError("SNAPSHOT_INCOHERENT")
