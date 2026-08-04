from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

from app.domain.avatar_performance import (
    AvatarBlendMode,
    AvatarContinuity,
    AvatarInterruptPolicy,
    AvatarMotionIntent,
    AvatarPerformancePlan,
    AvatarPerformanceTrack,
    AvatarReturnBehavior,
    AvatarTrackChannel,
)
from app.domain.body import (
    BodyActivityContext,
    BodyExpressionRequest,
    BodyPostureTendency,
    EmbodiedExpressionIntent,
    SpeechPresentationRequest,
)
from app.domain.body_runtime import BodyRuntimeSnapshot
from app.ports.avatar_output import AvatarOutputPort
from app.runtime.body_expression_planner import BodyExpressionPlanner


@dataclass(frozen=True, slots=True)
class BodyRuntimeConfig:
    """Body Runtimeの実時間制御設定。"""

    tick_hz: float = 30.0
    expression_queue_limit: int = 32
    max_expressions_per_tick: int = 4
    autonomous_interval_ms: int = 2400
    baseline_refresh_ms: int = 30_000

    def __post_init__(self) -> None:
        if isinstance(self.tick_hz, bool) or not isinstance(self.tick_hz, (int, float)):
            raise TypeError("tick_hz must be a number")
        normalized_tick_hz = float(self.tick_hz)
        if not 1.0 <= normalized_tick_hz <= 120.0:
            raise ValueError("tick_hz must be between 1.0 and 120.0")
        object.__setattr__(self, "tick_hz", normalized_tick_hz)

        for field_name, minimum, maximum in (
            ("expression_queue_limit", 1, 1024),
            ("max_expressions_per_tick", 1, 32),
            ("autonomous_interval_ms", 250, 120_000),
            ("baseline_refresh_ms", 1000, 120_000),
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if not minimum <= value <= maximum:
                raise ValueError(
                    f"{field_name} must be between {minimum} and {maximum}"
                )

    @property
    def tick_interval_seconds(self) -> float:
        return 1.0 / self.tick_hz


class BodyRuntime:
    """LLMを呼ばずに常時稼働するBody SubsystemのインプロセスMVP。

    Activity文脈、人格的な身体表現要求、発話状態を保持し、30〜60fps相当の
    Tick LoopでAvatarPerformancePlanへコンパイルする。Avatar出力障害は診断状態へ
    記録するだけで、Coreや次のTickを停止しない。
    """

    def __init__(
        self,
        avatar_output: AvatarOutputPort | None,
        *,
        expression_planner: BodyExpressionPlanner | None = None,
        config: BodyRuntimeConfig | None = None,
        performance_id_factory: Callable[[], str] | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._avatar_output = avatar_output
        self._expression_planner = expression_planner or BodyExpressionPlanner()
        self._config = config or BodyRuntimeConfig()
        self._performance_id_factory = performance_id_factory or (
            lambda: str(uuid4())
        )
        self._monotonic = monotonic_clock
        self._sleep = sleep

        self._state_lock = asyncio.Lock()
        self._expression_queue: asyncio.PriorityQueue[
            tuple[int, int, BodyExpressionRequest]
        ] = asyncio.PriorityQueue(maxsize=self._config.expression_queue_limit)
        self._request_sequence = 0
        self._activity_context: BodyActivityContext | None = None
        self._context_dirty = False
        self._active_speech: SpeechPresentationRequest | None = None
        self._speech_started_at: float | None = None
        self._running = False
        self._stopping = False
        self._task: asyncio.Task[None] | None = None
        self._tick_count = 0
        self._last_baseline_at: float | None = None
        self._last_autonomous_at: float | None = None
        self._last_performance_id: str | None = None
        self._last_error: str | None = None

    async def start(self) -> None:
        """常駐Tick Loopを開始する。複数回呼んでもTaskを重複生成しない。"""

        async with self._state_lock:
            if self._task is not None and not self._task.done():
                return
            self._stopping = False
            self._running = True
            self._task = asyncio.create_task(
                self._run_loop(),
                name="body-runtime",
            )

    async def stop(self) -> None:
        """Tick Loopを停止する。Avatar出力の状態には依存しない。"""

        async with self._state_lock:
            task = self._task
            self._task = None
            self._stopping = True
            self._running = False
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def update_activity_context(self, context: BodyActivityContext) -> None:
        """Activityが維持する注意・姿勢・動きの方針を更新する。"""

        async with self._state_lock:
            self._activity_context = context
            self._context_dirty = True

    async def request_expression(self, request: BodyExpressionRequest) -> None:
        """人格的意味を持つ高レベル表現要求を優先度付きキューへ追加する。"""

        async with self._state_lock:
            self._request_sequence += 1
            sequence = self._request_sequence
        try:
            self._expression_queue.put_nowait((-request.priority, sequence, request))
        except asyncio.QueueFull:
            await self._record_error("expression_queue_full")

    async def present_speech(self, request: SpeechPresentationRequest) -> None:
        """生成済み音声の再生期間をBody状態へ登録する。

        このMVPでは音声Transportの再生自体はまだ行わない。共通再生時計を接続する
        前段として、発話の開始時刻・実時間・強調情報をBody内部で保持する。
        """

        async with self._state_lock:
            self._active_speech = request
            self._speech_started_at = self._monotonic()

    async def snapshot(self) -> BodyRuntimeSnapshot:
        """会話本文や音声データを含まない診断状態を返す。"""

        async with self._state_lock:
            return BodyRuntimeSnapshot(
                running=self._running,
                tick_count=self._tick_count,
                active_activity_id=(
                    self._activity_context.source_activity_id
                    if self._activity_context is not None
                    else None
                ),
                pending_expression_count=self._expression_queue.qsize(),
                active_speech_id=(
                    self._active_speech.presentation_id
                    if self._active_speech is not None
                    else None
                ),
                last_performance_id=self._last_performance_id,
                last_error=self._last_error,
            )

    async def tick_once(self, *, now: float | None = None) -> None:
        """Body状態を1回進める。テストと外部Loop統合でも利用できる。"""

        current_time = self._monotonic() if now is None else float(now)
        async with self._state_lock:
            self._tick_count += 1
            context = self._activity_context
            context_dirty = self._context_dirty
            if context_dirty:
                self._context_dirty = False
            self._expire_speech_locked(current_time)

        if context is not None and (
            context_dirty or self._baseline_is_due(current_time)
        ):
            baseline = self._build_baseline_plan(context)
            self._last_baseline_at = current_time
            if baseline is not None:
                await self._submit(baseline)

        for _ in range(self._config.max_expressions_per_tick):
            try:
                _, _, request = self._expression_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                performance = self._build_expression_plan(request, context)
                if performance is not None:
                    await self._submit(performance)
            finally:
                self._expression_queue.task_done()

        if self._autonomous_is_due(current_time):
            self._last_autonomous_at = current_time
            await self._submit(self._build_autonomous_plan(context))

    async def _run_loop(self) -> None:
        try:
            while True:
                async with self._state_lock:
                    if self._stopping:
                        return
                started_at = self._monotonic()
                try:
                    await self.tick_once(now=started_at)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # pragma: no cover - safety net
                    await self._record_exception(exc)
                elapsed = max(0.0, self._monotonic() - started_at)
                await self._sleep(
                    max(0.0, self._config.tick_interval_seconds - elapsed)
                )
        finally:
            async with self._state_lock:
                self._running = False

    def _build_expression_plan(
        self,
        request: BodyExpressionRequest,
        context: BodyActivityContext | None,
    ) -> AvatarPerformancePlan | None:
        duration_ms = request.duration_hint_ms or 1600
        tracks = self._expression_planner.compile(
            request,
            activity_context=context,
            segment_index=0,
            start_offset_ms=0,
            duration_ms=duration_ms,
        )
        if not tracks:
            return None
        return AvatarPerformancePlan(
            performance_id=self._performance_id_factory(),
            source_activity_id=request.source_activity_id,
            output_unit_id=request.output_unit_id,
            priority=request.priority,
            tracks=tracks,
            interrupt_policy=AvatarInterruptPolicy.REPLACE_LOWER_PRIORITY,
            return_behavior=AvatarReturnBehavior.HOLD,
        )

    def _build_baseline_plan(
        self,
        context: BodyActivityContext,
    ) -> AvatarPerformancePlan | None:
        duration_ms = min(
            120_000,
            max(1000, self._config.baseline_refresh_ms * 2),
        )
        request = BodyExpressionRequest(
            source_activity_id=context.source_activity_id,
            output_unit_id="body-activity-context",
            expression=EmbodiedExpressionIntent(),
            priority=20,
            duration_hint_ms=duration_ms,
        )
        tracks = list(
            self._expression_planner.compile(
                request,
                activity_context=context,
                segment_index=0,
                start_offset_ms=0,
                duration_ms=duration_ms,
            )
        )
        posture_track = self._posture_track(context, duration_ms)
        if posture_track is not None:
            tracks.append(posture_track)
        if not tracks:
            return None
        return AvatarPerformancePlan(
            performance_id=self._performance_id_factory(),
            source_activity_id=context.source_activity_id,
            output_unit_id="body-activity-context",
            priority=20,
            tracks=tuple(tracks),
            interrupt_policy=AvatarInterruptPolicy.REPLACE_LOWER_PRIORITY,
            return_behavior=AvatarReturnBehavior.HOLD,
        )

    def _build_autonomous_plan(
        self,
        context: BodyActivityContext | None,
    ) -> AvatarPerformancePlan:
        energy = context.movement_energy if context is not None else 0.25
        activity_id = (
            context.source_activity_id if context is not None else "body-autonomous"
        )
        duration_ms = min(
            120_000,
            max(500, self._config.autonomous_interval_ms * 2),
        )
        tracks: list[AvatarPerformanceTrack] = [
            AvatarPerformanceTrack(
                track_id="autonomous-breathing",
                channel=AvatarTrackChannel.AUTONOMOUS,
                start_offset_ms=0,
                duration_ms=duration_ms,
                fade_in_ms=min(300, duration_ms),
                fade_out_ms=min(300, duration_ms),
                blend_mode=AvatarBlendMode.ADDITIVE,
                continuity=AvatarContinuity.CURRENT,
                hold=False,
                layer_priority=-100,
                motion=AvatarMotionIntent(
                    name="breathing",
                    intensity=min(1.0, 0.35 + energy * 0.45),
                    amplitude=min(1.5, 0.12 + energy * 0.28),
                    tempo=min(3.0, 0.65 + energy * 0.55),
                    repetitions=2,
                    body_participation=1.0,
                ),
            )
        ]
        if energy >= 0.15:
            tracks.append(
                AvatarPerformanceTrack(
                    track_id="autonomous-micro-sway",
                    channel=AvatarTrackChannel.AUTONOMOUS,
                    start_offset_ms=min(180, duration_ms // 6),
                    duration_ms=max(100, duration_ms - min(180, duration_ms // 6)),
                    fade_in_ms=min(350, duration_ms),
                    fade_out_ms=min(350, duration_ms),
                    blend_mode=AvatarBlendMode.ADDITIVE,
                    continuity=AvatarContinuity.CURRENT,
                    hold=False,
                    layer_priority=-110,
                    motion=AvatarMotionIntent(
                        name="micro_sway",
                        intensity=min(1.0, energy),
                        amplitude=min(1.5, 0.08 + energy * 0.2),
                        tempo=min(3.0, 0.4 + energy * 0.45),
                        repetitions=1,
                        body_participation=1.0,
                    ),
                )
            )
        return AvatarPerformancePlan(
            performance_id=self._performance_id_factory(),
            source_activity_id=activity_id,
            output_unit_id="body-autonomous",
            priority=0,
            tracks=tuple(tracks),
            interrupt_policy=AvatarInterruptPolicy.IGNORE_IF_BUSY,
            return_behavior=AvatarReturnBehavior.HOLD,
        )

    @staticmethod
    def _posture_track(
        context: BodyActivityContext,
        duration_ms: int,
    ) -> AvatarPerformanceTrack | None:
        posture_names = {
            BodyPostureTendency.OPEN: "posture_open",
            BodyPostureTendency.CLOSED: "posture_closed",
            BodyPostureTendency.FORWARD: "posture_forward",
            BodyPostureTendency.WITHDRAWN: "posture_withdrawn",
        }
        name = posture_names.get(context.posture_tendency)
        if name is None:
            return None
        return AvatarPerformanceTrack(
            track_id="activity-posture",
            channel=AvatarTrackChannel.TORSO,
            start_offset_ms=0,
            duration_ms=duration_ms,
            fade_in_ms=min(600, duration_ms),
            fade_out_ms=min(600, duration_ms),
            blend_mode=AvatarBlendMode.OVERRIDE,
            continuity=AvatarContinuity.CURRENT,
            hold=True,
            layer_priority=30,
            motion=AvatarMotionIntent(
                name=name,
                intensity=min(1.0, 0.35 + context.engagement * 0.45),
                amplitude=min(1.5, 0.1 + context.movement_energy * 0.35),
                tempo=min(3.0, 0.35 + context.movement_energy * 0.45),
                repetitions=1,
                body_participation=1.0,
            ),
        )

    def _baseline_is_due(self, now: float) -> bool:
        return self._last_baseline_at is None or (
            now - self._last_baseline_at
            >= self._config.baseline_refresh_ms / 1000.0
        )

    def _autonomous_is_due(self, now: float) -> bool:
        return self._last_autonomous_at is None or (
            now - self._last_autonomous_at
            >= self._config.autonomous_interval_ms / 1000.0
        )

    def _expire_speech_locked(self, now: float) -> None:
        if self._active_speech is None or self._speech_started_at is None:
            return
        elapsed_ms = (now - self._speech_started_at) * 1000.0
        if elapsed_ms >= self._active_speech.duration_ms:
            self._active_speech = None
            self._speech_started_at = None

    async def _submit(self, performance: AvatarPerformancePlan) -> bool:
        if self._avatar_output is None:
            return False
        try:
            await self._avatar_output.submit_performance(performance)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._record_exception(exc)
            return False
        async with self._state_lock:
            self._last_performance_id = performance.performance_id
            self._last_error = None
        return True

    async def _record_exception(self, exc: Exception) -> None:
        await self._record_error(f"{type(exc).__name__}: {exc}"[:240])

    async def _record_error(self, message: str) -> None:
        async with self._state_lock:
            self._last_error = message[:240]
