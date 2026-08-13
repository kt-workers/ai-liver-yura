from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol


class RuntimeClock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, delay_seconds: float) -> None: ...


class SystemRuntimeClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    async def sleep(self, delay_seconds: float) -> None:
        await asyncio.sleep(delay_seconds)


@dataclass(slots=True)
class FakeRuntimeClock:
    current: datetime
    sleeps: list[float] = field(default_factory=list)

    def now(self) -> datetime:
        return self.current

    async def sleep(self, delay_seconds: float) -> None:
        if type(delay_seconds) not in (int, float) or delay_seconds < 0:
            raise ValueError("delay_seconds must be a non-negative number")
        self.sleeps.append(delay_seconds)
        self.current += timedelta(seconds=delay_seconds)
        await asyncio.sleep(0)

    def advance(self, seconds: float) -> None:
        if type(seconds) not in (int, float) or seconds < 0:
            raise ValueError("seconds must be a non-negative number")
        self.current += timedelta(seconds=seconds)
