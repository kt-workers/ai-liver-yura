"""試験専用Ownerの型付き参照を明示したsnapshotへ束縛する。"""

from dataclasses import replace

from app.domain.contracts.finalization import AuthorityFinalizationParticipant
from app.domain.executive.contracts import ExecutiveContextSnapshot, ExecutiveFactKind
from app.domain.executive.speech_references import (
    ExecutiveSpeechResolutionKind,
    ExecutiveSpeechSourceBinding,
)
from app.domain.speech_semantics_vocabulary import SpeechSourceContractKind


class TestSourceOwner:
    def __init__(self) -> None:
        self.participant = AuthorityFinalizationParticipant(self, "test-speech-source", 16)


OWNER = TestSourceOwner()
KINDS = {
    ExecutiveFactKind.GOAL: SpeechSourceContractKind.GOAL,
    ExecutiveFactKind.COMMITMENT: SpeechSourceContractKind.COMMITMENT,
    ExecutiveFactKind.MEMORY_EVIDENCE: SpeechSourceContractKind.MEMORY,
}


def bind_test_sources(context: ExecutiveContextSnapshot) -> ExecutiveContextSnapshot:
    return replace(
        context,
        speech_source_bindings=tuple(
            ExecutiveSpeechSourceBinding(
                f.fact_id,
                ExecutiveSpeechResolutionKind.UPSTREAM_FACT,
                "test-speech-source",
                KINDS[f.kind],
                f.fact_id,
                f.revision,
                f.fact_id,
                f.kind,
                f.revision,
                (OWNER.participant.token(),),
            )
            for f in context.facts
            if f.kind in KINDS
        ),
    )
