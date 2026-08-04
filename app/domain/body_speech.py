from __future__ import annotations

from dataclasses import dataclass

from app.domain.body import BodyExpressionRequest


@dataclass(frozen=True, slots=True)
class SpeechCoupledBodyExpressionRequest(BodyExpressionRequest):
    """発話と明示的なアバター身体操作をBody側で扱う要求。"""

    speech_act: str = "statement"
    body_actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        BodyExpressionRequest.__post_init__(self)
        if not isinstance(self.speech_act, str):
            raise TypeError("speech_act must be a string")
        normalized = self.speech_act.strip().lower()
        if not normalized:
            normalized = "statement"
        if len(normalized) > 40:
            raise ValueError("speech_act must be 40 characters or fewer")
        object.__setattr__(self, "speech_act", normalized)

        normalized_actions: list[str] = []
        for action in self.body_actions:
            if not isinstance(action, str):
                raise TypeError("body_actions entries must be strings")
            value = action.strip().lower()
            if not value or len(value) > 80:
                raise ValueError("body action has invalid length")
            if value not in normalized_actions:
                normalized_actions.append(value)
        if len(normalized_actions) > 8:
            raise ValueError("body_actions supports at most 8 entries")
        object.__setattr__(self, "body_actions", tuple(normalized_actions))
