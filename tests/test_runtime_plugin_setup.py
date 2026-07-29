from __future__ import annotations

import ast
import importlib
from dataclasses import replace
from pathlib import Path

import pytest

from app.bootstrap import runtime_plugin_setup
from app.bootstrap.runtime_plugin_setup import (
    RuntimePluginServices,
    RuntimePluginSetupInput,
    setup_runtime_plugins,
)
from app.config.app_config import AppConfig, load_app_config
from app.core.plugins import PluginManager
from app.domain.activities import Activity, ActivityType
from app.domain.relationships import RelationshipMemory
from app.runtime.activity_manager import ActivityManager
from app.shared.contracts.memory import AgentMemorySnapshot
from app.shared.contracts.plugins.runtime import PluginContext


class _ResponseGenerator:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[Activity] = []

    async def generate_response(self, activity: Activity) -> str:
        self.requests.append(activity)
        if self.error is not None:
            raise self.error
        return "response"


class _RelationshipMemoryStore:
    def __init__(self, *, fail_load: bool = False) -> None:
        self.memory = RelationshipMemory()
        self.fail_load = fail_load

    def load(self) -> RelationshipMemory:
        if self.fail_load:
            raise OSError("relationship store offline")
        return self.memory

    def save(self, memory: RelationshipMemory) -> None:
        self.memory = memory


class _AgentMemoryStore:
    def __init__(self, *, fail_load: bool = False) -> None:
        self.snapshot = AgentMemorySnapshot()
        self.fail_load = fail_load

    def load(self) -> AgentMemorySnapshot:
        if self.fail_load:
            raise OSError("agent store offline")
        return self.snapshot

    def save(self, snapshot: AgentMemorySnapshot) -> None:
        self.snapshot = snapshot


class _SpeechSynthesizer:
    async def synthesize(
        self,
        text: str,
        voice_intent: object | None = None,
    ) -> bytes:
        return text.encode()


class _AudioPlayer:
    async def play(self, audio_data: bytes) -> None:
        return None


def _config(
    *,
    games: bool = False,
    relationship_memory: bool = False,
    agent_memory: bool = False,
    speech: bool = False,
) -> AppConfig:
    config = load_app_config()
    return replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=speech),
        plugins=replace(
            config.plugins,
            games=replace(config.plugins.games, enabled=games),
        ),
        memory=replace(
            config.memory,
            relationship_memory=replace(
                config.memory.relationship_memory,
                enabled=relationship_memory,
            ),
            agent_memory=replace(
                config.memory.agent_memory,
                enabled=agent_memory,
            ),
        ),
    )


def _setup_input(
    config: AppConfig,
    *,
    default_generator: _ResponseGenerator | None = None,
    situation_generator: _ResponseGenerator | None = None,
    character_generator: _ResponseGenerator | None = None,
    validator_generator: _ResponseGenerator | None = None,
    relationship_memory_store: _RelationshipMemoryStore | None = None,
    agent_memory_store: _AgentMemoryStore | None = None,
    speech_synthesizer: _SpeechSynthesizer | None = None,
    audio_player: _AudioPlayer | None = None,
) -> RuntimePluginSetupInput:
    return RuntimePluginSetupInput(
        config=config,
        activity_manager=ActivityManager(),
        raw_response_generator=default_generator or _ResponseGenerator(),
        raw_situation_generator=situation_generator or _ResponseGenerator(),
        raw_character_generator=character_generator,
        raw_validator_generator=validator_generator,
        raw_relationship_memory_store=relationship_memory_store,
        raw_agent_memory_store=agent_memory_store,
        speech_synthesizer=speech_synthesizer,
        audio_player=audio_player,
    )


def test_disabled_optional_plugins_are_not_imported_or_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import_module = importlib.import_module
    forbidden = {
        "app.plugins.agent_memory",
        "app.plugins.games",
        "app.plugins.relationship_memory",
        "app.plugins.voice_output",
    }

    def import_module(name: str, package: str | None = None) -> object:
        if name in forbidden:
            raise AssertionError(f"無効Pluginをimportしました: {name}")
        return original_import_module(name, package)

    monkeypatch.setattr(
        "app.core.plugins.plugin_loader.importlib.import_module",
        import_module,
    )

    services = setup_runtime_plugins(_setup_input(_config()))
    registered_ids = {
        plugin.plugin_id for plugin in services.plugin_manager.list_plugins()
    }

    assert registered_ids == {
        "llm_provider.default",
        "llm_provider.situation_evaluator",
    }
    assert services.relationship_memory_store is None
    assert services.agent_memory_store is None
    assert services.initial_agent_memory.episodic == ()
    assert services.speech_synthesizer is None
    assert services.audio_player is None


