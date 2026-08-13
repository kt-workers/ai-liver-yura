from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from .contracts import CancellationRecord


@dataclass(slots=True)
class CancellationToken:
    _record: CancellationRecord | None = None
    _event: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def cancelled(self) -> bool:
        return self._record is not None

    @property
    def record(self) -> CancellationRecord | None:
        return self._record

    async def wait(self) -> CancellationRecord:
        await self._event.wait()
        assert self._record is not None
        return self._record

    def cancel(self, record: CancellationRecord) -> bool:
        if self._record is not None:
            return False
        self._record = record
        self._event.set()
        return True


class CancellationRegistry:
    def __init__(self) -> None:
        self._tokens: dict[str, CancellationToken] = {}
        self._completed: set[str] = set()

    def register(self, work_id: str) -> CancellationToken:
        if work_id in self._completed or work_id in self._tokens:
            raise ValueError(f"work is already registered or completed: {work_id}")
        token = CancellationToken()
        self._tokens[work_id] = token
        return token

    def token_for(self, work_id: str) -> CancellationToken | None:
        return self._tokens.get(work_id)

    def cancel(self, work_id: str, reason: str, requested_at: datetime) -> bool:
        token = self._tokens.get(work_id)
        if token is None:
            return False
        return token.cancel(CancellationRecord(work_id, reason, requested_at))

    def complete(self, work_id: str) -> None:
        self._tokens.pop(work_id, None)
        self._completed.add(work_id)

    def release(self, work_id: str) -> None:
        self._tokens.pop(work_id, None)

    def is_known(self, work_id: str) -> bool:
        return work_id in self._tokens or work_id in self._completed

    def active_work_ids(self) -> tuple[str, ...]:
        return tuple(self._tokens)
