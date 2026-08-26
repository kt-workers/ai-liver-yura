"""#340の短時間・決定論的なRealtime overlay生成。BodyStateは変更しない。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite, pi, sin

from app.adapters.tts.contracts import SpeechTimingKind, SpeechTimingUnit
from app.domain.body import BodyState
from app.domain.body_expression import BodyExpressionAxis, BodyExpressionContext

from .contracts import (
    BlinkPhase,
    BodyGazeTargetView,
    ChannelOverlay,
    RealtimeChannel,
    RealtimeLayer,
    RealtimeLayerState,
    RealtimeLayerStatus,
    RealtimeOverlayBundle,
    RealtimeSpeechView,
    articulation_for,
)


@dataclass(slots=True)
class _LocalState:
    last_monotonic_tick_s: float | None = None
    gaze_x: float = 0.0
    gaze_y: float = 0.0
    gaze_strength: float = 0.0
    blink_phase: BlinkPhase = BlinkPhase.OPEN
    blink_progress: float = 0.0
    blink_elapsed: float = 0.0
    next_blink_after_s: float = 2.0
    breath_phase: float = 0.0
    breath_amplitude: float = 0.5
    breath_tempo: float = 1.0
    articulation: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    speech_presentation_id: str | None = None
    speech_monotonic_anchor_s: float | None = None
    subtle_phase: float = 0.0


class BodyRealtimeEngine:
    """外部I/O・await・BodyState書込みを持たない、runtime lane用の局所状態機械。"""

    def __init__(self, *, seed: int = 0, target_interval_s: float = 1 / 60) -> None:
        if (
            type(seed) is not int
            or type(target_interval_s) not in (int, float)
            or not 0 < target_interval_s <= 1
        ):
            raise ValueError("realtime engine設定が不正です")
        initial_blink = 2.0 + (float(seed % 101) / 100 - 0.5)
        self._state = _LocalState(
            subtle_phase=float(seed % 997) / 997 * 2 * pi,
            next_blink_after_s=initial_blink,
        )
        self._seed = seed
        self._target_interval_s = float(target_interval_s)
        self._sequence = 0

    @property
    def target_interval_s(self) -> float:
        return self._target_interval_s

    def tick(
        self,
        *,
        body_state: BodyState,
        expression: BodyExpressionContext | None,
        gaze_target: BodyGazeTargetView | None,
        speech: RealtimeSpeechView | None,
        now: datetime,
        monotonic_now_s: float | None = None,
    ) -> RealtimeOverlayBundle:
        if not isinstance(body_state, BodyState):
            raise ValueError("body_stateが不正です")
        if expression is not None and not isinstance(expression, BodyExpressionContext):
            raise ValueError("expressionが不正です")
        if gaze_target is not None and not isinstance(gaze_target, BodyGazeTargetView):
            raise ValueError("gaze_targetが不正です")
        if speech is not None and not isinstance(speech, RealtimeSpeechView):
            raise ValueError("speechが不正です")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("nowはtimezone-awareである必要があります")
        elapsed = self._elapsed(monotonic_now_s)
        overlays: list[ChannelOverlay] = []
        states: list[RealtimeLayerState] = []
        self._gaze(overlays, states, gaze_target, elapsed)
        self._blink(overlays, states, elapsed)
        self._breath(overlays, states, expression, elapsed)
        self._speech(overlays, states, speech, now, elapsed, monotonic_now_s)
        self._subtle(overlays, states, expression, elapsed)
        states.append(
            RealtimeLayerState(RealtimeLayer.POSTURE_ASSIST, RealtimeLayerStatus.INACTIVE_NO_SOURCE)
        )
        self._sequence += 1
        return RealtimeOverlayBundle(
            f"realtime-overlay-{self._sequence}",
            body_state.revision,
            None if expression is None else expression.revision,
            None if gaze_target is None else gaze_target.source_attention_revision,
            None if speech is None else speech.presentation.presentation_id,
            now,
            elapsed * 1000,
            abs(elapsed - self._target_interval_s) * 1000,
            tuple(overlays),
            tuple(states),
        )

    def _elapsed(self, monotonic_now_s: float | None) -> float:
        if monotonic_now_s is None:
            return self._target_interval_s
        if type(monotonic_now_s) not in (int, float) or not isfinite(monotonic_now_s):
            raise ValueError("monotonic_now_sが不正です")
        previous = self._state.last_monotonic_tick_s
        self._state.last_monotonic_tick_s = float(monotonic_now_s)
        if previous is None:
            return self._target_interval_s
        return max(float(monotonic_now_s) - previous, 0.0)

    def _add(
        self,
        values: list[ChannelOverlay],
        layer: RealtimeLayer,
        channel: RealtimeChannel,
        value: float,
        strength: float,
        priority: int,
    ) -> None:
        values.append(
            ChannelOverlay(
                f"{layer.value}-{self._sequence}-{channel.value}",
                layer,
                channel,
                value,
                strength,
                priority,
            )
        )

    def _gaze(
        self,
        overlays: list[ChannelOverlay],
        states: list[RealtimeLayerState],
        target: BodyGazeTargetView | None,
        elapsed: float,
    ) -> None:
        if target is None or not target.has_spatial_target:
            release = min(1.0, elapsed * 8.0)
            self._state.gaze_x += (0.0 - self._state.gaze_x) * release
            self._state.gaze_y += (0.0 - self._state.gaze_y) * release
            self._state.gaze_strength += (0.0 - self._state.gaze_strength) * release
            if abs(self._state.gaze_x) > 1e-6 or abs(self._state.gaze_y) > 1e-6:
                self._add(
                    overlays,
                    RealtimeLayer.GAZE,
                    RealtimeChannel.GAZE_X,
                    self._state.gaze_x,
                    self._state.gaze_strength,
                    90,
                )
                self._add(
                    overlays,
                    RealtimeLayer.GAZE,
                    RealtimeChannel.GAZE_Y,
                    self._state.gaze_y,
                    self._state.gaze_strength,
                    90,
                )
            states.append(
                RealtimeLayerState(
                    RealtimeLayer.GAZE,
                    RealtimeLayerStatus.DEGRADED
                    if target
                    else RealtimeLayerStatus.INACTIVE_NO_SOURCE,
                    None if target is None else target.target_ref,
                    "spatial_target_unavailable",
                )
            )
            return
        step = min(1.0, elapsed * 8.0)
        self._state.gaze_x += (target.horizontal - self._state.gaze_x) * step  # type: ignore[operator]
        self._state.gaze_y += (target.vertical - self._state.gaze_y) * step  # type: ignore[operator]
        self._state.gaze_strength += (target.confidence - self._state.gaze_strength) * step
        self._add(
            overlays,
            RealtimeLayer.GAZE,
            RealtimeChannel.GAZE_X,
            self._state.gaze_x,
            self._state.gaze_strength,
            90,
        )
        self._add(
            overlays,
            RealtimeLayer.GAZE,
            RealtimeChannel.GAZE_Y,
            self._state.gaze_y,
            self._state.gaze_strength,
            90,
        )
        states.append(
            RealtimeLayerState(RealtimeLayer.GAZE, RealtimeLayerStatus.ACTIVE, target.target_ref)
        )

    def _blink(
        self, overlays: list[ChannelOverlay], states: list[RealtimeLayerState], elapsed: float
    ) -> None:
        progress = self._state.blink_progress
        phase = self._state.blink_phase
        remaining = elapsed
        while remaining > 0:
            if phase is BlinkPhase.OPEN:
                until_blink = self._state.next_blink_after_s - self._state.blink_elapsed
                consumed = min(remaining, max(until_blink, 0.0))
                self._state.blink_elapsed += consumed
                remaining -= consumed
                if self._state.blink_elapsed < self._state.next_blink_after_s:
                    break
                phase, progress = BlinkPhase.CLOSING, 0.0
                continue
            duration = {
                BlinkPhase.CLOSING: 0.08,
                BlinkPhase.CLOSED: 0.04,
                BlinkPhase.OPENING: 0.1,
            }[phase]
            until_transition = (1.0 - progress) * duration
            consumed = min(remaining, until_transition)
            progress += consumed / duration
            remaining -= consumed
            if progress < 1.0:
                break
            if phase is BlinkPhase.CLOSING:
                phase, progress = BlinkPhase.CLOSED, 0.0
            elif phase is BlinkPhase.CLOSED:
                phase, progress = BlinkPhase.OPENING, 0.0
            else:
                phase, progress = BlinkPhase.OPEN, 0.0
                self._state.blink_elapsed = 0.0
                cycle = self._sequence + self._seed
                self._state.next_blink_after_s = 2.0 + (float(cycle % 101) / 100 - 0.5)
                # 遅延tickで複数周期を見えないまま消費せず、完了した現在blinkで止める。
                remaining = 0.0
        self._state.blink_phase, self._state.blink_progress = phase, progress
        openness = (
            1.0
            if phase is BlinkPhase.OPEN
            else (
                0.0
                if phase is BlinkPhase.CLOSED
                else (1 - progress if phase is BlinkPhase.CLOSING else progress)
            )
        )
        self._add(overlays, RealtimeLayer.BLINK, RealtimeChannel.EYELID_OPENNESS, openness, 1.0, 80)
        states.append(
            RealtimeLayerState(RealtimeLayer.BLINK, RealtimeLayerStatus.ACTIVE, detail=phase.value)
        )

    def _axis(self, expression: BodyExpressionContext | None, axis: BodyExpressionAxis) -> float:
        if expression is None:
            return 0.0
        return next(item.value.value for item in expression.axes if item.axis is axis)

    def _breath(
        self,
        overlays: list[ChannelOverlay],
        states: list[RealtimeLayerState],
        expression: BodyExpressionContext | None,
        elapsed: float,
    ) -> None:
        target_amplitude = max(
            0.0, 0.5 + self._axis(expression, BodyExpressionAxis.BREATHING_AMPLITUDE) / 2
        )
        transition = min(1.0, elapsed * 4)
        self._state.breath_amplitude += (
            target_amplitude - self._state.breath_amplitude
        ) * transition
        target_tempo = max(0.1, 1 + self._axis(expression, BodyExpressionAxis.BREATHING_TEMPO))
        self._state.breath_tempo += (target_tempo - self._state.breath_tempo) * transition
        self._state.breath_phase = (
            self._state.breath_phase + elapsed * self._state.breath_tempo / 4
        ) % 1.0
        self._add(
            overlays,
            RealtimeLayer.BREATH,
            RealtimeChannel.BREATH_PHASE,
            self._state.breath_phase,
            1.0,
            50,
        )
        self._add(
            overlays,
            RealtimeLayer.BREATH,
            RealtimeChannel.BREATH_AMPLITUDE,
            self._state.breath_amplitude,
            1.0,
            50,
        )
        states.append(RealtimeLayerState(RealtimeLayer.BREATH, RealtimeLayerStatus.ACTIVE))

    def _speech(
        self,
        overlays: list[ChannelOverlay],
        states: list[RealtimeLayerState],
        speech: RealtimeSpeechView | None,
        now: datetime,
        elapsed: float,
        monotonic_now_s: float | None,
    ) -> None:
        if speech is None:
            self._state.speech_presentation_id = None
            self._state.speech_monotonic_anchor_s = None
            blend = min(1.0, elapsed * 20.0)
            openness, roundness, jaw, closure = self._state.articulation
            self._state.articulation = (
                openness * (1.0 - blend),
                roundness * (1.0 - blend),
                jaw * (1.0 - blend),
                closure * (1.0 - blend),
            )
            if any(abs(value) > 1e-6 for value in self._state.articulation):
                self._add_articulation_overlays(overlays)
                states.append(
                    RealtimeLayerState(
                        RealtimeLayer.SPEECH_ARTICULATION,
                        RealtimeLayerStatus.ACTIVE,
                        detail="ending_fade",
                    )
                )
                return
            states.append(
                RealtimeLayerState(
                    RealtimeLayer.SPEECH_ARTICULATION, RealtimeLayerStatus.INACTIVE_NO_SOURCE
                )
            )
            return
        track = speech.timing_track
        if track is None:
            states.append(
                RealtimeLayerState(
                    RealtimeLayer.SPEECH_ARTICULATION,
                    RealtimeLayerStatus.DEGRADED,
                    speech.presentation.presentation_id,
                    "timing_unavailable",
                )
            )
            return
        presentation_id = speech.presentation.presentation_id
        if self._state.speech_presentation_id != presentation_id:
            self._state.speech_presentation_id = presentation_id
            self._state.speech_monotonic_anchor_s = speech.presentation_monotonic_started_at_s
        if self._state.speech_monotonic_anchor_s is not None and monotonic_now_s is not None:
            elapsed_ms = int(
                max(0.0, float(monotonic_now_s) - self._state.speech_monotonic_anchor_s) * 1000
            )
        else:
            # monotonic clockを渡せない呼出しでもwall clock差分で推測しない。
            elapsed_ms = 0
        unit = next(
            (item for item in track.units if item.start_ms <= elapsed_ms < item.end_ms), None
        )
        target = (0.0, 0.0, 0.0, 0.0)
        if unit is not None:
            if unit.kind is SpeechTimingKind.WORD_BOUNDARY:
                target = (0.0, 0.0, 0.0, 0.0)
            else:
                try:
                    if unit.kind is SpeechTimingKind.MORA and unit.symbol in {"ー", "ｰ"}:
                        target = self._standalone_long_mora_articulation(track.units, unit)
                    else:
                        target = articulation_for(unit.symbol, unit.kind)
                except ValueError:
                    states.append(
                        RealtimeLayerState(
                            RealtimeLayer.SPEECH_ARTICULATION,
                            RealtimeLayerStatus.DEGRADED,
                            speech.presentation.presentation_id,
                            "unsupported_timing_symbol",
                        )
                    )
                    return
        blend = min(1.0, elapsed * 20.0)
        current_openness, current_roundness, current_jaw, current_closure = self._state.articulation
        target_openness, target_roundness, target_jaw, target_closure = target
        self._state.articulation = (
            current_openness + (target_openness - current_openness) * blend,
            current_roundness + (target_roundness - current_roundness) * blend,
            current_jaw + (target_jaw - current_jaw) * blend,
            current_closure + (target_closure - current_closure) * blend,
        )
        self._add_articulation_overlays(overlays)
        states.append(
            RealtimeLayerState(
                RealtimeLayer.SPEECH_ARTICULATION,
                RealtimeLayerStatus.ACTIVE,
                speech.presentation.presentation_id,
            )
        )

    def _add_articulation_overlays(self, overlays: list[ChannelOverlay]) -> None:
        openness, roundness, jaw, closure = self._state.articulation
        for channel, value in (
            (RealtimeChannel.MOUTH_OPENNESS, openness),
            (RealtimeChannel.MOUTH_ROUNDNESS, roundness),
            (RealtimeChannel.JAW_OPENNESS, jaw),
            (RealtimeChannel.LIP_CLOSURE, closure),
        ):
            self._add(overlays, RealtimeLayer.SPEECH_ARTICULATION, channel, value, 1.0, 100)

    def _standalone_long_mora_articulation(
        self, units: tuple[SpeechTimingUnit, ...], unit: SpeechTimingUnit
    ) -> tuple[float, float, float, float]:
        """同一segmentで連続する単独長音を、直近の発音可能moraへ遡って継承する。"""
        for item in reversed(units):
            if item.end_ms > unit.start_ms:
                continue
            if item.kind is not SpeechTimingKind.MORA or item.segment_id != unit.segment_id:
                continue
            if item.symbol in {"ー", "ｰ"}:
                continue
            return articulation_for(item.symbol, item.kind)
        raise ValueError("先行moraがありません")

    def _subtle(
        self,
        overlays: list[ChannelOverlay],
        states: list[RealtimeLayerState],
        expression: BodyExpressionContext | None,
        elapsed: float,
    ) -> None:
        intensity = max(0.0, self._axis(expression, BodyExpressionAxis.IDLE_VARIATION))
        self._state.subtle_phase += elapsed * 1.7
        self._add(
            overlays,
            RealtimeLayer.SUBTLE_MOTION,
            RealtimeChannel.SUBTLE_SWAY,
            sin(self._state.subtle_phase) * intensity * 0.1,
            intensity,
            10,
        )
        states.append(
            RealtimeLayerState(
                RealtimeLayer.SUBTLE_MOTION,
                RealtimeLayerStatus.ACTIVE if intensity else RealtimeLayerStatus.INACTIVE_NO_SOURCE,
            )
        )