def test_enabled_plugins_receive_configuration_services_and_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(
        games=True,
        relationship_memory=True,
        agent_memory=True,
        speech=True,
    )
    relationship_store = _RelationshipMemoryStore()
    agent_store = _AgentMemoryStore()
    synthesizer = _SpeechSynthesizer()
    player = _AudioPlayer()
    character_generator = _ResponseGenerator()
    validator_generator = _ResponseGenerator()
    register_calls: list[dict[str, object]] = []
    initialized: dict[str, bool] = {}
    contexts: list[PluginContext] = []
    actual_register = runtime_plugin_setup.register_optional_plugin_from_factory
    actual_initialize = PluginManager.initialize_enabled_plugins

    def register_optional_plugin_from_factory(
        manager: PluginManager,
        **kwargs: object,
    ) -> object:
        register_calls.append(kwargs)
        return actual_register(manager, **kwargs)  # type: ignore[arg-type]

    def initialize_enabled_plugins(
        manager: PluginManager,
        context: PluginContext,
        enabled: dict[str, bool],
    ) -> None:
        contexts.append(context)
        initialized.update(enabled)
        actual_initialize(manager, context, enabled)

    monkeypatch.setattr(
        runtime_plugin_setup,
        "register_optional_plugin_from_factory",
        register_optional_plugin_from_factory,
    )
    monkeypatch.setattr(
        PluginManager,
        "initialize_enabled_plugins",
        initialize_enabled_plugins,
    )

    setup = _setup_input(
        config,
        character_generator=character_generator,
        validator_generator=validator_generator,
        relationship_memory_store=relationship_store,
        agent_memory_store=agent_store,
        speech_synthesizer=synthesizer,
        audio_player=player,
    )
    services = setup_runtime_plugins(setup)

    assert register_calls == [
        {
            "plugin_id": "llm_provider.default",
            "module": "app.plugins.llm_provider",
            "enabled": True,
            "configuration": {
                "role": "default",
                "configured_available": True,
            },
            "services": {"response_generator": setup.raw_response_generator},
        },
        {
            "plugin_id": "llm_provider.situation_evaluator",
            "module": "app.plugins.llm_provider",
            "enabled": True,
            "configuration": {
                "role": "situation_evaluator",
                "configured_available": True,
            },
            "services": {"response_generator": setup.raw_situation_generator},
        },
        {
            "plugin_id": "llm_provider.character",
            "module": "app.plugins.llm_provider",
            "enabled": True,
            "configuration": {
                "role": "character",
                "configured_available": runtime_plugin_setup._is_model_provider_available(
                    config,
                    config.llm_roles.character.model,
                ),
            },
            "services": {"response_generator": character_generator},
        },
        {
            "plugin_id": "llm_provider.response_validator",
            "module": "app.plugins.llm_provider",
            "enabled": True,
            "configuration": {
                "role": "response_validator",
                "configured_available": runtime_plugin_setup._is_model_provider_available(
                    config,
                    config.llm_roles.response_validator.model,
                ),
            },
            "services": {"response_generator": validator_generator},
        },
        {
            "plugin_id": "games",
            "module": "app.plugins.games",
            "enabled": True,
            "configuration": {"settings": config.plugins.games},
        },
        {
            "plugin_id": "relationship_memory",
            "module": "app.plugins.relationship_memory",
            "enabled": True,
            "services": {"relationship_memory_store": relationship_store},
        },
        {
            "plugin_id": "agent_memory",
            "module": "app.plugins.agent_memory",
            "enabled": True,
            "services": {"agent_memory_store": agent_store},
        },
        {
            "plugin_id": "voice_output",
            "module": "app.plugins.voice_output",
            "enabled": True,
            "services": {
                "speech_synthesizer": synthesizer,
                "audio_player": player,
            },
        },
    ]
    assert initialized == {
        "llm_provider.default": True,
        "llm_provider.situation_evaluator": True,
        "llm_provider.character": True,
        "llm_provider.response_validator": True,
        "games": True,
        "relationship_memory": True,
        "agent_memory": True,
        "voice_output": True,
    }
    assert contexts[0].configuration["llm_available"] is True
    assert vars(contexts[0].llm_gateway)["_generator"] is (
        services.default_response_generator
    )
    assert services.default_response_generator is services.plugin_manager.get_plugin(
        "llm_provider.default"
    )
    assert services.situation_response_generator is (
        services.plugin_manager.get_plugin("llm_provider.situation_evaluator")
    )
    assert services.character_response_generator is services.plugin_manager.get_plugin(
        "llm_provider.character"
    )
    assert services.validator_response_generator is services.plugin_manager.get_plugin(
        "llm_provider.response_validator"
    )
    assert services.initial_relationship_memory is relationship_store.memory
    assert services.initial_agent_memory.max_history_entries == (
        config.memory.agent_memory.max_history_entries
    )
    assert services.relationship_memory_store is not None
    assert services.agent_memory_store is not None
    assert services.speech_synthesizer is not synthesizer
    assert services.audio_player is services.speech_synthesizer
    assert services.plugin_manager.is_capability_available(
        "memory.relationship",
        "relationship_memory",
    )
    assert services.plugin_manager.is_capability_available(
        "memory.agent_state",
        "agent_memory",
    )
    assert services.plugin_manager.is_capability_available(
        "output.speech",
        "voice_output",
    )


