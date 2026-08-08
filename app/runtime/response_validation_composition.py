from __future__ import annotations

from app.domain.character_response import (
    CharacterResponse,
    Claim,
    ResponseContext,
    ResponseValidationResult,
)
from app.runtime.causal_decision_observer import CausalDecisionObserver
from app.runtime.response_budget_validator import ResponseBudgetValidator
from app.runtime.response_claim_validator import (
    DeterministicFactValidator as LegacyDeterministicFactValidator,
    _PHYSICAL_BODY_CLAIM_PATTERN,
    _UNSUPPORTED_EXPERIENCE_PATTERN,
)


class DeterministicResponseValidator(LegacyDeterministicFactValidator):
    """Budget検証と実行事実検証を分離した互換Facade。"""

    def __init__(
        self,
        causal_observer: CausalDecisionObserver | None = None,
        budget_validator: ResponseBudgetValidator | None = None,
    ) -> None:
        super().__init__(causal_observer=causal_observer)
        self._budget_validator = budget_validator or ResponseBudgetValidator()

    def validate(
        self,
        context: ResponseContext,
        response: CharacterResponse,
        extracted_claims: tuple[Claim, ...],
    ) -> ResponseValidationResult:
        budget_result = self._budget_validator.validate(context, response.speech)
        if not budget_result.accepted:
            return budget_result
        return super().validate(context, response, extracted_claims)

    @classmethod
    def _directive_conflicts(
        cls,
        context: ResponseContext,
        speech: str,
    ) -> tuple[str, ...]:
        """旧Facade内では存在境界だけをFact検証として維持する。"""

        envelope_value = context.constraints.get("_internal_directive")
        if not isinstance(envelope_value, dict):
            return ()
        internal_value = envelope_value.get("internal_directive")
        internal = dict(internal_value) if isinstance(internal_value, dict) else {}
        boundaries_value = envelope_value.get("existence_boundaries")
        boundaries = (
            tuple(str(item) for item in boundaries_value)
            if isinstance(boundaries_value, (list, tuple))
            else ()
        )
        forbidden_value = internal.get("forbidden_claims")
        forbidden = (
            tuple(str(item) for item in forbidden_value)
            if isinstance(forbidden_value, (list, tuple))
            else ()
        )
        existence_text = "\n".join((*boundaries, *forbidden))
        reasons: list[str] = []
        if (
            "実体験" in existence_text
            and _UNSUPPORTED_EXPERIENCE_PATTERN.search(speech)
        ):
            reasons.append("response_violates_existence_boundary")
        if (
            "物理的" in existence_text
            and "身体" in existence_text
            and _PHYSICAL_BODY_CLAIM_PATTERN.search(speech)
        ):
            reasons.append("response_violates_existence_boundary")
        return tuple(dict.fromkeys(reasons))
