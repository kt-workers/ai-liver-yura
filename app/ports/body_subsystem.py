from __future__ import annotations

from typing import Protocol

from app.domain.body import (
    BodyActivityContext,
    BodyExpressionRequest,
    SpeechPresentationRequest,
)


class BodySubsystemPort(Protocol):
    """脳・Activityと常時稼働する身体制御を分離する境界。"""

    async def update_activity_context(self, context: BodyActivityContext) -> None:
        """Activity中に維持する注意・姿勢・動きの方針を更新する。"""
        ...

    async def request_expression(self, request: BodyExpressionRequest) -> None:
        """驚き、拒否、喜びなど、必要時だけ高レベルな表現を要求する。"""
        ...

    async def present_speech(self, request: SpeechPresentationRequest) -> None:
        """生成済み音声を共通時計で再生し、口・身体表現と同期する。"""
        ...
