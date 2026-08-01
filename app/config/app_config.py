from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config.config_loader import (
    LEGACY_CONFIG_PATH,
    ConfigSourceBundle,
    load_config_bundle,
    load_raw_config,
)
from app.config.emotion_appraisal_config import load_emotion_appraisal_settings
from app.config.errors import ConfigError
from app.config.service_schema import (
    DisabledServiceSettings,
    OllamaServiceSettings,
    OpenAiServiceSettings,
    PostgresServiceSettings,
    ServiceSettings,
    VoiceVoxServiceSettings,
)
from app.config.strict import (
    immutable_mapping,
    optional_bool,
    optional_int,
    optional_mapping,
    optional_number,
    optional_string,
    reject_unknown_keys,
    require_bool,
    require_int,
    require_mapping,
    require_number,
    require_string,
    require_string_sequence,
)
from app.domain.emotions import EmotionAppraisalSettings

CONFIG_PATH = LEGACY_CONFIG_PATH

__all__ = [
    "AppConfig",
    "CONFIG_PATH",
    "ConfigSourceBundle",
    "ServiceSettings",
    "load_app_config",
    "load_config_bundle",
    "load_raw_config",
]


@dataclass(frozen=True, slots=True)
class AppSettings:
    name: str
    mode: str


@dataclass(frozen=True, slots=True)
class TraceSettings:
    level: str
    format: str
    file_path: str
    max_bytes: int
    backup_count: int
    timezone: str = "local"
    debug_file_enabled: bool = False
    debug_file_path: str = "logs/runtime_debug.log"
    log_llm_prompts: bool = False
    log_llm_responses: bool = False
    log_user_input: bool = False


@dataclass(frozen=True, slots=True)
class ModelSettings:
    service: str
    name: str
    dimension: int | None = None


@dataclass(frozen=True, slots=True)
class ResponseGeneratorSettings:
    type: str
    model: str
    fallback_response: str


@dataclass(frozen=True, slots=True)
class LlmRoleSettings:
    model: str
    temperature: float
    timeout_seconds: float
    fallback_response: str


@dataclass(frozen=True, slots=True)
class LlmRolesSettings:
    situation_evaluator: LlmRoleSettings
    character: LlmRoleSettings
    response_validator: LlmRoleSettings


@dataclass(frozen=True, slots=True)
class SpeechPlayerSettings:
    type: str
    command: str | None


@dataclass(frozen=True, slots=True)
class SpeechVoiceProfileSettings:
    speed_scale: float
    pitch_scale: float
    intonation_scale: float
    volume_scale: float


@dataclass(frozen=True, slots=True)
class SpeechSettings:
    enabled: bool
    service: str
    pronunciation_dictionary_path: str
    speaker_id: int
    default_profile: str
    voice_intent_profiles: Mapping[str, SpeechVoiceProfileSettings]
    player: SpeechPlayerSettings


@dataclass(frozen=True, slots=True)
class TopicClassifierSettings:
    model: str


# TopicMemory/Memory settings dataclasses
@dataclass(frozen=True, slots=True)
class TopicMemorySummarySettings:
    type: str
    model: str
    fallback_max_length: int


@dataclass(frozen=True, slots=True)
class TopicMemorySettings:
    enabled: bool
    database_service: str
    embedding_model: str
    summary: TopicMemorySummarySettings
    duplicate_threshold: float = 0.95
    max_entries: int | None = None
    retention_days: int | None = None


@dataclass(frozen=True, slots=True)
class RelationshipMemorySettings:
    enabled: bool = False
    path: str = "data/relationship_memory.json"
    max_entries: int = 1000


@dataclass(frozen=True, slots=True)
class AgentMemorySettings:
    enabled: bool = False
    path: str = "data/agent_memory.json"
    max_history_entries: int = 64


@dataclass(frozen=True, slots=True)
class MemorySettings:
    topic_memory: TopicMemorySettings
    relationship_memory: RelationshipMemorySettings = field(
        default_factory=RelationshipMemorySettings
    )
    agent_memory: AgentMemorySettings = field(default_factory=AgentMemorySettings)


