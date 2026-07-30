import importlib
from dataclasses import replace
from pathlib import Path

import pytest

from app.adapters.embedding.openai_embedding_generator import OpenAIEmbeddingGenerator
from app.adapters.storage.postgres_topic_memory_store import PostgresTopicMemoryStore
from app.adapters.topic.llm_topic_classifier import LlmTopicClassifier
from app.adapters.tts import SystemAudioPlayer, VoiceVoxSpeechSynthesizer
from app.bootstrap import create_runtime_coordinator
from app.bootstrap.runtime import (
    create_audio_player,
    create_embedding_generator,
    create_speech_synthesizer,
    create_topic_classifier,
    create_topic_memory_store,
)
from app.config.app_config import AppConfig, load_app_config
from app.runtime.emotion_runtime_integration import EmotionAwareRuntimeCoordinator


def _required_env_name(value: str | None) -> str:
    assert value is not None
    return value


def _openai_api_key_env(config: AppConfig) -> str:
    return _required_env_name(config.services["openai"].api_key_env)


def _database_dsn_env(config: AppConfig) -> str:
    service = config.services[config.memory.topic_memory.database_service]
    return _required_env_name(service.dsn_env)



def test_create_voicevox_speech_components() -> None:
    config = load_app_config()

    synthesizer = create_speech_synthesizer(config)
    player = create_audio_player(config)

    assert isinstance(synthesizer, VoiceVoxSpeechSynthesizer)
    assert isinstance(player, SystemAudioPlayer)


def test_trace_detail_settings_are_loaded_from_config() -> None:
    trace = load_app_config().trace

    assert trace.level == "INFO"
    assert trace.timezone == "local"
    assert trace.debug_file_enabled is True
    assert trace.debug_file_path == "logs/runtime_debug.log"
    assert trace.log_llm_prompts is True
    assert trace.log_llm_responses is True
    assert trace.log_user_input is True


def test_create_speech_components_returns_none_when_disabled() -> None:
    config = load_app_config()
    config = replace(config, speech=replace(config.speech, enabled=False))

    assert create_speech_synthesizer(config) is None
    assert create_audio_player(config) is None


def test_legacy_runtime_factory_module_reexports_bootstrap_factory() -> None:
    from app.runtime.runtime_factory import (
        create_runtime_coordinator as compatibility_factory,
    )

    assert compatibility_factory is create_runtime_coordinator


def test_create_runtime_coordinator_returns_emotion_aware_runtime() -> None:
    config = load_app_config()

    runtime = create_runtime_coordinator(config)

    assert isinstance(runtime, EmotionAwareRuntimeCoordinator)
    assert runtime.plugin_manager is not None
    assert runtime.plugin_manager.get_plugin("games") is None
    assert runtime.plugin_manager.get_plugin("voice_output") is not None
    assert runtime.plugin_manager.is_capability_available(
        "output.speech", "voice_output"
    )
    diagnostic = runtime.diagnostic_snapshot()
    plugins = diagnostic["plugins"]
    assert isinstance(plugins, dict)
    assert plugins["statuses"] == {
        "llm_provider.default": "initialized",
        "llm_provider.situation_evaluator": "initialized",
        "llm_provider.character": "initialized",
        "llm_provider.response_validator": "initialized",
        "voice_output": "initialized",
    }
    assert "output.speech" in plugins["available_capabilities"]


def test_create_runtime_coordinator_calls_plugin_setup_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
        ),
    )
    actual_setup = runtime_factory.setup_runtime_plugins
    setup_results: list[object] = []

    def setup_runtime_plugins(
        setup: runtime_factory.RuntimePluginSetupInput,
    ) -> object:
        result = actual_setup(setup)
        setup_results.append(result)
        return result

    monkeypatch.setattr(
        runtime_factory,
        "setup_runtime_plugins",
        setup_runtime_plugins,
    )

    runtime = runtime_factory.create_runtime_coordinator(config)

    assert len(setup_results) == 1
    assert runtime.plugin_manager is setup_results[0].plugin_manager  # type: ignore[attr-defined]


