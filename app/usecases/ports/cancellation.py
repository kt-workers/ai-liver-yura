"""実行処理が参照する取消状態。取消要求の所有者には依存しない。"""

from typing import Protocol


class CancellationState(Protocol):
    """既存の取消所有者が公開する読取り専用の状態。"""

    @property
    def cancelled(self) -> bool:
        ...
