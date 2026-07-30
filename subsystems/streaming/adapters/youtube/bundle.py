"""YouTube Adapter bundle selection inside Streaming Subsystem."""

from dataclasses import dataclass

from subsystems.streaming.adapters.youtube.contracts import (
    YouTubeLiveChatReadPort,
    YouTubePreparationPort,
    YouTubeStreamingControlPort,
)
from subsystems.streaming.adapters.youtube.fake_youtube import (
    FakeLiveChatAdapter,
    FakeYouTubePreparationAdapter,
    FakeYouTubePreparationConfig,
    FakeYouTubeStreamingControlAdapter,
    UnavailableYouTubePreparationAdapter,
    UnavailableYouTubeStreamingControlAdapter,
)
from subsystems.streaming.config.youtube import (
    YouTubeAdapterMode,
    YouTubeSubsystemConfig,
)


@dataclass(frozen=True, slots=True)
class YouTubeAdapterBundle:
    mode: YouTubeAdapterMode
    preparation: YouTubePreparationPort
    control: YouTubeStreamingControlPort
    live_chat: YouTubeLiveChatReadPort


def build_youtube_adapter_bundle(
    config: YouTubeSubsystemConfig,
) -> YouTubeAdapterBundle:
    if config.mode is YouTubeAdapterMode.FAKE:
        return YouTubeAdapterBundle(
            mode=config.mode,
            preparation=FakeYouTubePreparationAdapter(
                FakeYouTubePreparationConfig()
            ),
            control=FakeYouTubeStreamingControlAdapter(),
            live_chat=FakeLiveChatAdapter(),
        )

    if config.mode is YouTubeAdapterMode.DISABLED:
        reason = "youtube_subsystem_disabled"
        return YouTubeAdapterBundle(
            mode=config.mode,
            preparation=UnavailableYouTubePreparationAdapter(
                reason,
                adapter_type="disabled",
            ),
            control=UnavailableYouTubeStreamingControlAdapter(reason),
            live_chat=FakeLiveChatAdapter(),
        )

    if not config.client_secret_path_env or not config.token_path_env:
        raise ValueError("google youtube environment variable names are required")

    from subsystems.streaming.adapters.youtube.client import (
        GoogleYouTubeClientConfig,
        GoogleYouTubeClientFactory,
    )
    from subsystems.streaming.adapters.youtube.control import (
        GoogleYouTubeStreamingControlAdapter,
    )
    from subsystems.streaming.adapters.youtube.google_youtube import (
        GoogleYouTubePreparationAdapter,
        GoogleYouTubePreparationConfig,
    )
    from subsystems.streaming.adapters.youtube.live_chat import (
        GoogleYouTubeLiveChatAdapter,
    )
    from subsystems.streaming.adapters.youtube.oauth import (
        GoogleYouTubeAuthConfig,
        GoogleYouTubeAuthService,
    )

    auth = GoogleYouTubeAuthService(
        GoogleYouTubeAuthConfig(
            client_secret_path_env=config.client_secret_path_env,
            token_path_env=config.token_path_env,
            request_timeout_seconds=config.request_timeout_seconds,
            open_browser=config.oauth_open_browser,
            oauth_timeout_seconds=config.oauth_timeout_seconds,
        )
    )
    client = GoogleYouTubeClientFactory(
        auth,
        GoogleYouTubeClientConfig(
            request_timeout_seconds=config.request_timeout_seconds
        ),
    )
    preparation = GoogleYouTubePreparationAdapter(
        auth_service=auth,
        client_factory=client,
        config=GoogleYouTubePreparationConfig(
            max_retries=config.max_retries,
            retry_initial_delay_seconds=config.retry_initial_delay_seconds,
            allow_live_broadcast=config.allow_live_broadcast,
            allowed_privacy_statuses=config.allowed_privacy_statuses,
        ),
    )
    return YouTubeAdapterBundle(
        mode=config.mode,
        preparation=preparation,
        control=GoogleYouTubeStreamingControlAdapter(client, preparation),
        live_chat=GoogleYouTubeLiveChatAdapter(client),
    )
