"""本体の起動・停止が必要とする接続口。具体的な構成・保存実装を参照しない。"""

from __future__ import annotations

from typing import Protocol

from app.domain.contracts.lifecycle import ApplicationShutdownPolicy


class AsyncClosePort(Protocol):
    """所有者が公開する非同期の終了操作。"""

    async def close(self) -> None: ...


class BrainLifecyclePort(Protocol):
    """既存の脳実行基盤の開始・終了だけを扱う。"""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class AutonomyStartPort(Protocol):
    """既存の自律活動の開始操作。"""

    def start(self) -> None: ...


class CognitionLifecyclePort(Protocol):
    """認知の配送所有者が公開する終了対象を読む。"""

    @property
    def autonomy(self) -> AutonomyStartPort | None: ...

    @property
    def speech(self) -> AsyncClosePort | None: ...

    @property
    def reflection(self) -> AsyncClosePort | None: ...


class ShutdownConfigurationPort(Protocol):
    """設定の読込み方法によらず、既存の停止方針だけを読む。"""

    @property
    def shutdown_policy(self) -> ApplicationShutdownPolicy: ...


class CoreLifecycleComponents(Protocol):
    """構成済みの所有者を借用する。起動処理で再生成・差替えしない。"""

    @property
    def config(self) -> ShutdownConfigurationPort: ...

    @property
    def brain(self) -> BrainLifecyclePort: ...

    @property
    def cognition(self) -> CognitionLifecyclePort | None: ...

    @property
    def memory(self) -> AsyncClosePort | None: ...

    @property
    def memory_is_borrowed(self) -> bool: ...

    @property
    def lifecycle(self) -> AsyncClosePort: ...
