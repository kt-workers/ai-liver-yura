from __future__ import annotations

import os
from dataclasses import dataclass
from typing import cast

from app.bootstrap.plugin_registration import register_optional_plugin_from_factory
from app.config.app_config import AppConfig
from app.core.plugins import PluginManager, SystemClock
from app.domain.activities import Activity, ActivityType
from app.domain.memory import AgentMemoryState
from app.domain.relationships import RelationshipMemory
from app.ports.audio_player import AudioPlayer
from app.ports.relationship_memory_store import RelationshipMemoryStore
from app.ports.response_generator import ResponseGenerator
from app.ports.speech_synthesizer import SpeechSynthesizer
from app.runtime.activity_manager import ActivityManager
from app.shared.contracts.memory import AgentMemoryStore
from app.shared.contracts.plugins.runtime import (
    PluginActivityWorkItem,
    PluginContext,
    PluginLlmRequest,
)
from app.utils.trace import TraceLogger

_RELATIONSHIP_MEMORY_PLUGIN_ID = "relationship_memory"
_RELATIONSHIP_MEMORY_CAPABILITY = "memory.relationship"
_AGENT_MEMORY_PLUGIN_ID = "agent_memory"
_AGENT_MEMORY_CAPABILITY = "memory.agent_state"


@dataclass(frozen=True, slots=True)
class RuntimePluginSetupInput:
    config: AppConfig
    activity_manager: ActivityManager
    raw_response_generator: ResponseGenerator
    raw_situation_generator: ResponseGenerator
    raw_character_generator: ResponseGenerator | None
    raw_validator_generator: ResponseGenerator | None
    raw_relationship_memory_store: RelationshipMemoryStore | None
    raw_agent_memory_store: AgentMemoryStore | None
    speech_synthesizer: SpeechSynthesizer | None
    audio_player: AudioPlayer | None


@dataclass(frozen=True, slots=True)
class RuntimePluginServices:
    plugin_manager: PluginManager
    default_response_generator: ResponseGenerator
    situation_response_generator: ResponseGenerator
    character_response_generator: ResponseGenerator | None
    validator_response_generator: ResponseGenerator | None
    initial_relationship_memory: RelationshipMemory
    initial_agent_memory: AgentMemoryState
    relationship_memory_store: RelationshipMemoryStore | None
    agent_memory_store: AgentMemoryStore | None
    speech_synthesizer: SpeechSynthesizer | None
    audio_player: AudioPlayer | None


