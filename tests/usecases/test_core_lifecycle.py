"""外側の構成やDBなしで、実行所有者の起動・停止・取消を検証する。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from app.domain.contracts.lifecycle import (
    ApplicationShutdownError,
    ApplicationShutdownPolicy,
    ApplicationShutdownStage,
)
from app.usecases.core_lifecycle import (
    CoreActivationError,
    CoreApplicationLifecycle,
    start_core,
    stop_core,
)


class _Closer:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events
        self.error: BaseException | None = None
        self.entered = asyncio.Event()
        self.release: asyncio.Event | None = None

    async def close(self) -> None:
        self.events.append(self.name)
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error


class _Brain:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.start_error: BaseException | None = None
        self.stop_error: BaseException | None = None
        self.entered = asyncio.Event()
        self.release: asyncio.Event | None = None
        self.cancelled = False

    async def start(self) -> None:
        self.events.append("brain.start")
        self.entered.set()
        try:
            if self.release is not None:
                await self.release.wait()
            if self.start_error is not None:
                raise self.start_error
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def stop(self) -> None:
        self.events.append("brain.stop")
        if self.stop_error is not None:
            raise self.stop_error


class _Autonomy:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.error: BaseException | None = None

    def start(self) -> None:
        self.events.append("autonomy.start")
        if self.error is not None:
            raise self.error


@dataclass
class _Cognition:
    autonomy: _Autonomy | None
    speech: _Closer | None
    reflection: _Closer | None


@dataclass(frozen=True)
class _Configuration:
    shutdown_policy: ApplicationShutdownPolicy


@dataclass
class _Components:
    config: _Configuration
    brain: _Brain
    cognition: _Cognition | None
    memory: _Closer | None
    lifecycle: _Closer
    memory_is_borrowed: bool = False


def _components(events: list[str]) -> _Components:
    return _Components(
        _Configuration(ApplicationShutdownPolicy("test.shutdown", 1, 1.0, 1.0, 1.0, 1.0)),
        _Brain(events),
        _Cognition(_Autonomy(events), _Closer("speech", events), _Closer("reflection", events)),
        _Closer("memory", events),
        _Closer("lifecycle", events),
    )


async def _turn() -> None:
    resumed = asyncio.Event()
    asyncio.get_running_loop().call_soon(resumed.set)
    await resumed.wait()


@pytest.mark.asyncio
async def test_concurrent_start_and_stop_share_one_owned_operation() -> None:
    events: list[str] = []
    core = _components(events)
    owned = _Closer("owned", events)
    runtime = CoreApplicationLifecycle(core, owned)
    await asyncio.gather(*(runtime.start() for _ in range(4)))
    assert events == ["brain.start", "autonomy.start"]
    await asyncio.gather(*(runtime.stop() for _ in range(4)))
    expected = [
        "brain.start", "autonomy.start", "brain.stop", "speech", "reflection", "memory",
        "lifecycle", "owned",
    ]
    assert events == expected
    await runtime.stop()
    assert events == expected
    with pytest.raises(CoreActivationError):
        await runtime.start()
    assert events == expected


@pytest.mark.asyncio
async def test_stop_before_start_does_not_activate_any_owner() -> None:
    events: list[str] = []
    runtime = CoreApplicationLifecycle(_components(events), _Closer("owned", events))
    await runtime.stop()
    assert events == ["brain.stop", "speech", "reflection", "memory", "lifecycle", "owned"]
    with pytest.raises(CoreActivationError):
        await runtime.start()
    assert "brain.start" not in events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failing", ["brain.stop", "speech", "reflection", "memory", "lifecycle", "owned"]
)
async def test_each_shutdown_failure_still_reclaims_later_owners(failing: str) -> None:
    events: list[str] = []
    core = _components(events)
    owned = _Closer("owned", events)
    assert core.cognition is not None
    error = ValueError("試験で発生させた終了失敗")
    if failing == "brain.stop":
        core.brain.stop_error = error
    else:
        targets = {
            "speech": core.cognition.speech,
            "reflection": core.cognition.reflection,
            "memory": core.memory,
            "lifecycle": core.lifecycle,
            "owned": owned,
        }
        target = targets[failing]
        assert target is not None
        target.error = error
    runtime = CoreApplicationLifecycle(core, owned)
    with pytest.raises(ValueError) as caught:
        await runtime.stop()
    assert caught.value is error
    assert events == ["brain.stop", "speech", "reflection", "memory", "lifecycle", "owned"]
    with pytest.raises(ValueError) as repeated:
        await runtime.stop()
    assert repeated.value is error
    assert events.count("owned") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("remove_cognition", [False, True])
async def test_unconfigured_optional_resources_are_not_constructed(remove_cognition: bool) -> None:
    events: list[str] = []
    core = _components(events)
    core.cognition = None if remove_cognition else _Cognition(None, None, None)
    core.memory = None
    runtime = CoreApplicationLifecycle(core, _Closer("owned", events))
    await runtime.start()
    await runtime.stop()
    assert events == ["brain.start", "brain.stop", "lifecycle", "owned"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fails_in_autonomy", [False, True])
async def test_failed_start_reclaims_resources_before_reporting_failure(
    fails_in_autonomy: bool,
) -> None:
    events: list[str] = []
    core = _components(events)
    error = ValueError("非公開の試験詳細")
    if fails_in_autonomy:
        assert core.cognition is not None and core.cognition.autonomy is not None
        core.cognition.autonomy.error = error
    else:
        core.brain.start_error = error
    runtime = CoreApplicationLifecycle(core, _Closer("owned", events))
    with pytest.raises(CoreActivationError) as caught:
        await runtime.start()
    assert "非公開の試験詳細" not in str(caught.value)
    assert events[-5:] == ["speech", "reflection", "memory", "lifecycle", "owned"]
    assert events.count("brain.stop") == (2 if fails_in_autonomy else 1)
    await runtime.stop()
    assert events.count("owned") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_concurrently", [False, True])
async def test_cancelled_start_reclaims_start_task_and_resources(stop_concurrently: bool) -> None:
    events: list[str] = []
    core = _components(events)
    core.brain.release = asyncio.Event()
    runtime = CoreApplicationLifecycle(core, _Closer("owned", events))
    starting = asyncio.create_task(runtime.start())
    stopping: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(core.brain.entered.wait(), 1.0)
        if stop_concurrently:
            stopping = asyncio.create_task(runtime.stop())
        else:
            starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(starting), 1.0)
        if stopping is not None:
            await asyncio.wait_for(asyncio.shield(stopping), 1.0)
        assert core.brain.cancelled
        assert "autonomy.start" not in events
        assert events[-5:] == ["speech", "reflection", "memory", "lifecycle", "owned"]
        await runtime.stop()
        assert events.count("owned") == 1
    finally:
        core.brain.release.set()
        await asyncio.gather(
            starting, *(() if stopping is None else (stopping,)), return_exceptions=True
        )
        await runtime.stop()


@pytest.mark.asyncio
async def test_repeated_stop_cancellation_waits_for_owned_cleanup() -> None:
    events: list[str] = []
    owned = _Closer("owned", events)
    owned.release = asyncio.Event()
    runtime = CoreApplicationLifecycle(_components(events), owned)
    stopping = asyncio.create_task(runtime.stop())
    try:
        await asyncio.wait_for(owned.entered.wait(), 1.0)
        for _ in range(3):
            assert stopping.cancel()
            await _turn()
            assert not stopping.done()
        owned.release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(stopping), 1.0)
        await runtime.stop()
        assert events.count("owned") == 1
    finally:
        owned.release.set()
        await asyncio.gather(stopping, return_exceptions=True)
        await runtime.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("configured_timeout", [False, True])
async def test_final_persistence_timeout_retains_existing_typed_failure(
    configured_timeout: bool,
) -> None:
    events: list[str] = []
    core = _components(events)
    assert core.memory is not None
    if configured_timeout:
        core.config = _Configuration(
            ApplicationShutdownPolicy("test.shutdown", 1, 1.0, 0.0, 1.0, 1.0)
        )
        core.memory.release = asyncio.Event()
    else:
        core.memory.error = asyncio.TimeoutError()
    runtime = CoreApplicationLifecycle(core, _Closer("owned", events))
    with pytest.raises(ApplicationShutdownError) as caught:
        await runtime.stop()
    assert len(caught.value.failures) == 1
    assert caught.value.failures[0].stage is ApplicationShutdownStage.FINAL_PERSISTENCE
    assert caught.value.failures[0].error_class == "TimeoutError"
    assert events[-2:] == ["lifecycle", "owned"]


@pytest.mark.asyncio
async def test_lifecycle_uses_current_owners_without_copying_components() -> None:
    events: list[str] = []
    core = _components(events)
    runtime = CoreApplicationLifecycle(core, _Closer("owned", events))
    assert core.cognition is not None
    core.cognition.speech = _Closer("current.speech", events)
    await runtime.start()
    await runtime.stop()
    assert "current.speech" in events
    assert "speech" not in events


@pytest.mark.asyncio
async def test_core_operations_remain_available_without_application_wrapper() -> None:
    events: list[str] = []
    core = _components(events)
    await start_core(core)
    await stop_core(core)
    assert events == [
        "brain.start", "autonomy.start", "brain.stop", "speech", "reflection",
        "memory", "lifecycle",
    ]


@pytest.mark.asyncio
async def test_borrowed_memory_is_not_closed_by_core() -> None:
    events: list[str] = []
    core = _components(events)
    core.memory_is_borrowed = True
    assert core.memory is not None
    borrowed = core.memory
    await stop_core(core)
    assert "memory" not in events
    assert "brain.stop" in events
    assert "lifecycle" in events
    assert borrowed is core.memory
