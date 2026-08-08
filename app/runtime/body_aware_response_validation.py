from __future__ import annotations

import re

from app.domain.activities import Activity
from app.domain.body_instruction import (
    BODY_ACTION_INTENT_CONSTRAINT,
    BODY_EXPRESSION_ACTIVITY_TYPE,
    BodyInstruction,
)
from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    Claim,
    ClaimType,
    ResponseContext,
    ResponseValidationResult,
)
from app.domain.interaction_intention import InteractionIntentionType
from app.runtime.character_response_pipeline import ResponseValidator
from app.runtime.response_claim_validator import IndependentClaimExtractor

_EMBODIED_STATE_ASSERTION_PATTERN = re.compile(
    r"(?:見て(?:いる|る)|向いて(?:いる|る)|挙げて(?:いる|る)|上げて(?:いる|る)|"
    r"下げて(?:いる|る)|振って(?:いる|る)|動かして(?:いる|る)|伸ばして(?:いる|る)|"
    r"曲げて(?:いる|る)|しゃがんで(?:いる|る)|立って(?:いる|る)|座って(?:いる|る))"
)
_EMBODIED_CAPABILITY_DENIAL_PATTERN = re.compile(
    r"(?:(?:体|身体|アバター|腕|手|頭|首).{0,14}"
    r"(?:動かせない|動かせません|動かすことができない|動かすことはできない))"
    r"|(?:(?:その|この)?(?:動き|動作|ポーズ).{0,10}(?:できない|できません))"
    r"|(?:身体動作.{0,10}(?:できない|できません))"
)


def _directive_body_action_intent(context: ResponseContext) -> BodyInstruction | None:
    envelope = context.constraints.get("_internal_directive")
    if not isinstance(envelope, dict):
        return None
    internal = envelope.get("internal_directive")
    if not isinstance(internal, dict):
        return None
    activity_intent = internal.get("activity_intent")
    if not isinstance(activity_intent, dict):
        return None
    if str(activity_intent.get("activity_type") or "") != BODY_EXPRESSION_ACTIVITY_TYPE:
        return None
    constraints = activity_intent.get("constraints")
    if not isinstance(constraints, dict):
        return None
    return BodyInstruction.from_context(
        constraints.get(BODY_ACTION_INTENT_CONSTRAINT)
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
    """実行事実に加え、CharacterとValidated Internal Directiveの整合を検証する。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("claim_extractor", BodyAwareIndependentClaimExtractor())
        super().__init__(*args, **kwargs)

    async def validate(
        self,
        source: Activity,
        context: ResponseContext,
        response: CharacterResponse,
        *,
        attempt: int = 1,
    ) -> ResponseValidationResult:
        body_intent = _directive_body_action_intent(context)
        denied = _EMBODIED_CAPABILITY_DENIAL_PATTERN.search(response.speech)
        if (
            body_intent is not None
            and denied is not None
            and context.status
            not in {ActivityExecutionStatus.REJECTED, ActivityExecutionStatus.FAILED}
        ):
            result = ResponseValidationResult(
                False,
                "body_capability_denial_conflicts_with_internal_directive",
            )
            self._trace_result(source, result)
            return result
        return await super().validate(
            source,
            context,
            response,
            attempt=attempt,
        )


__all__ = [
    "BodyAwareIndependentClaimExtractor",
    "BodyAwareResponseValidator",
]
