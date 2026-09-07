from app.domain.memory_reflection import ReflectionOperationalPolicy

TEST_REFLECTION_POLICY_ID = "test.reflection.operational"
TEST_REFLECTION_POLICY_REVISION = 1


def reflection_operational_policy(
    *,
    revision: int = TEST_REFLECTION_POLICY_REVISION,
    max_primary_sources: int = 32,
    max_related_memory_items: int = 64,
    max_context_estimated_tokens: int = 16_384,
    max_source_excerpt_codepoints: int = 512,
    max_proposals_per_reflection: int = 32,
    max_relation_hints_per_proposal: int = 16,
    max_evidence_refs_per_proposal: int = 32,
    max_concurrent_reflections: int = 2,
) -> ReflectionOperationalPolicy:
    return ReflectionOperationalPolicy(
        TEST_REFLECTION_POLICY_ID,
        revision,
        max_primary_sources,
        max_related_memory_items,
        max_context_estimated_tokens,
        max_source_excerpt_codepoints,
        max_proposals_per_reflection,
        max_relation_hints_per_proposal,
        max_evidence_refs_per_proposal,
        max_concurrent_reflections,
    )
