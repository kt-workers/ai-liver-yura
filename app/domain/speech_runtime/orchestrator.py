from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from .contracts import TTSPreparationMode
from .tasks import CandidateTaskKey, CandidateTaskRegistry

RoleWork = Callable[[], Coroutine[Any, Any, object]]


class SpeechPreparationOrchestrator:
    """Character完了後のRole fan-outをcandidate/generation fence付きで開始する。"""

    def __init__(self, tasks: CandidateTaskRegistry) -> None:
        self._tasks = tasks

    def fan_out_after_character(
        self, candidate_id: str, generation: int, verifier: RoleWork, performance: RoleWork
    ) -> tuple[asyncio.Task[object], asyncio.Task[object]]:
        verifier_task = self._tasks.start(
            CandidateTaskKey(candidate_id, generation, "verifier"), verifier()
        )
        performance_task = self._tasks.start(
            CandidateTaskKey(candidate_id, generation, "performance"), performance()
        )
        return verifier_task, performance_task

    def start_tts_if_permitted(
        self,
        candidate_id: str,
        generation: int,
        mode: TTSPreparationMode,
        verifier_accepted: bool,
        tts: RoleWork,
    ) -> asyncio.Task[object] | None:
        if mode is TTSPreparationMode.DISABLED:
            return None
        if mode is TTSPreparationMode.AFTER_SEMANTIC_ACCEPTANCE and not verifier_accepted:
            return None
        return self._tasks.start(CandidateTaskKey(candidate_id, generation, "tts"), tts())
