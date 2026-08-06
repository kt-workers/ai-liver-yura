from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.body_speech import SpeechPresentationRequest


@dataclass(frozen=True, slots=True)
class BodySpeechMouthSample:
    mouth_open: float
    active_presentation_id: str | None
    completed: bool = False


class BodySpeechMouthDriver:
    """発話Presentationの継続時間から暫定口形だけを生成する。

    音素・Viseme入力が利用できるまでのFallbackであり、音声再生やTTSは行わない。
    """

    def __init__(self) -> None:
        self._request: SpeechPresentationRequest | None = None
        self._elapsed = 0.0
        self._energy = 0.5
        self._phase = 0.0

    @property
    def active_presentation_id(self) -> str | None:
        return self._request.presentation_id if self._request is not None else None

    def present(
        self,
        request: SpeechPresentationRequest,
        *,
        energy: float = 0.5,
    ) -> None:
        if not isinstance(request, SpeechPresentationRequest):
            raise TypeError("request must be SpeechPresentationRequest")
        if isinstance(energy, bool) or not isinstance(energy, (int, float)):
            raise TypeError("energy must be a number")
        normalized_energy = float(energy)
        if not 0.0 <= normalized_energy <= 1.0:
            raise ValueError("energy must be between 0 and 1")
        self._request = request
        self._elapsed = 0.0
        self._energy = normalized_energy
        self._phase = 0.0

    def clear(self) -> None:
        self._request = None
        self._elapsed = 0.0
        self._phase = 0.0

    def step(self, *, dt_seconds: float) -> BodySpeechMouthSample:
        request = self._request
        if request is None:
            return BodySpeechMouthSample(0.0, None)

        dt = max(1.0 / 240.0, min(0.1, float(dt_seconds)))
        self._elapsed += dt
        duration = request.duration_ms / 1000.0
        if self._elapsed >= duration:
            presentation_id = request.presentation_id
            self.clear()
            return BodySpeechMouthSample(
                mouth_open=0.0,
                active_presentation_id=presentation_id,
                completed=True,
            )

        self._phase = (self._phase + math.tau * (3.1 + self._energy * 2.4) * dt) % math.tau
        pulse = 0.5 + 0.5 * math.sin(self._phase)
        mouth_open = 0.16 + self._energy * 0.30
        mouth_open += pulse * (0.18 + self._energy * 0.24)
        return BodySpeechMouthSample(
            mouth_open=max(0.0, min(1.0, mouth_open)),
            active_presentation_id=request.presentation_id,
        )