def setup_runtime_plugins(
    setup: RuntimePluginSetupInput,
) -> RuntimePluginServices:
    config = setup.config
    plugin_manager = PluginManager()
    default_llm_plugin = _register_llm_provider(
        plugin_manager,
        plugin_id="llm_provider.default",
        role="default",
        generator=setup.raw_response_generator,
        configured_available=(
            config.response_generator.type == "dummy"
            or _is_model_provider_available(config, config.response_generator.model)
        ),
        required=True,
    )
    _register_llm_provider(
        plugin_manager,
        plugin_id="llm_provider.situation_evaluator",
        role="situation_evaluator",
        generator=setup.raw_situation_generator,
        configured_available=(
            config.response_generator.type == "dummy"
            or _is_model_provider_available(
                config,
                config.llm_roles.situation_evaluator.model,
            )
        ),
        required=True,
    )
    character_llm_plugin: ResponseGenerator | None = None
    validator_llm_plugin: ResponseGenerator | None = None
    if (
        setup.raw_character_generator is not None
        and setup.raw_validator_generator is not None
    ):
        character_llm_plugin = _register_llm_provider(
            plugin_manager,
            plugin_id="llm_provider.character",
            role="character",
            generator=setup.raw_character_generator,
            configured_available=_is_model_provider_available(
                config,
                config.llm_roles.character.model,
            ),
        )
        validator_llm_plugin = _register_llm_provider(
            plugin_manager,
            plugin_id="llm_provider.response_validator",
            role="response_validator",
            generator=setup.raw_validator_generator,
            configured_available=_is_model_provider_available(
                config,
                config.llm_roles.response_validator.model,
            ),
        )

    register_optional_plugin_from_factory(
        plugin_manager,
        plugin_id=_RELATIONSHIP_MEMORY_PLUGIN_ID,
        module="app.plugins.relationship_memory",
        enabled=config.memory.relationship_memory.enabled,
        services={
            "relationship_memory_store": setup.raw_relationship_memory_store,
        },
    )
    register_optional_plugin_from_factory(
        plugin_manager,
        plugin_id=_AGENT_MEMORY_PLUGIN_ID,
        module="app.plugins.agent_memory",
        enabled=config.memory.agent_memory.enabled,
        services={
            "agent_memory_store": setup.raw_agent_memory_store,
        },
    )
    register_optional_plugin_from_factory(
        plugin_manager,
        plugin_id="voice_output",
        module="app.plugins.voice_output",
        enabled=config.speech.enabled,
        services={
            "speech_synthesizer": setup.speech_synthesizer,
            "audio_player": setup.audio_player,
        },
    )

    plugin_manager.initialize_enabled_plugins(
        PluginContext(
            llm_gateway=_PluginLlmGateway(default_llm_plugin),
            activity_gateway=_ActivityManagerPluginGateway(setup.activity_manager),
            clock=SystemClock(),
            configuration={},
            capability_reporter=plugin_manager,
        ),
        {
            "llm_provider.default": True,
            "llm_provider.situation_evaluator": True,
            "llm_provider.character": character_llm_plugin is not None,
            "llm_provider.response_validator": validator_llm_plugin is not None,
            _RELATIONSHIP_MEMORY_PLUGIN_ID: (
                config.memory.relationship_memory.enabled
            ),
            _AGENT_MEMORY_PLUGIN_ID: config.memory.agent_memory.enabled,
            "voice_output": config.speech.enabled,
        },
    )

    default_response_generator = _require_initialized_llm_provider(
        plugin_manager,
        "llm_provider.default",
    )
    situation_response_generator = _require_initialized_llm_provider(
        plugin_manager,
        "llm_provider.situation_evaluator",
    )
    character_response_generator = _get_initialized_llm_provider(
        plugin_manager,
        "llm_provider.character",
    )
    validator_response_generator = _get_initialized_llm_provider(
        plugin_manager,
        "llm_provider.response_validator",
    )

    relationship_memory_store: RelationshipMemoryStore | None = None
    relationship_memory_plugin = plugin_manager.get_plugin(
        _RELATIONSHIP_MEMORY_PLUGIN_ID
    )
    if relationship_memory_plugin is not None and plugin_manager.is_capability_available(
        _RELATIONSHIP_MEMORY_CAPABILITY,
        _RELATIONSHIP_MEMORY_PLUGIN_ID,
    ):
        relationship_memory_store = cast(
            RelationshipMemoryStore,
            relationship_memory_plugin,
        )

    agent_memory_store: AgentMemoryStore | None = None
    agent_memory_plugin = plugin_manager.get_plugin(_AGENT_MEMORY_PLUGIN_ID)
    if agent_memory_plugin is not None and plugin_manager.is_capability_available(
        _AGENT_MEMORY_CAPABILITY,
        _AGENT_MEMORY_PLUGIN_ID,
    ):
        agent_memory_store = cast(AgentMemoryStore, agent_memory_plugin)

    initial_relationship_memory = _load_relationship_memory(
        relationship_memory_store,
        max_entries=config.memory.relationship_memory.max_entries,
    )
    if not plugin_manager.is_capability_available(
        _RELATIONSHIP_MEMORY_CAPABILITY,
        _RELATIONSHIP_MEMORY_PLUGIN_ID,
    ):
        relationship_memory_store = None

    initial_agent_memory = _load_agent_memory(
        agent_memory_store,
        max_history_entries=config.memory.agent_memory.max_history_entries,
    )
    if not plugin_manager.is_capability_available(
        _AGENT_MEMORY_CAPABILITY,
        _AGENT_MEMORY_PLUGIN_ID,
    ):
        agent_memory_store = None

    speech_synthesizer = setup.speech_synthesizer
    audio_player = setup.audio_player
    voice_output_plugin = plugin_manager.get_plugin("voice_output")
    if voice_output_plugin is not None:
        speech_synthesizer = cast(SpeechSynthesizer, voice_output_plugin)
        audio_player = cast(AudioPlayer, voice_output_plugin)

    return RuntimePluginServices(
        plugin_manager=plugin_manager,
        default_response_generator=default_response_generator,
        situation_response_generator=situation_response_generator,
        character_response_generator=character_response_generator,
        validator_response_generator=validator_response_generator,
        initial_relationship_memory=initial_relationship_memory,
        initial_agent_memory=initial_agent_memory,
        relationship_memory_store=relationship_memory_store,
        agent_memory_store=agent_memory_store,
        speech_synthesizer=speech_synthesizer,
        audio_player=audio_player,
    )


