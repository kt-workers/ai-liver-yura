from __future__ import annotations

import re

from app.domain.character_response import (
    ActivityExecutionStatus,
    Claim,
    ClaimType,
    ResponseContext,
)
from app.domain.interaction_intention import InteractionIntentionType
from app.runtime.character_response_pipeline import ResponseValidator
from app.runtime.response_claim_validator import IndependentClaimExtractor

_EMBODIED_STATE_ASSERTION_PATTERN = re.compile(
    r"(?:見て(?:いる|る)|向いて(?:いる|る)|挙げて(?:いる|る)|上げて(?:いる|る)|"
    r"下げて(?:いる|る)|振って(?:いる|る)|動かして(?:いる|る)|伸ばして(?:いる|る)|"
    r"曲げて(?:いる|る)|しゃがんで(?:いる|る)|立って(?:いる|る)|座って(?:いる|る))"
)


class BodyAwareIndependentClaimExtractor(IndependentClaimExtractor):
    """ACT意図時の身体状態主張を、実行済み根拠が必要なClaimとして補足する。"""

    def extract(self, context: ResponseContext, speech: str) -> tuple[Claim, ...]:
        claims = list(super().extract(context, speech))
        intention = context.interaction_intention
        if (
            intention is None
            or intention.intention is not InteractionIntentionType.ACT
            or any(
                claim.claim_type
                in {
                    ClaimType.ACTIVITY_COMPLETED,
                    ClaimType.ACTIVITY_SUCCEEDED,
                }
                for claim in claims
            )
        ):
            return tuple(claims)
        match = _EMBODIED_STATE_ASSERTION_PATTERN.search(speech)
        if match is None:
            return tuple(claims)
        claims.append(
            Claim(
                claim_type=ClaimType.ACTIVITY_SUCCEEDED,
                activity_type=(
                    context.activity_type
                    if context.activity_type != "conversation"
                    else None
                ),
                operation=context.operation,
                status=ActivityExecutionStatus.SUCCEEDED,
                target=None,
                confidence=0.99,
                evidence=match.group(0),
            )
        )
        return tuple(claims)


class BodyAwareResponseValidator(ResponseValidator):
    """既存Response検証へ、身体状態主張の独立抽出だけを追加する。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("claim_extractor", BodyAwareIndependentClaimExtractor())
        super().__init__(*args, **kwargs)


__all__ = [
    "BodyAwareIndependentClaimExtractor",
    "BodyAwareResponseValidator",
]
