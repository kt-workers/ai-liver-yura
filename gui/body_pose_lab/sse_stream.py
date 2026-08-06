from __future__ import annotations

import json
from collections.abc import Iterator
from queue import Empty

from gui.body_pose_lab.frame_hub import (
    BodyPoseLabFrameHub,
    BodyPoseLabSubscription,
)


class BodyPoseLabSseStream:
    """Frame Hub subscriptionをSSE Eventへ変換する。"""

    def __init__(
        self,
        frame_hub: BodyPoseLabFrameHub,
        *,
        keep_alive_seconds: float = 12.0,
    ) -> None:
        if keep_alive_seconds <= 0.0:
            raise ValueError("keep_alive_seconds must be greater than zero")
        self._frame_hub = frame_hub
        self._keep_alive_seconds = float(keep_alive_seconds)

    def open(self) -> BodyPoseLabSubscription:
        return self._frame_hub.subscribe()

    def close(self, subscription: BodyPoseLabSubscription) -> None:
        self._frame_hub.unsubscribe(subscription.subscription_id)

    def events(
        self,
        subscription: BodyPoseLabSubscription,
    ) -> Iterator[bytes]:
        while True:
            try:
                published = subscription.queue.get(
                    timeout=self._keep_alive_seconds
                )
            except Empty:
                yield b": keep-alive\n\n"
                continue
            try:
                data = json.dumps(
                    published.as_payload(),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"event: body-pose-frame\ndata: {data}\n\n".encode("utf-8")
            finally:
                subscription.queue.task_done()
