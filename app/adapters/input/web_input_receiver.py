from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from time import monotonic

from app.domain.events import AgentEvent, AgentEventType, InputAuthority
from app.runtime import EventPublisher, InputReceiver
from app.utils.trace import TraceLogger

SUPPORTED_VISUALIZER_STIMULI = frozenset({"tap", "double_tap", "long_press", "drag"})
STIMULUS_DESCRIPTIONS = {
    "tap": "ユーザーからそっと触れられた",
    "double_tap": "ユーザーから続けて二度触れられた",
    "long_press": "ユーザーからしばらく触れ続けられた",
    "drag": "ユーザーから指でなぞられた",
}
INTERACTION_BURST_WINDOW_SECONDS = 8.0


@dataclass
class _DragStreamState:
    last_relative_position: tuple[float, float] | None = None
    last_duration_ms: float = 0.0
    last_direction: tuple[float, float] | None = None
    inside_particle_zone: bool = False
    contact_duration_ms: float = 0.0
    contact_path_distance: float = 0.0
    reversal_count: int = 0
    speed_ema: float = 0.0
    contact_origin: tuple[float, float] | None = None
    min_relative_x: float = 0.0
    max_relative_x: float = 0.0
    min_relative_y: float = 0.0
    max_relative_y: float = 0.0
    speed_sum: float = 0.0
    speed_square_sum: float = 0.0
    speed_sample_count: int = 0
    reversal_interval_sum_ms: float = 0.0
    reversal_interval_square_sum_ms: float = 0.0
    reversal_interval_count: int = 0
    last_reversal_at_ms: float | None = None
    turn_angle_sum: float = 0.0
    turn_sample_count: int = 0


@dataclass(frozen=True)
class WebInputReceiverConfig:
    host: str = "127.0.0.1"
    port: int = 8771
    max_text_length: int = 4000
    interaction_min_interval_seconds: float = 0.75
    drag_stream_min_interval_seconds: float = 0.10

    def __post_init__(self) -> None:
        if not 0 <= self.port <= 65535:
            raise ValueError("Web入力UDPポートは0から65535の範囲で指定してください。")
        if self.max_text_length < 1:
            raise ValueError("Web入力の最大文字数は1以上で指定してください。")
        if self.interaction_min_interval_seconds < 0:
            raise ValueError("画面刺激の最小間隔は0以上で指定してください。")
        if self.drag_stream_min_interval_seconds < 0:
            raise ValueError("連続ドラッグ入力の最小間隔は0以上で指定してください。")


