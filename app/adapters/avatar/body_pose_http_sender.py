from __future__ import annotations

import asyncio
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.adapters.avatar.body_pose_frame_json_encoder import BodyPoseFrameJsonEncoder
from app.adapters.avatar.body_pose_http_config import HttpBodyPoseOutputConfig
from app.domain.body_pose_frame import BodyPoseFrame

JsonPoster = Callable[[str, bytes, float], None]


class BodyPoseHttpSender:
    """1件のBodyPoseFrameをHTTPで送信する。BufferやWorker状態は持たない。"""

    def __init__(
        self,
        config: HttpBodyPoseOutputConfig,
        *,
        encoder: BodyPoseFrameJsonEncoder | None = None,
        post_json: JsonPoster | None = None,
    ) -> None:
        if not isinstance(config, HttpBodyPoseOutputConfig):
            raise TypeError("config must be HttpBodyPoseOutputConfig")
        self._config = config
        self._encoder = encoder or BodyPoseFrameJsonEncoder()
        self._post_json = post_json or self._blocking_post_json

    async def send(self, frame: BodyPoseFrame) -> None:
        body = self._encoder.encode(
            frame,
            source_name=self._config.source_name,
        )
        await asyncio.to_thread(
            self._post_json,
            self._config.endpoint_url,
            body,
            self._config.timeout_seconds,
        )

    @staticmethod
    def _blocking_post_json(
        url: str,
        body: bytes,
        timeout_seconds: float,
    ) -> None:
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
                status = int(getattr(response, "status", 200))
                if not 200 <= status < 300:
                    raise RuntimeError(
                        f"body pose runtime returned HTTP {status}"
                    )
        except HTTPError as error:
            raise RuntimeError(
                f"body pose runtime returned HTTP {error.code}"
            ) from error
        except URLError as error:
            raise RuntimeError("body pose runtime is unreachable") from error
