from app.runtime.action_planner import ActionPlanner as CoreActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy
from app.runtime.avatar_performance_action_planner import AvatarPerformanceActionPlanner
from app.runtime.event_buffer import EventBuffer
from app.runtime.event_bus import EventBus
from app.runtime.event_filter import DefaultEventFilter, EventFilter
from app.runtime.event_prioritizer import DefaultEventPrioritizer, EventPrioritizer
from app.runtime.event_queue import EventQueue
from app.runtime.input_receiver import EventPublisher, InputReceiver
from app.runtime.internal_state_response_context import (
    InternalStateAwareResponseContextBuilder,
)
from app.runtime.runtime_coordinator import RuntimeCoordinator

# Composition Rootがapp.runtime.action_plannerを直接importする既存経路でも、
# 会話・字幕・音声計画を維持したAvatar Performance拡張版へ統一する。
from app.runtime import action_planner as _action_planner

_action_planner.ActionPlanner = AvatarPerformanceActionPlanner
ActionPlanner = AvatarPerformanceActionPlanner

# Character応答生成の既存Composition Rootは
# app.runtime.character_response_pipelineの具象クラスを直接参照する。
# パッケージ初期化時に状態投影版とAvatar演技Intent対応版へ統一する。
from app.runtime import character_response_pipeline as _character_response_pipeline
from app.runtime.avatar_performance_character_service import (
    AvatarPerformanceCharacterLlmService,
)

_character_response_pipeline.ResponseContextBuilder = InternalStateAwareResponseContextBuilder
_character_response_pipeline.CharacterLlmService = AvatarPerformanceCharacterLlmService

__all__ = [
    "ActionPlanner",
    "ActionScheduler",
    "ActivityManager",
    "AvatarPerformanceActionPlanner",
    "AvatarPerformanceCharacterLlmService",
    "CoreActionPlanner",
    "DefaultEventFilter",
    "DefaultEventPrioritizer",
    "EventBuffer",
    "EventBus",
    "EventFilter",
    "EventPrioritizer",
    "EventPublisher",
    "EventQueue",
    "InputReceiver",
    "RuntimeCoordinator",
    "AgentState",
    "AgentLifeService",
    "AutonomousActivityPolicy",
    "InternalStateAwareResponseContextBuilder",
]
