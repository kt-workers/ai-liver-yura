from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from .policy import SpeechCandidatePriority, SpeechRuntimeOperationalPolicy


class SpeechPreparationAdmission:
    """D10 runtime policyに基づくbounded preparation admission。"""

    def __init__(self, policy: SpeechRuntimeOperationalPolicy) -> None:
        if not isinstance(policy, SpeechRuntimeOperationalPolicy):
            raise ValueError("Speech Runtime operational policy が必要です")
        self._policy = policy
        self._active = 0
        self._background = 0

    @property
    def policy(self) -> SpeechRuntimeOperationalPolicy:
        return self._policy

    def try_acquire(self, priority: SpeechCandidatePriority) -> bool:
        if not isinstance(priority, SpeechCandidatePriority):
            raise ValueError("speech admission priority が不正です")
        if self._active >= self._policy.max_in_flight_preparations:
            return False
        if (
            priority is SpeechCandidatePriority.BACKGROUND
            and self._background >= self._policy.max_background_in_flight_preparations
        ):
            return False
        self._active += 1
        if priority is SpeechCandidatePriority.BACKGROUND:
            self._background += 1
        return True

    @property
    def active_count(self) -> int:
        return self._active

    @property
    def background_active_count(self) -> int:
        return self._background

    def release(self, priority: SpeechCandidatePriority) -> None:
        if not isinstance(priority, SpeechCandidatePriority):
            raise ValueError("speech admission priority が不正です")
        if self._active < 1:
            raise ValueError("admission lease が存在しません")
        if priority is SpeechCandidatePriority.BACKGROUND:
            if self._background < 1:
                raise ValueError("background admission lease が存在しません")
            self._background -= 1
        self._active -= 1


_Result = TypeVar("_Result")
PreparationWork = Callable[[], Awaitable[_Result]]


class AdmittedPreparationExecutor:
    """permitを持つworkだけを開始し、終了理由を問わずleaseを返す。"""

    def __init__(self, admission: SpeechPreparationAdmission) -> None:
        self._admission = admission

    async def run(
        self,
        priority: SpeechCandidatePriority,
        work: PreparationWork[_Result],
    ) -> _Result | None:
        if not self._admission.try_acquire(priority):
            return None
        try:
            return await work()
        finally:
            self._admission.release(priority)
