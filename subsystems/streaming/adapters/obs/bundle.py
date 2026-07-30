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


@dataclass(frozen=True, slots=True)
class ObsAdapterBundle:
    mode: ObsAdapterMode
    preparation: ObsPreparationPort
    control: ObsStreamingControlPort


def build_obs_adapter_bundle(config: ObsSubsystemConfig) -> ObsAdapterBundle:
    """Build OBS adapters without loading obsws-python unless real mode is selected."""

    if config.mode is ObsAdapterMode.FAKE:
        return ObsAdapterBundle(
            mode=config.mode,
            preparation=FakeObsPreparationAdapter(
                FakeObsPreparationConfig(
                    audio_source_states={
                        name: True for name in config.required_audio_sources
                    }
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
    if not config.password_env:
        raise ValueError("OBS password environment variable name is required")

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
            password_env=config.password_env,
            connect_timeout_seconds=config.connect_timeout_seconds,
            request_timeout_seconds=config.request_timeout_seconds,
        )
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
