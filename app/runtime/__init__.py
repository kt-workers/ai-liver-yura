from app.runtime.action_planner import ActionPlanner as CoreActionPlanner
from app.runtime.action_scheduler import ActionScheduler
from app.runtime.activity_manager import ActivityManager
from app.runtime.agent_life_service import AgentLifeService
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_activity_policy import AutonomousActivityPolicy
from app.runtime.avatar_performance_action_planner import AvatarPerformanceActionPlanner
from app.runtime.body_runtime import BodyRuntime, BodyRuntimeConfig
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
# パッケージ初期化時にSemantic検証済みContextへ統一し、Semantic Plan対象は
# v2 Structured Realizer + relative CharacterSemanticVerifierを使用する。
# v2対象外は各compatibility serviceが既存経路へ委譲する。
from app.runtime import character_response_pipeline as _character_response_pipeline
from app.runtime import response_claim_validator as _response_claim_validator
from app.runtime.avatar_performance_character_service import (
    AvatarPerformanceCharacterLlmService,
)
from app.runtime.character_language_realizer_service import (
    CharacterLanguageRealizerService,
)
from app.runtime.character_language_realizer_v2_service import (
    CharacterLanguageRealizerV2Service,
)
from app.runtime.character_realization_validator_schema_retry import (
    CharacterRealizationValidator,
)
from app.runtime.character_semantic_verifier_validator import (
    CharacterSemanticVerifierValidator,
)
from app.runtime.response_validation_composition import (
    DeterministicResponseValidator,
)
from app.runtime.semantic_validated_response_context import (
    SemanticValidatedResponseContextBuilder,
)

_character_response_pipeline.ResponseContextBuilder = SemanticValidatedResponseContextBuilder
_character_response_pipeline.CharacterLlmService = CharacterLanguageRealizerV2Service
_character_response_pipeline.ResponseValidator = CharacterSemanticVerifierValidator

# 既存公開名は維持しながら、質問・話題展開Budgetと実行事実検証を
# 独立責務へ分離した決定論的Validatorへ統一する。
_response_claim_validator.DeterministicFactValidator = DeterministicResponseValidator
_character_response_pipeline.DeterministicFactValidator = DeterministicResponseValidator

__all__ = [
    "ActionPlanner",
    "ActionScheduler",
    "ActivityManager",
    "AvatarPerformanceActionPlanner",
    "AvatarPerformanceCharacterLlmService",
    "CharacterLanguageRealizerService",
    "CharacterLanguageRealizerV2Service",
    "CharacterRealizationValidator",
    "CharacterSemanticVerifierValidator",
    "BodyRuntime",
    "BodyRuntimeConfig",
    "CoreActionPlanner",
    "DefaultEventFilter",
    "DefaultEventPrioritizer",
    "DeterministicResponseValidator",
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
    "SemanticValidatedResponseContextBuilder",
]