def test_runtime_does_not_import_games_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    original_import_module = importlib.import_module
    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
    )

    def fail_import(name: str) -> object:
        if name == "app.plugins.games":
            raise AssertionError(f"無効なGames Pluginをimportしました: {name}")
        return original_import_module(name)

    monkeypatch.setattr(
        "app.core.plugins.plugin_loader.importlib.import_module",
        fail_import,
    )

    runtime = runtime_factory.create_runtime_coordinator(config)

    assert runtime.plugin_manager is not None
    assert "games" not in {
        plugin.plugin_id for plugin in runtime.plugin_manager.list_plugins()
    }
    assert runtime.plugin_manager.get_plugin("games") is None


@pytest.mark.asyncio
async def test_shiritori_request_uses_core_conversation_without_games_plugin() -> None:
    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
        ),
    )
    runtime = create_runtime_coordinator(config)

    await runtime.submit_user_text("しりとりしよう", source="console")
    group = await runtime.run_once()

    assert runtime.plugin_manager is not None
    assert runtime.plugin_manager.get_plugin("games") is None
    assert runtime.activity_manager.ongoing_activity is None
    assert runtime.last_behavior_evaluation is not None
    assert runtime.last_behavior_evaluation.plan.activity_type == "conversation"
    assert group is not None


class _RuntimeAudioPlayer:
    async def play(self, audio_data: bytes) -> None:
        return None


@pytest.mark.asyncio
async def test_runtime_does_not_import_voice_output_when_speech_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
        ),
    )
    original_import_module = importlib.import_module

    def import_module(name: str, package: str | None = None) -> object:
        if name == "app.plugins.voice_output":
            raise AssertionError("無効なVoice Output Pluginをimportしました")
        return original_import_module(name, package)

    monkeypatch.setattr(
        "app.core.plugins.plugin_loader.importlib.import_module",
        import_module,
    )

    runtime = runtime_factory.create_runtime_coordinator(config)
    await runtime.submit_user_text("こんにちは", source="console")
    group = await runtime.run_once()

    assert runtime.plugin_manager is not None
    assert "voice_output" not in {
        plugin.plugin_id for plugin in runtime.plugin_manager.list_plugins()
    }
    assert runtime.plugin_manager.get_plugin("voice_output") is None
    assert group is not None


@pytest.mark.asyncio
async def test_runtime_initializes_voice_output_degraded_with_missing_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
        ),
    )
    monkeypatch.setattr(
        runtime_factory,
        "create_speech_synthesizer",
        lambda _: None,
    )
    monkeypatch.setattr(
        runtime_factory,
        "create_audio_player",
        lambda _: _RuntimeAudioPlayer(),
    )

    runtime = runtime_factory.create_runtime_coordinator(config)
    await runtime.submit_user_text("こんにちは", source="console")
    group = await runtime.run_once()

    assert runtime.plugin_manager is not None
    assert "voice_output" in {
        plugin.plugin_id for plugin in runtime.plugin_manager.list_plugins()
    }
    assert runtime.plugin_manager.get_plugin("voice_output") is not None
    assert not runtime.plugin_manager.is_capability_available(
        "output.speech",
        "voice_output",
    )
    assert group is not None


@pytest.mark.asyncio
async def test_runtime_does_not_import_relationship_memory_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
            relationship_memory=replace(
                config.memory.relationship_memory,
                enabled=False,
            ),
        ),
    )
    original_import_module = importlib.import_module

    def import_module(name: str, package: str | None = None) -> object:
        if name == "app.plugins.relationship_memory":
            raise AssertionError("無効なRelationship Memory Pluginをimportしました")
        return original_import_module(name, package)

    monkeypatch.setattr(
        "app.core.plugins.plugin_loader.importlib.import_module",
        import_module,
    )

    runtime = runtime_factory.create_runtime_coordinator(config)
    assert runtime.agent_state.relationship_memory.current is None
    await runtime.submit_user_text("こんにちは", source="console")
    group = await runtime.run_once()

    assert runtime.plugin_manager is not None
    assert "relationship_memory" not in {
        plugin.plugin_id for plugin in runtime.plugin_manager.list_plugins()
    }
    assert group is not None


