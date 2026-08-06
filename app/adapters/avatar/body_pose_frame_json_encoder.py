from __future__ import annotations

import json

from app.domain.body_pose_frame import BodyPoseFrame


class BodyPoseFrameJsonEncoder:
    """BodyPoseFrameをHTTP Transport用JSONへ変換する。"""

    def encode(self, frame: BodyPoseFrame, *, source_name: str) -> bytes:
        if not isinstance(frame, BodyPoseFrame):
            raise TypeError("frame must be BodyPoseFrame")
        if not isinstance(source_name, str) or not source_name.strip():
            raise ValueError("source_name must not be empty")
        payload = {
            "type": "body.pose.frame",
            "source": source_name.strip(),
            **frame.as_payload(),
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
