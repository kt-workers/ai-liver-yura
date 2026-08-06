from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.domain.cognitive_direction import (
    InternalDirective,
    ResponseMode,
    StructuredInputMeaning,
)
from app.domain.interaction_intention import (
    InteractionIntention,
    InteractionIntentionComparison,
    InteractionIntentionType,
)
from app.runtime.causal_decision_observer import CausalDecisionObserver
from app.runtime.interaction_intention_appraiser import (
    InteractionIntentionAppraiser,
)
from app.utils.trace import TraceLogger


@dataclass(frozen=True, slots=True)
class InternalDirectivePlanningObservation:
    directive: InternalDirective
    interaction_intention: InteractionIntention
    comparison: InteractionIntentionComparison

    def as_context(self) -> dict[str, object]:
        return {
            "directive": self.directive.as_context(),
            "interaction_intention": self.interaction_intention.as_context(),
            "comparison": self.comparison.as_context(),
        }


class InteractionIntentionShadowObserver:
    """Interaction Intentionを既存Internal Directiveへ影響させず比較する。"""

    _COMPATIBLE: Mapping[
        InteractionIntentionType,
        frozenset[InteractionIntentionType],
    ] = {
        InteractionIntentionType.ANSWER: frozenset(
            {InteractionIntentionType.ANSWER}
        ),
        InteractionIntentionType.ACKNOWLEDGE: frozenset(
            {
                InteractionIntentionType.ACKNOWLEDGE,
                InteractionIntentionType.LISTEN,
            }
        ),
        InteractionIntentionType.LISTEN: frozenset(
            {
                InteractionIntentionType.LISTEN,
                InteractionIntentionType.ACKNOWLEDGE,
            }
        ),
        InteractionIntentionType.ASK: frozenset(
            {
                InteractionIntentionType.ASK,
                InteractionIntentionType.INVITE,
            }
        ),
        InteractionIntentionType.SHARE: frozenset(
            {
                InteractionIntentionType.SHARE,
                InteractionIntentionType.ACKNOWLEDGE,
            }
        ),
        InteractionIntentionType.INVITE: frozenset(
            {
                InteractionIntentionType.INVITE,
                InteractionIntentionType.ASK,
                InteractionIntentionType.SHARE,
            }
        ),
        InteractionIntentionType.COMFORT: frozenset(
            {
                InteractionIntentionType.COMFORT,
                InteractionIntentionType.ACKNOWLEDGE,
                InteractionIntentionType.SHARE,
            }
        ),
        InteractionIntentionType.SET_BOUNDARY: frozenset(
            {
                InteractionIntentionType.SET_BOUNDARY,
                InteractionIntentionType.SHARE,
                InteractionIntentionType.ACKNOWLEDGE,
            }
        ),
        InteractionIntentionType.PAUSE: frozenset(
            {
                InteractionIntentionType.PAUSE,
                InteractionIntentionType.OBSERVE,
                InteractionIntentionType.LISTEN,
            }
        ),
        InteractionIntentionType.ACT: frozenset(
            {InteractionIntentionType.ACT}
        ),
        InteractionIntentionType.OBSERVE: frozenset(
            {
                InteractionIntentionType.OBSERVE,
                InteractionIntentionType.PAUSE,
                InteractionIntentionType.LISTEN,
            }
        ),
    }

    def __init__(
        self,
        *,
        appraiser: InteractionIntentionAppraiser | None = None,
        trace_logger: TraceLogger | None = None,
        causal_observer: CausalDecisionObserver | None = None,
    ) -> None:
        self._appraiser = appraiser or InteractionIntentionAppraiser()
        self._trace_logger = trace_logger or TraceLogger()
        self._causal_observer = causal_observer or CausalDecisionObserver()

    def observe(
        self,
        meaning: StructuredInputMeaning,
        directive: InternalDirective,
        planning_input: Mapping[str, object],
        *,
        comparison_stage: str = "normalized_internal_directive_candidate",
    ) -> InternalDirectivePlanningObservation:
        intention = self._appraiser.appraise(meaning, planning_input)
        projection = self.project_directive(directive)
        exact = intention.intention is projection
        compatible = projection in self._COMPATIBLE[intention.intention]
        comparison = InteractionIntentionComparison(
            expected=intention.intention,
            directive_projection=projection,
            exact_match=exact,
            compatible=compatible,
            comparison_stage=comparison_stage,
            reason=(
                "exact_intention_match"
                if exact
                else "compatible_intention_projection"
                if compatible
                else "interaction_intention_mismatch"
            ),
        )
        self._trace_logger.info(
            "interaction_intention:shadow_compared",
            input_speech_act=meaning.input_speech_act.value,
            primary_intent=meaning.primary_intent,
            expected_response=meaning.expected_response.value,
            target_type=(
                meaning.target.target_type if meaning.target is not None else None
            ),
            target_id=(
                meaning.target.target_id if meaning.target is not None else None
            ),
            intention=intention.intention.value,
            intention_source=intention.source,
            intention_reason=intention.reason,
            intention_confidence=intention.confidence,
            directive_response_mode=directive.response_mode.value,
            directive_has_activity_intent=directive.activity_intent is not None,
            directive_projection=projection.value,
            exact_match=exact,
            compatible=compatible,
            comparison_stage=comparison_stage,
        )
        self._causal_observer.observe_interaction_intention(
            intention,
            comparison,
        )
        return InternalDirectivePlanningObservation(
            directive=directive,
            interaction_intention=intention,
            comparison=comparison,
        )

    @classmethod
    def project_directive(
        cls,
        directive: InternalDirective,
    ) -> InteractionIntentionType:
        if directive.activity_intent is not None:
            return InteractionIntentionType.ACT
        semantic_text = " ".join(
            (
                directive.response_goal,
                directive.reason,
                *directive.content_requirements,
                *directive.forbidden_claims,
            )
        ).casefold()
        if cls._contains(
            semantic_text,
            ("set_boundary", "boundary", "refus", "境界", "拒否", "やめて"),
        ):
            return InteractionIntentionType.SET_BOUNDARY
        if cls._contains(
            semantic_text,
            ("comfort", "console", "empath", "寄り添", "慰め", "共感"),
        ):
            return InteractionIntentionType.COMFORT
        if cls._contains(
            semantic_text,
            ("invite", "encourage participation", "誘う", "促す"),
        ):
            return InteractionIntentionType.INVITE
        if cls._contains(
            semantic_text,
            ("pause", "no response", "silence", "待機", "発話しない"),
        ):
            return InteractionIntentionType.PAUSE
        return {
            ResponseMode.ANSWER: InteractionIntentionType.ANSWER,
            ResponseMode.LISTEN: InteractionIntentionType.LISTEN,
            ResponseMode.REACT: InteractionIntentionType.ACKNOWLEDGE,
            ResponseMode.ASK: InteractionIntentionType.ASK,
            ResponseMode.SPEAK: InteractionIntentionType.SHARE,
            ResponseMode.OBSERVE: InteractionIntentionType.OBSERVE,
        }[directive.response_mode]

    @staticmethod
    def _contains(text: str, tokens: tuple[str, ...]) -> bool:
        return any(token in text for token in tokens)
