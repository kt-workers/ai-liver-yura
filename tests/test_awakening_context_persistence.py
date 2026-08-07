from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.adapters.storage.json_awakening_snapshot_store import (
    JsonAwakeningSnapshotStore,
)
from app.bootstrap.awakening_runtime_setup import AwakeningRuntimeSettings
from app.domain.awakening import (
    AwakeningCapabilities,
    AwakeningSnapshotLoadResult,
    AwakeningSnapshotLoadStatus,
    AwakeningStartupKind,
)
from app.domain.desires import DesireState, DesireType
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState, MoodType, ReactiveEmotionState
from app.runtime.agent_state import AgentState
from app.runtime.awakening_context_service import AwakeningContextService

UTC = timezone.utc


def _capabilities() -> AwakeningCapabilities:
    return AwakeningCapabilities(
        body_available=True,
        tts_available=False,
        conversation_output_available=True,
    )


def _state() -> AgentState:
    desire = DesireState().with_value(
        DesireType.CURIOSITY,
        DesireState().curiosity.adjusted(level_delta=0.25),
    )
    return AgentState(
        current_emotion=EmotionState(
            mood=MoodType.EXCITED,
            arousal=0.78,
            valence=0.42,
            talkativeness=0.72,
            reactive=ReactiveEmotionState(joy=0.61, surprise=0.2),
        ),
        current_drive=DriveState(
            curiosity=0.84,
            engagement=0.76,
            boredom=0.08,
            energy=0.67,
        ),
        current_desire=desire,
    )


def test_missing_snapshot_becomes_safe_cold_start(tmp_path: Path) -> None:
    now = datetime(2026, 8, 7, 3, 0, tzinfo=UTC)
    service = AwakeningContextService(
        JsonAwakeningSnapshotStore(tmp_path / "missing.json"),
        clock=lambda: now,
    )

    context = service.begin(_capabilities())

    assert context.startup_kind is AwakeningStartupKind.COLD_START
    assert context.persistence_status is AwakeningSnapshotLoadStatus.MISSING
    assert context.previous_inner_state is None
    assert context.downtime_seconds is None


def test_short_downtime_is_resume_and_restores_snapshot_to_context(tmp_path: Path) -> None:
    path = tmp_path / "awakening.json"
    shutdown_at = datetime(2026, 8, 7, 3, 0, tzinfo=UTC)
    save_service = AwakeningContextService(
        JsonAwakeningSnapshotStore(path),
        clock=lambda: shutdown_at,
    )
    assert save_service.save_shutdown_snapshot(_state()) is True

    started_at = shutdown_at + timedelta(minutes=8)
    context = AwakeningContextService(
        JsonAwakeningSnapshotStore(path),
        clock=lambda: started_at,
        resume_window_seconds=1800,
    ).begin(_capabilities())

    assert context.startup_kind is AwakeningStartupKind.RESUME
    assert context.persistence_status is AwakeningSnapshotLoadStatus.LOADED
    assert context.downtime_seconds == pytest.approx(480.0)
    assert context.previous_inner_state is not None
    assert context.previous_inner_state.emotion.mood == "excited"
    assert context.previous_inner_state.drive.curiosity == pytest.approx(0.84)
    assert context.previous_inner_state.desire.curiosity > 0.5


def test_long_downtime_is_restart_not_resume(tmp_path: Path) -> None:
    path = tmp_path / "awakening.json"
    shutdown_at = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)
    service = AwakeningContextService(
        JsonAwakeningSnapshotStore(path),
        clock=lambda: shutdown_at,
    )
    assert service.save_shutdown_snapshot(_state()) is True

    context = AwakeningContextService(
        JsonAwakeningSnapshotStore(path),
        clock=lambda: shutdown_at + timedelta(hours=9),
        resume_window_seconds=1800,
    ).begin(_capabilities())

    assert context.startup_kind is AwakeningStartupKind.RESTART
    assert context.downtime_seconds == pytest.approx(9 * 3600)


def test_corrupt_snapshot_falls_back_without_raising(tmp_path: Path) -> None:
    path = tmp_path / "awakening.json"
    path.write_text("{broken", encoding="utf-8")

    context = AwakeningContextService(
        JsonAwakeningSnapshotStore(path),
        clock=lambda: datetime(2026, 8, 7, 3, 0, tzinfo=UTC),
    ).begin(_capabilities())

    assert context.startup_kind is AwakeningStartupKind.COLD_START
    assert context.persistence_status is AwakeningSnapshotLoadStatus.CORRUPT


def test_old_schema_falls_back_without_raising(tmp_path: Path) -> None:
    path = tmp_path / "awakening.json"
    path.write_text(
        json.dumps({"schema_version": 999, "shutdown_at": "unused"}),
        encoding="utf-8",
    )

    context = AwakeningContextService(
        JsonAwakeningSnapshotStore(path),
        clock=lambda: datetime(2026, 8, 7, 3, 0, tzinfo=UTC),
    ).begin(_capabilities())

    assert context.startup_kind is AwakeningStartupKind.COLD_START
    assert context.persistence_status is AwakeningSnapshotLoadStatus.VERSION_MISMATCH


def test_persisted_snapshot_contains_only_finite_inner_state_not_conversation(tmp_path: Path) -> None:
    path = tmp_path / "awakening.json"
    service = AwakeningContextService(
        JsonAwakeningSnapshotStore(path),
        clock=lambda: datetime(2026, 8, 7, 3, 0, tzinfo=UTC),
    )

    assert service.save_shutdown_snapshot(_state()) is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False)

    assert set(payload) == {"schema_version", "shutdown_at", "inner_state"}
    assert set(payload["inner_state"]) == {"emotion", "drive", "desire"}
    for prohibited in (
        "conversation",
        "speech",
        "prompt",
        "user_text",
        "pose",
        "activity",
        "relationship",
    ):
        assert prohibited not in serialized.lower()


class _BrokenStore:
    def load(self) -> AwakeningSnapshotLoadResult:
        raise OSError("unavailable")

    def save(self, snapshot: object) -> None:
        raise OSError("unavailable")


def test_store_failure_does_not_make_startup_or_shutdown_fatal() -> None:
    now = datetime(2026, 8, 7, 3, 0, tzinfo=UTC)
    service = AwakeningContextService(_BrokenStore(), clock=lambda: now)  # type: ignore[arg-type]

    context = service.begin(_capabilities())
    saved = service.save_shutdown_snapshot(_state())

    assert context.startup_kind is AwakeningStartupKind.COLD_START
    assert context.persistence_status is AwakeningSnapshotLoadStatus.IO_ERROR
    assert saved is False


def test_runtime_settings_are_typed_and_environment_overridable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YURA_AWAKENING_STATE_PATH", "tmp/yura-awakening.json")
    monkeypatch.setenv("YURA_AWAKENING_RESUME_WINDOW_SECONDS", "900")

    settings = AwakeningRuntimeSettings.from_env()

    assert settings.snapshot_path == "tmp/yura-awakening.json"
    assert settings.resume_window_seconds == 900.0
