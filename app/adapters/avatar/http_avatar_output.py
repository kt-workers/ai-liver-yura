from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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

    async def set_expression(self, expression: str) -> None:
        name = self._require_name(expression, "expression")
        await self._send(
            {
                "schema_version": 1,
                "type": "avatar.action",
                "action": "expression",
                "name": name,
                "intensity": 1.0,
            }
        )

    async def play_gesture(self, gesture: str) -> None:
        name = self._require_name(gesture, "gesture")
        await self._send(
            {
                "schema_version": 1,
                "type": "avatar.action",
                "action": "gesture",
                "name": name,
                "intensity": 1.0,
            }
        )

    async def set_gaze(self, gaze: AvatarGazeIntent) -> None:
        await self._send(
            {
                "schema_version": 1,
                "type": "avatar.action",
                "action": "gaze",
                "target": gaze.target,
                "behavior": gaze.behavior,
                "intensity": gaze.intensity,
            }
        )

    async def _send(self, payload: dict[str, object]) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        endpoint = f"{self._config.base_url}/api/avatar/actions"
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
