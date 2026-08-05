from __future__ import annotations

from dataclasses import replace

from app.domain.body_pose_frame import BodyPoseFrame, BodyVector3
from app.runtime.procedural_body_controller import ProceduralBodyController

_DIRECTIONAL_COMMANDS: dict[str, tuple[float, float]] = {
    "body_move_up": (0.0, 1.0),
    "body_move_down": (0.0, -1.0),
    "body_move_left": (-1.0, 0.0),
    "body_move_right": (1.0, 0.0),
}
_DIRECTIONAL_COMMAND_DEFAULT_DURATION_MS = 2200


class BodyPoseLabController(ProceduralBodyController):
    """Procedural Body Controllerへ2D確認用のルート移動を重ねる。

    前後方向は棒人間では判別しにくいため扱わず、BodyPoseFrameの
    root_transform.positionを上下左右へ連続的に移動させる。
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._directional_command: str | None = None
        self._directional_elapsed = 0.0
        self._directional_duration = 0.0

    @property
    def active_body_command(self) -> str | None:
        return self._directional_command or super().active_body_command

    def apply_body_command(
        self,
        command: str,
        *,
        duration_ms: int | None = None,
    ) -> None:
        normalized = command.strip().lower()
        if normalized not in _DIRECTIONAL_COMMANDS:
            self._clear_directional_command()
            super().apply_body_command(normalized, duration_ms=duration_ms)
            return

        resolved_duration = (
            _DIRECTIONAL_COMMAND_DEFAULT_DURATION_MS
            if duration_ms is None
            else duration_ms
        )
        if isinstance(resolved_duration, bool) or not isinstance(resolved_duration, int):
            raise TypeError("duration_ms must be an integer")
        if not 200 <= resolved_duration <= 10_000:
            raise ValueError("duration_ms must be between 200 and 10000")

        super().clear_body_command()
        self._directional_command = normalized
        self._directional_elapsed = 0.0
        self._directional_duration = resolved_duration / 1000.0

    def clear_body_command(self) -> None:
        self._clear_directional_command()
        super().clear_body_command()

    def tick(
        self,
        *,
        timestamp_ms: int | None = None,
        dt_seconds: float | None = None,
    ) -> BodyPoseFrame:
        frame = super().tick(
            timestamp_ms=timestamp_ms,
            dt_seconds=dt_seconds,
        )
        command = self._directional_command
        if command is None or self._directional_duration <= 0.0:
            return frame

        progress = max(
            0.0,
            min(1.0, self._directional_elapsed / self._directional_duration),
        )
        envelope = self._command_envelope(progress)
        direction_x, direction_y = _DIRECTIONAL_COMMANDS[command]
        base_position = frame.root_transform.position
        position = BodyVector3(
            x=base_position.x + direction_x * 0.72 * envelope,
            y=base_position.y + direction_y * 0.58 * envelope,
            z=base_position.z,
        )
        projected = replace(
            frame,
            root_transform=replace(frame.root_transform, position=position),
        )

        dt = 1.0 / self.tick_hz if dt_seconds is None else float(dt_seconds)
        self._directional_elapsed += max(1.0 / 240.0, min(0.1, dt))
        if self._directional_elapsed >= self._directional_duration:
            self._clear_directional_command()
        return projected

    def _clear_directional_command(self) -> None:
        self._directional_command = None
        self._directional_elapsed = 0.0
        self._directional_duration = 0.0
