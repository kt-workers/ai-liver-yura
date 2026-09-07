"""本番の姿勢投影を、取消可能な模擬描画先で隣接検証する。"""

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from threading import Event, Lock, Thread
from time import monotonic_ns

from app.domain.body import CanonicalBodyModel
from app.domain.body_solver import BodyPoseFrame
from app.domain.contracts.common import JsonValue
from app.subsystems.avatar import (
    AvatarModelBinding,
    AvatarPresentationRuntime,
    AvatarProjectionCommand,
    AvatarRendererResult,
    AvatarRendererStatus,
    validate_avatar_model_binding,
)

from .body import _project
from .contracts import positive


@dataclass(frozen=True)
class BodyAvatarLabSettings:
    binding: AvatarModelBinding
    delay_s: float
    outcomes: tuple[AvatarRendererStatus, ...]
    binding_reloads: tuple[tuple[int, AvatarModelBinding], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.binding, AvatarModelBinding):
            raise ValueError("描画先の対応付けが不正です")
        if type(self.delay_s) not in (int, float) or not isfinite(self.delay_s) or self.delay_s < 0:
            raise ValueError("描画先の遅延は有限の非負秒数で指定してください")
        outcomes = tuple(self.outcomes)
        if not outcomes or any(not isinstance(value, AvatarRendererStatus) for value in outcomes):
            raise ValueError("描画先の応答列を公開型で指定してください")
        object.__setattr__(self, "outcomes", outcomes)
        reloads = tuple(self.binding_reloads)
        indices = []
        for index, binding in reloads:
            if type(index) is not int or index < 1 or not isinstance(binding, AvatarModelBinding):
                raise ValueError("描画先の交換は1以降の姿勢番号と対応付けで指定してください")
            indices.append(index)
        if indices != sorted(set(indices)):
            raise ValueError("描画先の交換番号は重複しない昇順で指定してください")
        object.__setattr__(self, "binding_reloads", reloads)

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "binding": asdict(self.binding),
                "delay_s": self.delay_s,
                "outcomes": self.outcomes,
                "binding_reloads": tuple(
                    (index, asdict(binding)) for index, binding in self.binding_reloads
                ),
            }
        )


class _InterruptibleRenderer:
    def __init__(self, settings: BodyAvatarLabSettings, stop: Event) -> None:
        self._settings, self._stop = settings, stop
        self.calls = 0
        self.latest_command: AvatarProjectionCommand | None = None

    def present(
        self, command: AvatarProjectionCommand, *, started_at: datetime
    ) -> AvatarRendererResult:
        index = self.calls
        self.calls += 1
        interrupted = self._stop.wait(self._settings.delay_s)
        status = (
            AvatarRendererStatus.UNAVAILABLE
            if interrupted
            else self._settings.outcomes[min(index, len(self._settings.outcomes) - 1)]
        )
        if status is AvatarRendererStatus.APPLIED:
            self.latest_command = command
        return AvatarRendererResult(status, datetime.now(timezone.utc))


class BodyAvatarLabSession:
    """身体側は本番の投入入口だけを呼び、描画の待機は別スレッドへ閉じる。"""

    def __init__(
        self, model: CanonicalBodyModel, settings: BodyAvatarLabSettings, *, max_reports: int
    ) -> None:
        positive(max_reports)
        validate_avatar_model_binding(settings.binding, model)
        for _, binding in settings.binding_reloads:
            validate_avatar_model_binding(binding, model)
        self._stop, self._wake = Event(), Event()
        self._lock = Lock()
        self._renderer = _InterruptibleRenderer(settings, self._stop)
        self._runtime = AvatarPresentationRuntime(model, settings.binding, self._renderer)
        self._reports: list[JsonValue] = []
        self._max_reports = max_reports
        self._binding_reloads = dict(settings.binding_reloads)
        self._submitted = 0
        self._worker_failed = False
        self._thread = Thread(target=self._consume, name="validation-body-avatar")
        self._thread.start()

    def submit(self, frame: BodyPoseFrame) -> None:
        replacement = self._binding_reloads.get(self._submitted)
        if replacement is not None:
            self._runtime.reload_binding(replacement)
        self._runtime.submit_frame(frame)
        self._submitted += 1
        self._wake.set()

    def _consume(self) -> None:
        try:
            while not self._stop.is_set():
                self._wake.wait()
                self._wake.clear()
                if self._stop.is_set():
                    break
                started = monotonic_ns()
                report = self._runtime.present_latest(started_at=datetime.now(timezone.utc))
                completed = monotonic_ns()
                if report is not None:
                    with self._lock:
                        if len(self._reports) >= self._max_reports:
                            raise ValueError("描画の観測数が上限に達しました")
                        self._reports.append(
                            _project(
                                {
                                    "started_ns": started,
                                    "completed_ns": completed,
                                    "report": asdict(report),
                                }
                            )
                        )
        except Exception:
            with self._lock:
                self._worker_failed = True

    async def close(self) -> None:
        self._stop.set()
        self._wake.set()
        await asyncio.to_thread(self._thread.join)

    def observation(self) -> JsonValue:
        with self._lock:
            reports = tuple(self._reports)
            failed = self._worker_failed
        command = self._renderer.latest_command
        return _project(
            {
                "reports": reports,
                "binding": asdict(self._runtime.binding),
                "worker_failed": failed,
                "pending_worker_count": int(self._thread.is_alive()),
                "pending_frame_count": self._runtime.pending_frame_count,
                "latest_command": None if command is None else command.to_dict(),
            }
        )
