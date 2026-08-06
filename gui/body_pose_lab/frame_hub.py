from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import RLock
from time import time_ns
from uuid import uuid4

from app.domain.body_pose_frame import BodyPoseFrame

_MAX_SUBSCRIBERS = 32


@dataclass(frozen=True, slots=True)
class BodyPoseLabPublishedFrame:
    """Frame本体と、Lab受信時に付与する有限診断情報。"""

    source: str
    frame: BodyPoseFrame
    received_at_ms: int

    def as_payload(self) -> dict[str, object]:
        return {
            "type": "body.pose.frame",
            "source": self.source,
            "received_at_ms": self.received_at_ms,
            **self.frame.as_payload(),
        }


@dataclass(frozen=True, slots=True)
class BodyPoseLabFrameHubSnapshot:
    latest: BodyPoseLabPublishedFrame | None
    received_count: int
    stale_count: int
    subscriber_count: int
    dropped_delivery_count: int

    def as_payload(self) -> dict[str, object]:
        latest = self.latest
        return {
            "received_count": self.received_count,
            "stale_count": self.stale_count,
            "subscriber_count": self.subscriber_count,
            "dropped_delivery_count": self.dropped_delivery_count,
            "latest_source": latest.source if latest is not None else None,
            "latest_sequence": latest.frame.sequence if latest is not None else None,
            "latest_received_at_ms": (
                latest.received_at_ms if latest is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class BodyPoseLabSubscription:
    subscription_id: str
    queue: Queue[BodyPoseLabPublishedFrame]


class BodyPoseLabFrameHub:
    """最新FrameとSSE subscriberを管理するthread-safeなHub。"""

    def __init__(self, *, maximum_subscribers: int = _MAX_SUBSCRIBERS) -> None:
        if isinstance(maximum_subscribers, bool) or not isinstance(
            maximum_subscribers, int
        ):
            raise TypeError("maximum_subscribers must be an integer")
        if not 1 <= maximum_subscribers <= 256:
            raise ValueError("maximum_subscribers must be between 1 and 256")
        self._maximum_subscribers = maximum_subscribers
        self._lock = RLock()
        self._latest: BodyPoseLabPublishedFrame | None = None
        self._last_sequence_by_source: dict[str, int] = {}
        self._subscribers: dict[str, Queue[BodyPoseLabPublishedFrame]] = {}
        self._received_count = 0
        self._stale_count = 0
        self._dropped_delivery_count = 0

    def publish(
        self,
        frame: BodyPoseFrame,
        *,
        source: str = "unknown",
        received_at_ms: int | None = None,
    ) -> bool:
        if not isinstance(frame, BodyPoseFrame):
            raise TypeError("frame must be BodyPoseFrame")
        normalized_source = self._normalize_source(source)
        timestamp = time_ns() // 1_000_000 if received_at_ms is None else received_at_ms
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            raise TypeError("received_at_ms must be an integer")
        if timestamp < 0:
            raise ValueError("received_at_ms must be non-negative")

        published = BodyPoseLabPublishedFrame(
            source=normalized_source,
            frame=frame,
            received_at_ms=timestamp,
        )
        with self._lock:
            previous_sequence = self._last_sequence_by_source.get(normalized_source)
            if previous_sequence is not None and frame.sequence <= previous_sequence:
                self._stale_count += 1
                return False
            self._last_sequence_by_source[normalized_source] = frame.sequence
            self._latest = published
            self._received_count += 1
            subscribers = tuple(self._subscribers.values())

        dropped = 0
        for subscriber in subscribers:
            if subscriber.full():
                try:
                    subscriber.get_nowait()
                except Empty:
                    pass
                else:
                    subscriber.task_done()
                    dropped += 1
            try:
                subscriber.put_nowait(published)
            except Full:
                dropped += 1
        if dropped:
            with self._lock:
                self._dropped_delivery_count += dropped
        return True

    def subscribe(self) -> BodyPoseLabSubscription:
        with self._lock:
            if len(self._subscribers) >= self._maximum_subscribers:
                raise RuntimeError("body pose lab subscriber limit reached")
            subscription_id = str(uuid4())
            channel: Queue[BodyPoseLabPublishedFrame] = Queue(maxsize=1)
            self._subscribers[subscription_id] = channel
            latest = self._latest
        if latest is not None:
            channel.put_nowait(latest)
        return BodyPoseLabSubscription(subscription_id, channel)

    def unsubscribe(self, subscription_id: str) -> None:
        with self._lock:
            self._subscribers.pop(subscription_id, None)

    def latest(self) -> BodyPoseLabPublishedFrame | None:
        with self._lock:
            return self._latest

    def snapshot(self) -> BodyPoseLabFrameHubSnapshot:
        with self._lock:
            return BodyPoseLabFrameHubSnapshot(
                latest=self._latest,
                received_count=self._received_count,
                stale_count=self._stale_count,
                subscriber_count=len(self._subscribers),
                dropped_delivery_count=self._dropped_delivery_count,
            )

    @staticmethod
    def _normalize_source(source: str) -> str:
        if not isinstance(source, str):
            raise TypeError("source must be a string")
        normalized = source.strip()
        if not normalized or len(normalized) > 80:
            raise ValueError("source must contain 1 to 80 characters")
        return normalized