class _WebInputProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        publish_event: EventPublisher,
        config: WebInputReceiverConfig,
        task_started: Callable[[asyncio.Task[None]], None],
        task_finished: Callable[[asyncio.Task[None]], None],
    ) -> None:
        self._publish_event = publish_event
        self._config = config
        self._task_started = task_started
        self._task_finished = task_finished
        self._trace_logger = TraceLogger()
        self._last_interaction_at_by_kind: dict[str, float] = {}
        self._last_interaction_at: float | None = None
        self._interaction_burst_count = 0
        self._active_drag_bursts: dict[str, int] = {}
        self._last_drag_sequence: dict[str, int] = {}
        self._drag_stream_states: dict[str, _DragStreamState] = {}

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        del addr
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            return
        is_drag_sample = (
            payload.get("type") == "interaction_stimulus" and payload.get("stimulus_kind") == "drag"
        )
        if is_drag_sample:
            self._trace_logger.debug(
                "web_input_receiver:drag_sample_received",
                gesture_id=payload.get("gesture_id"),
                gesture_phase=payload.get("gesture_phase"),
                gesture_sequence=payload.get("gesture_sequence"),
                position=payload.get("position"),
            )
        event = self._event_from_payload(payload)
        if event is None:
            if is_drag_sample:
                self._trace_logger.debug(
                    "web_input_receiver:drag_sample_rejected",
                    gesture_id=payload.get("gesture_id"),
                    gesture_phase=payload.get("gesture_phase"),
                    gesture_sequence=payload.get("gesture_sequence"),
                )
            return

        task: asyncio.Task[None] = asyncio.create_task(self._publish(event))
        self._task_started(task)
        task.add_done_callback(self._task_finished)
        self._trace_logger.debug(
            "web_input_receiver:event_received",
            event_type=event.event_type.value,
            source=str(event.payload.get("source") or "web"),
            stimulus_kind=event.payload.get("stimulus_kind"),
            gesture_id=event.payload.get("gesture_id"),
            gesture_phase=event.payload.get("gesture_phase"),
            gesture_sequence=event.payload.get("gesture_sequence"),
        )

    def _event_from_payload(self, payload: dict[str, object]) -> AgentEvent | None:
        if payload.get("type") == "interaction_stimulus":
            event = self._interaction_event(payload)
            if event is None:
                return None
            now = monotonic()
            kind = str(event.payload["stimulus_kind"])
            gesture_id = event.payload.get("gesture_id")
            gesture_phase = event.payload.get("gesture_phase")
            is_drag_stream = (
                kind == "drag" and isinstance(gesture_id, str) and isinstance(gesture_phase, str)
            )
            rate_limit_key = f"drag:{gesture_id}" if is_drag_stream else kind
            minimum_interval = (
                self._config.drag_stream_min_interval_seconds
                if is_drag_stream
                else self._config.interaction_min_interval_seconds
            )
            last_interaction_at = self._last_interaction_at_by_kind.get(
                rate_limit_key, -minimum_interval
            )
            if gesture_phase != "end" and now - last_interaction_at < minimum_interval:
                if is_drag_stream:
                    self._trace_logger.debug(
                        "web_input_receiver:drag_sample_throttled",
                        gesture_id=gesture_id,
                        gesture_phase=gesture_phase,
                        gesture_sequence=event.payload.get("gesture_sequence"),
                        minimum_interval_seconds=minimum_interval,
                    )
                return None
            if is_drag_stream:
                sequence = int(event.payload["gesture_sequence"])
                previous_sequence = self._last_drag_sequence.get(gesture_id, -1)
                if sequence <= previous_sequence:
                    return None
                self._last_drag_sequence[gesture_id] = sequence
            self._last_interaction_at_by_kind[rate_limit_key] = now
            if is_drag_stream:
                contact_event = self._drag_contact_event(event, gesture_id)
                if contact_event is None:
                    if gesture_phase == "end":
                        self._finish_drag_stream(gesture_id, rate_limit_key)
                    return None
                event = contact_event
            interval_seconds = (
                None
                if self._last_interaction_at is None
                else max(0.0, now - self._last_interaction_at)
            )
            if is_drag_stream:
                burst_count = self._active_drag_bursts.get(gesture_id)
                if burst_count is None:
                    burst_count = self._next_burst_count(interval_seconds)
                    self._active_drag_bursts[gesture_id] = burst_count
                if gesture_phase == "end":
                    self._finish_drag_stream(gesture_id, rate_limit_key)
            else:
                burst_count = self._next_burst_count(interval_seconds)
            self._last_interaction_at = now
            return replace(
                event,
                payload={
                    **event.payload,
                    "interaction_burst_count": burst_count,
                    "interval_since_previous_ms": (
                        None if interval_seconds is None else round(interval_seconds * 1000.0, 3)
                    ),
                },
            )
        if payload.get("type") != "user_text":
            return None
        raw_text = payload.get("text")
        if not isinstance(raw_text, str):
            return None
        text = raw_text.strip()
        if not text or len(text) > self._config.max_text_length:
            return None
        return AgentEvent(
            event_type=AgentEventType.USER_TEXT,
            payload={"text": text, "source": "web"},
            authority=InputAuthority.USER,
        )

    @staticmethod
    def _interaction_event(payload: dict[str, object]) -> AgentEvent | None:
        kind = payload.get("stimulus_kind")
        if not isinstance(kind, str) or kind not in SUPPORTED_VISUALIZER_STIMULI:
            return None
        position = _WebInputProtocol._normalized_position(payload.get("position"))
        if position is None:
            return None
        event_payload: dict[str, object] = {
            "stimulus_kind": kind,
            "stimulus_description": STIMULUS_DESCRIPTIONS[kind],
            "position": position,
            "contact_region": _WebInputProtocol._contact_region(position),
            "source": "inner_state_visualizer",
        }
        if kind == "drag":
            start_position = _WebInputProtocol._normalized_position(payload.get("start_position"))
            if start_position is None:
                return None
            event_payload["start_position"] = start_position
            stream_metadata = _WebInputProtocol._drag_stream_metadata(payload)
            if stream_metadata is None and any(
                key in payload for key in ("gesture_id", "gesture_phase", "gesture_sequence")
            ):
                return None
            if stream_metadata is not None:
                event_payload.update(stream_metadata)
                particle_zone = _WebInputProtocol._particle_zone(payload.get("particle_zone"))
                if particle_zone is None:
                    return None
                event_payload["particle_zone"] = particle_zone
        if kind in {"long_press", "drag"}:
            duration_ms = payload.get("duration_ms")
            maximum_duration_ms = 60_000 if kind == "drag" else 10_000
            if (
                not isinstance(duration_ms, (int, float))
                or isinstance(duration_ms, bool)
                or not 0 <= float(duration_ms) <= maximum_duration_ms
            ):
                return None
            event_payload["duration_ms"] = float(duration_ms)
        return AgentEvent(
            event_type=AgentEventType.USER_INTERACTION,
            payload=event_payload,
            authority=InputAuthority.USER,
        )

    @staticmethod
    def _normalized_position(value: object) -> dict[str, float] | None:
        position = value
        if not isinstance(position, dict):
            return None
        x = position.get("x")
        y = position.get("y")
        if (
            not isinstance(x, (int, float))
            or isinstance(x, bool)
            or not isinstance(y, (int, float))
            or isinstance(y, bool)
            or not 0.0 <= float(x) <= 1.0
            or not 0.0 <= float(y) <= 1.0
        ):
            return None
        return {"x": float(x), "y": float(y)}

    @staticmethod
    def _drag_stream_metadata(
        payload: dict[str, object],
    ) -> dict[str, object] | None:
        gesture_id = payload.get("gesture_id")
        gesture_phase = payload.get("gesture_phase")
        gesture_sequence = payload.get("gesture_sequence")
        if gesture_id is None and gesture_phase is None and gesture_sequence is None:
            return None
        if (
            not isinstance(gesture_id, str)
            or not 1 <= len(gesture_id) <= 64
            or gesture_phase not in {"start", "update", "end"}
            or not isinstance(gesture_sequence, int)
            or isinstance(gesture_sequence, bool)
            or not 0 <= gesture_sequence <= 1_000_000
        ):
            return None
        return {
            "gesture_id": gesture_id,
            "gesture_phase": gesture_phase,
            "gesture_sequence": gesture_sequence,
        }

    def _next_burst_count(self, interval_seconds: float | None) -> int:
        if interval_seconds is None or interval_seconds > INTERACTION_BURST_WINDOW_SECONDS:
            self._interaction_burst_count = 1
        else:
            self._interaction_burst_count += 1
        return self._interaction_burst_count

    def _drag_contact_event(
        self,
        event: AgentEvent,
        gesture_id: str,
    ) -> AgentEvent | None:
        state = self._drag_stream_states.setdefault(
            gesture_id,
            _DragStreamState(),
        )
        position = event.payload["position"]
        particle_zone = event.payload["particle_zone"]
        assert isinstance(position, dict)
        assert isinstance(particle_zone, dict)
        center = particle_zone["center"]
        assert isinstance(center, dict)
        radius_x = float(particle_zone["radius_x"])
        radius_y = float(particle_zone["radius_y"])
        relative_position = (
            (float(position["x"]) - float(center["x"])) / radius_x,
            (float(position["y"]) - float(center["y"])) / radius_y,
        )
        center_distance = (relative_position[0] ** 2 + relative_position[1] ** 2) ** 0.5
        duration_ms = float(event.payload["duration_ms"])
        elapsed_ms = max(0.0, duration_ms - state.last_duration_ms)
        was_inside = state.inside_particle_zone
        inside = center_distance <= 1.0

        if not inside:
            self._trace_logger.debug(
                "web_input_receiver:drag_sample_outside_particle_zone",
                gesture_id=gesture_id,
                gesture_phase=event.payload.get("gesture_phase"),
                gesture_sequence=event.payload.get("gesture_sequence"),
                center_distance_ratio=round(center_distance, 4),
                position=position,
                particle_zone=particle_zone,
            )
            state.last_relative_position = relative_position
            state.last_duration_ms = duration_ms
            state.last_direction = None
            state.inside_particle_zone = False
            state.contact_duration_ms = 0.0
            state.contact_path_distance = 0.0
            state.reversal_count = 0
            state.speed_ema = 0.0
            state.contact_origin = None
            return None

        contact_phase = "update"
        segment_distance = 0.0
        speed = 0.0
        if not was_inside or state.last_relative_position is None:
            contact_phase = "start"
            self._reset_contact_motion(state, relative_position)
        else:
            direction = (
                relative_position[0] - state.last_relative_position[0],
                relative_position[1] - state.last_relative_position[1],
            )
            segment_distance = (direction[0] ** 2 + direction[1] ** 2) ** 0.5
            if elapsed_ms > 0:
                speed = segment_distance / (elapsed_ms / 1000.0)
                state.speed_sum += speed
                state.speed_square_sum += speed * speed
                state.speed_sample_count += 1
            state.contact_duration_ms += elapsed_ms
            if state.speed_ema == 0.0:
                state.speed_ema = speed
            else:
                state.speed_ema = state.speed_ema * 0.65 + speed * 0.35
            if state.last_direction is not None and segment_distance >= 0.04:
                direction_cosine = self._direction_cosine(
                    state.last_direction,
                    direction,
                )
                state.turn_angle_sum += math.acos(max(-1.0, min(1.0, direction_cosine)))
                state.turn_sample_count += 1
                if direction_cosine <= -0.35:
                    state.reversal_count += 1
                    if state.last_reversal_at_ms is not None:
                        reversal_interval = state.contact_duration_ms - state.last_reversal_at_ms
                        state.reversal_interval_sum_ms += reversal_interval
                        state.reversal_interval_square_sum_ms += (
                            reversal_interval * reversal_interval
                        )
                        state.reversal_interval_count += 1
                    state.last_reversal_at_ms = state.contact_duration_ms
            if segment_distance >= 0.01:
                state.last_direction = direction
            state.contact_path_distance += segment_distance
            state.min_relative_x = min(
                state.min_relative_x,
                relative_position[0],
            )
            state.max_relative_x = max(
                state.max_relative_x,
                relative_position[0],
            )
            state.min_relative_y = min(
                state.min_relative_y,
                relative_position[1],
            )
            state.max_relative_y = max(
                state.max_relative_y,
                relative_position[1],
            )

        if event.payload.get("gesture_phase") == "end":
            contact_phase = "end"
        back_and_forth = state.reversal_count >= 1
        stroking = (
            back_and_forth
            and state.contact_duration_ms >= 350
            and state.contact_path_distance >= 0.35
            and 0.15 <= state.speed_ema <= 6.0
        )
        state.last_relative_position = relative_position
        state.last_duration_ms = duration_ms
        state.inside_particle_zone = True
        motion = {
            "instantaneous_speed": round(speed, 4),
            "smoothed_speed": round(state.speed_ema, 4),
            "center_distance_ratio": round(center_distance, 4),
            "segment_distance_ratio": round(segment_distance, 4),
            "path_distance_ratio": round(state.contact_path_distance, 4),
            "reversal_count": state.reversal_count,
            "back_and_forth": back_and_forth,
        }
        return replace(
            event,
            payload={
                **event.payload,
                "continuous_contact": True,
                "contact_phase": contact_phase,
                "contact_sample_interval_ms": round(elapsed_ms, 3),
                "contact_duration_ms": round(state.contact_duration_ms, 3),
                "contact_motion": "stroke" if stroking else "trace",
                "motion": motion,
                "touch_features": self._touch_features(
                    state,
                    relative_position=relative_position,
                    center_distance=center_distance,
                ),
                "stimulus_description": (
                    "ユーザーから往復する動きで撫でられている"
                    if stroking
                    else "ユーザーのドラッグが粒子の領域に触れた"
                ),
            },
        )

    @staticmethod
    def _reset_contact_motion(
        state: _DragStreamState,
        relative_position: tuple[float, float],
    ) -> None:
        state.contact_duration_ms = 0.0
        state.contact_path_distance = 0.0
        state.reversal_count = 0
        state.last_direction = None
        state.speed_ema = 0.0
        state.contact_origin = relative_position
        state.min_relative_x = relative_position[0]
        state.max_relative_x = relative_position[0]
        state.min_relative_y = relative_position[1]
        state.max_relative_y = relative_position[1]
        state.speed_sum = 0.0
        state.speed_square_sum = 0.0
        state.speed_sample_count = 0
        state.reversal_interval_sum_ms = 0.0
        state.reversal_interval_square_sum_ms = 0.0
        state.reversal_interval_count = 0
        state.last_reversal_at_ms = None
        state.turn_angle_sum = 0.0
        state.turn_sample_count = 0

    @staticmethod
    def _touch_features(
        state: _DragStreamState,
        *,
        relative_position: tuple[float, float],
        center_distance: float,
    ) -> dict[str, object]:
        mean_speed, speed_variability = _WebInputProtocol._distribution(
            state.speed_sum,
            state.speed_square_sum,
            state.speed_sample_count,
        )
        _, reversal_interval_variability = _WebInputProtocol._distribution(
            state.reversal_interval_sum_ms,
            state.reversal_interval_square_sum_ms,
            state.reversal_interval_count,
        )
        smoothness = max(0.0, min(1.0, 1.0 - speed_variability))
        rhythmicity = (
            max(0.0, min(1.0, 1.0 - reversal_interval_variability))
            if state.reversal_interval_count >= 2
            else 0.0
        )
        mean_turn_ratio = (
            state.turn_angle_sum / state.turn_sample_count / math.pi
            if state.turn_sample_count
            else 0.0
        )
        origin = state.contact_origin or relative_position
        displacement = (
            (relative_position[0] - origin[0]) ** 2 + (relative_position[1] - origin[1]) ** 2
        ) ** 0.5
        path_efficiency = (
            min(1.0, displacement / state.contact_path_distance)
            if state.contact_path_distance > 0
            else 1.0
        )
        oscillation = min(
            1.0,
            state.reversal_count * 0.45 + max(0.0, 1.0 - path_efficiency) * 0.45,
        )
        jitter = min(
            1.0,
            mean_turn_ratio * 0.65 + speed_variability * 0.35,
        )
        coverage_x = min(
            1.0,
            max(0.0, state.max_relative_x - state.min_relative_x) / 2.0,
        )
        coverage_y = min(
            1.0,
            max(0.0, state.max_relative_y - state.min_relative_y) / 2.0,
        )
        coverage = min(1.0, (coverage_x**2 + coverage_y**2) ** 0.5)
        if jitter >= 0.58:
            trajectory_shape = "erratic"
        elif oscillation >= 0.42:
            trajectory_shape = "oscillating"
        elif mean_turn_ratio >= 0.22:
            trajectory_shape = "curved"
        elif state.contact_path_distance < 0.12:
            trajectory_shape = "localized"
        else:
            trajectory_shape = "sweep"
        if mean_speed < 0.25:
            speed_band = "very_slow"
        elif mean_speed < 1.0:
            speed_band = "gentle"
        elif mean_speed < 2.5:
            speed_band = "brisk"
        else:
            speed_band = "rapid"
        vertical_location = (
            "upper"
            if relative_position[1] < -0.33
            else "lower"
            if relative_position[1] > 0.33
            else "middle"
        )
        radial_location = (
            "inner" if center_distance < 0.35 else "surface" if center_distance > 0.75 else "middle"
        )
        return {
            "location": {
                "vertical": vertical_location,
                "radial": radial_location,
                "relative_x": round(relative_position[0], 4),
                "relative_y": round(relative_position[1], 4),
                "center_distance_ratio": round(center_distance, 4),
            },
            "movement": {
                "speed_band": speed_band,
                "mean_speed": round(mean_speed, 4),
                "trajectory_shape": trajectory_shape,
                "smoothness": round(smoothness, 4),
                "rhythmicity": round(rhythmicity, 4),
                "oscillation": round(oscillation, 4),
                "curvature": round(mean_turn_ratio, 4),
                "jitter": round(jitter, 4),
                "coverage": round(coverage, 4),
                "path_efficiency": round(path_efficiency, 4),
            },
        }

    @staticmethod
    def _distribution(
        total: float,
        square_total: float,
        count: int,
    ) -> tuple[float, float]:
        if count <= 0:
            return 0.0, 0.0
        mean = total / count
        variance = max(0.0, square_total / count - mean * mean)
        coefficient_of_variation = variance**0.5 / max(0.1, abs(mean))
        return mean, min(1.0, coefficient_of_variation)

    def _finish_drag_stream(self, gesture_id: str, rate_limit_key: str) -> None:
        self._active_drag_bursts.pop(gesture_id, None)
        self._last_drag_sequence.pop(gesture_id, None)
        self._drag_stream_states.pop(gesture_id, None)
        self._last_interaction_at_by_kind.pop(rate_limit_key, None)

    @staticmethod
    def _direction_cosine(
        previous: tuple[float, float],
        current: tuple[float, float],
    ) -> float:
        previous_length = (previous[0] ** 2 + previous[1] ** 2) ** 0.5
        current_length = (current[0] ** 2 + current[1] ** 2) ** 0.5
        if previous_length == 0 or current_length == 0:
            return 1.0
        return (previous[0] * current[0] + previous[1] * current[1]) / (
            previous_length * current_length
        )

    @staticmethod
    def _particle_zone(value: object) -> dict[str, object] | None:
        if not isinstance(value, dict):
            return None
        center = _WebInputProtocol._normalized_position(value.get("center"))
        radius_x = value.get("radius_x")
        radius_y = value.get("radius_y")
        if (
            center is None
            or not isinstance(radius_x, (int, float))
            or isinstance(radius_x, bool)
            or not isinstance(radius_y, (int, float))
            or isinstance(radius_y, bool)
            or not 0 < float(radius_x) <= 1
            or not 0 < float(radius_y) <= 1
        ):
            return None
        return {
            "center": center,
            "radius_x": float(radius_x),
            "radius_y": float(radius_y),
        }

    @staticmethod
    def _contact_region(position: dict[str, float]) -> str:
        x = position["x"]
        y = position["y"]
        if ((x - 0.5) ** 2 + (y - 0.5) ** 2) ** 0.5 >= 0.42:
            return "periphery"
        if y < 0.33:
            return "upper"
        if y > 0.67:
            return "lower"
        return "center"

    async def _publish(self, event: AgentEvent) -> None:
        await self._publish_event(event)


class WebInputReceiver(InputReceiver):
    """ローカルWeb画面から会話入力と画面刺激を受け取るUDP Adapter。"""

    def __init__(self, config: WebInputReceiverConfig | None = None) -> None:
        self._config = config or WebInputReceiverConfig()
        self._transport: asyncio.DatagramTransport | None = None
        self._stopped = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(self, publish_event: EventPublisher) -> None:
        if self._transport is not None:
            return
        self._stopped.clear()
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _WebInputProtocol(
                publish_event,
                self._config,
                self._tasks.add,
                self._task_finished,
            ),
            local_addr=(self._config.host, self._config.port),
        )
        self._transport = transport

    async def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        self._stopped.set()

    async def wait_until_stopped(self) -> None:
        await self._stopped.wait()

    @property
    def bound_port(self) -> int | None:
        if self._transport is None:
            return None
        address = self._transport.get_extra_info("sockname")
        return int(address[1]) if isinstance(address, tuple) else None

    def _task_finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        try:
            task.result()
        except Exception as error:
            TraceLogger().warning(
                "web_input_receiver:event_publish_failed",
                error_type=type(error).__name__,
                error_message=str(error),
            )
