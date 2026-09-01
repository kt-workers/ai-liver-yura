from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from .admission import PreparationWork, SpeechPreparationAdmission
from .contracts import TTSPreparationMode
from .policy import SpeechCandidatePriority, SpeechRuntimeOperationalPolicy
from .tasks import CandidateTaskKey, CandidateTaskRegistry

RoleWork = Callable[[], Coroutine[Any, Any, object]]


class SpeechPreparationOrchestrator:
    """Character完了後のRole fan-outをcandidate/generation fence付きで開始する。"""

    def __init__(
        self,
        tasks: CandidateTaskRegistry,
        admission: SpeechPreparationAdmission,
        policy: SpeechRuntimeOperationalPolicy,
    ) -> None:
        if not isinstance(policy, SpeechRuntimeOperationalPolicy):
            raise ValueError("Speech Runtime operational policy が必要です")
        if not admission.policy.same_generation(policy.policy_id, policy.policy_revision):
            raise ValueError("admissionとorchestratorのoperational policy generationが一致しません")
        self._tasks = tasks
        self._admission = admission
        self._policy = policy
        self._leases: dict[tuple[str, int], tuple[SpeechCandidatePriority, asyncio.Event]] = {}
        self._active_speculative_tts = 0

    @property
    def active_speculative_tts_count(self) -> int:
        return self._active_speculative_tts

    def start_preparation(
        self,
        candidate_id: str,
        generation: int,
        priority: SpeechCandidatePriority,
        character: PreparationWork[object],
    ) -> asyncio.Task[object] | None:
        """candidate lifecycle全体をadmission leaseへbindしてCharacterを開始する。"""
        key = (candidate_id, generation)
        if key in self._leases:
            raise ValueError("Speech preparation admission leaseは一意です")
        if not self._admission.try_acquire(priority):
            return None
        release = asyncio.Event()
        self._leases[key] = (priority, release)

        async def hold_lease() -> object:
            try:
                await release.wait()
            finally:
                self._leases.pop(key, None)
                self._admission.release(priority)
            return object()

        async def run_character() -> object:
            return await character()

        self._tasks.start(CandidateTaskKey(candidate_id, generation, "admission"), hold_lease())
        return self._tasks.start(
            CandidateTaskKey(candidate_id, generation, "character"),
            run_character(),
        )

    def fan_out_after_character(
        self,
        candidate_id: str,
        generation: int,
        verifier: RoleWork,
        performance: RoleWork,
    ) -> tuple[asyncio.Task[object], asyncio.Task[object]]:
        self._require_lease(candidate_id, generation)
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
        self._require_lease(candidate_id, generation)
        if type(verifier_accepted) is not bool:
            raise ValueError("verifier_accepted が不正です")
        if mode is TTSPreparationMode.DISABLED:
            return None
        if mode is TTSPreparationMode.AFTER_SEMANTIC_ACCEPTANCE and not verifier_accepted:
            return None
        speculative = (
            mode is TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE
            and not verifier_accepted
        )
        if speculative and self._active_speculative_tts >= self._policy.speculative_tts_limit:
            return None
        if speculative:
            self._active_speculative_tts += 1

        async def run_tts() -> object:
            try:
                return await tts()
            finally:
                if speculative:
                    self._active_speculative_tts -= 1

        return self._tasks.start(
            CandidateTaskKey(candidate_id, generation, "tts"),
            run_tts(),
        )

    def complete_preparation(self, candidate_id: str, generation: int) -> None:
        """candidateがterminal又はqueueへ移った後にlifecycle leaseを返す。"""
        _, release = self._require_lease(candidate_id, generation)
        if self._tasks.has_pending_candidate_work(
            candidate_id,
            generation,
            excluding_role="admission",
        ):
            raise ValueError("未完了Roleがある間はSpeech preparation leaseを解放できません")
        release.set()

    def _require_lease(
        self, candidate_id: str, generation: int
    ) -> tuple[SpeechCandidatePriority, asyncio.Event]:
        lease = self._leases.get((candidate_id, generation))
        if lease is None:
            raise ValueError("admitted Speech preparation leaseが必要です")
        return lease
