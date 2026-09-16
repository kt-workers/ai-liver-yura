"""#348の受理済み状態を#657経由で#329へ渡すPresentation接続。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from app.composition.execution_observation import (
    SPEECH_OBSERVATION_POLICY,
    project_speech_execution_observation,
)
from app.domain.activity_execution import ActivityExecutionAuthority
from app.domain.activity_execution.observation import (
    ExecutionObservationProvenance,
    ObservedExecutionFactRecord,
)
from app.domain.speech_runtime.contracts import SpeechPresentationCommand, SpeechPresentationReport
from app.domain.speech_runtime.execution import (
    SpeechPresentationExecutionBoundary,
    SpeechPresentationExecutionSession,
)
from app.domain.speech_runtime.policy import SpeechPresentationTimeoutPolicy
from app.domain.speech_runtime.runtime import SpeechRuntime


class SpeechFactDeliveryDisposition(str, Enum):
    DELIVERED = "delivered"
    RETRY = "retry"
    TERMINAL = "terminal"
    INTEGRITY_ERROR = "integrity_error"


@dataclass
class CoreSpeechFeedback:
    """観測の意味を補作せず、同じOwner recordの再配送を抑制する。"""

    runtime: SpeechRuntime
    authority: ActivityExecutionAuthority
    presentation_id: str
    provenance: ExecutionObservationProvenance
    deliver: Callable[[ObservedExecutionFactRecord], SpeechFactDeliveryDisposition | None]
    _delivered_revision: int = 0
    disposition: SpeechFactDeliveryDisposition | None = None
    integration_error: Exception | None = field(default=None, init=False, repr=False)

    async def publish_for_presentation(self) -> None:
        """下流の失敗を明示保持し、Adapter report受理と資源回収を継続する。"""
        try:
            await self.publish()
        except Exception as error:
            # 成功へ変換せず、呼出元が検査できる局所のhard errorとして残す。
            # 直接publishする再配送入口では同じ例外を呼出元へ返す。
            self.disposition = SpeechFactDeliveryDisposition.INTEGRITY_ERROR
            self.integration_error = error

    async def publish(self) -> ObservedExecutionFactRecord | None:
        observation = await project_speech_execution_observation(
            self.runtime, self.presentation_id, self.provenance
        )
        if observation is None:
            return None
        record = self.authority.ingest_observation(
            observation,
            policy_id=SPEECH_OBSERVATION_POLICY.policy_id,
            policy_revision=SPEECH_OBSERVATION_POLICY.policy_revision,
        )
        if record.record_revision > self._delivered_revision:
            result = self.deliver(record)
            # 従来のgeneric callbackのNoneは正常配送完了を表す。
            if result is None:
                result = SpeechFactDeliveryDisposition.DELIVERED
            if not isinstance(result, SpeechFactDeliveryDisposition):
                raise TypeError("Fact配送結果の型が不正です")
            self.disposition = result
            if result in (
                SpeechFactDeliveryDisposition.DELIVERED,
                SpeechFactDeliveryDisposition.TERMINAL,
            ):
                self._delivered_revision = record.record_revision
        return record


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
