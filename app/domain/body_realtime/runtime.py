"""#340のbounded realtime lane。#339へのoverlay publicationはPortで分離する。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.body import BodyState
from app.domain.body_expression import BodyExpressionContext

from .contracts import BodyGazeTargetView, RealtimeOverlayBundle, RealtimeSpeechView
from .engine import BodyRealtimeEngine


@dataclass(frozen=True, slots=True)
class RealtimeTickInput:
    body_state: BodyState
    expression: BodyExpressionContext | None
    gaze_target: BodyGazeTargetView | None
    speech: RealtimeSpeechView | None

    def __post_init__(self) -> None:
        if not isinstance(self.body_state, BodyState):
            raise ValueError("body_stateが不正です")
        if self.expression is not None and not isinstance(self.expression, BodyExpressionContext):
            raise ValueError("expressionが不正です")
        if self.gaze_target is not None and not isinstance(self.gaze_target, BodyGazeTargetView):
            raise ValueError("gaze_targetが不正です")
        if self.speech is not None and not isinstance(self.speech, RealtimeSpeechView):
            raise ValueError("speechが不正です")


RealtimeInputReadPort = Callable[[], RealtimeTickInput]
RealtimeOverlayPublishPort = Callable[[RealtimeOverlayBundle], None]


class BodyRealtimeRuntime:
    """停止可能な単一lane。遅延tickをcatch-up burstへ展開しない。"""

    def __init__(
        self,
        engine: BodyRealtimeEngine,
        read_input: RealtimeInputReadPort,
        publish_overlay: RealtimeOverlayPublishPort,
        *,
        target_interval_s: float = 1 / 60,
    ) -> None:
        if not isinstance(engine, BodyRealtimeEngine):
            raise ValueError("engineが不正です")
        if not callable(read_input) or not callable(publish_overlay):
            raise ValueError("realtime Portが不正です")
        if type(target_interval_s) not in (int, float) or not 0 < target_interval_s <= 1:
            raise ValueError("target_interval_sが不正です")
        self._engine = engine
        self._read_input = read_input
        self._publish_overlay = publish_overlay
        self._interval = float(target_interval_s)
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._late_tick_count = 0

    @property
    def pending_task_count(self) -> int:
        return int(self._task is not None and not self._task.done())

    @property
    def late_tick_count(self) -> int:
        return self._late_tick_count

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("closed realtime runtimeは再開できません")
        if self.pending_task_count:
            return
        self._task = asyncio.create_task(self._run(), name="body-realtime")

    async def close(self) -> None:
        self._closed = True
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        next_tick = loop.time()
        while not self._closed:
            now = datetime.now(timezone.utc)
            value = self._read_input()
            overlay = self._engine.tick(
                body_state=value.body_state,
                expression=value.expression,
                gaze_target=value.gaze_target,
                speech=value.speech,
                now=now,
            )
            self._publish_overlay(overlay)
            next_tick += self._interval
            delay = next_tick - loop.time()
            if delay <= 0:
                self._late_tick_count += 1
                next_tick = loop.time() + self._interval
                await asyncio.sleep(0)
            else:
                await asyncio.sleep(delay)
