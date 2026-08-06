from __future__ import annotations

import asyncio
from contextlib import suppress

from app.domain.body_pose_frame import BodyPoseFrame


class LatestBodyPoseFrameBuffer:
    """未送信Frameを1件だけ保持し、古いFrameを最新値で置換する。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[BodyPoseFrame] = asyncio.Queue(maxsize=1)
        self._dropped_count = 0

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    def offer(self, frame: BodyPoseFrame) -> bool:
        if not isinstance(frame, BodyPoseFrame):
            raise TypeError("frame must be BodyPoseFrame")
        dropped = False
        if self._queue.full():
            with suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
                self._queue.task_done()
                self._dropped_count += 1
                dropped = True
        self._queue.put_nowait(frame)
        return dropped

    async def receive(self) -> BodyPoseFrame:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()
