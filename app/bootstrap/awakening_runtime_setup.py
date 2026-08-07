from __future__ import annotations

import os
from dataclasses import dataclass

from app.adapters.storage.json_awakening_snapshot_store import (
    JsonAwakeningSnapshotStore,
)
from app.domain.awakening import AwakeningCapabilities
from app.runtime.awakening_context_service import AwakeningContextService


@dataclass(frozen=True, slots=True)
class AwakeningRuntimeSettings:
    snapshot_path: str = "data/awakening_state.json"
    resume_window_seconds: float = 1800.0

    def __post_init__(self) -> None:
        path = self.snapshot_path.strip()
        if not path:
            raise ValueError("snapshot_path must not be empty")
        if self.resume_window_seconds <= 0.0:
            raise ValueError("resume_window_seconds must be positive")
        object.__setattr__(self, "snapshot_path", path)
        object.__setattr__(self, "resume_window_seconds", float(self.resume_window_seconds))

    @classmethod
    def from_env(cls) -> AwakeningRuntimeSettings:
        raw_window = os.getenv("YURA_AWAKENING_RESUME_WINDOW_SECONDS", "1800").strip()
        try:
            window = float(raw_window)
        except ValueError as error:
            raise ValueError(
                "YURA_AWAKENING_RESUME_WINDOW_SECONDS must be a number"
            ) from error
        return cls(
            snapshot_path=os.getenv(
                "YURA_AWAKENING_STATE_PATH",
                "data/awakening_state.json",
            ),
            resume_window_seconds=window,
        )


def create_awakening_context_service_from_env() -> AwakeningContextService:
    settings = AwakeningRuntimeSettings.from_env()
    return AwakeningContextService(
        JsonAwakeningSnapshotStore(settings.snapshot_path),
        resume_window_seconds=settings.resume_window_seconds,
    )


def build_awakening_capabilities(
    *,
    body_available: bool,
    tts_available: bool,
    conversation_output_available: bool,
) -> AwakeningCapabilities:
    return AwakeningCapabilities(
        body_available=bool(body_available),
        tts_available=bool(tts_available),
        conversation_output_available=bool(conversation_output_available),
    )


__all__ = [
    "AwakeningRuntimeSettings",
    "build_awakening_capabilities",
    "create_awakening_context_service_from_env",
]
