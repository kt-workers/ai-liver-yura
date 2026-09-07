"""一つの検証実行内で生成・合成・待ち行列が使う本番所有者を保持する。"""

from datetime import datetime

from app.domain.speech_runtime.admission import SpeechPreparationAdmission
from app.domain.speech_runtime.discard import PreparedAudioDiscarder, PreparedAudioDiscardReason
from app.domain.speech_runtime.orchestrator import SpeechPreparationOrchestrator
from app.domain.speech_runtime.policy import SpeechRuntimeOperationalPolicy
from app.domain.speech_runtime.queue import PreparedSpeechQueue, PreparedSpeechQueueCoordinator
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.tasks import CandidateTaskRegistry

from .audio_presentation import LabAudioResources
from .runtime import RunContext


class SpeechPreparationSession:
    """記録用JSONを状態へ戻さず、同じ型付き所有者を共有する。"""

    def __init__(
        self, context: RunContext, policy: SpeechRuntimeOperationalPolicy, observed_at: datetime
    ) -> None:
        self.context = context
        self.policy = policy
        self.observed_at = observed_at
        self.runtime = SpeechRuntime(policy, lambda: self.observed_at)
        self.resources = LabAudioResources()
        self.tasks = CandidateTaskRegistry()
        self.admission = SpeechPreparationAdmission(policy)
        self.owner = SpeechPreparationOrchestrator(self.tasks, self.admission)
        self.discarder = PreparedAudioDiscarder(self.runtime, self.resources)
        self.queue = PreparedSpeechQueueCoordinator(
            self.runtime,
            PreparedSpeechQueue(policy),
            self.discarder,
        )
        self.closed = False
        context.add_cleanup("speech.shared_session", self.close)

    def observe(
        self, context: RunContext, policy: SpeechRuntimeOperationalPolicy, observed_at: datetime
    ) -> None:
        if self.closed or self.context is not context or self.policy != policy:
            raise ValueError("発話の共有実行基盤の所有者または運用方針が一致しません")
        self.observed_at = max(self.observed_at, observed_at)

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.queue.shutdown()
        failed = False
        try:
            await self.tasks.shutdown()
            for candidate_id in await self.runtime.active_candidate_ids():
                try:
                    await self.discarder.discard_current(
                        candidate_id,
                        self.runtime.generation(candidate_id),
                        PreparedAudioDiscardReason.CANDIDATE_CANCELLED,
                    )
                except Exception:
                    failed = True
        finally:
            try:
                await self.runtime.shutdown()
            finally:
                await self.resources.close()
        if failed:
            raise RuntimeError("共有発話実行基盤の一部の音声を破棄できませんでした") from None
