"""OBS Adapter bundle selection inside Streaming Subsystem."""

from dataclasses import dataclass

from subsystems.streaming.adapters.obs.contracts import (
    ObsPreparationPort,
    ObsStreamingControlPort,
)
from subsystems.streaming.adapters.obs.fake_obs import (
    DisabledObsPreparationAdapter,
    DisabledObsStreamingControlAdapter,
    FakeObsPreparationAdapter,
    FakeObsPreparationConfig,
    FakeObsStreamingControlAdapter,
)
from subsystems.streaming.config.obs import ObsAdapterMode, ObsSubsystemConfig
from subsystems.streaming.config.secrets import (
    EnvironmentSecretProvider,
    SecretProvider,
)
from subsystems.streaming.config.validation import validate_obs_config


@dataclass(frozen=True, slots=True)
class ObsAdapterBundle:
    mode: ObsAdapterMode
    preparation: ObsPreparationPort
    control: ObsStreamingControlPort


def build_obs_adapter_bundle(
    config: ObsSubsystemConfig,
    secret_provider: SecretProvider | None = None,
) -> ObsAdapterBundle:
    """Build OBS adapters without loading obsws-python unless real mode is selected."""

    secrets = secret_provider or EnvironmentSecretProvider()
    validate_obs_config(config, secrets)
    if config.mode is ObsAdapterMode.FAKE:
        return ObsAdapterBundle(
            mode=config.mode,
            preparation=FakeObsPreparationAdapter(
                FakeObsPreparationConfig(
                    audio_source_states={name: True for name in config.required_audio_sources}
                )
            ),
            control=FakeObsStreamingControlAdapter(),
        )
    if config.mode is ObsAdapterMode.DISABLED:
        return ObsAdapterBundle(
            mode=config.mode,
            preparation=DisabledObsPreparationAdapter(),
            control=DisabledObsStreamingControlAdapter(),
        )
    from subsystems.streaming.adapters.obs.client import (
        ObsWebSocketClientConfig,
        ObsWebSocketClientFactory,
    )
    from subsystems.streaming.adapters.obs.control import (
        ObsWebSocketStreamingControlAdapter,
    )
    from subsystems.streaming.adapters.obs.obs_websocket import (
        ObsWebSocketPreparationAdapter,
        ObsWebSocketPreparationConfig,
    )

    factory = ObsWebSocketClientFactory(
        ObsWebSocketClientConfig(
            host=config.host,
            port=config.port,
            password_env=config.password_ref,
            connect_timeout_seconds=config.connect_timeout_seconds,
            request_timeout_seconds=config.request_timeout_seconds,
        ),
        secret_provider=secrets,
    )
    return ObsAdapterBundle(
        mode=config.mode,
        preparation=ObsWebSocketPreparationAdapter(
            factory,
            ObsWebSocketPreparationConfig(
                required_audio_sources=config.required_audio_sources,
                optional_audio_sources=config.optional_audio_sources,
                avatar_source_name=config.avatar_source_name,
                low_volume_threshold_db=config.low_volume_threshold_db,
                request_timeout_seconds=config.request_timeout_seconds,
                max_retries=config.max_retries,
                retry_initial_delay_seconds=config.retry_initial_delay_seconds,
                max_scene_depth=config.max_scene_depth,
            ),
        ),
        control=ObsWebSocketStreamingControlAdapter(
            factory,
            request_timeout_seconds=config.request_timeout_seconds,
            state_timeout_seconds=config.state_timeout_seconds,
            poll_interval_seconds=config.poll_interval_seconds,
        ),
    )
