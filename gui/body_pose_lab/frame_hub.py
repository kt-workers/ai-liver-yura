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
    producer_instance_id: str | None = None
    producer_started_at_ms: int | None = None

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "type": "body.pose.frame",
            "source": self.source,
            "received_at_ms": self.received_at_ms,
            **self.frame.as_payload(),
        }
        if (
            self.producer_instance_id is not None
            and self.producer_started_at_ms is not None
        ):
            payload["producer_instance_id"] = self.producer_instance_id
            payload["producer_started_at_ms"] = self.producer_started_at_ms
        return payload


@dataclass(frozen=True, slots=True)
class BodyPoseLabFrameHubSnapshot:
    latest: BodyPoseLabPublishedFrame | None
    received_count: int
    stale_count: int
    inactive_producer_count: int
    subscriber_count: int
    dropped_delivery_count: int

    def as_payload(self) -> dict[str, object]:
        latest = self.latest
        return {
            "received_count": self.received_count,
            "stale_count": self.stale_count,
            "inactive_producer_count": self.inactive_producer_count,
            "subscriber_count": self.subscriber_count,
            "dropped_delivery_count": self.dropped_delivery_count,
            "latest_source": latest.source if latest is not None else None,
            "latest_sequence": latest.frame.sequence if latest is not None else None,
            "latest_received_at_ms": (
                latest.received_at_ms if latest is not None else None
            ),
            "latest_producer_instance_id": (
                latest.producer_instance_id if latest is not None else None
            ),
            "latest_producer_started_at_ms": (
                latest.producer_started_at_ms if latest is not None else None
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
        self._active_producer_by_source: dict[str, tuple[int, str] | None] = {}
        self._last_sequence_by_producer: dict[tuple[str, str], int] = {}
        self._subscribers: dict[str, Queue[BodyPoseLabPublishedFrame]] = {}
        self._received_count = 0
        self._stale_count = 0
        self._inactive_producer_count = 0
        self._dropped_delivery_count = 0

    def publish(
        self,
        frame: BodyPoseFrame,
        *,
        source: str = "unknown",
        received_at_ms: int | None = None,
        producer_instance_id: str | None = None,
        producer_started_at_ms: int | None = None,
    ) -> bool:
        if not isinstance(frame, BodyPoseFrame):
            raise TypeError("frame must be BodyPoseFrame")
        normalized_source = self._normalize_source(source)
        producer = self._normalize_producer(
            producer_instance_id,
            producer_started_at_ms,
        )
        timestamp = time_ns() // 1_000_000 if received_at_ms is None else received_at_ms
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            raise TypeError("received_at_ms must be an integer")
        if timestamp < 0:
            raise ValueError("received_at_ms must be non-negative")

        published = BodyPoseLabPublishedFrame(
            source=normalized_source,
            frame=frame,
            received_at_ms=timestamp,
            producer_instance_id=(producer[1] if producer is not None else None),
            producer_started_at_ms=(producer[0] if producer is not None else None),
        )
        with self._lock:
            has_active_producer = normalized_source in self._active_producer_by_source
            active_producer = self._active_producer_by_source.get(normalized_source)
            if producer is None:
                if has_active_producer and active_producer is not None:
                    self._inactive_producer_count += 1
                    return False
                self._active_producer_by_source.setdefault(normalized_source, None)
                producer_key = (normalized_source, "__legacy__")
            else:
                if (
                    not has_active_producer
                    or active_producer is None
                    or producer > active_producer
                ):
                    self._active_producer_by_source[normalized_source] = producer
                elif producer != active_producer:
                    self._inactive_producer_count += 1
                    return False
                producer_key = (normalized_source, producer[1])

            previous_sequence = self._last_sequence_by_producer.get(producer_key)
            if previous_sequence is not None and frame.sequence <= previous_sequence:
                self._stale_count += 1
                return False
            self._last_sequence_by_producer[producer_key] = frame.sequence
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
                inactive_producer_count=self._inactive_producer_count,
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

    @staticmethod
    def _normalize_producer(
        producer_instance_id: str | None,
        producer_started_at_ms: int | None,
    ) -> tuple[int, str] | None:
        if producer_instance_id is None and producer_started_at_ms is None:
            return None
        if producer_instance_id is None or producer_started_at_ms is None:
            raise ValueError(
                "producer_instance_id and producer_started_at_ms must be provided together"
            )
        if not isinstance(producer_instance_id, str):
            raise TypeError("producer_instance_id must be a string")
        normalized_id = producer_instance_id.strip()
        if not normalized_id or len(normalized_id) > 120:
            raise ValueError("producer_instance_id must contain 1 to 120 characters")
        if (
            isinstance(producer_started_at_ms, bool)
            or not isinstance(producer_started_at_ms, int)
        ):
            raise TypeError("producer_started_at_ms must be an integer")
        if producer_started_at_ms < 0:
            raise ValueError("producer_started_at_ms must be non-negative")
        return producer_started_at_ms, normalized_id