@dataclass(frozen=True, slots=True)
class CharacterSettings:
    name: str
    name_reading: str
    personality: str
    speaking_style: str
    streaming_style: str
    likes: tuple[str, ...] = ()
    dislikes: tuple[str, ...] = ()
    behavior_policy: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConsoleInputReceiverSettings:
    enabled: bool


@dataclass(frozen=True, slots=True)
class TimerInputReceiverSettings:
    enabled: bool
    interval_seconds: float
    max_events: int | None


@dataclass(frozen=True, slots=True)
class InputReceiverSettings:
    console: ConsoleInputReceiverSettings
    timer: TimerInputReceiverSettings


@dataclass(frozen=True, slots=True)
class ConfirmationSettings:
    timeout_seconds: float
    max_attempts: int


@dataclass(frozen=True, slots=True)
class PluginRegistrationSettings:
    enabled: bool = True
    config_reference: str | None = None


@dataclass(frozen=True, slots=True)
class PluginSettings:
    registrations: Mapping[str, PluginRegistrationSettings] = field(
        default_factory=lambda: immutable_mapping({})
    )
    opaque_configs: Mapping[str, Mapping[str, Any]] = field(
        default_factory=lambda: immutable_mapping({})
    )


@dataclass(frozen=True, slots=True)
class AppConfig:
    app: AppSettings
    trace: TraceSettings
    services: Mapping[str, ServiceSettings]
    models: Mapping[str, ModelSettings]
    response_generator: ResponseGeneratorSettings
    llm_roles: LlmRolesSettings
    speech: SpeechSettings
    topic_classifier: TopicClassifierSettings
    memory: MemorySettings
    character: CharacterSettings
    input_receivers: InputReceiverSettings
    confirmation: ConfirmationSettings
    plugins: PluginSettings = field(default_factory=PluginSettings)
    emotion_appraisal: EmotionAppraisalSettings = field(
        default_factory=EmotionAppraisalSettings
    )
    config_path: str = ""


def load_app_config(config_path: str | Path | None = None) -> AppConfig:
    bundle = load_config_bundle(config_path)
    raw_config = dict(bundle.values)
    try:
        reject_unknown_keys(
            raw_config,
            {
                "app",
                "trace",
                "services",
                "models",
                "response_generator",
                "llm_roles",
                "speech",
                "topic_classifier",
                "memory",
                "character",
                "input_receivers",
                "confirmation",
                "plugins",
                "emotion_appraisal",
            },
            "",
        )
        config = AppConfig(
            app=_load_app_settings(_require_dict(raw_config, "app")),
            trace=_load_trace_settings(_require_dict(raw_config, "trace")),
            services=immutable_mapping(
                _load_services(_require_dict(raw_config, "services"))
            ),
            models=immutable_mapping(_load_models(_require_dict(raw_config, "models"))),
            response_generator=_load_response_generator_settings(
                _require_dict(raw_config, "response_generator")
            ),
            llm_roles=_load_llm_roles_settings(_require_dict(raw_config, "llm_roles")),
            speech=_load_speech_settings(_require_dict(raw_config, "speech")),
            topic_classifier=_load_topic_classifier_settings(
                _require_dict(raw_config, "topic_classifier")
            ),
            memory=_load_memory_settings(_require_dict(raw_config, "memory")),
            character=_load_character_settings(_require_dict(raw_config, "character")),
            input_receivers=_load_input_receiver_settings(
                _require_dict(raw_config, "input_receivers")
            ),
            confirmation=_load_confirmation_settings(
                _require_dict(raw_config, "confirmation")
            ),
            plugins=_load_plugin_settings(raw_config.get("plugins")),
            emotion_appraisal=load_emotion_appraisal_settings(
                raw_config.get("emotion_appraisal")
            ),
            config_path=str(bundle.root_path),
        )
        _validate_reference_graph(config)
        return config
    except ConfigError as error:
        if error.source_file is not None:
            raise
        raise error.with_source(str(bundle.source_for(error.path))) from error


