"""実PostgreSQL publicationをSpeech V1へexact搬送する。"""

from dataclasses import replace

from app.composition.speech_semantics_sources import (
    ProductionSpeechSources,
    SpeechOwnerSourceRegistration,
    build_projection_v1,
)
from app.domain.executive.contracts import ExecutiveFactKind, ExecutiveFactRef
from app.domain.memory import MemoryStoreAuthority, MemoryWriteRequest
from app.domain.speech_semantics.production import SpeechSemanticFactProjector
from app.domain.speech_semantics_vocabulary import SpeechSourceContractKind as K
from app.infrastructure.persistence.postgresql_connection import PostgresDatabase, PostgresEndpoint
from app.infrastructure.persistence.postgresql_memory import PostgresMemoryRepository
from tests.domain.memory.test_memory_store_retrieval import candidate
from tests.domain.memory.test_semantic_assertions import SEMANTICS
from tests.domain.speech_semantics.test_production_owner_sources import resolution
from tests.helpers.speech_production import IDENTITY, production_sources
from tests.infrastructure.postgresql.test_memory import POLICY


def test_postgres_owner_publication_to_speech(endpoint: PostgresEndpoint) -> None:
    database = PostgresDatabase.connect(endpoint, POLICY)
    try:
        repository = PostgresMemoryRepository(database)
        repository.migrate()
        memory = MemoryStoreAuthority(repository)
        c = replace(
            candidate(),
            subject_identity=IDENTITY.reference_subject("user:1"),
            assertion_semantics=SEMANTICS,
        )
        record = memory.write(MemoryWriteRequest(c)).record
        assert record is not None
        p = production_sources()
        sources = ProductionSpeechSources(
            goals=p._goals,
            memory=memory,
            execution=p._execution,
            registrations=(
                SpeechOwnerSourceRegistration(
                    record.memory_id, ExecutiveFactKind.MEMORY_EVIDENCE, record.memory_id, K.MEMORY
                ),
            ),
        )
        r = resolution(
            sources,
            ExecutiveFactRef(
                record.memory_id, ExecutiveFactKind.MEMORY_EVIDENCE, record.revision, {}
            ),
        )
        binding = sources.resolve(r)
        assert binding.tokens and all(
            t.owner_identity == "MemoryStoreAuthority" for t in binding.tokens
        )
        fact = SpeechSemanticFactProjector(build_projection_v1(IDENTITY)).project(binding)
        assert fact.subject_ref == "user:1" and fact.predicate == c.content.predicate
        assert fact.value == {
            "semantic_value": c.content.value,
            "temporal_meaning": SEMANTICS.temporal_meaning.value,
            "temporal_scope_ref": None,
            "qualifiers": (),
        }
    finally:
        database.close()
