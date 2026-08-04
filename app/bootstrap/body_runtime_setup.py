from __future__ import annotations

import os

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
    """初期化済みAvatar Outputへ接続するBody Runtimeを生成・束縛する。"""

    bind_body_subsystem(None)
    avatar_output = get_bound_avatar_output()
    enabled = _env_enabled(
        "YURA_BODY_RUNTIME_ENABLED",
        default=avatar_output is not None,
    )
    if not enabled:
        TraceLogger().info(
            "body_runtime_setup:skipped",
            reason="disabled",
        )
        return None
    if avatar_output is None:
        TraceLogger().warning(
            "body_runtime_setup:skipped",
            reason="avatar_output_unavailable",
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
    runtime = BodyRuntime(
        avatar_output,
        config=config,
        expression_planner=ConversationalBodyExpressionPlanner(),
    )
    bind_body_subsystem(runtime)
    TraceLogger().info(
        "body_runtime_setup:created",
        tick_hz=config.tick_hz,
        expression_planner="conversational_with_avatar_commands",
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