def _load_plugin_settings(value: object) -> PluginSettings:
    if value is None:
        return PluginSettings()
    config = require_mapping(value, "plugins")
    registrations = optional_mapping(config, "registry", "plugins")
    parsed_registrations: dict[str, PluginRegistrationSettings] = {}
    for plugin_id, raw in registrations.items():
        plugin_path = f"plugins.registry.{plugin_id}"
        registration = require_mapping(raw, plugin_path)
        reject_unknown_keys(registration, {"enabled", "config_reference"}, plugin_path)
        parsed_registrations[plugin_id] = PluginRegistrationSettings(
            enabled=optional_bool(
                registration, "enabled", plugin_path, default=True
            ),
            config_reference=optional_string(
                registration, "config_reference", plugin_path
            ),
        )
    if parsed_registrations:
        warnings.warn(
            "plugins.registry は将来の動的Plugin登録用に予約されており、"
            "現在の実行経路では使用されません。",
            FutureWarning,
            stacklevel=2,
        )
    opaque_configs: dict[str, Mapping[str, Any]] = {}
    for plugin_id, raw in config.items():
        if plugin_id == "registry":
            continue
        opaque_configs[plugin_id] = immutable_mapping(
            require_mapping(raw, f"plugins.{plugin_id}")
        )
    return PluginSettings(
        registrations=immutable_mapping(parsed_registrations),
        opaque_configs=immutable_mapping(opaque_configs),
    )


def _load_confirmation_settings(config: dict[str, Any]) -> ConfirmationSettings:
    reject_unknown_keys(config, {"timeout_seconds", "max_attempts"}, "confirmation")
    return ConfirmationSettings(
        timeout_seconds=_positive_number_setting(
            config, "timeout_seconds", "confirmation"
        ),
        max_attempts=_positive_int_setting(config, "max_attempts", "confirmation"),
    )


def _load_app_settings(config: dict[str, Any]) -> AppSettings:
    reject_unknown_keys(config, {"name", "mode"}, "app")
    mode = require_string(config, "mode", "app")
    _require_enum(mode, {"console", "streaming_demo"}, "app.mode")
    return AppSettings(
        name=require_string(config, "name", "app"),
        mode=mode,
    )


def _load_trace_settings(config: dict[str, Any]) -> TraceSettings:
    reject_unknown_keys(
        config,
        {
            "level",
            "format",
            "file_path",
            "max_bytes",
            "backup_count",
            "timezone",
            "debug_file_enabled",
            "debug_file_path",
            "log_llm_prompts",
            "log_llm_responses",
            "log_user_input",
        },
        "trace",
    )
    level = require_string(config, "level", "trace").upper()
    _require_enum(level, {"DEBUG", "INFO", "WARNING", "ERROR", "OFF"}, "trace.level")
    output_format = require_string(config, "format", "trace").lower()
    _require_enum(output_format, {"text", "jsonl"}, "trace.format")
    timezone_name = optional_string(config, "timezone", "trace") or "local"
    timezone_name = timezone_name.lower()
    _require_enum(timezone_name, {"local"}, "trace.timezone")
    debug_file_path = optional_string(config, "debug_file_path", "trace")
    return TraceSettings(
        level=level,
        format=output_format,
        file_path=require_string(config, "file_path", "trace"),
        max_bytes=_positive_int_setting(config, "max_bytes", "trace"),
        backup_count=_non_negative_int_setting(config, "backup_count", "trace"),
        timezone=timezone_name,
        debug_file_enabled=optional_bool(
            config, "debug_file_enabled", "trace", default=False
        ),
        debug_file_path=debug_file_path or "logs/runtime_debug.log",
        log_llm_prompts=optional_bool(
            config, "log_llm_prompts", "trace", default=False
        ),
        log_llm_responses=optional_bool(
            config, "log_llm_responses", "trace", default=False
        ),
        log_user_input=optional_bool(
            config, "log_user_input", "trace", default=False
        ),
    )


