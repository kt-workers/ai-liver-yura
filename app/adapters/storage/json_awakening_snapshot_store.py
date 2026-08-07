from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path

from app.domain.awakening import (
    AWAKENING_SNAPSHOT_SCHEMA_VERSION,
    AwakeningDesireSnapshot,
    AwakeningDriveSnapshot,
    AwakeningEmotionSnapshot,
    AwakeningInnerStateSnapshot,
    AwakeningSnapshot,
    AwakeningSnapshotLoadResult,
    AwakeningSnapshotLoadStatus,
)


class JsonAwakeningSnapshotStore:
    """覚醒評価用の小さなSnapshotを原子的に保存するJSON Adapter。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> AwakeningSnapshotLoadResult:
        if not self._path.exists():
            return AwakeningSnapshotLoadResult(
                AwakeningSnapshotLoadStatus.MISSING,
                reason="snapshot_missing",
            )
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except JSONDecodeError:
            return AwakeningSnapshotLoadResult(
                AwakeningSnapshotLoadStatus.CORRUPT,
                reason="invalid_json",
            )
        except OSError as error:
            return AwakeningSnapshotLoadResult(
                AwakeningSnapshotLoadStatus.IO_ERROR,
                reason=f"read_failed:{type(error).__name__}",
            )
        if not isinstance(payload, dict):
            return AwakeningSnapshotLoadResult(
                AwakeningSnapshotLoadStatus.CORRUPT,
                reason="root_not_object",
            )
        if payload.get("schema_version") != AWAKENING_SNAPSHOT_SCHEMA_VERSION:
            return AwakeningSnapshotLoadResult(
                AwakeningSnapshotLoadStatus.VERSION_MISMATCH,
                reason="unsupported_schema_version",
            )
        try:
            snapshot = self._parse_snapshot(payload)
        except (KeyError, TypeError, ValueError):
            return AwakeningSnapshotLoadResult(
                AwakeningSnapshotLoadStatus.CORRUPT,
                reason="invalid_snapshot_payload",
            )
        return AwakeningSnapshotLoadResult(
            AwakeningSnapshotLoadStatus.LOADED,
            snapshot=snapshot,
            reason="snapshot_loaded",
        )

    def save(self, snapshot: AwakeningSnapshot) -> None:
        if not isinstance(snapshot, AwakeningSnapshot):
            raise TypeError("snapshot must be AwakeningSnapshot")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            dir=self._path.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(
                    snapshot.as_payload(),
                    file,
                    ensure_ascii=False,
                    indent=2,
                )
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, self._path)
        except BaseException:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
            raise

    @classmethod
    def _parse_snapshot(cls, payload: dict[str, object]) -> AwakeningSnapshot:
        inner = cls._mapping(payload["inner_state"])
        emotion = cls._mapping(inner["emotion"])
        reactive = cls._mapping(emotion.get("reactive", {}))
        drive = cls._mapping(inner["drive"])
        desire = cls._mapping(inner["desire"])
        return AwakeningSnapshot(
            shutdown_at=cls._datetime(payload["shutdown_at"]),
            inner_state=AwakeningInnerStateSnapshot(
                emotion=AwakeningEmotionSnapshot(
                    mood=str(emotion["mood"]),
                    arousal=cls._number(emotion["arousal"]),
                    valence=cls._number(emotion["valence"]),
                    talkativeness=cls._number(emotion["talkativeness"]),
                    joy=cls._number(reactive.get("joy", 0.0)),
                    amusement=cls._number(reactive.get("amusement", 0.0)),
                    anger=cls._number(reactive.get("anger", 0.0)),
                    sadness=cls._number(reactive.get("sadness", 0.0)),
                    fear=cls._number(reactive.get("fear", 0.0)),
                    surprise=cls._number(reactive.get("surprise", 0.0)),
                    discomfort=cls._number(reactive.get("discomfort", 0.0)),
                    emotional_pressure=cls._number(
                        reactive.get("emotional_pressure", 0.0)
                    ),
                ),
                drive=AwakeningDriveSnapshot(
                    curiosity=cls._number(drive["curiosity"]),
                    engagement=cls._number(drive["engagement"]),
                    boredom=cls._number(drive["boredom"]),
                    energy=cls._number(drive["energy"]),
                ),
                desire=AwakeningDesireSnapshot(
                    connection=cls._number(desire["connection"]),
                    curiosity=cls._number(desire["curiosity"]),
                    expression=cls._number(desire["expression"]),
                    recognition=cls._number(desire["recognition"]),
                    autonomy=cls._number(desire["autonomy"]),
                    security=cls._number(desire["security"]),
                    achievement=cls._number(desire["achievement"]),
                ),
            ),
        )

    @staticmethod
    def _mapping(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise TypeError("expected object")
        return {str(key): item for key, item in value.items()}

    @staticmethod
    def _datetime(value: object) -> datetime:
        if not isinstance(value, str):
            raise TypeError("expected ISO datetime string")
        return datetime.fromisoformat(value)

    @staticmethod
    def _number(value: object) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("expected number")
        return float(value)


__all__ = ["JsonAwakeningSnapshotStore"]
