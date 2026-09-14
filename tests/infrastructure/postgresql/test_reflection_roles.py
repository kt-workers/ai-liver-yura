"""Reflection production候補の意味を実PostgreSQL保存・公開まで検証する。"""

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
async def test_accepted_current_candidate_round_trips_without_semantics(
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


@pytest.mark.asyncio
async def test_v2_semantics_reach_store_but_subject_remains_unresolved(
    endpoint: PostgresEndpoint,
) -> None:
    from dataclasses import replace

    from app.domain.memory.contracts import MemoryAssertionPolarity
    from app.domain.memory_reflection.llm_roles import proposal_to_wire_v2
    from tests.domain.memory_reflection.test_llm_roles import candidate
    from tests.domain.memory_reflection.test_semantic_supply import SEMANTICS

    db = PostgresDatabase.connect(endpoint, POLICY)
    try:
        repo = PostgresMemoryRepository(db)
        repo.migrate()
        store = MemoryStoreAuthority(repo)
        ids: list[str] = []
        for polarity in MemoryAssertionPolarity:
            semantics = replace(SEMANTICS, polarity=polarity)
            p = replace(
                candidate(), proposal_id=f"p-{polarity.value}", assertion_semantics=semantics
            )
            policy = role_policy()
            port = RolePort({"proposals": [proposal_to_wire_v2(p)]})
            parsed = (
                await LLMReflectionProposalPort(port, policy, now=lambda: NOW).propose(snapshot())
            )[0]
            from tests.domain.memory_reflection.test_llm_roles import support_wire

            wire = support_wire()
            wire["proposal_id"] = p.proposal_id
            support = await LLMReflectionSupportPort(
                RolePort(wire), policy, now=lambda: NOW
            ).observe(snapshot(), parsed)
            accepted = authority().accept(snapshot(), parsed, support)
            assert accepted.candidate is not None
            assert accepted.candidate.assertion_semantics == semantics
            result = store.write(MemoryWriteRequest(accepted.candidate))
            assert result.record is not None
            ids.append(result.record.memory_id)
            record = repo.get(result.record.memory_id)
            assert record is not None and record.assertion_semantics == semantics
            assert record.content == p.content
            publication = store.read_semantic_assertion_publication(
                record.memory_id, record.revision
            )
            assert record.subject_identity is None
            assert accepted.candidate.subject_identity is None
            assert publication.tokens == ()
            assert publication.value.assertion is None
            assert (
                publication.value.unavailable_reason
                is MemorySemanticAssertionUnavailableReason.SUBJECT_UNRESOLVED
            )
        assert ids[0] != ids[1]
    finally:
        db.close()
