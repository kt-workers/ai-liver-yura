from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from time import time_ns
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from app.adapters.avatar.body_pose_frame_json_encoder import BodyPoseFrameJsonEncoder
from app.adapters.avatar.body_pose_http_config import HttpBodyPoseOutputConfig
from app.domain.body_pose_frame import BodyPoseFrame


@dataclass(frozen=True, slots=True)
class BodyPoseHttpSendReceipt:
    accepted: bool
    http_status: int | None = None
    reason: str | None = None


JsonPoster = Callable[[str, bytes, float], BodyPoseHttpSendReceipt | None]


class BodyPoseHttpSender:
    """1件のBodyPoseFrameをHTTPで送信する。BufferやWorker状態は持たない。"""

    def __init__(
        self,
        config: HttpBodyPoseOutputConfig,
        *,
        encoder: BodyPoseFrameJsonEncoder | None = None,
        post_json: JsonPoster | None = None,
        producer_instance_id: str | None = None,
        producer_started_at_ms: int | None = None,
    ) -> None:
        if not isinstance(config, HttpBodyPoseOutputConfig):
            raise TypeError("config must be HttpBodyPoseOutputConfig")
        self._config = config
        self._encoder = encoder or BodyPoseFrameJsonEncoder()
        self._post_json = post_json or self._blocking_post_json
        self._producer_instance_id = (
            producer_instance_id.strip()
            if isinstance(producer_instance_id, str) and producer_instance_id.strip()
            else f"body-runtime-{uuid4()}"
        )
        self._producer_started_at_ms = (
            producer_started_at_ms
            if producer_started_at_ms is not None
            else time_ns() // 1_000_000
        )
        if (
            isinstance(self._producer_started_at_ms, bool)
            or not isinstance(self._producer_started_at_ms, int)
            or self._producer_started_at_ms < 0
        ):
            raise ValueError("producer_started_at_ms must be a non-negative integer")

    @property
    def producer_instance_id(self) -> str:
        return self._producer_instance_id

    @property
    def producer_started_at_ms(self) -> int:
        return self._producer_started_at_ms

    async def send(self, frame: BodyPoseFrame) -> BodyPoseHttpSendReceipt:
        body = self._encoder.encode(
            frame,
            source_name=self._config.source_name,
            producer_instance_id=self._producer_instance_id,
            producer_started_at_ms=self._producer_started_at_ms,
        )
        receipt = await asyncio.to_thread(
            self._post_json,
            self._config.endpoint_url,
            body,
            self._config.timeout_seconds,
        )
        if receipt is None:
            return BodyPoseHttpSendReceipt(accepted=True)
        if not isinstance(receipt, BodyPoseHttpSendReceipt):
            raise TypeError("body pose HTTP poster returned an invalid receipt")
        return receipt

    @staticmethod
    def _blocking_post_json(
        url: str,
        body: bytes,
        timeout_seconds: float,
    ) -> BodyPoseHttpSendReceipt:
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
                raw_body = response.read()
        except HTTPError as error:
            raise RuntimeError(
                f"body pose runtime returned HTTP {error.code}"
            ) from error
        except URLError as error:
            raise RuntimeError("body pose runtime is unreachable") from error

        if not raw_body:
            return BodyPoseHttpSendReceipt(accepted=True, http_status=status)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return BodyPoseHttpSendReceipt(accepted=True, http_status=status)
        if not isinstance(payload, dict):
            return BodyPoseHttpSendReceipt(accepted=True, http_status=status)
        if payload.get("status") == "ignored":
            reason = payload.get("reason")
            return BodyPoseHttpSendReceipt(
                accepted=False,
                http_status=status,
                reason=reason if isinstance(reason, str) else "ignored",
            )
        return BodyPoseHttpSendReceipt(accepted=True, http_status=status)
