from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

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
    FakeObsServiceSettings,
    FakeYouTubeServiceSettings,
    ObsWebSocketServiceSettings,
    OllamaServiceSettings,
    OpenAiServiceSettings,
    PostgresServiceSettings,
    ServiceSettings,
    VoiceVoxServiceSettings,
    YouTubeServiceSettings,
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
    string_sequence_value,
)
from app.domain.emotions import EmotionAppraisalSettings
from app.plugins.games.settings import GamesPluginSettings, load_games_plugin_settings

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
    games: GamesPluginSettings = field(default_factory=GamesPluginSettings)
    registrations: Mapping[str, PluginRegistrationSettings] = field(
        default_factory=lambda: immutable_mapping({})
    )
    opaque_configs: Mapping[str, Mapping[str, Any]] = field(
        default_factory=lambda: immutable_mapping({})
    )


@dataclass(frozen=True, slots=True)
class StreamingReadinessSettings:
    require_youtube: bool = True
    require_obs: bool = True
    require_tts: bool = True
    require_avatar: bool = False
    require_run_of_show: bool = True
    require_emergency_stop: bool = False
    allow_required_degraded: bool = False
    require_live_chat: bool = False


@dataclass(frozen=True, slots=True)
class StreamingObsSettings:
    expected_scene_collection: str = "AI Liver"
    expected_start_scene: str = "Starting Soon"
    required_audio_sources: tuple[str, ...] = ("VOICEVOX",)
    optional_audio_sources: tuple[str, ...] = ()
    avatar_source_name: str | None = None
    require_avatar_source_visible: bool = False
    low_volume_threshold_db: float = -60.0
    max_scene_depth: int = 8


@dataclass(frozen=True, slots=True)
class StreamingRunOfShowSettings:
    directory: str = "config/run_of_show"
    default_id: str = "default"


@dataclass(frozen=True, slots=True)
class StreamingFakeSettings:
    broadcast_id: str = "fake-broadcast-1"
    broadcast_title: str = "配信準備テスト枠"


@dataclass(frozen=True, slots=True)
class CommentModerationSettings:
    blocked_terms: tuple[str, ...] = ()
    allowed_terms: tuple[str, ...] = ()
    max_comment_length: int = 300
    repeated_message_window_seconds: int = 30
    repeated_message_limit: int = 3
    url_policy: str = "review"
    unknown_message_type_policy: str = "ignore"
    max_concurrent_evaluations: int = 4
    evaluation_queue_capacity: int = 128
    timeout_seconds: float = 3.0


