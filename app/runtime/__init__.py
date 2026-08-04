from app.runtime.action_planner import ActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy
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

# Character応答生成の既存Composition Rootは
# app.runtime.character_response_pipeline.ResponseContextBuilderを参照する。
# パッケージ初期化時に状態投影対応版へ統一し、すべての生成経路で同じ契約を使う。
from app.runtime import character_response_pipeline as _character_response_pipeline

_character_response_pipeline.ResponseContextBuilder = InternalStateAwareResponseContextBuilder

__all__ = [
    "ActionPlanner",
    "ActionScheduler",
    "ActivityManager",
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
