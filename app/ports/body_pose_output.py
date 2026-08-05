from __future__ import annotations

from typing import Protocol

from app.domain.body_pose_frame import BodyPoseFrame


class BodyPoseFrameOutputPort(Protocol):
    """連続トラッキングフレームをAvatar Runtimeへ送る境界。"""

    async def publish_body_pose_frame(self, frame: BodyPoseFrame) -> None:
        """最新フレームを送信する。

        実装は古い未送信フレームを破棄できる。Body制御をネットワーク待ちで
        停止させないことを前提とする。
        """
        ...
