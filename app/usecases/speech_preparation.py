"""Speech準備の未採用音声を、世代Authorityと分離して所有する。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.domain.speech_runtime.discard import (
    PreparedAudioDiscardPort,
    PreparedAudioDiscardReason,
    PreparedAudioDiscardRequest,
)


@dataclass(frozen=True, slots=True)
class PendingPreparedAudio:
    """元世代は採用判定だけに使用し、資源回収要求へ移管しない。"""

    candidate_id: str
    generation: int
    utterance_id: str
    performance_plan_id: str
    audio_ref: str


class SpeechPreparationCleanupError(RuntimeError):
    """元の終端理由を保持し、資源Ownerの生例外を公開しない。"""

    def __init__(self, terminal_reason: str) -> None:
        super().__init__("Speech準備資源の回収が完了していません")
        self.terminal_reason = terminal_reason


class PendingSpeechAudioOwner:
    """Runtime未採用の資源だけを保持し、移管済み音声を二重破棄しない。"""

    def __init__(self, port: PreparedAudioDiscardPort) -> None:
        self._port = port
        self._owned: dict[tuple[str, int], PendingPreparedAudio] = {}
        self._failed: set[tuple[str, int]] = set()

    @property
    def pending_count(self) -> int:
        return len(self._owned)

    def receive(self, result: PendingPreparedAudio) -> None:
        key = (result.candidate_id, result.generation)
        if key in self._owned:
            raise ValueError("未採用音声の所有権は重複できません")
        self._owned[key] = result

    def transferred(self, candidate_id: str, generation: int) -> None:
        self._owned.pop((candidate_id, generation), None)

    def result(self, candidate_id: str, generation: int) -> PendingPreparedAudio | None:
        return self._owned.get((candidate_id, generation))

    async def discard(
        self, candidate_id: str, generation: int, reason: PreparedAudioDiscardReason
    ) -> None:
        key = (candidate_id, generation)
        result = self._owned.get(key)
        if result is None:
            return
        if key in self._failed:
            # effectが不明な失敗を自動再送して二重破棄にしない。
            raise SpeechPreparationCleanupError(reason.value)
        try:
            await self._port.discard(
                PreparedAudioDiscardRequest(
                    result.candidate_id,
                    result.utterance_id,
                    result.performance_plan_id,
                    result.audio_ref,
                    reason,
                )
            )
        except BaseException:
            self._failed.add(key)
            raise SpeechPreparationCleanupError(reason.value) from None
        self._owned.pop(key)


async def finish_cleanup(work: asyncio.Task[None]) -> None:
    """再取消でも回収taskをjoinしてから取消を伝播する。"""
    cancelled = False
    while not work.done():
        try:
            await asyncio.shield(work)
        except asyncio.CancelledError:
            cancelled = True
    work.result()
    if cancelled:
        raise asyncio.CancelledError