def test_missing_store_and_voice_providers_initialize_degraded() -> None:
    services = setup_runtime_plugins(
        _setup_input(
            _config(relationship_memory=True, agent_memory=True, speech=True),
        )
    )

    assert services.plugin_manager.get_plugin("relationship_memory") is not None
    assert services.plugin_manager.get_plugin("agent_memory") is not None
    assert services.plugin_manager.get_plugin("voice_output") is not None
    assert not services.plugin_manager.is_capability_available(
        "memory.relationship",
        "relationship_memory",
    )
    assert not services.plugin_manager.is_capability_available(
        "memory.agent_state",
        "agent_memory",
    )
    assert not services.plugin_manager.is_capability_available(
        "output.speech",
        "voice_output",
    )
    assert services.relationship_memory_store is None
    assert services.agent_memory_store is None
    assert services.initial_relationship_memory.current is None
    assert services.initial_agent_memory.episodic == ()
    assert services.speech_synthesizer is not None
    assert services.audio_player is services.speech_synthesizer


def test_memory_load_failures_revoke_capabilities_and_return_no_store() -> None:
    services = setup_runtime_plugins(
        _setup_input(
            _config(relationship_memory=True, agent_memory=True),
            relationship_memory_store=_RelationshipMemoryStore(fail_load=True),
            agent_memory_store=_AgentMemoryStore(fail_load=True),
        )
    )

    assert services.relationship_memory_store is None
    assert services.agent_memory_store is None
    assert services.initial_relationship_memory.current is None
    assert services.initial_agent_memory.episodic == ()
    assert not services.plugin_manager.is_capability_available(
        "memory.relationship",
        "relationship_memory",
    )
    assert not services.plugin_manager.is_capability_available(
        "memory.agent_state",
        "agent_memory",
    )


@pytest.mark.parametrize(
    ("character_generator", "validator_generator"),
    [
        (_ResponseGenerator(), None),
        (None, _ResponseGenerator()),
    ],
)
def test_incomplete_llm_role_pair_is_not_registered(
    monkeypatch: pytest.MonkeyPatch,
    character_generator: _ResponseGenerator | None,
    validator_generator: _ResponseGenerator | None,
) -> None:
    registered_ids: list[str] = []
    actual_register = runtime_plugin_setup.register_optional_plugin_from_factory

    def register_optional_plugin_from_factory(
        manager: PluginManager,
        **kwargs: object,
    ) -> object:
        registered_ids.append(str(kwargs["plugin_id"]))
        return actual_register(manager, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        runtime_plugin_setup,
        "register_optional_plugin_from_factory",
        register_optional_plugin_from_factory,
    )

    services = setup_runtime_plugins(
        _setup_input(
            _config(),
            character_generator=character_generator,
            validator_generator=validator_generator,
        )
    )

    assert services.plugin_manager.get_plugin("llm_provider.default") is not None
    assert (
        services.plugin_manager.get_plugin("llm_provider.situation_evaluator")
        is not None
    )
    assert services.plugin_manager.get_plugin("llm_provider.character") is None
    assert services.plugin_manager.get_plugin("llm_provider.response_validator") is None
    assert services.character_response_generator is None
    assert services.validator_response_generator is None
    assert "llm_provider.character" not in registered_ids
    assert "llm_provider.response_validator" not in registered_ids


