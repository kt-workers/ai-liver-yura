from __future__ import annotations

from typing import Protocol


class BodyPoseFrameEnvelope(Protocol):
    """通常Pose FrameとGenerative Motion Frameに共通する出力契約。"""

    def as_payload(self) -> dict[str, object]:
        ...


class BodyPoseFrameOutputPort(Protocol):
    """Coreが生成した連続Pose FrameをAvatar Runtimeへ送る境界。"""

    async def publish_body_pose_frame(
        self,
        frame: BodyPoseFrameEnvelope,
    ) -> None:
        """最新フレームを送信する。

        実装は古い未送信フレームを破棄できる。Body制御をネットワーク待ちで
        停止させないことを前提とする。
        """
        ...
