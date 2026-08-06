from __future__ import annotations

from app.adapters.avatar.body_pose_http_config import HttpBodyPoseOutputConfig
from app.adapters.avatar.http_body_pose_output import HttpBodyPoseFrameOutput
from app.bootstrap.body_runtime_settings import BodyRuntimeSettings
from app.ports.body_pose_output import BodyPoseFrameOutputPort


class BodyOutputFactory:
    """Transport設定からBodyPoseFrame Output Portを生成する。"""

    def create(
        self,
        settings: BodyRuntimeSettings,
    ) -> BodyPoseFrameOutputPort | None:
        if not isinstance(settings, BodyRuntimeSettings):
            raise TypeError("settings must be BodyRuntimeSettings")
        if settings.pose_output_url is None:
            return None
        return HttpBodyPoseFrameOutput(
            HttpBodyPoseOutputConfig(
                base_url=settings.pose_output_url,
                timeout_seconds=settings.pose_timeout_seconds,
                source_name=settings.pose_source_name,
            )
        )