def _load_response_generator_settings(
    config: dict[str, Any],
) -> ResponseGeneratorSettings:
    reject_unknown_keys(config, {"type", "model", "fallback_response"}, "response_generator")
    generator_type = require_string(config, "type", "response_generator")
    _require_enum(generator_type, {"llm", "dummy"}, "response_generator.type")
    return ResponseGeneratorSettings(
        type=generator_type,
        model=require_string(config, "model", "response_generator"),
        fallback_response=require_string(
            config, "fallback_response", "response_generator"
        ),
    )


def _load_llm_roles_settings(config: dict[str, Any]) -> LlmRolesSettings:
    reject_unknown_keys(
        config,
        {"situation_evaluator", "character", "response_validator"},
        "llm_roles",
    )
    return LlmRolesSettings(
        situation_evaluator=_load_llm_role_settings(
            _require_dict(
                config,
                "situation_evaluator",
                error_path="llm_roles.situation_evaluator",
            ),
            "situation_evaluator",
        ),
        character=_load_llm_role_settings(
            _require_dict(config, "character", error_path="llm_roles.character"),
            "character",
        ),
        response_validator=_load_llm_role_settings(
            _require_dict(
                config,
                "response_validator",
                error_path="llm_roles.response_validator",
            ),
            "response_validator",
        ),
    )


def _load_llm_role_settings(config: dict[str, Any], role: str) -> LlmRoleSettings:
    path = f"llm_roles.{role}"
    reject_unknown_keys(
        config, {"model", "temperature", "timeout_seconds", "fallback_response"}, path
    )
    temperature = require_number(config, "temperature", path)
    if not 0.0 <= temperature <= 2.0:
        raise ConfigError(
            path=f"{path}.temperature",
            expected="number between 0.0 and 2.0",
            actual="out of range",
        )
    timeout = _positive_number_setting(config, "timeout_seconds", path)
    return LlmRoleSettings(
        model=require_string(config, "model", path),
        temperature=temperature,
        timeout_seconds=timeout,
        fallback_response=require_string(config, "fallback_response", path),
    )


def _load_speech_settings(config: dict[str, Any]) -> SpeechSettings:
    reject_unknown_keys(
        config,
        {
            "enabled",
            "service",
            "pronunciation_dictionary_path",
            "speaker_id",
            "default_profile",
            "voice_intent_profiles",
            "player",
        },
        "speech",
    )
    player = _require_dict(config, "player", error_path="speech.player")
    voice_intent_profiles_config = _require_dict(
        config,
        "voice_intent_profiles",
        error_path="speech.voice_intent_profiles",
    )
    voice_intent_profiles = {
        name: _load_speech_voice_profile(profile, name)
        for name, profile in voice_intent_profiles_config.items()
        if isinstance(profile, dict)
    }
    if len(voice_intent_profiles) != len(voice_intent_profiles_config):
        raise RuntimeError(
            "speech.voice_intent_profilesの各値はobject形式で指定してください。"
        )
    default_profile = require_string(config, "default_profile", "speech")
    if default_profile not in voice_intent_profiles:
        raise ConfigError(
            path="speech.default_profile",
            expected="name present in speech.voice_intent_profiles",
            actual="unknown profile",
        )
    reject_unknown_keys(player, {"type", "command"}, "speech.player")
    player_type = require_string(player, "type", "speech.player")
    _require_enum(player_type, {"system"}, "speech.player.type")
    speaker_id = require_int(config, "speaker_id", "speech")
    _require_non_negative(speaker_id, "speech.speaker_id")
    return SpeechSettings(
        enabled=require_bool(config, "enabled", "speech"),
        service=require_string(config, "service", "speech"),
        pronunciation_dictionary_path=require_string(
            config, "pronunciation_dictionary_path", "speech"
        ),
        speaker_id=speaker_id,
        default_profile=default_profile,
        voice_intent_profiles=immutable_mapping(voice_intent_profiles),
        player=SpeechPlayerSettings(
            type=player_type,
            command=optional_string(player, "command", "speech.player"),
        ),
    )


