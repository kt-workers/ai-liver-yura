from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.domain.body_pose_frame import BodyPoseFrame

JsonSender = Callable[[str, bytes, float], None]


@dataclass(frozen=True, slots=True)
class HttpBodyPoseOutputConfig:
    """BodyPoseFrame受信先へ接続する暫定HTTP設定。"""

    base_url: str
    timeout_seconds: float = 1.0
    endpoint_path: str = "/api/body-pose-frame"

    def __post_init__(self) -> None:
        base_url = self.base_url.strip().rstrip("/")
        endpoint_path = self.endpoint_path.strip()
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        if self.timeout_seconds <= 0.0:
            raise ValueError("timeout_seconds must be greater than zero")
        if not endpoint_path.startswith("/"):
            raise ValueError("endpoint_path must start with /")
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "endpoint_path", endpoint_path)


class HttpBodyPoseFrameOutput:
    """Coreの最新BodyPoseFrameだけを非同期送信する。

    送信待ち中に次のFrameが到着した場合は古い未送信Frameを破棄し、Body Tickを
    HTTP待ちで停止させない。HTTPは検証用であり、正規Transportは後続の双方向
    ストリームへ置き換えられる。
    """

    def __init__(
        self,
        config: HttpBodyPoseOutputConfig,
        *,
        send_json: JsonSender | None = None,
    ) -> None:
        self._config = config
        self._send_json = send_json or self._post_json
        self._queue: asyncio.Queue[BodyPoseFrame] = asyncio.Queue(maxsize=1)
        self._worker: asyncio.Task[None] | None = None
        self._closed = False
        self._last_error: str | None = None
        self._sent_count = 0
        self._dropped_count = 0

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def sent_count(self) -> int:
        return self._sent_count

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    async def publish_body_pose_frame(self, frame: BodyPoseFrame) -> None:
        if self._closed:
            return
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(
                self._run(),
                name="http-body-pose-output",
            )
        if self._queue.full():
            with suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
                self._queue.task_done()
                self._dropped_count += 1
        self._queue.put_nowait(frame)

    async def close(self) -> None:
        self._closed = True
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker

    async def _run(self) -> None:
        while True:
            frame = await self._queue.get()
            try:
                await self._send(frame)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self._last_error = f"{type(error).__name__}: {error}"[:240]
            else:
                self._last_error = None
                self._sent_count += 1
            finally:
                self._queue.task_done()

    async def _send(self, frame: BodyPoseFrame) -> None:
        payload = {
            "type": "body.pose.frame",
            "source": "yura-core-state-driven-body",
            **frame.as_payload(),
        }
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        await asyncio.to_thread(
            self._send_json,
            f"{self._config.base_url}{self._config.endpoint_path}",
            body,
            self._config.timeout_seconds,
        )

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
                status = int(getattr(response, "status", 200))
                if not 200 <= status < 300:
                    raise RuntimeError(f"body pose runtime returned HTTP {status}")
        except HTTPError as error:
            raise RuntimeError(
                f"body pose runtime returned HTTP {error.code}"
            ) from error
        except URLError as error:
            raise RuntimeError("body pose runtime is unreachable") from error
