"""実行カーネルが利用する時計の公開契約。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class RuntimeClock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, delay_seconds: float) -> None: ...