def _load_speech_voice_profile(
    config: dict[str, Any], name: str
) -> SpeechVoiceProfileSettings:
    path = f"speech.voice_intent_profiles.{name}"
    reject_unknown_keys(
        config,
        {"speed_scale", "pitch_scale", "intonation_scale", "volume_scale"},
        path,
    )
    speed_scale = _positive_number_setting(config, "speed_scale", path)
    pitch_scale = require_number(config, "pitch_scale", path)
    intonation_scale = _positive_number_setting(config, "intonation_scale", path)
    volume_scale = _positive_number_setting(config, "volume_scale", path)
    return SpeechVoiceProfileSettings(
        speed_scale=speed_scale,
        pitch_scale=pitch_scale,
        intonation_scale=intonation_scale,
        volume_scale=volume_scale,
    )


def _load_services(config: dict[str, Any]) -> dict[str, ServiceSettings]:
    services: dict[str, ServiceSettings] = {}
    for key, value in config.items():
        path = f"services.{key}"
        service_config = require_mapping(value, path)
        service_type = require_string(service_config, "type", path)
        services[key] = _load_service(key, service_type, service_config)
    return services


def _load_service(
    service_name: str,
    service_type: str,
    config: dict[str, Any],
) -> ServiceSettings:
    path = f"services.{service_name}"
    if service_type == "openai":
        reject_unknown_keys(
            config, {"type", "base_url", "api_key_env", "timeout_seconds"}, path
        )
        return OpenAiServiceSettings(
            base_url=require_string(config, "base_url", path),
            api_key_env=require_string(config, "api_key_env", path),
            timeout_seconds=_positive_number_setting(config, "timeout_seconds", path),
        )
    if service_type == "ollama":
        reject_unknown_keys(config, {"type", "base_url", "timeout_seconds"}, path)
        return OllamaServiceSettings(
            base_url=require_string(config, "base_url", path),
            timeout_seconds=_positive_number_setting(config, "timeout_seconds", path),
        )
    if service_type == "voicevox":
        reject_unknown_keys(config, {"type", "base_url", "timeout_seconds"}, path)
        return VoiceVoxServiceSettings(
            base_url=require_string(config, "base_url", path),
            timeout_seconds=_positive_number_setting(config, "timeout_seconds", path),
        )
    if service_type == "postgres":
        reject_unknown_keys(config, {"type", "dsn_env"}, path)
        return PostgresServiceSettings(dsn_env=require_string(config, "dsn_env", path))
    if service_type == "disabled":
        reject_unknown_keys(config, {"type"}, path)
        return DisabledServiceSettings()
    raise ConfigError(
        path=f"{path}.type",
        expected=(
            "openai, ollama, voicevox, postgres, or disabled"
        ),
        actual="unknown service type",
    )


def _load_models(config: dict[str, Any]) -> dict[str, ModelSettings]:
    models: dict[str, ModelSettings] = {}
    for key, value in config.items():
        path = f"models.{key}"
        model_config = require_mapping(value, path)
        reject_unknown_keys(model_config, {"service", "name", "dimension"}, path)
        dimension = optional_int(model_config, "dimension", path)
        if dimension is not None:
            _require_positive(dimension, f"{path}.dimension")
        models[key] = ModelSettings(
            service=require_string(model_config, "service", path),
            name=require_string(model_config, "name", path),
            dimension=dimension,
        )
    return models


def _load_topic_classifier_settings(config: dict[str, Any]) -> TopicClassifierSettings:
    reject_unknown_keys(config, {"model"}, "topic_classifier")
    return TopicClassifierSettings(
        model=require_string(config, "model", "topic_classifier")
    )


