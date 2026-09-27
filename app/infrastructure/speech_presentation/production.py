"""trusted本番Presentation登録を完全一致で解決する。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.domain.contracts.common import require_identifier, require_revision

from .supervisor import PresentationWorkerRegistration, SpeechPresentationWorkerSupervisor


class PresentationProductionConfigurationError(ValueError):
    """要求されたbindingとtrusted登録が一致しない。"""


class PresentationProductionCleanupError(RuntimeError):
    """lease返却前後のSupervisor回収が完了しなかった。"""


@dataclass(frozen=True, slots=True)
class PresentationWorkerBinding:
    """公開構成が指定できるのはbinding identityとrevisionだけである。"""

    binding_id: str
    binding_revision: int
    availability: str

    def __post_init__(self) -> None:
        require_identifier(self.binding_id, "binding_id")
        require_revision(self.binding_revision, "binding_revision")
        if self.availability not in ("available", "unavailable"):
            raise PresentationProductionConfigurationError("Presentation bindingが不正です")


@dataclass(frozen=True, slots=True)
class PresentationProductionRegistration:
    """構成rootだけが作る、worker factoryを含むtrusted登録。"""

    binding_id: str
    binding_revision: int
    worker: PresentationWorkerRegistration

    def __post_init__(self) -> None:
        require_identifier(self.binding_id, "binding_id")
        require_revision(self.binding_revision, "binding_revision")
        if not isinstance(self.worker, PresentationWorkerRegistration):
            raise PresentationProductionConfigurationError("Presentation worker登録が不正です")

    def create_supervisor(self) -> SpeechPresentationWorkerSupervisor:
        return SpeechPresentationWorkerSupervisor(self.worker)


class PresentationWorkerLease:
    """Supervisorの使用中ownershipを一つのcloseへ閉じ込める。"""

    def __init__(self, supervisor: SpeechPresentationWorkerSupervisor) -> None:
        self.supervisor = supervisor
        self._close_task: asyncio.Task[None] | None = None

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await _settle(self._close_task)

    async def _close(self) -> None:
        try:
            await self.supervisor.shutdown()
        except asyncio.CancelledError:
            raise
        except Exception:
            raise PresentationProductionCleanupError(
                "Presentation Supervisorを回収できません"
            ) from None


class PresentationWorkerRegistry:
    """任意importを許さず、trusted codeの完全一致登録だけを解決する。"""

    def __init__(self, registrations: tuple[PresentationProductionRegistration, ...]) -> None:
        if type(registrations) is not tuple or any(
            not isinstance(item, PresentationProductionRegistration) for item in registrations
        ):
            raise PresentationProductionConfigurationError("Presentation登録tupleが不正です")
        indexed = {(item.binding_id, item.binding_revision): item for item in registrations}
        if len(indexed) != len(registrations):
            raise PresentationProductionConfigurationError(
                "Presentation binding登録が重複しています"
            )
        self._registrations = indexed

    async def acquire(self, binding: PresentationWorkerBinding) -> PresentationWorkerLease:
        if not isinstance(binding, PresentationWorkerBinding):
            raise PresentationProductionConfigurationError("Presentation binding要求が不正です")
        registration = self._registrations.get((binding.binding_id, binding.binding_revision))
        if registration is None or binding.availability != "available":
            raise PresentationProductionConfigurationError(
                "Presentation bindingが登録と一致しません"
            )
        try:
            supervisor = registration.create_supervisor()
        except Exception:
            raise PresentationProductionConfigurationError(
                "Presentation Supervisorを取得できません"
            ) from None
        try:
            if (
                not isinstance(supervisor, SpeechPresentationWorkerSupervisor)
                or supervisor.registration != registration.worker
            ):
                raise PresentationProductionConfigurationError("Presentation Supervisorが不正です")
            return PresentationWorkerLease(supervisor)
        except BaseException:
            await self._release_failed_acquisition(supervisor)
            raise

    @staticmethod
    async def _release_failed_acquisition(supervisor: object) -> None:
        """lease返却前のSupervisorを、呼出側取消より先に必ず回収する。"""
        if not isinstance(supervisor, SpeechPresentationWorkerSupervisor):
            return
        task = asyncio.create_task(supervisor.shutdown())
        try:
            await _settle(task)
        except asyncio.CancelledError:
            if task.cancelled():
                raise PresentationProductionCleanupError(
                    "取得中のPresentation Supervisorを回収できません"
                ) from None
            raise
        except Exception:
            raise PresentationProductionCleanupError(
                "取得中のPresentation Supervisorを回収できません"
            ) from None


async def _settle(task: asyncio.Task[None]) -> None:
    """取消されても既に開始したcleanupを完了まで待機する。"""
    cancelled = False
    while True:
        try:
            await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
