from __future__ import annotations

import os

from app.adapters.avatar.http_body_pose_output import (
    HttpBodyPoseFrameOutput,
    HttpBodyPoseOutputConfig,
)
from app.bootstrap import runtime as runtime_bootstrap
from app.ports.avatar_output import get_bound_avatar_output
from app.ports.body_subsystem import bind_body_subsystem
from app.runtime.avatar_body_command_action_planner import (
    AvatarBodyCommandActionPlanner,
)
from app.runtime.avatar_performance_character_service import (
    AvatarPerformanceCharacterLlmService,
)
from app.runtime.body_runtime import BodyRuntime, BodyRuntimeConfig
from app.runtime.conversational_body_expression_planner import (
    ConversationalBodyExpressionPlanner,
)
from app.runtime.core_generative_body_runtime import (
    CoreGenerativeBodyRuntime,
)
from app.runtime.living_body_runtime import LivingBodyRuntime
from app.utils.trace import TraceLogger


def install_body_aware_runtime_components() -> None:
    """既存Composition RootへBody対応Plannerを組み込む。"""

    setattr(runtime_bootstrap, "ActionPlanner", AvatarBodyCommandActionPlanner)
    setattr(
        runtime_bootstrap,
        "CharacterLlmService",
        AvatarPerformanceCharacterLlmService,
    )


def create_bound_body_runtime_from_env() -> BodyRuntime | None:
    """Core Body RuntimeをAvatar出力とPose Frame出力へ接続する。"""

    bind_body_subsystem(None)
    avatar_output = get_bound_avatar_output()
    body_pose_url = os.getenv("YURA_BODY_POSE_OUTPUT_URL", "").strip()
    body_pose_output = (
        HttpBodyPoseFrameOutput(
            HttpBodyPoseOutputConfig(
                base_url=body_pose_url,
                timeout_seconds=_env_float(
                    "YURA_BODY_POSE_OUTPUT_TIMEOUT_SECONDS",
                    default=1.0,
                ),
            )
        )
        if body_pose_url
        else None
    )
    enabled = _env_enabled(
        "YURA_BODY_RUNTIME_ENABLED",
        default=avatar_output is not None or body_pose_output is not None,
    )
    if not enabled:
        TraceLogger().info(
            "body_runtime_setup:skipped",
            reason="disabled",
        )
        return None
    if avatar_output is None and body_pose_output is None:
        TraceLogger().warning(
            "body_runtime_setup:skipped",
            reason="avatar_and_body_pose_output_unavailable",
        )
        return None

    config = BodyRuntimeConfig(
        tick_hz=_env_float("YURA_BODY_TICK_HZ", default=30.0),
        expression_queue_limit=_env_int(
            "YURA_BODY_EXPRESSION_QUEUE_LIMIT",
            default=32,
        ),
        max_expressions_per_tick=_env_int(
            "YURA_BODY_MAX_EXPRESSIONS_PER_TICK",
            default=4,
        ),
        autonomous_interval_ms=_env_int(
            "YURA_BODY_AUTONOMOUS_INTERVAL_MS",
            default=1800,
        ),
        baseline_refresh_ms=_env_int(
            "YURA_BODY_BASELINE_REFRESH_MS",
            default=30_000,
        ),
    )
    planner = ConversationalBodyExpressionPlanner()
    if body_pose_output is not None:
        runtime: BodyRuntime = CoreGenerativeBodyRuntime(
            avatar_output,
            body_pose_output=body_pose_output,
            config=config,
            expression_planner=planner,
        )
        runtime_type = "core_generative_body_pose"
    else:
        runtime = LivingBodyRuntime(
            avatar_output,
            config=config,
            expression_planner=planner,
        )
        runtime_type = "living"
    bind_body_subsystem(runtime)
    TraceLogger().info(
        "body_runtime_setup:created",
        tick_hz=config.tick_hz,
        expression_planner="conversational_with_motion_requests",
        runtime_type=runtime_type,
        body_pose_output_enabled=body_pose_output is not None,
        body_pose_output_url=(body_pose_url if body_pose_url else None),
    )
    return runtime


def clear_bound_body_runtime() -> None:
    """停止済みBody Runtimeのプロセス束縛を解除する。"""

    bind_body_subsystem(None)


def _env_enabled(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "off", "no", ""}


def _env_float(name: str, *, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be a number") from error


def _env_int(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