@pytest.mark.asyncio
async def test_runtime_initializes_relationship_memory_degraded_without_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap import runtime as runtime_factory

    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
            relationship_memory=replace(
                config.memory.relationship_memory,
                enabled=True,
            ),
        ),
    )
    monkeypatch.setattr(
        runtime_factory,
        "create_relationship_memory_store",
        lambda _: None,
    )

    runtime = runtime_factory.create_runtime_coordinator(config)
    assert runtime.agent_state.relationship_memory.current is None
    await runtime.submit_user_text("こんにちは", source="console")
    group = await runtime.run_once()

    assert runtime.plugin_manager is not None
    assert "relationship_memory" in {
        plugin.plugin_id for plugin in runtime.plugin_manager.list_plugins()
    }
    assert runtime.plugin_manager.get_plugin("relationship_memory") is not None
    assert not runtime.plugin_manager.is_capability_available(
        "memory.relationship",
        "relationship_memory",
    )
    assert group is not None


@pytest.mark.asyncio
async def test_runtime_factory_persists_and_restores_relationship_memory(
    tmp_path: Path,
) -> None:
    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
            relationship_memory=replace(
                config.memory.relationship_memory,
                enabled=True,
                path=str(tmp_path / "relationships.json"),
            ),
        ),
    )
    runtime = create_runtime_coordinator(config)

    await runtime.submit_user_text("こんにちは", source="console")

    restored = create_runtime_coordinator(config)
    current = restored.agent_state.relationship_memory.current
    assert current is not None
    assert current.counterpart_id == "local:user"
    assert current.interaction_count == 1
    assert restored.plugin_manager is not None
    assert restored.plugin_manager.is_capability_available(
        "memory.relationship", "relationship_memory"
    )



def test_create_topic_classifier_returns_none_when_response_generator_is_dummy() -> (
    None
):
    config = load_app_config()
    config = replace(
        config,
        response_generator=replace(config.response_generator, type="dummy"),
    )

    topic_classifier = create_topic_classifier(config)

    assert topic_classifier is None


def test_create_topic_classifier_uses_ollama_model() -> None:
    config = load_app_config()
    config = replace(
        config,
        topic_classifier=replace(config.topic_classifier, model="ollama_chat"),
    )

    topic_classifier = create_topic_classifier(config)

    assert isinstance(topic_classifier, LlmTopicClassifier)


def test_create_topic_classifier_returns_none_when_openai_api_key_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = replace(
        config,
        topic_classifier=replace(config.topic_classifier, model="openai_chat"),
    )
    monkeypatch.delenv(_openai_api_key_env(config), raising=False)

    topic_classifier = create_topic_classifier(config)

    assert topic_classifier is None


def test_create_topic_classifier_returns_llm_topic_classifier_when_response_generator_is_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = replace(
        config,
        topic_classifier=replace(config.topic_classifier, model="openai_chat"),
    )
    monkeypatch.setenv(_openai_api_key_env(config), "test-api-key")

    topic_classifier = create_topic_classifier(config)

    assert isinstance(topic_classifier, LlmTopicClassifier)


# Helper functions for topic memory config manipulation
def _replace_topic_memory_enabled(config: AppConfig, enabled: bool) -> AppConfig:
    return replace(
        config,
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=enabled),
        ),
    )