@pytest.mark.parametrize(
    "missing_plugin_id",
    [
        "llm_provider.default",
        "llm_provider.situation_evaluator",
    ],
)
def test_required_llm_provider_missing_registration_fails_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    missing_plugin_id: str,
) -> None:
    actual_register = runtime_plugin_setup.register_optional_plugin_from_factory

    def register_optional_plugin_from_factory(
        manager: PluginManager,
        **kwargs: object,
    ) -> object:
        if kwargs["plugin_id"] == missing_plugin_id:
            return None
        return actual_register(manager, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        runtime_plugin_setup,
        "register_optional_plugin_from_factory",
        register_optional_plugin_from_factory,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            "必須LLM Providerを登録できませんでした: "
            + missing_plugin_id.replace(".", r"\.")
        ),
    ):
        setup_runtime_plugins(_setup_input(_config()))


def test_required_llm_provider_unregistered_after_load_fails_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_register = runtime_plugin_setup.register_optional_plugin_from_factory

    def register_optional_plugin_from_factory(
        manager: PluginManager,
        **kwargs: object,
    ) -> object:
        if kwargs["plugin_id"] == "llm_provider.default":
            return _ResponseGenerator()
        return actual_register(manager, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        runtime_plugin_setup,
        "register_optional_plugin_from_factory",
        register_optional_plugin_from_factory,
    )

    with pytest.raises(
        RuntimeError,
        match=(
            r"必須LLM Providerを初期化できませんでした: "
            r"llm_provider\.default \(status=unregistered\)"
        ),
    ):
        setup_runtime_plugins(_setup_input(_config()))


@pytest.mark.asyncio
async def test_configured_unavailable_provider_is_initialized_without_capability() -> (
    None
):
    config = _config()
    config = replace(
        config,
        response_generator=replace(
            config.response_generator,
            type="openai",
            model="missing-model",
        ),
    )

    services = setup_runtime_plugins(_setup_input(config))

    assert services.plugin_manager.status("llm_provider.default") is not None
    assert services.plugin_manager.get_plugin("llm_provider.default") is (
        services.default_response_generator
    )
    assert not services.plugin_manager.is_capability_available(
        "llm.provider.default",
        "llm_provider.default",
    )
    with pytest.raises(RuntimeError, match=r"llm_provider\.default\.unavailable"):
        await services.default_response_generator.generate_response(
            Activity(
                activity_type=ActivityType.CONVERSATION_WITH_USER,
                goal="test",
            ),
        )


@pytest.mark.asyncio
async def test_provider_failure_revokes_generic_and_role_capabilities() -> None:
    generator = _ResponseGenerator(error=OSError("provider offline"))
    services = setup_runtime_plugins(
        _setup_input(
            _config(),
            default_generator=generator,
        )
    )

    with pytest.raises(OSError, match="provider offline"):
        await services.default_response_generator.generate_response(
            Activity(
                activity_type=ActivityType.CONVERSATION_WITH_USER,
                goal="test",
            ),
        )

    assert not services.plugin_manager.is_capability_available(
        "llm.provider",
        "llm_provider.default",
    )
    assert not services.plugin_manager.is_capability_available(
        "llm.provider.default",
        "llm_provider.default",
    )


def test_runtime_plugin_setup_has_no_static_llm_provider_import() -> None:
    path = Path(runtime_plugin_setup.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "app.plugins.llm_provider" not in imports


def test_setup_result_exposes_only_shared_contract_types() -> None:
    annotations = RuntimePluginServices.__annotations__

    assert all(
        "app.plugins" not in str(annotation) for annotation in annotations.values()
    )
