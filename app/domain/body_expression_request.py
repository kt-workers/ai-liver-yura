from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from app.domain.body_attention_intent import BodyAttentionIntent
from app.domain.body_expression import EmbodiedExpressionIntent
from app.domain.body_speech import SpeechEmphasis
from app.domain.body_value_validation import (
    bounded_number,
    non_negative_integer,
    normalized_identifier,
)
from app.domain.interaction_intention import InteractionIntention


@dataclass(frozen=True, slots=True)
class BodyExpressionRequest:
    """脳側からBodyへ送る高レベル表現要求。

    Pose、Joint角度、Transport情報、実行権限は含まない。
    """

    source_activity_id: str
    output_unit_id: str
    expression: EmbodiedExpressionIntent
    attention: BodyAttentionIntent | None = None
    facial_expression: str | None = None
    facial_intensity: float = 1.0
    speech_emphasis: tuple[SpeechEmphasis, ...] = ()
    priority: int = 0
    duration_hint_ms: int | None = None
    interaction_intention: InteractionIntention | None = None
    request_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        for field_name in ("source_activity_id", "output_unit_id", "request_id"):
            object.__setattr__(
                self,
                field_name,
                normalized_identifier(
                    str(getattr(self, field_name)),
                    field_name,
                    maximum_length=128,
                ),
            )
        if not isinstance(self.expression, EmbodiedExpressionIntent):
            raise TypeError("expression must be EmbodiedExpressionIntent")
        if self.attention is not None and not isinstance(
            self.attention,
            BodyAttentionIntent,
        ):
            raise TypeError("attention must be BodyAttentionIntent")
        if self.facial_expression is not None:
            object.__setattr__(
                self,
                "facial_expression",
                normalized_identifier(
                    self.facial_expression,
                    "facial_expression",
                ),
            )
        object.__setattr__(
            self,
            "facial_intensity",
            bounded_number(
                self.facial_intensity,
                "facial_intensity",
                0.0,
                1.0,
            ),
        )
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")
        if not 0 <= self.priority <= 1000:
            raise ValueError("priority must be between 0 and 1000")
        emphasis = tuple(self.speech_emphasis)
        if len(emphasis) > 16:
            raise ValueError("speech_emphasis supports at most 16 entries")
        if not all(isinstance(value, SpeechEmphasis) for value in emphasis):
            raise TypeError("speech_emphasis must contain SpeechEmphasis values")
        object.__setattr__(self, "speech_emphasis", emphasis)
        if self.duration_hint_ms is not None:
            duration = non_negative_integer(
                self.duration_hint_ms,
                "duration_hint_ms",
            )
            if not 100 <= duration <= 120_000:
                raise ValueError(
                    "duration_hint_ms must be between 100 and 120000"
                )
            object.__setattr__(self, "duration_hint_ms", duration)