# Memory settings loader functions
def _load_memory_settings(config: dict[str, Any]) -> MemorySettings:
    reject_unknown_keys(
        config, {"relationship_memory", "agent_memory", "topic_memory"}, "memory"
    )
    relationship_config = optional_mapping(config, "relationship_memory", "memory")
    reject_unknown_keys(
        relationship_config, {"enabled", "path", "max_entries"}, "memory.relationship_memory"
    )
    max_entries = _optional_positive_int(
        relationship_config, "max_entries", "memory.relationship_memory", 1000
    )
    agent_config = optional_mapping(config, "agent_memory", "memory")
    reject_unknown_keys(
        agent_config, {"enabled", "path", "max_history_entries"}, "memory.agent_memory"
    )
    max_history = _optional_positive_int(
        agent_config, "max_history_entries", "memory.agent_memory", 64
    )
    return MemorySettings(
        topic_memory=_load_topic_memory_settings(
            _require_dict(
                config,
                "topic_memory",
                error_path="memory.topic_memory",
            )
        ),
        relationship_memory=RelationshipMemorySettings(
            enabled=optional_bool(
                relationship_config,
                "enabled",
                "memory.relationship_memory",
                default=False,
            ),
            path=(
                optional_string(
                    relationship_config, "path", "memory.relationship_memory"
                )
                or "data/relationship_memory.json"
            ),
            max_entries=max_entries,
        ),
        agent_memory=AgentMemorySettings(
            enabled=optional_bool(
                agent_config, "enabled", "memory.agent_memory", default=False
            ),
            path=optional_string(agent_config, "path", "memory.agent_memory")
            or "data/agent_memory.json",
            max_history_entries=max_history,
        ),
    )


def _load_topic_memory_settings(config: dict[str, Any]) -> TopicMemorySettings:
    reject_unknown_keys(
        config,
        {
            "enabled",
            "database_service",
            "embedding_model",
            "summary",
            "duplicate_threshold",
            "max_entries",
            "retention_days",
        },
        "memory.topic_memory",
    )
    duplicate_threshold = optional_number(
        config, "duplicate_threshold", "memory.topic_memory"
    )
    if duplicate_threshold is None:
        duplicate_threshold = 0.95
    if not 0.0 <= duplicate_threshold <= 1.0:
        raise ConfigError(
            path="memory.topic_memory.duplicate_threshold",
            expected="number between 0.0 and 1.0",
            actual="out of range",
        )

    max_entries = optional_int(config, "max_entries", "memory.topic_memory")
    if max_entries is not None and max_entries <= 0:
        raise ConfigError(
            path="memory.topic_memory.max_entries",
            expected="integer greater than 0",
            actual="out of range",
        )

    retention_days = optional_int(config, "retention_days", "memory.topic_memory")
    if retention_days is not None and retention_days <= 0:
        raise ConfigError(
            path="memory.topic_memory.retention_days",
            expected="integer greater than 0",
            actual="out of range",
        )

    return TopicMemorySettings(
        enabled=require_bool(config, "enabled", "memory.topic_memory"),
        database_service=require_string(
            config, "database_service", "memory.topic_memory"
        ),
        embedding_model=require_string(
            config, "embedding_model", "memory.topic_memory"
        ),
        duplicate_threshold=duplicate_threshold,
        max_entries=max_entries,
        retention_days=retention_days,
        summary=_load_topic_memory_summary_settings(
            _require_dict(
                config,
                "summary",
                error_path="memory.topic_memory.summary",
            )
        ),
    )


def _load_topic_memory_summary_settings(
    config: dict[str, Any],
) -> TopicMemorySummarySettings:
    reject_unknown_keys(
        config, {"type", "model", "fallback_max_length"}, "memory.topic_memory.summary"
    )
    summary_type = require_string(config, "type", "memory.topic_memory.summary")
    _require_enum(summary_type, {"llm", "simple"}, "memory.topic_memory.summary.type")
    return TopicMemorySummarySettings(
        type=summary_type,
        model=require_string(config, "model", "memory.topic_memory.summary"),
        fallback_max_length=_positive_int_setting(
            config, "fallback_max_length", "memory.topic_memory.summary"
        ),
    )


