from __future__ import annotations

import json

from app.domain.body_pose_frame import BodyPoseFrame


class BodyPoseFrameJsonEncoder:
    """BodyPoseFrameをHTTP Transport用JSONへ変換する。"""

    def encode(
        self,
        frame: BodyPoseFrame,
        *,
        source_name: str,
        producer_instance_id: str | None = None,
        producer_started_at_ms: int | None = None,
    ) -> bytes:
        if not isinstance(frame, BodyPoseFrame):
            raise TypeError("frame must be BodyPoseFrame")
        if not isinstance(source_name, str) or not source_name.strip():
            raise ValueError("source_name must not be empty")
        if producer_instance_id is not None and (
            not isinstance(producer_instance_id, str)
            or not producer_instance_id.strip()
        ):
            raise ValueError("producer_instance_id must not be empty")
        if producer_started_at_ms is not None and (
            isinstance(producer_started_at_ms, bool)
            or not isinstance(producer_started_at_ms, int)
            or producer_started_at_ms < 0
        ):
            raise ValueError("producer_started_at_ms must be a non-negative integer")
        if (producer_instance_id is None) != (producer_started_at_ms is None):
            raise ValueError(
                "producer_instance_id and producer_started_at_ms must be provided together"
            )

        payload: dict[str, object] = {
            "type": "body.pose.frame",
            "source": source_name.strip(),
            **frame.as_payload(),
        }
        if producer_instance_id is not None and producer_started_at_ms is not None:
            payload["producer_instance_id"] = producer_instance_id.strip()
            payload["producer_started_at_ms"] = producer_started_at_ms
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
