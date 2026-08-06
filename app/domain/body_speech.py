from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from app.domain.body_value_validation import (
    bounded_number,
    non_negative_integer,
    normalized_identifier,
)


@dataclass(frozen=True, slots=True)
class SpeechEmphasis:
    """発話内の意味的な強調点。実時間への変換は音声生成後に行う。"""

    text: str
    intent: str
    strength: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "text",
            normalized_identifier(
                self.text,
                "emphasis text",
                maximum_length=4000,
            ),
        )
        object.__setattr__(
            self,
            "intent",
            normalized_identifier(self.intent, "emphasis intent"),
        )
        object.__setattr__(
            self,
            "strength",
            bounded_number(self.strength, "emphasis strength", 0.0, 1.0),
        )


@dataclass(frozen=True, slots=True)
class SpeechPresentationRequest:
    """生成済み音声をBody時計と同期して提示するための契約。"""

    source_activity_id: str
    output_unit_id: str
    text: str
    audio_reference: str
    duration_ms: int
    emphasis: tuple[SpeechEmphasis, ...] = ()
    presentation_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        for field_name, maximum in (
            ("source_activity_id", 128),
            ("output_unit_id", 128),
            ("audio_reference", 512),
            ("presentation_id", 128),
        ):
            object.__setattr__(
                self,
                field_name,
                normalized_identifier(
                    str(getattr(self, field_name)),
                    field_name,
                    maximum_length=maximum,
                ),
            )
        object.__setattr__(
            self,
            "text",
            normalized_identifier(self.text, "text", maximum_length=4000),
        )
        duration = non_negative_integer(self.duration_ms, "duration_ms")
        if not 100 <= duration <= 600_000:
            raise ValueError("duration_ms must be between 100 and 600000")
        object.__setattr__(self, "duration_ms", duration)
        emphasis = tuple(self.emphasis)
        if len(emphasis) > 16:
            raise ValueError("emphasis supports at most 16 entries")
        if not all(isinstance(value, SpeechEmphasis) for value in emphasis):
            raise TypeError("emphasis must contain SpeechEmphasis values")
        object.__setattr__(self, "emphasis", emphasis)
