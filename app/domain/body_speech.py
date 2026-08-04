from __future__ import annotations

from dataclasses import dataclass

from app.domain.body import BodyExpressionRequest


@dataclass(frozen=True, slots=True)
class SpeechCoupledBodyExpressionRequest(BodyExpressionRequest):
    """発話に伴う非言語動作をBody側で生成するための要求。

    Character LLMが身体部位やモーションを指定しなくても、Bodyは発話時間と
    Activity文脈から会話中の首・胴体の微細動作を生成できる。
    """

    speech_act: str = "statement"

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.speech_act, str):
            raise TypeError("speech_act must be a string")
        normalized = self.speech_act.strip().lower()
        if not normalized:
            normalized = "statement"
        if len(normalized) > 40:
            raise ValueError("speech_act must be 40 characters or fewer")
        object.__setattr__(self, "speech_act", normalized)
