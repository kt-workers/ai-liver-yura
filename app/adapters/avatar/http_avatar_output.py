from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.domain.avatar_performance import AvatarPerformancePlan, AvatarPerformanceTrack
from app.ports.avatar_output import AvatarGazeIntent

JsonSender = Callable[[str, bytes, float], None]


@dataclass(frozen=True, slots=True)
class HttpAvatarOutputConfig:
    """Avatar Runtime Web MVPへ接続するHTTP Adapter設定。"""

    base_url: str
    timeout_seconds: float = 3.0

    def __post_init__(self) -> None:
        normalized_url = self.base_url.strip().rstrip("/")
        if not normalized_url:
            raise ValueError("base_url must not be empty")
        if not normalized_url.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        object.__setattr__(self, "base_url", normalized_url)


class HttpAvatarOutput:
    """高レベルAvatar ActionをWeb MVPのHTTP DTOへ変換して送信する。"""

    def __init__(
        self,
        config: HttpAvatarOutputConfig,
        *,
        send_json: JsonSender | None = None,
    ) -> None:
        self._config = config
        self._send_json = send_json or self._post_json

    async def submit_performance(
        self,
        performance: AvatarPerformancePlan,
    ) -> None:
        await self._send(
            "/api/avatar/performances",
            {
                "schema_version": 2,
                "type": "avatar.performance.submit",
                "performance_id": performance.performance_id,
                "source_activity_id": performance.source_activity_id,
                "output_unit_id": performance.output_unit_id,
                "priority": performance.priority,
                "interrupt_policy": performance.interrupt_policy.value,
                "return_behavior": performance.return_behavior.value,
                "duration_ms": performance.duration_ms,
                "tracks": [self._track_payload(track) for track in performance.tracks],
                # 移行期間中は旧Runtime向けの直列Segmentも同時送信する。
                "segments": [
                    {
                        "expression": {
                            "name": segment.expression.name,
                            "intensity": segment.expression.intensity,
                        },
                        "gesture": (
                            {
                                "name": segment.gesture.name,
                                "intensity": segment.gesture.intensity,
                            }
                            if segment.gesture is not None
                            else None
                        ),
                        "gaze": (
                            {
                                "target": segment.gaze.target,
                                "behavior": segment.gaze.behavior,
                                "intensity": segment.gaze.intensity,
                            }
                            if segment.gaze is not None
                            else None
                        ),
                        "duration_ms": segment.duration_ms,
                        "fade_in_ms": segment.fade_in_ms,
                        "fade_out_ms": segment.fade_out_ms,
                    }
                    for segment in performance.segments
                ],
            },
        )

    @staticmethod
    def _track_payload(track: AvatarPerformanceTrack) -> dict[str, object]:
        intent: dict[str, object]
        if track.expression is not None:
            intent = {
                "type": "expression",
                "name": track.expression.name,
                "intensity": track.expression.intensity,
            }
        elif track.attention is not None:
            intent = {
                "type": "attention",
                "target": track.attention.target,
                "behavior": track.attention.behavior,
                "intensity": track.attention.intensity,
                "eye_follow": track.attention.eye_follow,
                "head_follow": track.attention.head_follow,
                "body_follow": track.attention.body_follow,
            }
        elif track.motion is not None:
            intent = {
                "type": "motion",
                "name": track.motion.name,
                "intensity": track.motion.intensity,
                "amplitude": track.motion.amplitude,
                "tempo": track.motion.tempo,
                "repetitions": track.motion.repetitions,
                "body_participation": track.motion.body_participation,
                "direction": track.motion.direction,
            }
        else:  # pragma: no cover - Domain validation prevents this.
            raise ValueError("avatar performance track has no intent")
        return {
            "track_id": track.track_id,
            "channel": track.channel.value,
            "start_offset_ms": track.start_offset_ms,
            "duration_ms": track.duration_ms,
            "fade_in_ms": track.fade_in_ms,
            "fade_out_ms": track.fade_out_ms,
            "blend_mode": track.blend_mode.value,
            "continuity": track.continuity.value,
            "hold": track.hold,
            "layer_priority": track.layer_priority,
            "intent": intent,
        }

    async def set_expression(self, expression: str) -> None:
        name = self._require_name(expression, "expression")
        await self._send(
            "/api/avatar/actions",
            {
                "schema_version": 1,
                "type": "avatar.action",
                "action": "expression",
                "name": name,
                "intensity": 1.0,
            },
        )

    async def play_gesture(self, gesture: str) -> None:
        name = self._require_name(gesture, "gesture")
        await self._send(
            "/api/avatar/actions",
            {
                "schema_version": 1,
                "type": "avatar.action",
                "action": "gesture",
                "name": name,
                "intensity": 1.0,
            },
        )

    async def set_gaze(self, gaze: AvatarGazeIntent) -> None:
        await self._send(
            "/api/avatar/actions",
            {
                "schema_version": 1,
                "type": "avatar.action",
                "action": "gaze",
                "target": gaze.target,
                "behavior": gaze.behavior,
                "intensity": gaze.intensity,
            },
        )

    async def _send(
        self,
        endpoint_path: str,
        payload: dict[str, object],
    ) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        endpoint = f"{self._config.base_url}{endpoint_path}"
        await asyncio.to_thread(
            self._send_json,
            endpoint,
            body,
            self._config.timeout_seconds,
        )

    @staticmethod
    def _require_name(value: str, field_name: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field_name} must not be empty")
        if len(normalized) > 80:
            raise ValueError(f"{field_name} must be 80 characters or fewer")
        return normalized

    @staticmethod
    def _post_json(url: str, body: bytes, timeout_seconds: float) -> None:
        request = Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if not 200 <= int(status) < 300:
                    raise RuntimeError(f"avatar runtime returned HTTP {status}")
        except HTTPError as error:
            raise RuntimeError(
                f"avatar runtime returned HTTP {error.code}"
            ) from error
        except URLError as error:
            raise RuntimeError("avatar runtime is unreachable") from error
