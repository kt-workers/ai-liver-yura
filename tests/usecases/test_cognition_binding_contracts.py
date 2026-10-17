"""具体Runtimeを継承しない作業入力と取消状態で、既存Ownerへ接続する。"""

from __future__ import annotations

import asyncio
import importlib

import pytest

from app.domain.brain_integration import BrainIntegrationModule, BrainWorkEnvelope
from app.usecases.brain_appraisal import AppraisalBrainModulePort
from app.usecases.brain_integration_runtime import BrainIntegrationWork
from tests.system_integration.test_core_appraisal import Port, brain_work, setup


class WorkView:
    """新しいDTOを捏造せず、既存の作業を読取りだけで公開する。"""

    def __init__(self, work: BrainIntegrationWork) -> None:
        self._work = work

    @property
    def module(self) -> BrainIntegrationModule:
        return self._work.module

    @property
    def envelope(self) -> BrainWorkEnvelope:
        return self._work.envelope

    @property
    def payload(self) -> object:
        return self._work.payload


class CancellationView:
    """利用側へは取消済みかどうかだけを公開する。"""

    def __init__(self, cancelled: bool = False) -> None:
        self._cancelled = cancelled

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def request(self) -> None:
        self._cancelled = True


@pytest.mark.asyncio
async def test_appraisal_accepts_read_only_work_and_cancellation() -> None:
    value = setup()
    item = WorkView(brain_work(value))
    module = AppraisalBrainModulePort(value.connection)
    assert module.is_fresh(item)
    result = await module.execute(item, CancellationView())
    assert result is value.connection.current_commit()
    assert result.internal_state is value.owner.snapshot()
    assert len(value.port.requests) == 1


@pytest.mark.asyncio
async def test_read_only_cancelled_state_does_not_invoke_or_commit() -> None:
    value = setup()
    before = value.owner.snapshot()
    module = AppraisalBrainModulePort(value.connection)
    with pytest.raises(asyncio.CancelledError):
        await module.execute(WorkView(brain_work(value)), CancellationView(True))
    assert value.owner.snapshot() is before
    assert value.connection.latest_commit() is None
    assert not value.port.requests


@pytest.mark.asyncio
async def test_read_only_cancellation_after_response_rejects_commit() -> None:
    value = setup(Port(waiting=True))
    before = value.owner.snapshot()
    cancellation = CancellationView()
    task = asyncio.create_task(
        AppraisalBrainModulePort(value.connection).execute(
            WorkView(brain_work(value)), cancellation
        )
    )
    try:
        await asyncio.wait_for(value.port.started.wait(), timeout=1.0)
        cancellation.request()
        value.port.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert value.owner.snapshot() is before
        assert value.connection.latest_commit() is None
    finally:
        value.port.release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "module,names",
    [
        ("app.usecases.input_reference_context",
         ("CoreGoalSnapshotReader", "CoreInputReferenceSnapshot",
          "CoreInputReferenceContextBinding", "PresentationReferenceCapacityError",
          "PresentationReferenceStaleError")),
        ("app.usecases.brain_appraisal",
         ("CoreAppraisalBinding", "AppraisalBrainWorkPayload", "AppraisalBrainModulePort")),
        ("app.usecases.attention_binding",
         ("CoreAttentionBinding", "CoreAttentionCurrentState", "CoreAttentionDispatch")),
    ],
)
def test_canonical_imports_resolve_owned_classes(
    module: str, names: tuple[str, ...],
) -> None:
    owner = importlib.import_module(module)
    for name in names:
        actual = getattr(owner, name)
        assert actual.__module__ == module
