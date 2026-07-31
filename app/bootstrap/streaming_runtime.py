from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING

from app.bootstrap.config_helpers import (
    require_service_value as _require_service_value,
)
from app.bootstrap.config_helpers import resolve_service as _resolve_service
from app.bootstrap.config_helpers import service_timeout as _service_timeout
from app.config.app_config import AppConfig
from app.config.service_schema import (
    FakeObsServiceSettings,
    FakeYouTubeServiceSettings,
    ObsWebSocketServiceSettings,
    VoiceVoxServiceSettings,
    YouTubeServiceSettings,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.adapters.streaming import (
        InMemoryStreamMainSegmentRepository,
        InMemoryStreamOpeningRepository,
        InMemoryStreamPreparationPublisher,
        InMemoryStreamSessionRepository,
    )
    from app.core.plugins import CapabilityRegistry
    from app.plugins.youtube_streaming.application import (
        PrepareStreamSessionUsecase,
        StartStreamSessionUsecase,
    )
    from app.ports.streaming_control import (
        ObsStreamingControlPort,
        YouTubeStreamingControlPort,
    )
    from app.ports.streaming_preparation import RunOfShowRepository
    from app.ports.youtube_live_chat import YouTubeLiveChatReadPort


@dataclass(frozen=True, slots=True)
class StreamPreparationRuntime:
    config: AppConfig
    usecase: PrepareStreamSessionUsecase
    sessions: InMemoryStreamSessionRepository
    publisher: InMemoryStreamPreparationPublisher
    capability_registry: CapabilityRegistry
    start_usecase: StartStreamSessionUsecase
    openings: InMemoryStreamOpeningRepository
    main_segments: InMemoryStreamMainSegmentRepository
    run_of_show: RunOfShowRepository
    obs_control: ObsStreamingControlPort
    youtube_control: YouTubeStreamingControlPort
    live_chat: YouTubeLiveChatReadPort


def create_streaming_demo_config(config: AppConfig) -> AppConfig:
    """Return an explicit, external-I/O-free composition preset."""
    services = dict(config.services)
    youtube = services["youtube"]
    if isinstance(youtube, YouTubeServiceSettings):
        services["youtube"] = FakeYouTubeServiceSettings(
            client_secret_path_env=youtube.client_secret_path_env,
            token_path_env=youtube.token_path_env,
            request_timeout_seconds=youtube.request_timeout_seconds,
            max_retries=youtube.max_retries,
            retry_initial_delay_seconds=youtube.retry_initial_delay_seconds,
            oauth_open_browser=youtube.oauth_open_browser,
            allow_live_broadcast=youtube.allow_live_broadcast,
            oauth_timeout_seconds=youtube.oauth_timeout_seconds,
            allowed_privacy_statuses=youtube.allowed_privacy_statuses,
        )
    services["obs"] = FakeObsServiceSettings()
    return replace(
        config,
        app=replace(config.app, mode="streaming_demo"),
        services=services,
        response_generator=replace(config.response_generator, type="dummy"),
        speech=replace(config.speech, enabled=False),
        memory=replace(
            config.memory,
            topic_memory=replace(config.memory.topic_memory, enabled=False),
        ),
        streaming=replace(
            config.streaming,
            fake=replace(
                config.streaming.fake,
                broadcast_id="demo-broadcast",
                broadcast_title="ゆら ローカル配信テスト",
            ),
        ),
    )


def create_stream_preparation_runtime(config: AppConfig) -> StreamPreparationRuntime:
    """状態確認専用Runtimeを組み立てる。配信開始・停止の依存は含めない。"""
    from app.adapters.streaming import (
        FakeLiveChatAdapter,
        FakeObsPreparationAdapter,
        FakeObsPreparationConfig,
        FakeTtsHealthAdapter,
        FakeYouTubePreparationAdapter,
        FakeYouTubePreparationConfig,
        InMemoryStreamMainSegmentRepository,
        InMemoryStreamOpeningRepository,
        InMemoryStreamPreparationPublisher,
        InMemoryStreamSessionRepository,
        UnavailableAvatarHealthAdapter,
        UnavailableYouTubePreparationAdapter,
        VoiceVoxHealthAdapter,
        VoiceVoxHealthConfig,
        YamlRunOfShowRepository,
    )
    from app.core.plugins import (
        CapabilityAvailability,
        CapabilityRegistry,
        StaticCapabilityProvider,
    )
    from app.plugins.youtube_streaming.application import (
        PrepareStreamSessionUsecase,
        StartStreamSessionUsecase,
        StreamPreparationRequirements,
    )
    from app.plugins.youtube_streaming.domain import (
        HealthStatus,
        ReadinessPolicy,
        YouTubeBroadcastSummary,
    )
    from app.ports.streaming_preparation import (
        ObsPreparationPort,
        TtsHealthPort,
        YouTubePreparationPort,
    )
    from subsystems.streaming.adapters.obs.fake_obs import (
        FakeObsStreamingControlAdapter,
    )
    from subsystems.streaming.adapters.youtube.fake_youtube import (
        FakeYouTubeStreamingControlAdapter,
    )

    youtube_service = _resolve_service(config, "youtube")
    youtube: YouTubePreparationPort
    youtube_control: YouTubeStreamingControlPort
    live_chat: YouTubeLiveChatReadPort
    if youtube_service.type == "fake":
        youtube = FakeYouTubePreparationAdapter(
            FakeYouTubePreparationConfig(
                broadcasts=(
                    YouTubeBroadcastSummary(
                        broadcast_id=config.streaming.fake.broadcast_id,
                        title=config.streaming.fake.broadcast_title,
                        live_chat_id=(
                            "demo-live-chat"
                            if config.app.mode == "streaming_demo"
                            else None
                        ),
                    ),
                )
            )
        )
        youtube_control = FakeYouTubeStreamingControlAdapter()
        live_chat = FakeLiveChatAdapter(keep_alive=config.app.mode == "streaming_demo")
        if config.app.mode == "streaming_demo":
            youtube_control.adapter_type = "demo_fake"
            youtube_control.stream_statuses = ["active", "active", "inactive"]
            youtube_control.broadcast_statuses = [
                "ready",
                "live",
                "live",
                "live",
                "complete",
            ]
    elif youtube_service.type in {"google", "google_youtube"}:
        from subsystems.streaming.adapters.youtube import (
            GoogleYouTubeAuthConfig,
            GoogleYouTubeAuthService,
            GoogleYouTubeClientConfig,
            GoogleYouTubeClientFactory,
            GoogleYouTubePreparationAdapter,
            GoogleYouTubePreparationConfig,
        )

        required_settings = {
            "client_secret_path_env": youtube_service.client_secret_path_env,
            "token_path_env": youtube_service.token_path_env,
            "request_timeout_seconds": youtube_service.request_timeout_seconds,
            "max_retries": youtube_service.max_retries,
            "retry_initial_delay_seconds": youtube_service.retry_initial_delay_seconds,
            "oauth_open_browser": youtube_service.oauth_open_browser,
            "allow_live_broadcast": youtube_service.allow_live_broadcast,
            "oauth_timeout_seconds": youtube_service.oauth_timeout_seconds,
            "allowed_privacy_statuses": youtube_service.allowed_privacy_statuses,
        }
        missing = [name for name, value in required_settings.items() if value is None]
        if missing:
            youtube = UnavailableYouTubePreparationAdapter(
                "YouTube Google Adapterの設定が不足しています: " + ", ".join(missing)
            )
            youtube_control = FakeYouTubeStreamingControlAdapter()
            live_chat = FakeLiveChatAdapter()
        else:
            assert youtube_service.request_timeout_seconds is not None
            assert youtube_service.max_retries is not None
            assert youtube_service.retry_initial_delay_seconds is not None
            assert youtube_service.oauth_timeout_seconds is not None
            assert youtube_service.allowed_privacy_statuses is not None
            client_secret_path_env = str(youtube_service.client_secret_path_env)
            token_path_env = str(youtube_service.token_path_env)
            request_timeout = float(youtube_service.request_timeout_seconds)
            auth_service = GoogleYouTubeAuthService(
                GoogleYouTubeAuthConfig(
                    client_secret_path_env=client_secret_path_env,
                    token_path_env=token_path_env,
                    request_timeout_seconds=request_timeout,
                    open_browser=bool(youtube_service.oauth_open_browser),
                    oauth_timeout_seconds=youtube_service.oauth_timeout_seconds,
                )
            )
            client_factory = GoogleYouTubeClientFactory(
                auth_service,
                GoogleYouTubeClientConfig(request_timeout_seconds=request_timeout),
            )
            youtube = GoogleYouTubePreparationAdapter(
                auth_service=auth_service,
                client_factory=client_factory,
                config=GoogleYouTubePreparationConfig(
                    max_retries=int(youtube_service.max_retries),
                    retry_initial_delay_seconds=float(
                        youtube_service.retry_initial_delay_seconds
                    ),
                    allow_live_broadcast=bool(youtube_service.allow_live_broadcast),
                    allowed_privacy_statuses=youtube_service.allowed_privacy_statuses,
                ),
            )
            from subsystems.streaming.adapters.youtube import (
                GoogleYouTubeStreamingControlAdapter,
            )

            youtube_control = GoogleYouTubeStreamingControlAdapter(
                client_factory, youtube
            )
            from subsystems.streaming.adapters.youtube import GoogleYouTubeLiveChatAdapter

            live_chat = GoogleYouTubeLiveChatAdapter(client_factory)
    else:
        raise RuntimeError(f"未対応のYouTubeサービスです: {youtube_service.type}")

    obs_service = _resolve_service(config, "obs")
    obs: ObsPreparationPort
    obs_control: ObsStreamingControlPort
    if obs_service.type == "fake":
        obs = FakeObsPreparationAdapter(
            FakeObsPreparationConfig(
                current_scene=config.streaming.obs.expected_start_scene,
                current_scene_collection=config.streaming.obs.expected_scene_collection,
                audio_source_states={
                    name: True for name in config.streaming.obs.required_audio_sources
                },
            )
        )
        obs_control = FakeObsStreamingControlAdapter()
        if config.app.mode == "streaming_demo":
            obs_control.adapter_type = "demo_fake"
            obs_control.statuses = ["idle", "active", "active", "active", "idle"]
    elif obs_service.type == "disabled":
        from app.adapters.streaming import DisabledObsPreparationAdapter
        from subsystems.streaming.adapters.obs.fake_obs import (
            DisabledObsStreamingControlAdapter,
        )

        obs = DisabledObsPreparationAdapter()
        obs_control = DisabledObsStreamingControlAdapter()
    elif obs_service.type == "obs_websocket":
        from urllib.parse import urlparse

        from subsystems.streaming.adapters.obs import (
            ObsWebSocketClientConfig,
            ObsWebSocketClientFactory,
            ObsWebSocketPreparationAdapter,
            ObsWebSocketPreparationConfig,
            ObsWebSocketStreamingControlAdapter,
        )

        parsed = urlparse(obs_service.websocket_url or "")
        host = obs_service.host or parsed.hostname or ""
        port = obs_service.port or parsed.port or 4455
        password_env = obs_service.password_env or ""
        obs_client_factory = ObsWebSocketClientFactory(
            ObsWebSocketClientConfig(
                host=host,
                port=port,
                password_env=password_env,
                connect_timeout_seconds=obs_service.connect_timeout_seconds,
                request_timeout_seconds=obs_service.request_timeout_seconds,
            )
        )
        obs = ObsWebSocketPreparationAdapter(
            obs_client_factory,
            ObsWebSocketPreparationConfig(
                required_audio_sources=config.streaming.obs.required_audio_sources,
                optional_audio_sources=config.streaming.obs.optional_audio_sources,
                avatar_source_name=config.streaming.obs.avatar_source_name,
                low_volume_threshold_db=config.streaming.obs.low_volume_threshold_db,
                request_timeout_seconds=obs_service.request_timeout_seconds,
                max_retries=obs_service.max_retries or 0,
                retry_initial_delay_seconds=obs_service.retry_initial_delay_seconds
                or 0.5,
                max_scene_depth=config.streaming.obs.max_scene_depth,
            ),
        )
        obs_control = ObsWebSocketStreamingControlAdapter(
            obs_client_factory,
            request_timeout_seconds=obs_service.request_timeout_seconds,
        )
    else:
        raise RuntimeError(f"未対応のOBSサービスです: {obs_service.type}")

    if (
        isinstance(youtube_control, FakeYouTubeStreamingControlAdapter)
        and obs_control.adapter_type == "obs_websocket"
    ):
        youtube_control.stream_statuses = ["active", "active", "inactive"]
        youtube_control.broadcast_statuses = [
            "ready",
            "live",
            "live",
            "live",
            "complete",
        ]

    tts: TtsHealthPort
    if config.app.mode == "streaming_demo":
        tts = FakeTtsHealthAdapter()
    else:
        voicevox_service = _resolve_service(config, config.speech.service)
        if not isinstance(voicevox_service, VoiceVoxServiceSettings):
            raise RuntimeError(
                f"未対応の音声合成サービスです: {voicevox_service.type}"
            )
        player_command = config.speech.player.command or (
            "afplay" if sys.platform == "darwin" else "aplay"
        )
        tts = VoiceVoxHealthAdapter(
            VoiceVoxHealthConfig(
                base_url=_require_service_value(
                    voicevox_service.base_url, "base_url", config.speech.service
                ),
                timeout_seconds=_service_timeout(voicevox_service),
                speaker_id=config.speech.speaker_id,
                player_command=player_command,
            )
        )
    sessions = InMemoryStreamSessionRepository()
    publisher = InMemoryStreamPreparationPublisher()
    capability_registry = CapabilityRegistry()
    provider = StaticCapabilityProvider(
        "youtube_streaming",
        frozenset(
            {
                "stream.session.prepare",
                "stream.session.end.normal",
                "stream.session.stop.emergency",
                "youtube.broadcast.transition_complete",
                "obs.stream.stop",
                "output.cancel",
            }
        ),
        "YouTube Streaming Capability Health",
    )
    capability_registry.register(provider, "stream.session.prepare")
    for capability in (
        "stream.session.end.normal",
        "stream.session.stop.emergency",
        "youtube.broadcast.transition_complete",
        "obs.stream.stop",
        "output.cancel",
    ):
        capability_registry.register(provider, capability)

    status_mapping = {
        HealthStatus.HEALTHY: CapabilityAvailability.AVAILABLE,
        HealthStatus.DEGRADED: CapabilityAvailability.DEGRADED,
        HealthStatus.UNAVAILABLE: CapabilityAvailability.UNAVAILABLE,
        HealthStatus.UNKNOWN: CapabilityAvailability.UNKNOWN,
    }

    def report_capability(
        capability: str,
        status: HealthStatus,
        failure_reason: str | None,
        observed_at: datetime,
    ) -> None:
        availability = status_mapping[status]
        if availability in {
            CapabilityAvailability.AVAILABLE,
            CapabilityAvailability.DEGRADED,
        }:
            capability_registry.register(provider, capability)
        else:
            capability_registry.unregister(provider.plugin_id, capability)
        capability_registry.update_health(
            provider.plugin_id,
            capability,
            status=availability,
            failure_reason=failure_reason,
            observed_at=observed_at,
        )

    readiness = config.streaming.readiness
    run_of_show = YamlRunOfShowRepository(config.streaming.run_of_show.directory)
    usecase = PrepareStreamSessionUsecase(
        youtube=youtube,
        obs=obs,
        tts=tts,
        avatar=UnavailableAvatarHealthAdapter(),
        run_of_show=run_of_show,
        sessions=sessions,
        publisher=publisher,
        requirements=StreamPreparationRequirements(
            require_youtube=readiness.require_youtube,
            require_obs=readiness.require_obs,
            require_tts=readiness.require_tts,
            require_avatar=readiness.require_avatar,
            require_run_of_show=readiness.require_run_of_show,
            require_emergency_stop=readiness.require_emergency_stop,
            require_live_chat=readiness.require_live_chat,
            expected_scene_collection=config.streaming.obs.expected_scene_collection,
            expected_start_scene=config.streaming.obs.expected_start_scene,
            required_audio_sources=config.streaming.obs.required_audio_sources,
            require_obs_avatar_visible=config.streaming.obs.require_avatar_source_visible,
            timeout_seconds=config.streaming.health_timeout_seconds,
        ),
        readiness_policy=ReadinessPolicy(
            allow_required_degraded=readiness.allow_required_degraded
        ),
        capability_reporter=report_capability,
    )
    start_usecase = StartStreamSessionUsecase(
        sessions=sessions,
        obs=obs_control,
        youtube=youtube_control,
        poll_interval_seconds=0 if config.app.mode == "streaming_demo" else 1,
        allow_fake_youtube=(
            youtube_control.adapter_type == "fake"
            and obs_control.adapter_type == "obs_websocket"
        ),
    )
    logger.info(
        "Streaming adapters configured: config_path=%s youtube_adapter=%s "
        "obs_adapter=%s obs_host=%s obs_port=%s obs_password_env_set=%s",
        config.config_path,
        youtube_control.adapter_type,
        obs_control.adapter_type,
        obs_service.host if isinstance(obs_service, ObsWebSocketServiceSettings) else None,
        obs_service.port if isinstance(obs_service, ObsWebSocketServiceSettings) else None,
        bool(
            isinstance(obs_service, ObsWebSocketServiceSettings)
            and obs_service.password_env
            and os.getenv(obs_service.password_env)
        ),
    )
    return StreamPreparationRuntime(
        config,
        usecase,
        sessions,
        publisher,
        capability_registry,
        start_usecase,
        InMemoryStreamOpeningRepository(),
        InMemoryStreamMainSegmentRepository(),
        run_of_show,
        obs_control,
        youtube_control,
        live_chat,
    )
