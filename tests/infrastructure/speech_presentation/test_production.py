from __future__ import annotations

import asyncio

import pytest

from app.domain.speech_runtime.contracts import SpeechPresentationReportStatus
from app.domain.speech_runtime.execution import PresentationExecutionError
from app.infrastructure.speech_presentation.production import (
    PresentationProductionConfigurationError,
    PresentationProductionRegistration,
    PresentationWorkerBinding,
    PresentationWorkerRegistry,
)
from app.infrastructure.speech_presentation.supervisor import (
    PresentationWorkerRegistration,
    SpeechPresentationWorkerSupervisor,
)
from tests.domain.speech_runtime.test_presentation_timeout import committed
from tests.infrastructure.speech_presentation.test_process import policy


def worker(kind: str = "production_display") -> PresentationWorkerRegistration:
    return PresentationWorkerRegistration(
        kind,
        "tests.infrastructure.speech_presentation.worker_fixture",
        "build",
        {"trusted": True},
    )


def registration() -> PresentationProductionRegistration:
    return PresentationProductionRegistration("presentation", 1, worker())


def binding(*, revision: int = 1, availability: str = "available") -> PresentationWorkerBinding:
    return PresentationWorkerBinding("presentation", revision, availability)


@pytest.mark.asyncio
async def test_exact_trusted_binding_transfers_supervisor_ownership_to_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = registration()
    supervisor = SpeechPresentationWorkerSupervisor(item.worker)
    calls = 0
    original = supervisor.shutdown

    async def shutdown() -> None:
        nonlocal calls
        calls += 1
        await original()

    monkeypatch.setattr(
        PresentationProductionRegistration, "create_supervisor", lambda self: supervisor
    )
    monkeypatch.setattr(supervisor, "shutdown", shutdown)

    lease = await PresentationWorkerRegistry((item,)).acquire(binding())

    assert lease.supervisor is supervisor
    assert calls == 0
    await asyncio.gather(lease.close(), lease.close())
    assert calls == 1
    assert supervisor.active_execution_count == 0
    with pytest.raises(PresentationExecutionError):
        supervisor.open(None, None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_unknown_or_unavailable_binding_is_rejected_without_fallback() -> None:
    registry = PresentationWorkerRegistry((registration(),))

    with pytest.raises(PresentationProductionConfigurationError, match="登録と一致"):
        await registry.acquire(PresentationWorkerBinding("unknown", 1, "available"))
    with pytest.raises(PresentationProductionConfigurationError, match="登録と一致"):
        await registry.acquire(binding(availability="unavailable"))


@pytest.mark.asyncio
async def test_trusted_registration_uses_existing_supervisor_report_transport() -> None:
    item = PresentationProductionRegistration("presentation", 1, worker("normal"))
    lease = await PresentationWorkerRegistry((item,)).acquire(binding())
    _, _, command, _ = await committed()

    session = lease.supervisor.open(command, policy())
    assert (await session.receive()).status is SpeechPresentationReportStatus.STARTED
    assert (await session.receive()).status is SpeechPresentationReportStatus.COMPLETED
    await lease.close()

    assert lease.supervisor.active_execution_count == 0


@pytest.mark.asyncio
async def test_invalid_supervisor_is_shutdown_once_before_acquisition_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = registration()
    supervisor = SpeechPresentationWorkerSupervisor(worker("other_display"))
    calls = 0
    original = supervisor.shutdown

    async def shutdown() -> None:
        nonlocal calls
        calls += 1
        await original()

    monkeypatch.setattr(
        PresentationProductionRegistration, "create_supervisor", lambda self: supervisor
    )
    monkeypatch.setattr(supervisor, "shutdown", shutdown)

    with pytest.raises(PresentationProductionConfigurationError, match="Supervisorが不正"):
        await PresentationWorkerRegistry((item,)).acquire(binding())
    assert calls == 1


@pytest.mark.asyncio
async def test_cancelled_invalid_acquisition_waits_for_supervisor_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = registration()
    supervisor = SpeechPresentationWorkerSupervisor(worker("other_display"))
    entered = asyncio.Event()
    finish = asyncio.Event()
    calls = 0

    async def shutdown() -> None:
        nonlocal calls
        calls += 1
        entered.set()
        await finish.wait()

    monkeypatch.setattr(
        PresentationProductionRegistration, "create_supervisor", lambda self: supervisor
    )
    monkeypatch.setattr(supervisor, "shutdown", shutdown)

    acquiring = asyncio.create_task(PresentationWorkerRegistry((item,)).acquire(binding()))
    await entered.wait()
    acquiring.cancel()
    await asyncio.sleep(0)
    assert not acquiring.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await acquiring
    assert calls == 1
