from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    """業務処理が必要とする時刻と待機の契約。"""

    def now(self) -> datetime: ...

    async def sleep(self, delay_seconds: float) -> None: ...


class SystemClock:
    """実行環境のUTC時刻を供給する実装。"""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def sleep(self, delay_seconds: float) -> None:
        await asyncio.sleep(delay_seconds)


@dataclass(slots=True)
class ControlledClock:
    """試験で明示的に進める時計。"""

    current: datetime
    sleeps: list[float] = field(default_factory=list)

    def now(self) -> datetime:
        return self.current

    async def sleep(self, delay_seconds: float) -> None:
        if type(delay_seconds) not in (int, float) or delay_seconds < 0:
            raise ValueError("delay_secondsは0以上のnumberでなければなりません")
        self.sleeps.append(float(delay_seconds))
        self.current += timedelta(seconds=delay_seconds)
        await asyncio.sleep(0)

    def advance(self, seconds: float) -> None:
        if type(seconds) not in (int, float) or seconds < 0:
            raise ValueError("secondsは0以上のnumberでなければなりません")
        self.current += timedelta(seconds=seconds)
