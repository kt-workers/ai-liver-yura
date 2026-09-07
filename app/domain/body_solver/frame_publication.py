from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Lock

from app.domain.contracts.common import require_identifier, require_revision

from .contracts import BodyPoseFrame


class BodyFramePublicationFailureCode(str, Enum):
    MODEL_MISMATCH = "model_mismatch"
    STALE_REVISION = "stale_revision"


class BodyFramePublicationError(ValueError):
    def __init__(self, code: BodyFramePublicationFailureCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True, slots=True)
class BodyFrameTakeResult:
    frame: BodyPoseFrame | None
    coalesced_frames: int

    def __post_init__(self) -> None:
        if self.frame is not None and not isinstance(self.frame, BodyPoseFrame):
            raise ValueError("frame が不正です")
        if type(self.coalesced_frames) is not int or self.coalesced_frames < 0:
            raise ValueError("coalesced_frames は0以上の整数でなければなりません")


class LatestBodyFrameBuffer:
    """遅い出力先へ過去frameを蓄積せず、最新frameだけを保持する。"""

    def __init__(self, body_model_id: str) -> None:
        require_identifier(body_model_id, "body_model_id")
        self._body_model_id = body_model_id
        self._latest: BodyPoseFrame | None = None
        self._last_published_revision: int | None = None
        self._coalesced_since_take = 0
        self._lock = Lock()

    @property
    def last_published_revision(self) -> int | None:
        with self._lock:
            return self._last_published_revision

    def peek_latest(self) -> BodyPoseFrame | None:
        with self._lock:
            return self._latest

    def publish(self, frame: BodyPoseFrame) -> None:
        if not isinstance(frame, BodyPoseFrame):
            raise ValueError("frame が不正です")
        if frame.body_model_id != self._body_model_id:
            raise BodyFramePublicationError(BodyFramePublicationFailureCode.MODEL_MISMATCH)
        require_revision(frame.body_state_revision, "body_state_revision")

        with self._lock:
            if (
                self._last_published_revision is not None
                and frame.body_state_revision <= self._last_published_revision
            ):
                raise BodyFramePublicationError(
                    BodyFramePublicationFailureCode.STALE_REVISION
                )
            if self._latest is not None:
                self._coalesced_since_take += 1
            self._latest = frame
            self._last_published_revision = frame.body_state_revision

    def take_latest(self) -> BodyFrameTakeResult:
        with self._lock:
            result = BodyFrameTakeResult(
                frame=self._latest,
                coalesced_frames=self._coalesced_since_take,
            )
            self._latest = None
            self._coalesced_since_take = 0
            return result
