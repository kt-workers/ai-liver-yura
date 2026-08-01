from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ObsAudioSourceState:
    source_name: str
    exists: bool
    muted: bool | None = None
    volume_db: float | None = None
    monitoring_type: str | None = None
    active: bool | None = None

    @property
    def usable(self) -> bool:
        return self.exists and self.muted is False and self.active is not False


@dataclass(frozen=True, slots=True)
class ObsSourceVisibility:
    source_name: str
    exists: bool
    visible: bool
    paths: tuple[str, ...] = ()
    ambiguous: bool = False


@dataclass(frozen=True, slots=True)
class ObsInspection:
    obs_version: str
    websocket_version: str
    output_status: str
    scene_collection: str
    current_scene: str
    audio_sources: tuple[ObsAudioSourceState, ...]
    avatar: ObsSourceVisibility


@dataclass(frozen=True, slots=True)
class ObsPreparationSnapshot:
    """Subsystem-owned preparation snapshot compatible with the legacy port."""

    connected: bool
    output_status: str
    current_scene: str
    current_scene_collection: str
    audio_source_states: dict[str, bool]
    avatar_source_visible: bool
    obs_version: str | None = None
    websocket_version: str | None = None
    audio_source_details: dict[str, dict[str, object]] = field(default_factory=dict)
    avatar_source_exists: bool = True
    avatar_source_paths: tuple[str, ...] = ()
    adapter_type: str = "fake"


class ObsPreparationPort(Protocol):
    adapter_type: str

    async def health_check(self) -> bool: ...

    async def snapshot(self) -> ObsPreparationSnapshot: ...


class ObsStreamingControlPort(Protocol):
    adapter_type: str

    async def start_stream(self) -> None: ...

    async def stop_stream(self) -> None: ...

    async def get_output_status(self) -> str: ...

    async def get_connection_status(self) -> str: ...

    async def disconnect(self) -> None: ...