def _replace_topic_memory_embedding_service(
    config: AppConfig, service: str
) -> AppConfig:
    model_key = config.memory.topic_memory.embedding_model
    return replace(
        config,
        models={
            **config.models,
            model_key: replace(config.models[model_key], service=service),
        },
    )


def _replace_topic_memory_database_type(
    config: AppConfig, database_type: str
) -> AppConfig:
    from app.config.service_schema import DisabledServiceSettings

    service_key = config.memory.topic_memory.database_service
    service = config.services[service_key]
    replacement = (
        service if database_type == "postgres" else DisabledServiceSettings()
    )
    return replace(
        config,
        services={
            **config.services,
            service_key: replacement,
        },
    )


def test_create_embedding_generator_returns_none_when_topic_memory_is_disabled() -> (
    None
):
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=False)

    embedding_generator = create_embedding_generator(config)

    assert embedding_generator is None


def test_create_embedding_generator_returns_none_when_embedding_type_is_unsupported() -> (
    None
):
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    config = _replace_topic_memory_embedding_service(
        config, service="topic_memory_database"
    )

    embedding_generator = create_embedding_generator(config)

    assert embedding_generator is None


def test_create_embedding_generator_returns_none_when_openai_api_key_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.delenv(_openai_api_key_env(config), raising=False)

    embedding_generator = create_embedding_generator(config)

    assert embedding_generator is None


def test_create_embedding_generator_returns_openai_embedding_generator_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.setenv(_openai_api_key_env(config), "test-api-key")

    embedding_generator = create_embedding_generator(config)

    assert isinstance(embedding_generator, OpenAIEmbeddingGenerator)


def test_create_topic_memory_store_returns_none_when_topic_memory_is_disabled() -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=False)

    topic_memory_store = create_topic_memory_store(config)

    assert topic_memory_store is None


def test_create_topic_memory_store_returns_none_when_database_type_is_unsupported() -> (
    None
):
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    config = _replace_topic_memory_database_type(config, database_type="unsupported")

    topic_memory_store = create_topic_memory_store(config)

    assert topic_memory_store is None


def test_create_topic_memory_store_returns_none_when_database_dsn_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.delenv(_database_dsn_env(config), raising=False)

    topic_memory_store = create_topic_memory_store(config)

    assert topic_memory_store is None


def test_create_topic_memory_store_returns_postgres_topic_memory_store_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    monkeypatch.setenv(
        _database_dsn_env(config),
        "postgresql://user:password@localhost:5432/ai_liver_test",
    )

    topic_memory_store = create_topic_memory_store(config)

    assert isinstance(topic_memory_store, PostgresTopicMemoryStore)


def _replace_topic_memory_summary_type(
    config: AppConfig, summary_type: str
) -> AppConfig:
    return replace(
        config,
        memory=replace(
            config.memory,
            topic_memory=replace(
                config.memory.topic_memory,
                summary=replace(
                    config.memory.topic_memory.summary,
                    type=summary_type,
                ),
            ),
        ),
    )


def test_create_memory_summary_generator_returns_none_when_openai_api_key_is_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.bootstrap.runtime import create_memory_summary_generator

    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    config = _replace_topic_memory_summary_type(config, summary_type="llm")
    monkeypatch.delenv(_openai_api_key_env(config), raising=False)

    memory_summary_generator = create_memory_summary_generator(config)

    assert memory_summary_generator is None


def test_create_memory_summary_generator_returns_llm_generator_when_response_generator_is_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.adapters.memory.llm_memory_summary_generator import (
        LlmMemorySummaryGenerator,
    )
    from app.bootstrap.runtime import create_memory_summary_generator

    config = load_app_config()
    config = _replace_topic_memory_enabled(config, enabled=True)
    config = _replace_topic_memory_summary_type(config, summary_type="llm")
    monkeypatch.setenv(_openai_api_key_env(config), "test-api-key")

    memory_summary_generator = create_memory_summary_generator(config)

    assert isinstance(memory_summary_generator, LlmMemorySummaryGenerator)
