from __future__ import annotations

from typing import cast

import pytest

from app.bootstrap.body_runtime_factory import BodyRuntimeFactory
from app.bootstrap.body_runtime_settings import BodyRuntimeSettings
from app.domain.avatar_performance import AvatarPerformancePlan
from app.domain.body_pose_frame import BodyPoseFrame
from app.domain.emotions.emotion_state import EmotionState
from app.ports.avatar_output import AvatarGazeIntent, AvatarOutputPort
from app.ports.body_pose_output import BodyPoseFrameOutputPort
from app.runtime.body_runtime import BodyRuntime
from app.runtime.state_driven_body_pose_runtime import StateDrivenBodyPoseRuntime


class FakePoseOutput:
    def __init__(self) -> None:
        self.frames: list[BodyPoseFrame] = []
        self.closed = False

    async def publish_body_pose_frame(self, frame: BodyPoseFrame) -> None:
        self.frames.append(frame)

    async def close(self) -> None:
        self.closed = True


class FakeAvatarOutput:
    async def submit_performance(self, performance: AvatarPerformancePlan) -> None:
        del performance

    async def set_expression(self, expression: str) -> None:
        del expression

    async def play_gesture(self, gesture: str) -> None:
        del gesture

    async def set_gaze(self, gaze: AvatarGazeIntent) -> None:
        del gaze


def test_body_runtime_settings_preserve_continuous_and_compatibility_values() -> None:
    settings = BodyRuntimeSettings.from_env(
        {
            "YURA_BODY_RUNTIME_ENABLED": "true",
            "YURA_BODY_TICK_HZ": "24",
            "YURA_BODY_POSE_OUTPUT_URL": "http://127.0.0.1:8768",
            "YURA_BODY_POSE_TIMEOUT_SECONDS": "2.5",
            "YURA_BODY_POSE_SOURCE_NAME": "body-lab",
            "YURA_BODY_RANDOM_SEED": "17",
            "YURA_BODY_EXPRESSION_QUEUE_LIMIT": "48",
            "YURA_BODY_MAX_EXPRESSIONS_PER_TICK": "7",
            "YURA_BODY_AUTONOMOUS_INTERVAL_MS": "3100",
            "YURA_BODY_BASELINE_REFRESH_MS": "45000",
        }
    )

    assert settings.enabled is True
    assert settings.tick_hz == 24.0
    assert settings.pose_output_url == "http://127.0.0.1:8768"
    assert settings.pose_timeout_seconds == 2.5
    assert settings.pose_source_name == "body-lab"
    assert settings.random_seed == 17
    assert settings.expression_queue_limit == 48
    assert settings.max_expressions_per_tick == 7
    assert settings.autonomous_interval_ms == 3100
    assert settings.baseline_refresh_ms == 45_000


def test_body_runtime_settings_use_caller_default_only_when_env_is_missing() -> None:
    assert BodyRuntimeSettings.from_env({}, default_enabled=True).enabled is True
    assert (
        BodyRuntimeSettings.from_env(
            {"YURA_BODY_RUNTIME_ENABLED": "off"},
            default_enabled=True,
        ).enabled
        is False
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("expression_queue_limit", 0),
        ("max_expressions_per_tick", 33),
        ("autonomous_interval_ms", 249),
        ("baseline_refresh_ms", 120_001),
    ],
)
def test_body_runtime_settings_reject_invalid_compatibility_ranges(
    field_name: str,
    value: int,
) -> None:
    values = {field_name: value}
    with pytest.raises(ValueError):
        BodyRuntimeSettings(**values)


@pytest.mark.asyncio
async def test_factory_prefers_continuous_pose_output_and_publishes_one_frame() -> None:
    pose_output = FakePoseOutput()
    runtime = BodyRuntimeFactory().create(
        settings=BodyRuntimeSettings(enabled=True, tick_hz=24.0, random_seed=5),
        avatar_output=cast(AvatarOutputPort, FakeAvatarOutput()),
        pose_output=cast(BodyPoseFrameOutputPort, pose_output),
        emotion_provider=EmotionState,
    )

    assert isinstance(runtime, StateDrivenBodyPoseRuntime)
    frame = await runtime.tick_once()
    assert pose_output.frames == [frame]
    snapshot = await runtime.snapshot()
    assert snapshot.tick_count == 1
    assert snapshot.last_performance_id == f"body-frame-{frame.sequence}"



def test_factory_preserves_compatibility_runtime_settings() -> None:
    settings = BodyRuntimeSettings(
        enabled=True,
        tick_hz=20.0,
        expression_queue_limit=45,
        max_expressions_per_tick=6,
        autonomous_interval_ms=4200,
        baseline_refresh_ms=55_000,
    )
    runtime = BodyRuntimeFactory().create(
        settings=settings,
        avatar_output=cast(AvatarOutputPort, FakeAvatarOutput()),
        pose_output=None,
        emotion_provider=EmotionState,
    )

    assert isinstance(runtime, BodyRuntime)
    assert runtime._config.tick_hz == 20.0
    assert runtime._config.expression_queue_limit == 45
    assert runtime._config.max_expressions_per_tick == 6
    assert runtime._config.autonomous_interval_ms == 4200
    assert runtime._config.baseline_refresh_ms == 55_000


def test_factory_returns_none_when_disabled_or_no_output_exists() -> None:
    factory = BodyRuntimeFactory()
    assert (
        factory.create(
            settings=BodyRuntimeSettings(enabled=False),
            avatar_output=cast(AvatarOutputPort, FakeAvatarOutput()),
            pose_output=None,
            emotion_provider=EmotionState,
        )
        is None
    )
    assert (
        factory.create(
            settings=BodyRuntimeSettings(enabled=True),
            avatar_output=None,
            pose_output=None,
            emotion_provider=EmotionState,
        )
        is None
    )