def _load_character_settings(config: dict[str, Any]) -> CharacterSettings:
    reject_unknown_keys(
        config,
        {
            "name",
            "name_reading",
            "personality",
            "speaking_style",
            "streaming_style",
            "likes",
            "dislikes",
            "behavior_policy",
        },
        "character",
    )
    return CharacterSettings(
        name=require_string(config, "name", "character"),
        name_reading=require_string(config, "name_reading", "character"),
        personality=require_string(config, "personality", "character"),
        speaking_style=require_string(config, "speaking_style", "character"),
        streaming_style=require_string(config, "streaming_style", "character"),
        likes=require_string_sequence(config, "likes", "character"),
        dislikes=require_string_sequence(config, "dislikes", "character"),
        behavior_policy=require_string_sequence(config, "behavior_policy", "character"),
    )


def _load_input_receiver_settings(config: dict[str, Any]) -> InputReceiverSettings:
    reject_unknown_keys(config, {"console", "timer"}, "input_receivers")
    console_config = _require_dict(
        config,
        "console",
        error_path="input_receivers.console",
    )
    timer_config = _require_dict(
        config,
        "timer",
        error_path="input_receivers.timer",
    )
    reject_unknown_keys(console_config, {"enabled"}, "input_receivers.console")
    reject_unknown_keys(
        timer_config,
        {"enabled", "interval_seconds", "max_events"},
        "input_receivers.timer",
    )
    interval = _positive_number_setting(
        timer_config, "interval_seconds", "input_receivers.timer"
    )
    max_events = optional_int(timer_config, "max_events", "input_receivers.timer")
    if max_events is not None:
        _require_non_negative(max_events, "input_receivers.timer.max_events")

    return InputReceiverSettings(
        console=ConsoleInputReceiverSettings(
            enabled=require_bool(
                console_config, "enabled", "input_receivers.console"
            ),
        ),
        timer=TimerInputReceiverSettings(
            enabled=require_bool(timer_config, "enabled", "input_receivers.timer"),
            interval_seconds=interval,
            max_events=max_events,
        ),
    )


def _validate_reference_graph(config: AppConfig) -> None:
    ai_service_types = (OpenAiServiceSettings, OllamaServiceSettings)
    for model_key, model in config.models.items():
        service = config.services.get(model.service)
        if service is None:
            raise ConfigError(
                path=f"models.{model_key}.service",
                expected="defined service name",
                actual="unknown service",
            )
        if not isinstance(service, ai_service_types):
            raise ConfigError(
                path=f"models.{model_key}.service",
                expected="service with type openai or ollama",
                actual=f"service type {service.type}",
            )

    if config.response_generator.type == "llm":
        _require_model_reference(
            config, config.response_generator.model, "response_generator.model"
        )
        for role_name, role in (
            ("situation_evaluator", config.llm_roles.situation_evaluator),
            ("character", config.llm_roles.character),
            ("response_validator", config.llm_roles.response_validator),
        ):
            _require_model_reference(
                config, role.model, f"llm_roles.{role_name}.model"
            )
        _require_model_reference(
            config, config.topic_classifier.model, "topic_classifier.model"
        )

    if config.speech.enabled:
        service = _require_service_reference(config, config.speech.service, "speech.service")
        if not isinstance(service, VoiceVoxServiceSettings):
            raise ConfigError(
                path="speech.service",
                expected="service with type voicevox",
                actual=f"service type {service.type}",
            )

    topic_memory = config.memory.topic_memory
    if topic_memory.enabled:
        database = _require_service_reference(
            config,
            topic_memory.database_service,
            "memory.topic_memory.database_service",
        )
        if not isinstance(database, PostgresServiceSettings):
            raise ConfigError(
                path="memory.topic_memory.database_service",
                expected="service with type postgres",
                actual=f"service type {database.type}",
            )
        embedding = _require_model_reference(
            config,
            topic_memory.embedding_model,
            "memory.topic_memory.embedding_model",
        )
        if embedding.dimension is None or embedding.dimension <= 0:
            raise ConfigError(
                path=f"models.{topic_memory.embedding_model}.dimension",
                expected="integer greater than 0 for embedding model",
                actual="missing or out of range",
            )
        if topic_memory.summary.type == "llm":
            _require_model_reference(
                config,
                topic_memory.summary.model,
                "memory.topic_memory.summary.model",
            )

