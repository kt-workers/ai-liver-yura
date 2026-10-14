"""意味処理が参照する作業入力。具体スケジューラの実行状態を公開しない。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.domain.brain_integration import BrainIntegrationModule, BrainWorkEnvelope


class BrainModuleWork(Protocol):
    """既存の実行基盤から受け取る、読取り専用の入力契約。"""

    @property
    def module(self) -> BrainIntegrationModule: ...

    @property
    def envelope(self) -> BrainWorkEnvelope: ...

    @property
    def payload(self) -> object: ...
