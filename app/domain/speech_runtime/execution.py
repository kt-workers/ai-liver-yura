"""Presentation外部実行の境界。OSや具体Adapterの構成をDomainへ持ち込まない。"""

from enum import Enum
from typing import Protocol

from .contracts import SpeechPresentationCommand, SpeechPresentationReport
from .policy import SpeechPresentationTimeoutPolicy


class PresentationExecutionFailureCode(str, Enum):
    SPAWN_FAILED = "spawn_failed"
    COMMAND_ENCODE_FAILED = "command_encode_failed"
    PROTOCOL_INVALID = "protocol_invalid"
    IDENTITY_MISMATCH = "identity_mismatch"
    EXIT_BEFORE_START = "exit_before_start"
    EXIT_AFTER_START = "exit_after_start"
    TERMINAL_MISSING = "terminal_missing"
    ADAPTER_FAILED = "adapter_failed"
    CLEANUP_FAILED = "cleanup_failed"


class PresentationExecutionError(ValueError):
    def __init__(self, code: PresentationExecutionFailureCode) -> None:
        self.code = code
        super().__init__(f"Presentation実行境界で失敗しました: {code.value}")


class SpeechPresentationExecutionSession(Protocol):
    async def receive(self) -> SpeechPresentationReport: ...

    async def close(self) -> None:
        """実行・通信資源を回収する。再取消でも回収責務を放棄しない。"""
        ...


class SpeechPresentationExecutionBoundary(Protocol):
    def open(
        self, command: SpeechPresentationCommand, policy: SpeechPresentationTimeoutPolicy
    ) -> SpeechPresentationExecutionSession: ...