def _require_model_reference(
    config: AppConfig,
    model_key: str,
    path: str,
) -> ModelSettings:
    model = config.models.get(model_key)
    if model is None:
        raise ConfigError(
            path=path,
            expected="defined model name",
            actual="unknown model",
        )
    return model


def _require_service_reference(
    config: AppConfig,
    service_name: str,
    path: str,
) -> ServiceSettings:
    service = config.services.get(service_name)
    if service is None:
        raise ConfigError(
            path=path,
            expected="defined service name",
            actual="unknown service",
        )
    return service


def _require_dict(
    config: dict[str, Any],
    setting_path: str,
    *,
    error_path: str | None = None,
) -> dict[str, Any]:
    display_path = error_path or setting_path
    value = _get_required_value(config, setting_path, error_path=display_path)
    return require_mapping(value, display_path)


def _get_required_value(
    config: dict[str, Any],
    setting_path: str,
    *,
    error_path: str | None = None,
) -> Any:
    current: Any = config

    for key in setting_path.split("."):
        if not isinstance(current, dict) or key not in current:
            raise ConfigError(
                path=error_path or setting_path,
                expected="required value",
                actual="missing",
            )
        current = current[key]

    return current


def _number_value(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(path=path, expected="number", actual=type(value).__name__)
    return float(value)


def _require_positive(value: int | float, path: str) -> None:
    if value <= 0:
        raise ConfigError(
            path=path, expected="number greater than 0", actual="out of range"
        )


def _require_non_negative(value: int | float, path: str) -> None:
    if value < 0:
        raise ConfigError(
            path=path,
            expected="number greater than or equal to 0",
            actual="out of range",
        )


def _require_enum(value: str, allowed: set[str], path: str) -> None:
    if value not in allowed:
        raise ConfigError(
            path=path,
            expected="one of " + ", ".join(sorted(allowed)),
            actual="unsupported value",
        )


def _positive_number_setting(
    config: Mapping[str, Any], key: str, path: str
) -> float:
    value = require_number(config, key, path)
    _require_positive(value, f"{path}.{key}")
    return value


def _positive_int_setting(config: Mapping[str, Any], key: str, path: str) -> int:
    value = require_int(config, key, path)
    _require_positive(value, f"{path}.{key}")
    return value


def _non_negative_int_setting(
    config: Mapping[str, Any], key: str, path: str
) -> int:
    value = require_int(config, key, path)
    _require_non_negative(value, f"{path}.{key}")
    return value


def _optional_positive_int(
    config: Mapping[str, Any],
    key: str,
    path: str,
    default: int,
) -> int:
    value = optional_int(config, key, path, default=default)
    assert value is not None
    _require_positive(value, f"{path}.{key}")
    return value


def _optional_non_negative_int(
    config: Mapping[str, Any],
    key: str,
    path: str,
    default: int,
) -> int:
    value = optional_int(config, key, path, default=default)
    assert value is not None
    _require_non_negative(value, f"{path}.{key}")
    return value


def _optional_number_required(
    config: Mapping[str, Any],
    key: str,
    path: str,
    default: float,
) -> float:
    value = optional_number(config, key, path, default=default)
    assert value is not None
    return value


def _optional_positive_number(
    config: Mapping[str, Any],
    key: str,
    path: str,
    default: float,
) -> float:
    value = _optional_number_required(config, key, path, default)
    _require_positive(value, f"{path}.{key}")
    return value


def _enum_setting(
    config: Mapping[str, Any],
    key: str,
    path: str,
    default: str,
    allowed: set[str],
) -> str:
    value = optional_string(config, key, path) or default
    _require_enum(value, allowed, f"{path}.{key}")
    return value
