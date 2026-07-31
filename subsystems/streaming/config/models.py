"""Root configuration owned by Streaming Subsystem."""

from dataclasses import dataclass
from pathlib import Path

from subsystems.streaming.config.obs import ObsSubsystemConfig
from subsystems.streaming.config.youtube import YouTubeSubsystemConfig


@dataclass(frozen=True, slots=True)
class StreamingSecretRefs:
    youtube_client_secret_path: str
    youtube_token_path: str
    obs_password: str


@dataclass(frozen=True, slots=True)
class StreamingSubsystemConfig:
    youtube: YouTubeSubsystemConfig = YouTubeSubsystemConfig()
    obs: ObsSubsystemConfig = ObsSubsystemConfig()
    source_path: Path | None = None

    @property
    def secret_refs(self) -> StreamingSecretRefs:
        return StreamingSecretRefs(
            youtube_client_secret_path=self.youtube.client_secret_path_ref,
            youtube_token_path=self.youtube.token_path_ref,
            obs_password=self.obs.password_ref,
        )
