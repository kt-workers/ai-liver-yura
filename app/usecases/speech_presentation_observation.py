"""Owner観測を伴うSpeech Presentation Session境界。"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.speech_runtime.contracts import SpeechPresentationCommand, SpeechPresentationReport
from app.domain.speech_runtime.execution import (
    SpeechPresentationExecutionBoundary,
    SpeechPresentationExecutionSession,
)
from app.domain.speech_runtime.policy import SpeechPresentationTimeoutPolicy
from app.usecases.speech_feedback import CoreSpeechFeedback


@dataclass
class _ObservedSession:
    session: SpeechPresentationExecutionSession
    feedback: CoreSpeechFeedback

    async def receive(self) -> SpeechPresentationReport:
        # 次report要求時には、前reportのOwner受理が済んでいる。
        # STARTEDを終端より前に受理させ、raw report自体をFactとして渡さない。
        await self.feedback.publish_for_presentation()
        return await self.session.receive()

    async def close(self) -> None:
        await self.session.close()
        # 回収失敗を還流側の失敗で隠さず、回収後のOwner確定状態だけを渡す。
        await self.feedback.publish_for_presentation()


@dataclass
class ObservedSpeechPresentationBoundary:
    """既存実行Sessionを包むだけで、同一process Adapterへfallbackしない。"""

    boundary: SpeechPresentationExecutionBoundary
    feedback: CoreSpeechFeedback

    def open(
        self, command: SpeechPresentationCommand, policy: SpeechPresentationTimeoutPolicy
    ) -> SpeechPresentationExecutionSession:
        if command.presentation_id != self.feedback.presentation_id:
            raise ValueError("提示と還流先のidentityが一致しません")
        return _ObservedSession(self.boundary.open(command, policy), self.feedback)

