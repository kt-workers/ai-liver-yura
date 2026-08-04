from __future__ import annotations

from threading import RLock
from typing import Protocol

from app.domain.body import (
    BodyActivityContext,
    BodyExpressionRequest,
    SpeechPresentationRequest,
)
from app.domain.body_runtime import BodyRuntimeSnapshot

__all__ = [
    "BodySubsystemPort",
    "bind_body_subsystem",
    "get_bound_body_subsystem",
]


class BodySubsystemPort(Protocol):
    """脳・Activityと常時稼働する身体制御を分離する境界。"""

    async def start(self) -> None:
        """常駐する身体制御Loopを開始する。"""
        ...

    async def stop(self) -> None:
        """身体制御Loopを安全に停止する。"""
        ...

    async def update_activity_context(self, context: BodyActivityContext) -> None:
        """Activity中に維持する注意・姿勢・動きの方針を更新する。"""
        ...

    async def request_expression(self, request: BodyExpressionRequest) -> None:
        """驚き、拒否、喜びなど、必要時だけ高レベルな表現を要求する。"""
        ...

    async def present_speech(self, request: SpeechPresentationRequest) -> None:
        """生成済み音声を共通時計で再生し、口・身体表現と同期する。"""
        ...

    async def snapshot(self) -> BodyRuntimeSnapshot:
        """本文や音声データを含まない診断状態を返す。"""
        ...


_binding_lock = RLock()
_bound_body_subsystem: BodySubsystemPort | None = None


def bind_body_subsystem(body: BodySubsystemPort | None) -> None:
    """Composition Rootが構築したBody Subsystemを実行経路へ束縛する。

    通常起動時の依存配線を一箇所へ集めるための移行境界。Runtime再構成時は
    Noneを渡し、以前の参照を必ず解除する。
    """

    global _bound_body_subsystem
    with _binding_lock:
        _bound_body_subsystem = body


def get_bound_body_subsystem() -> BodySubsystemPort | None:
    """現在のComposition Rootが束縛しているBody Subsystemを返す。"""

    with _binding_lock:
        return _bound_body_subsystem
