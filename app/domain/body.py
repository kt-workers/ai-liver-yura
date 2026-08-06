"""Body高レベル契約の互換Facade。

新規実装は責務別Moduleから直接importする。既存利用側の
`from app.domain.body import ...`はこのFacadeで維持する。
"""

from app.domain.body_activity_context import (
    BodyActivityContext,
    BodyPostureTendency,
)
from app.domain.body_attention_intent import (
    BodyAttentionBehavior,
    BodyAttentionIntent,
)
from app.domain.body_expression import EmbodiedExpressionIntent
from app.domain.body_expression_request import BodyExpressionRequest
from app.domain.body_speech import SpeechEmphasis, SpeechPresentationRequest

__all__ = [
    "BodyActivityContext",
    "BodyAttentionBehavior",
    "BodyAttentionIntent",
    "BodyExpressionRequest",
    "BodyPostureTendency",
    "EmbodiedExpressionIntent",
    "SpeechEmphasis",
    "SpeechPresentationRequest",
]
