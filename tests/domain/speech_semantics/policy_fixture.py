"""試験専用の明示方針。production compositionから利用しない。"""

from app.domain.brain_operational_bounds import (
    V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    BrainOperationalBoundsPolicy,
)
from app.domain.speech_semantics_vocabulary import (
    CommunicativeGoalCatalogView,
    SelfDisclosurePolicy,
    SpeechSemanticMeaningPolicy,
)


def explicit_meaning_policy(
    *,
    bounds: BrainOperationalBoundsPolicy = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    disclosure: SelfDisclosurePolicy = SelfDisclosurePolicy.FACT_GROUNDED,
    questions: int = 1,
    directions: int = 1,
) -> SpeechSemanticMeaningPolicy:
    return SpeechSemanticMeaningPolicy(
        "test-only.meaning",
        1,
        disclosure,
        questions,
        directions,
        CommunicativeGoalCatalogView(
            "test-only.meaning", 1, (), bounds.policy_id, bounds.policy_revision
        ),
    )
