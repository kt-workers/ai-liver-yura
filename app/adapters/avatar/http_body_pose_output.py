from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass

from app.adapters.avatar.body_pose_http_config import HttpBodyPoseOutputConfig
from app.adapters.avatar.body_pose_http_sender import BodyPoseHttpSender, JsonPoster
from app.adapters.avatar.latest_body_pose_frame_buffer import LatestBodyPoseFrameBuffer
from app.domain.body_pose_frame import BodyPoseFrame
from app.utils.trace import TraceLogger


@dataclass(frozen=True, slots=True)
class HttpBodyPoseOutputSnapshot:
    running: bool
    closed: bool
    pending_count: int
    sent_count: int
    dropped_count: int
    failed_count: int
    last_error: str | None


class HttpBodyPoseFrameOutput:
    """latest-frame-wins BufferとHTTP Workerを束ねるOutput Port実装。"""

    def __init__(
        self,
        config: HttpBodyPoseOutputConfig,
        *,
        sender: BodyPoseHttpSender | None = None,
        send_json: JsonPoster | None = None,
    ) -> None:
        self._buffer = LatestBodyPoseFrameBuffer()
        self._sender = sender or BodyPoseHttpSender(config, post_json=send_json)
        self._worker: asyncio.Task[None] | None = None
        self._closed = False
        self._sent_count = 0
        self._failed_count = 0
        self._last_error: str | None = None
        self._trace = TraceLogger()
        self._source_name = config.source_name

    async def publish_body_pose_frame(self, frame: BodyPoseFrame) -> None:
        if self._closed:
            return
        self._ensure_worker()
        self._buffer.offer(frame)

    async def close(self) -> None:
        self._closed = True
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker

    def snapshot(self) -> HttpBodyPoseOutputSnapshot:
        worker = self._worker
        return HttpBodyPoseOutputSnapshot(
            running=worker is not None and not worker.done(),
            closed=self._closed,
            pending_count=self._buffer.pending_count,
            sent_count=self._sent_count,
            dropped_count=self._buffer.dropped_count,
            failed_count=self._failed_count,
            last_error=self._last_error,
        )

    def _ensure_worker(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        self._worker = asyncio.create_task(
            self._run(),
            name="http-body-pose-output",
        )

    async def _run(self) -> None:
        while True:
            frame = await self._buffer.receive()
            try:
                await self._sender.send(frame)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._failed_count += 1
                self._last_error = f"{type(error).__name__}: {error}"[:240]
                self._trace.warning(
                    "body_pose_http_output_failed",
                    source=self._source_name,
                    frame_sequence=frame.sequence,
                    error_type=type(error).__name__,
                )
            else:
                self._sent_count += 1
                self._last_error = None
                self._trace.debug(
                    "body_pose_http_output_sent",
                    source=self._source_name,
                    frame_sequence=frame.sequence,
                    sent_count=self._sent_count,
                    dropped_count=self._buffer.dropped_count,
                    pose_axes={
                        "head_yaw": frame.pose.head_yaw,
                        "gaze_x": frame.pose.gaze_x,
                        "left_arm_raise": frame.pose.left_arm_raise,
                        "right_arm_raise": frame.pose.right_arm_raise,
                    },
                )
            finally:
                self._buffer.task_done()
