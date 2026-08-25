from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from app.domain.llm import LLMPriority


@dataclass(frozen=True, slots=True)
class SpeechPreparationAdmissionPolicy:
    max_active_foreground: int
    max_active_background: int
    max_active_total: int

    def __post_init__(self) -> None:
        values = (
            self.max_active_foreground,
            self.max_active_background,
            self.max_active_total,
        )
        if any(type(value) is not int or value < 1 for value in values):
            raise ValueError("admission bound が不正です")
        if self.max_active_total < self.max_active_foreground:
            raise ValueError("total bound がforeground boundより小さいです")
        if self.max_active_background >= self.max_active_total:
            raise ValueError("foreground reservationが必要です")


class SpeechPreparationAdmission:
    """準備開始前のbounded admission。待機列やglobal lockは作らない。"""

    def __init__(self, policy: SpeechPreparationAdmissionPolicy) -> None:
        self._policy = policy
        self._foreground = 0
        self._background = 0

    def try_acquire(self, priority: LLMPriority) -> bool:
        if priority not in {LLMPriority.FOREGROUND, LLMPriority.BACKGROUND}:
            raise ValueError("speech admission priority が不正です")
        total = self._foreground + self._background
        if total >= self._policy.max_active_total:
            return False
        if priority is LLMPriority.FOREGROUND:
            if self._foreground >= self._policy.max_active_foreground:
                return False
            self._foreground += 1
            return True
        if self._background >= self._policy.max_active_background:
            return False
        self._background += 1
        return True

    @property
    def active_count(self) -> int:
        return self._foreground + self._background

    def release(self, priority: LLMPriority) -> None:
        if priority is LLMPriority.FOREGROUND and self._foreground:
            self._foreground -= 1
        elif priority is LLMPriority.BACKGROUND and self._background:
            self._background -= 1
        else:
            raise ValueError("admission lease が存在しません")


_Result = TypeVar("_Result")
PreparationWork = Callable[[], Awaitable[_Result]]


class AdmittedPreparationExecutor:
    """permitを持つworkだけを開始し、終了理由を問わずleaseを返す。"""

    def __init__(self, admission: SpeechPreparationAdmission) -> None:
        self._admission = admission

    async def run(self, priority: LLMPriority, work: PreparationWork[_Result]) -> _Result | None:
        if not self._admission.try_acquire(priority):
            return None
        try:
            return await work()
        finally:
            self._admission.release(priority)
