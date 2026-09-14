"""Reflection production Portで受理したV1候補を実PostgreSQLへ保存する。"""

import pytest

from app.domain.memory import MemoryStoreAuthority, MemoryWriteRequest
from app.domain.memory.semantic_assertions import MemorySemanticAssertionUnavailableReason
from app.domain.memory_reflection.llm_roles import (
    LLMReflectionProposalPort,
    LLMReflectionSupportPort,
)
from app.infrastructure.persistence import PostgresEndpoint
from app.infrastructure.persistence.postgresql_connection import PostgresDatabase
from app.infrastructure.persistence.postgresql_memory import PostgresMemoryRepository
from tests.domain.memory_reflection.test_llm_roles import RolePort, role_policy, snapshot
from tests.domain.memory_reflection.test_memory_reflection import NOW, authority
from tests.infrastructure.postgresql.test_memory import POLICY


@pytest.mark.asyncio
async def test_accepted_v1_candidate_round_trips_without_v2_facets(
    endpoint: PostgresEndpoint,
) -> None:
    port, policy, context = RolePort(), role_policy(), snapshot()
    proposal = (await LLMReflectionProposalPort(port, policy, now=lambda: NOW).propose(context))[0]
    support = await LLMReflectionSupportPort(port, policy, now=lambda: NOW).observe(
        context, proposal
    )
    accepted = authority().accept(context, proposal, support)
    assert accepted.candidate is not None and accepted.candidate.assertion_semantics is None
    db = PostgresDatabase.connect(endpoint, POLICY)
    try:
        repo = PostgresMemoryRepository(db)
        repo.migrate()
        result = MemoryStoreAuthority(repo).write(MemoryWriteRequest(accepted.candidate))
        assert result.record is not None
        stored = repo.get(result.record.memory_id)
        assert stored is not None and stored.content == proposal.content
        assert stored.assertion_semantics is None
        publication = MemoryStoreAuthority(repo).read_semantic_assertion_publication(
            stored.memory_id
        )
        assert publication.tokens == ()
        assert (
            publication.value.unavailable_reason
            is MemorySemanticAssertionUnavailableReason.SEMANTICS_UNRESOLVED
        )
    finally:
        db.close()