def _register_llm_provider(
    plugin_manager: PluginManager,
    *,
    plugin_id: str,
    role: str,
    generator: ResponseGenerator,
    configured_available: bool,
    required: bool = False,
) -> ResponseGenerator:
    plugin = register_optional_plugin_from_factory(
        plugin_manager,
        plugin_id=plugin_id,
        module="app.plugins.llm_provider",
        enabled=True,
        configuration={
            "role": role,
            "configured_available": configured_available,
        },
        services={
            "response_generator": generator,
        },
    )
    if plugin is None:
        if required:
            raise RuntimeError(f"必須LLM Providerを登録できませんでした: {plugin_id}")
        raise RuntimeError(f"LLM Providerを登録できませんでした: {plugin_id}")
    return cast(ResponseGenerator, plugin)


def _require_initialized_llm_provider(
    plugin_manager: PluginManager,
    plugin_id: str,
) -> ResponseGenerator:
    plugin = _get_initialized_llm_provider(plugin_manager, plugin_id)
    if plugin is None:
        status = plugin_manager.status(plugin_id)
        status_value = status.value if status is not None else "unregistered"
        raise RuntimeError(
            f"必須LLM Providerを初期化できませんでした: "
            f"{plugin_id} (status={status_value})"
        )
    return plugin


def _get_initialized_llm_provider(
    plugin_manager: PluginManager,
    plugin_id: str,
) -> ResponseGenerator | None:
    plugin = plugin_manager.get_plugin(plugin_id)
    if plugin is None:
        return None
    return cast(ResponseGenerator, plugin)


class _ActivityManagerPluginGateway:
    def __init__(self, activity_manager: ActivityManager) -> None:
        self._activity_manager = activity_manager

    def register(self, activity: Activity) -> Activity:
        return self._activity_manager.register_plugin_activity(activity)


class _PluginLlmGateway:
    """Shared Plugin要求をCore Activityへ変換するcomposition-root Adapter。"""

    def __init__(self, generator: ResponseGenerator) -> None:
        self._generator = generator

    async def generate_response(self, request: object) -> str:
        if isinstance(request, PluginActivityWorkItem):
            activity = Activity(
                activity_type=ActivityType.PLUGIN_ACTIVITY,
                goal=request.goal,
                priority=request.priority,
                context=dict(request.context),
                interruptible=request.interruptible,
                activity_id=request.work_item_id,
            )
            return await self._generator.generate_response(activity)
        if not isinstance(request, PluginLlmRequest):
            return await self._generator.generate_response(cast(Activity, request))
        activity = Activity(
            activity_type=ActivityType.BEHAVIOR_PLANNING,
            goal=request.purpose,
            context={
                **request.context,
                "plugin_prompt_override": request.prompt,
                "llm_role": request.purpose,
                "request_id": request.request_id,
            },
        )
        return await self._generator.generate_response(activity)


def _is_model_provider_available(config: AppConfig, model_key: str) -> bool:
    if config.response_generator.type == "dummy":
        return True
    model = config.models.get(model_key)
    if model is None:
        return False
    service = config.services.get(model.service)
    if service is None:
        return False
    if service.type == "openai":
        return bool(service.api_key_env and os.getenv(service.api_key_env))
    return True


def _load_relationship_memory(
    store: RelationshipMemoryStore | None,
    *,
    max_entries: int,
) -> RelationshipMemory:
    if store is None:
        return RelationshipMemory(max_entries=max_entries)
    try:
        return store.load()
    except Exception as error:
        TraceLogger().error(
            "runtime_factory:load_relationship_memory:failed",
            error_type=type(error).__name__,
        )
        return RelationshipMemory(max_entries=max_entries)


def _load_agent_memory(
    store: AgentMemoryStore | None,
    *,
    max_history_entries: int,
) -> AgentMemoryState:
    if store is None:
        return AgentMemoryState(max_history_entries=max_history_entries)
    try:
        return AgentMemoryState.from_snapshot(
            store.load(),
            max_history_entries=max_history_entries,
        )
    except Exception as error:
        TraceLogger().error(
            "runtime_factory:load_agent_memory:failed",
            error_type=type(error).__name__,
        )
        return AgentMemoryState(max_history_entries=max_history_entries)
