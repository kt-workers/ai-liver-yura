from __future__ import annotations

import os

from app.bootstrap import runtime as runtime_bootstrap
from app.bootstrap.body_output_factory import BodyOutputFactory
from app.bootstrap.body_runtime_factory import BodyRuntimeFactory
from app.bootstrap.body_runtime_settings import BodyRuntimeSettings
from app.ports.avatar_output import get_bound_avatar_output
from app.ports.body_subsystem import BodySubsystemPort, bind_body_subsystem
from app.runtime.avatar_performance_action_planner import (
    AvatarPerformanceActionPlanner,
)
from app.runtime.avatar_performance_character_service import (
    AvatarPerformanceCharacterLlmService,
)
from app.runtime.body_aware_agent_life_service import BodyAwareAgentLifeService
from app.runtime.body_emotion_bridge import get_body_emotion_state_store
from app.utils.trace import TraceLogger


def install_body_aware_runtime_components() -> None:
    """既存Composition RootへBody対応部品を起動前に登録する。"""

    setattr(runtime_bootstrap, "ActionPlanner", AvatarPerformanceActionPlanner)
    setattr(
        runtime_bootstrap,
        "CharacterLlmService",
        AvatarPerformanceCharacterLlmService,
    )
    setattr(
        runtime_bootstrap,
        "AgentLifeService",
        BodyAwareAgentLifeService,
    )


def create_bound_body_runtime_from_env() -> BodySubsystemPort | None:
    """型付き設定と利用可能PortからBody Runtimeを生成・束縛する。"""

    bind_body_subsystem(None)
    trace = TraceLogger()
    avatar_output = get_bound_avatar_output()
    has_pose_output = bool(os.getenv("YURA_BODY_POSE_OUTPUT_URL", "").strip())
    settings = BodyRuntimeSettings.from_env(
        default_enabled=avatar_output is not None or has_pose_output,
    )
    if not settings.enabled:
        trace.info("body_runtime_setup:skipped", reason="disabled")
        return None

    pose_output = BodyOutputFactory().create(settings)
    causal_store = get_body_emotion_state_store()
    runtime = BodyRuntimeFactory().create(
        settings=settings,
        avatar_output=avatar_output,
        pose_output=pose_output,
        emotion_provider=causal_store.snapshot,
        awakening_provider=causal_store.awakening_snapshot,
    )
    if runtime is None:
        trace.warning(
            "body_runtime_setup:skipped",
            reason="body_output_unavailable",
        )
        return None

    bind_body_subsystem(runtime)
    trace.info(
        "body_runtime_setup:created",
        tick_hz=settings.tick_hz,
        runtime_type=type(runtime).__name__,
        pose_output_enabled=pose_output is not None,
        avatar_output_enabled=avatar_output is not None,
    )
    return runtime


def clear_bound_body_runtime() -> None:
    """停止済みBody Runtimeのプロセス束縛を解除する。"""

    bind_body_subsystem(None)