@dataclass(frozen=True, slots=True)
class CommentRankingSettings:
    weights: Mapping[str, float] = field(
        default_factory=lambda: immutable_mapping(
            {
                "recency": 0.15,
                "relevance": 0.25,
                "novelty": 0.15,
                "conversation_fit": 0.20,
                "engagement": 0.15,
                "fairness": 0.10,
            }
        )
    )
    selection_threshold: float = 0.55
    minimum_conversation_fit: float = 0.5
    candidate_ttl_seconds: int = 90
    reservation_ttl_seconds: int = 30
    max_pool_size: int = 200
    max_rank_batch_size: int = 50
    history_size: int = 100
    author_cooldown_count: int = 2
    semantic_timeout_seconds: float = 2.0
    max_concurrent_rankings: int = 1
    queue_capacity: int = 16

    def __post_init__(self) -> None:
        expected = {
            "recency",
            "relevance",
            "novelty",
            "conversation_fit",
            "engagement",
            "fairness",
        }
        if (
            set(self.weights) != expected
            or abs(sum(self.weights.values()) - 1.0) > 0.000001
        ):
            raise ValueError("comment_ranking.weights_invalid")
        if any(not 0 <= value <= 1 for value in self.weights.values()):
            raise ValueError("comment_ranking.weights_invalid")
        if (
            not 0 <= self.selection_threshold <= 1
            or not 0 <= self.minimum_conversation_fit <= 1
        ):
            raise ValueError("comment_ranking.threshold_invalid")
        positive = (
            self.candidate_ttl_seconds,
            self.reservation_ttl_seconds,
            self.max_pool_size,
            self.max_rank_batch_size,
            self.history_size,
            self.author_cooldown_count,
            self.semantic_timeout_seconds,
            self.max_concurrent_rankings,
            self.queue_capacity,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("comment_ranking.capacity_invalid")


@dataclass(frozen=True, slots=True)
class CommentResponseSettings:
    max_characters: int = 140
    max_sentences: int = 3
    allow_follow_up_question: bool = True
    mention_author_name: str = "optional"
    repeat_comment_text: bool = False
    response_cooldown_seconds: int = 5
    max_retries: int = 2

    def __post_init__(self) -> None:
        if self.max_characters <= 0 or self.max_sentences <= 0:
            raise ValueError("comment_response.length_invalid")
        if self.mention_author_name not in {"never", "optional"}:
            raise ValueError("comment_response.author_policy_invalid")
        if self.response_cooldown_seconds < 0 or self.max_retries < 0:
            raise ValueError("comment_response.retry_invalid")


@dataclass(frozen=True, slots=True)
class StreamingSettings:
    readiness: StreamingReadinessSettings = field(
        default_factory=StreamingReadinessSettings
    )
    obs: StreamingObsSettings = field(default_factory=StreamingObsSettings)
    run_of_show: StreamingRunOfShowSettings = field(
        default_factory=StreamingRunOfShowSettings
    )
    fake: StreamingFakeSettings = field(default_factory=StreamingFakeSettings)
    moderation: CommentModerationSettings = field(
        default_factory=CommentModerationSettings
    )
    comment_ranking: CommentRankingSettings = field(
        default_factory=CommentRankingSettings
    )
    comment_response: CommentResponseSettings = field(
        default_factory=CommentResponseSettings
    )
    health_timeout_seconds: float = 5.0


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
    streaming: StreamingSettings = field(default_factory=StreamingSettings)
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
                "streaming",
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
            streaming=_load_streaming_settings(raw_config.get("streaming")),
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


def _load_streaming_settings(value: object) -> StreamingSettings:
    if value is None:
        return StreamingSettings()
    config = require_mapping(value, "streaming")
    reject_unknown_keys(
        config,
        {
            "health_timeout_seconds",
            "readiness",
            "obs",
            "run_of_show",
            "fake",
            "moderation",
            "comment_ranking",
            "comment_response",
        },
        "streaming",
    )
    readiness = optional_mapping(config, "readiness", "streaming")
    obs = optional_mapping(config, "obs", "streaming")
    run_of_show = optional_mapping(config, "run_of_show", "streaming")
    fake = optional_mapping(config, "fake", "streaming")
    moderation = optional_mapping(config, "moderation", "streaming")
    ranking = optional_mapping(config, "comment_ranking", "streaming")
    response = optional_mapping(config, "comment_response", "streaming")
    reject_unknown_keys(
        readiness,
        {
            "require_youtube",
            "require_obs",
            "require_tts",
            "require_avatar",
            "require_run_of_show",
            "require_emergency_stop",
            "allow_required_degraded",
            "require_live_chat",
        },
        "streaming.readiness",
    )
    reject_unknown_keys(
        obs,
        {
            "expected_scene_collection",
            "expected_start_scene",
            "required_audio_sources",
            "optional_audio_sources",
            "avatar_source_name",
            "require_avatar_source_visible",
            "low_volume_threshold_db",
            "max_scene_depth",
        },
        "streaming.obs",
    )
    reject_unknown_keys(run_of_show, {"directory", "default_id"}, "streaming.run_of_show")
    reject_unknown_keys(fake, {"broadcast_id", "broadcast_title"}, "streaming.fake")
    reject_unknown_keys(
        moderation,
        {
            "blocked_terms",
            "allowed_terms",
            "max_comment_length",
            "repeated_message_window_seconds",
            "repeated_message_limit",
            "url_policy",
            "unknown_message_type_policy",
            "max_concurrent_evaluations",
            "evaluation_queue_capacity",
            "timeout_seconds",
        },
        "streaming.moderation",
    )
    reject_unknown_keys(
        ranking,
        {
            "weights",
            "selection_threshold",
            "minimum_conversation_fit",
            "candidate_ttl_seconds",
            "reservation_ttl_seconds",
            "max_pool_size",
            "max_rank_batch_size",
            "history_size",
            "author_cooldown_count",
            "semantic_timeout_seconds",
            "max_concurrent_rankings",
            "queue_capacity",
        },
        "streaming.comment_ranking",
    )
    reject_unknown_keys(
        response,
        {
            "max_characters",
            "max_sentences",
            "allow_follow_up_question",
            "mention_author_name",
            "repeat_comment_text",
            "response_cooldown_seconds",
            "max_retries",
        },
        "streaming.comment_response",
    )
    default_weights = CommentRankingSettings().weights
    weights = ranking.get("weights", default_weights)
    if not isinstance(weights, Mapping) or set(weights) != set(default_weights):
        raise ConfigError(
            path="streaming.comment_ranking.weights",
            expected="all six ranking feature weights",
            actual=type(weights).__name__,
        )
    parsed_weights = {
        key: _number_value(value, f"streaming.comment_ranking.weights.{key}")
        for key, value in weights.items()
    }
    if (
        any(item < 0 or item > 1 for item in parsed_weights.values())
        or abs(sum(parsed_weights.values()) - 1.0) > 0.000001
    ):
        raise ConfigError(
            path="streaming.comment_ranking.weights",
            expected="weights between 0.0 and 1.0 whose sum is 1.0",
            actual="out of range",
        )
    audio_sources = string_sequence_value(
        obs.get("required_audio_sources", ["VOICEVOX"]),
        "streaming.obs.required_audio_sources",
    )
    optional_audio_sources = string_sequence_value(
        obs.get("optional_audio_sources", []),
        "streaming.obs.optional_audio_sources",
    )
    timeout = optional_number(
        config, "health_timeout_seconds", "streaming", default=5.0
    )
    assert timeout is not None
    _require_positive(timeout, "streaming.health_timeout_seconds")
    max_scene_depth = optional_int(obs, "max_scene_depth", "streaming.obs", default=8)
    assert max_scene_depth is not None
    _require_positive(max_scene_depth, "streaming.obs.max_scene_depth")

    moderation_ints = {
        "max_comment_length": (300, True),
        "repeated_message_window_seconds": (30, True),
        "repeated_message_limit": (3, True),
        "max_concurrent_evaluations": (4, True),
        "evaluation_queue_capacity": (128, True),
    }
    parsed_moderation_ints: dict[str, int] = {}
    for key, (default, positive) in moderation_ints.items():
        parsed = optional_int(moderation, key, "streaming.moderation", default=default)
        assert parsed is not None
        if positive:
            _require_positive(parsed, f"streaming.moderation.{key}")
        parsed_moderation_ints[key] = parsed
    moderation_timeout = optional_number(
        moderation, "timeout_seconds", "streaming.moderation", default=3.0
    )
    assert moderation_timeout is not None
    _require_positive(moderation_timeout, "streaming.moderation.timeout_seconds")
    url_policy = optional_string(moderation, "url_policy", "streaming.moderation") or "review"
    _require_enum(
        url_policy,
        {"allow", "review", "ignore"},
        "streaming.moderation.url_policy",
    )
    unknown_policy = (
        optional_string(
            moderation, "unknown_message_type_policy", "streaming.moderation"
        )
        or "ignore"
    )
    _require_enum(
        unknown_policy,
        {"allow", "review", "ignore"},
        "streaming.moderation.unknown_message_type_policy",
    )
    return StreamingSettings(
        readiness=StreamingReadinessSettings(
            require_youtube=optional_bool(
                readiness, "require_youtube", "streaming.readiness", default=True
            ),
            require_obs=optional_bool(
                readiness, "require_obs", "streaming.readiness", default=True
            ),
            require_tts=optional_bool(
                readiness, "require_tts", "streaming.readiness", default=True
            ),
            require_avatar=optional_bool(
                readiness, "require_avatar", "streaming.readiness", default=False
            ),
            require_run_of_show=optional_bool(
                readiness, "require_run_of_show", "streaming.readiness", default=True
            ),
            require_emergency_stop=optional_bool(
                readiness,
                "require_emergency_stop",
                "streaming.readiness",
                default=False,
            ),
            allow_required_degraded=optional_bool(
                readiness,
                "allow_required_degraded",
                "streaming.readiness",
                default=False,
            ),
            require_live_chat=optional_bool(
                readiness, "require_live_chat", "streaming.readiness", default=False
            ),
        ),
        obs=StreamingObsSettings(
            expected_scene_collection=(
                optional_string(obs, "expected_scene_collection", "streaming.obs")
                or "AI Liver"
            ),
            expected_start_scene=(
                optional_string(obs, "expected_start_scene", "streaming.obs")
                or "Starting Soon"
            ),
            required_audio_sources=audio_sources,
            optional_audio_sources=optional_audio_sources,
            avatar_source_name=optional_string(
                obs, "avatar_source_name", "streaming.obs"
            ),
            require_avatar_source_visible=optional_bool(
                obs,
                "require_avatar_source_visible",
                "streaming.obs",
                default=False,
            ),
            low_volume_threshold_db=optional_number(
                obs, "low_volume_threshold_db", "streaming.obs", default=-60.0
            )
            or 0.0,
            max_scene_depth=max_scene_depth,
        ),
        run_of_show=StreamingRunOfShowSettings(
            directory=optional_string(
                run_of_show, "directory", "streaming.run_of_show"
            )
            or "config/run_of_show",
            default_id=optional_string(
                run_of_show, "default_id", "streaming.run_of_show"
            )
            or "default",
        ),
        fake=StreamingFakeSettings(
            broadcast_id=optional_string(fake, "broadcast_id", "streaming.fake")
            or "fake-broadcast-1",
            broadcast_title=(
                optional_string(fake, "broadcast_title", "streaming.fake")
                or "配信準備テスト枠"
            ),
        ),
        moderation=CommentModerationSettings(
            blocked_terms=string_sequence_value(
                moderation.get("blocked_terms", []),
                "streaming.moderation.blocked_terms",
            ),
            allowed_terms=string_sequence_value(
                moderation.get("allowed_terms", []),
                "streaming.moderation.allowed_terms",
            ),
            max_comment_length=parsed_moderation_ints["max_comment_length"],
            repeated_message_window_seconds=parsed_moderation_ints[
                "repeated_message_window_seconds"
            ],
            repeated_message_limit=parsed_moderation_ints["repeated_message_limit"],
            url_policy=url_policy,
            unknown_message_type_policy=unknown_policy,
            max_concurrent_evaluations=parsed_moderation_ints[
                "max_concurrent_evaluations"
            ],
            evaluation_queue_capacity=parsed_moderation_ints[
                "evaluation_queue_capacity"
            ],
            timeout_seconds=moderation_timeout,
        ),
        comment_ranking=CommentRankingSettings(
            weights=immutable_mapping(parsed_weights),
            selection_threshold=_optional_number_required(
                ranking, "selection_threshold", "streaming.comment_ranking", 0.55
            ),
            minimum_conversation_fit=_optional_number_required(
                ranking,
                "minimum_conversation_fit",
                "streaming.comment_ranking",
                0.5,
            ),
            candidate_ttl_seconds=_optional_positive_int(
                ranking, "candidate_ttl_seconds", "streaming.comment_ranking", 90
            ),
            reservation_ttl_seconds=_optional_positive_int(
                ranking, "reservation_ttl_seconds", "streaming.comment_ranking", 30
            ),
            max_pool_size=_optional_positive_int(
                ranking, "max_pool_size", "streaming.comment_ranking", 200
            ),
            max_rank_batch_size=_optional_positive_int(
                ranking, "max_rank_batch_size", "streaming.comment_ranking", 50
            ),
            history_size=_optional_positive_int(
                ranking, "history_size", "streaming.comment_ranking", 100
            ),
            author_cooldown_count=_optional_positive_int(
                ranking, "author_cooldown_count", "streaming.comment_ranking", 2
            ),
            semantic_timeout_seconds=_optional_positive_number(
                ranking, "semantic_timeout_seconds", "streaming.comment_ranking", 2.0
            ),
            max_concurrent_rankings=_optional_positive_int(
                ranking, "max_concurrent_rankings", "streaming.comment_ranking", 1
            ),
            queue_capacity=_optional_positive_int(
                ranking, "queue_capacity", "streaming.comment_ranking", 16
            ),
        ),
        comment_response=CommentResponseSettings(
            max_characters=_optional_positive_int(
                response, "max_characters", "streaming.comment_response", 140
            ),
            max_sentences=_optional_positive_int(
                response, "max_sentences", "streaming.comment_response", 3
            ),
            allow_follow_up_question=optional_bool(
                response,
                "allow_follow_up_question",
                "streaming.comment_response",
                default=True,
            ),
            mention_author_name=_enum_setting(
                response,
                "mention_author_name",
                "streaming.comment_response",
                "optional",
                {"never", "optional"},
            ),
            repeat_comment_text=optional_bool(
                response,
                "repeat_comment_text",
                "streaming.comment_response",
                default=False,
            ),
            response_cooldown_seconds=_optional_non_negative_int(
                response,
                "response_cooldown_seconds",
                "streaming.comment_response",
                5,
            ),
            max_retries=_optional_non_negative_int(
                response, "max_retries", "streaming.comment_response", 2
            ),
        ),
        health_timeout_seconds=timeout,
    )


def _load_plugin_settings(value: object) -> PluginSettings:
    if value is None:
        return PluginSettings()
    config = require_mapping(value, "plugins")
    games = config.get("games", {})
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
        if plugin_id in {"registry", "games"}:
            continue
        opaque_configs[plugin_id] = immutable_mapping(
            require_mapping(raw, f"plugins.{plugin_id}")
        )
    return PluginSettings(
        games=load_games_plugin_settings(games),
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
    if service_type in {"youtube", "youtube_api", "google", "google_youtube"}:
        values = _load_youtube_values(config, path)
        youtube_type = cast(
            Literal["youtube", "youtube_api", "google", "google_youtube"],
            service_type,
        )
        return YouTubeServiceSettings(type=youtube_type, **values)
    if service_type == "fake":
        if service_name == "youtube":
            values = _load_youtube_values(config, path)
            return FakeYouTubeServiceSettings(**values)
        if service_name == "obs":
            reject_unknown_keys(config, {"type"}, path)
            return FakeObsServiceSettings()
        raise ConfigError(
            path=f"{path}.type",
            expected="fake service named youtube or obs",
            actual="unsupported service name",
        )
    if service_type == "obs_websocket":
        reject_unknown_keys(
            config,
            {
                "type",
                "host",
                "port",
                "password_env",
                "connect_timeout_seconds",
                "request_timeout_seconds",
                "max_retries",
                "retry_initial_delay_seconds",
                "websocket_url",
            },
            path,
        )
        port = require_int(config, "port", path)
        if not 1 <= port <= 65535:
            raise ConfigError(
                path=f"{path}.port",
                expected="integer between 1 and 65535",
                actual="out of range",
            )
        return ObsWebSocketServiceSettings(
            host=require_string(config, "host", path),
            port=port,
            password_env=optional_string(config, "password_env", path),
            connect_timeout_seconds=_positive_number_setting(
                config, "connect_timeout_seconds", path
            ),
            request_timeout_seconds=_positive_number_setting(
                config, "request_timeout_seconds", path
            ),
            max_retries=_non_negative_int_setting(config, "max_retries", path),
            retry_initial_delay_seconds=_positive_number_setting(
                config, "retry_initial_delay_seconds", path
            ),
            websocket_url=optional_string(config, "websocket_url", path),
        )
    if service_type == "disabled":
        reject_unknown_keys(config, {"type"}, path)
        return DisabledServiceSettings()
    raise ConfigError(
        path=f"{path}.type",
        expected=(
            "openai, ollama, voicevox, postgres, youtube, youtube_api, "
            "google, google_youtube, fake, obs_websocket, or disabled"
        ),
        actual="unknown service type",
    )


def _load_youtube_values(config: dict[str, Any], path: str) -> dict[str, Any]:
    reject_unknown_keys(
        config,
        {
            "type",
            "client_secret_path_env",
            "token_path_env",
            "request_timeout_seconds",
            "max_retries",
            "retry_initial_delay_seconds",
            "oauth_open_browser",
            "allow_live_broadcast",
            "oauth_timeout_seconds",
            "allowed_privacy_statuses",
        },
        path,
    )
    statuses = require_string_sequence(
        config, "allowed_privacy_statuses", path, allow_empty=False
    )
    if any(status not in {"private", "unlisted", "public"} for status in statuses):
        raise ConfigError(
            path=f"{path}.allowed_privacy_statuses",
            expected="list containing only private, unlisted, or public",
            actual="unsupported value",
        )
    return {
        "client_secret_path_env": require_string(config, "client_secret_path_env", path),
        "token_path_env": require_string(config, "token_path_env", path),
        "request_timeout_seconds": _positive_number_setting(
            config, "request_timeout_seconds", path
        ),
        "max_retries": _non_negative_int_setting(config, "max_retries", path),
        "retry_initial_delay_seconds": _positive_number_setting(
            config, "retry_initial_delay_seconds", path
        ),
        "oauth_open_browser": require_bool(config, "oauth_open_browser", path),
        "allow_live_broadcast": require_bool(config, "allow_live_broadcast", path),
        "oauth_timeout_seconds": _positive_number_setting(
            config, "oauth_timeout_seconds", path
        ),
        "allowed_privacy_statuses": statuses,
    }


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

    games = config.plugins.games
    if games.enabled and games.intent_interpreter.enabled:
        game_model = games.intent_interpreter.model
        if game_model is not None:
            _require_model_reference(
                config, game_model, "plugins.games.intent_interpreter.model"
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
