from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.domain.body_activity_context import (
    BodyActivityContext,
    BodyPostureTendency,
)
from app.domain.emotions.emotion_state import EmotionState
from app.runtime.body_expression_input_builder import BodyExpressionInputBuilder
from app.runtime.state_driven_body_controller import StateDrivenBodyController
from gui.body_pose_lab.api_controller import BodyPoseLabApiController
from gui.body_pose_lab.application import BodyPoseLabApplicationService
from gui.body_pose_lab.config import BodyPoseLabConfig
from gui.body_pose_lab.frame_hub import BodyPoseLabFrameHub
from gui.body_pose_lab.http_server import BodyPoseLabHttpServer
from gui.body_pose_lab.sse_stream import BodyPoseLabSseStream
from gui.body_pose_lab.static_files import BodyPoseLabStaticFiles
from gui.body_pose_lab.tick_loop import BodyPoseLabTickLoop


@dataclass(slots=True)
class BodyPoseLabComponents:
    config: BodyPoseLabConfig
    frame_hub: BodyPoseLabFrameHub
    application: BodyPoseLabApplicationService
    tick_loop: BodyPoseLabTickLoop
    api: BodyPoseLabApiController
    sse: BodyPoseLabSseStream
    static_files: BodyPoseLabStaticFiles
    http_server: BodyPoseLabHttpServer

    def run(self) -> None:
        if self.config.local_simulation:
            self.tick_loop.start()
        try:
            self.http_server.serve_forever()
        finally:
            self.tick_loop.stop()
            self.http_server.close()

    def stop(self) -> None:
        self.tick_loop.stop()
        self.http_server.shutdown()


class BodyPoseLabComposition:
    """Body Pose Labの依存生成と起動順だけを組み立てる。"""

    @staticmethod
    def create(
        config: BodyPoseLabConfig | None = None,
        *,
        web_root: Path | None = None,
    ) -> BodyPoseLabComponents:
        settings = config or BodyPoseLabConfig.from_env()
        emotion = EmotionState()
        context = BodyActivityContext(
            source_activity_id="body-pose-lab",
            attention_target="conversation_partner",
            engagement=0.55,
            posture_tendency=BodyPostureTendency.NEUTRAL,
            movement_energy=0.32,
            gaze_freedom=0.72,
        )
        input_builder = BodyExpressionInputBuilder()
        initial_input = input_builder.build(emotion=emotion, context=context)
        controller = StateDrivenBodyController(
            initial_input,
            tick_hz=settings.tick_hz,
            seed=settings.random_seed,
        )
        frame_hub = BodyPoseLabFrameHub(
            maximum_subscribers=settings.maximum_subscribers
        )
        application = BodyPoseLabApplicationService(
            controller=controller,
            frame_hub=frame_hub,
            initial_emotion=emotion,
            initial_context=context,
            input_builder=input_builder,
        )
        tick_loop = BodyPoseLabTickLoop(application)
        api = BodyPoseLabApiController(
            application=application,
            frame_hub=frame_hub,
            tick_loop=tick_loop,
        )
        sse = BodyPoseLabSseStream(frame_hub)
        static_files = BodyPoseLabStaticFiles(
            web_root or BodyPoseLabConfig.default_web_root()
        )
        http_server = BodyPoseLabHttpServer(
            host=settings.host,
            port=settings.port,
            api=api,
            sse=sse,
            static_files=static_files,
            maximum_json_bytes=settings.maximum_json_bytes,
        )
        return BodyPoseLabComponents(
            config=settings,
            frame_hub=frame_hub,
            application=application,
            tick_loop=tick_loop,
            api=api,
            sse=sse,
            static_files=static_files,
            http_server=http_server,
        )
