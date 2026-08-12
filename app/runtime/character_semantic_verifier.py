from __future__ import annotations

from dataclasses import dataclass

from app.domain.activities import Activity, ActivityType
from app.domain.character_response import ResponseContext
from app.domain.character_utterance import CharacterUtterance
from app.domain.semantic_utterance import SemanticUtterancePlan
from app.domain.semantic_validation import CharacterSemanticVerification
from app.ports.llm_roles import CharacterSemanticVerificationModel
from app.ports.prompt_builder import CharacterSemanticVerifierPromptBuilder
from app.ports.structured_output import (
    StructuredOutputGenerationError,
    StructuredOutputUnsupportedError,
)
from app.runtime.character_semantic_verification_policy import (
    CharacterSemanticDecision,
    CharacterSemanticVerificationPolicy,
    SemanticVerificationDifference,
)
from app.runtime.semantic_realization_v2_contracts import (
    character_semantic_verification_v2_contract,
)


@dataclass(frozen=True, slots=True)
class CharacterSemanticVerifierResult:
    verification: CharacterSemanticVerification | None
    decision: CharacterSemanticDecision

    def as_context(self) -> dict[str, object]:
        return {
            "verification": (
                self.verification.as_context() if self.verification is not None else None
            ),
            "decision": self.decision.as_context(),
        }


class CharacterSemanticVerifier:
    """Plan-vs-speechのrelative semanticsを1つの独立Verifierで検証する。"""

    def __init__(
        self,
        model: CharacterSemanticVerificationModel,
        prompt_builder: CharacterSemanticVerifierPromptBuilder,
        *,
        policy: CharacterSemanticVerificationPolicy | None = None,
    ) -> None:
        self._model = model
        self._prompt_builder = prompt_builder
        self._policy = policy or CharacterSemanticVerificationPolicy()

    async def verify(
        self,
        source: Activity,
        context: ResponseContext,
        utterance: CharacterUtterance,
        plan: SemanticUtterancePlan,
        *,
        existence_boundaries: tuple[str, ...] = (),
        attempt: int = 1,
    ) -> CharacterSemanticVerifierResult:
        prompt = self._prompt_builder.build(
            context,
            utterance,
            plan,
            existence_boundaries=existence_boundaries,
        )
        activity = Activity(
            activity_type=ActivityType.BEHAVIOR_PLANNING,
            goal="Semantic Planに対するCharacter speechの相対的意味保持を検証する",
            source_event_id=source.source_event_id,
            context={
                "plugin_prompt_override": prompt,
                "llm_role": "character_semantic_verifier",
                "trace_context": source.context.get("trace_context"),
                "activity_turn_id": source.context.get("activity_turn_id"),
                "llm_attempt": attempt,
                "semantic_boundary": True,
            },
        )
        try:
            payload = await self._model.verify_character_semantics(
                activity,
                character_semantic_verification_v2_contract(),
            )
        except StructuredOutputUnsupportedError:
            return self._failed("character_semantic_verifier_structured_output_unsupported")
        except StructuredOutputGenerationError:
            return self._failed("character_semantic_verifier_model_failed")
        except Exception:
            return self._failed("character_semantic_verifier_model_failed")

        verification = CharacterSemanticVerification.from_mapping(payload)
        if verification is None:
            return self._failed("character_semantic_verifier_schema_invalid")

        decision = self._policy.decide(
            plan,
            verification,
            speech=utterance.speech,
        )
        return CharacterSemanticVerifierResult(verification, decision)

    @staticmethod
    def _failed(reason: str) -> CharacterSemanticVerifierResult:
        return CharacterSemanticVerifierResult(
            verification=None,
            decision=CharacterSemanticDecision(
                accepted=False,
                reason=reason,
                differences=(
                    SemanticVerificationDifference(
                        proposition_id=None,
                        facet="verifier",
                        relation="failed",
                        repair="retry_transport_or_fail_closed",
                    ),
                ),
            ),
        )
