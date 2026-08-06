from __future__ import annotations

from typing import Protocol

from app.domain.body_pose_frame import BodyPoseFrame


class BodyPoseFrameOutputPort(Protocol):
    """連続BodyPoseFrameの出力境界。"""

    async def publish_body_pose_frame(self, frame: BodyPoseFrame) -> None: ...

    async def close(self) -> None: ...
