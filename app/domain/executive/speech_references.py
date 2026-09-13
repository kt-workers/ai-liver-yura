"""Executiveが選択したSpeech参照を元Ownerの型付き解決記録へ束縛する。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from app.domain.contracts.common import require_identifier, require_revision
from app.domain.contracts.finalization import AuthorityGenerationToken
from app.domain.speech_semantics_vocabulary import (
    SpeechSemanticContextError,
    SpeechSemanticContextFailureCode,
    SpeechSourceContractKind,
)

if TYPE_CHECKING:
    from .contracts import (
        ExecutiveCommitState,
        ExecutiveContextSnapshot,
        ExecutiveDecisionCandidate,
    )


class ExecutiveFactKind(str, Enum):
    PLAN = "plan"
    GOAL = "goal"
    COMMITMENT = "commitment"
    MEMORY_EVIDENCE = "memory_evidence"
    RELATIONSHIP = "relationship"
    ACTIVITY = "activity"
    EXECUTION = "execution"
    TURN = "turn"
    ATTENTION = "attention"
    SPEECH = "speech"
    BODY = "body"
    TIME = "time"
    ENVIRONMENT = "environment"


class ExecutiveSpeechReferenceRole(str, Enum):
    SEMANTIC_GOAL = "semantic_goal"
    TARGET = "target"
    EVIDENCE = "evidence"
    FORBIDDEN_CLAIM = "forbidden_claim"
    CONSTRAINT = "constraint"


class ExecutiveSpeechResolutionKind(str, Enum):
    UPSTREAM_FACT = "upstream_fact"
    TYPED_CONSTRAINT = "typed_constraint"
    COMMUNICATIVE_ACT_DEFINITION = "communicative_act_definition"


@dataclass(frozen=True, slots=True)
class ExecutiveSpeechSourceBinding:
    selected_ref: str
    resolution_kind: ExecutiveSpeechResolutionKind
    source_owner: str
    source_contract_kind: SpeechSourceContractKind
    source_identity: str
    source_revision: int
    fact_id: str | None = None
    fact_kind: ExecutiveFactKind | None = None
    fact_revision: int | None = None
    source_tokens: tuple[AuthorityGenerationToken, ...] = ()

    def __post_init__(self) -> None:
        for name in ("selected_ref", "source_owner", "source_identity"):
            require_identifier(getattr(self, name), name)
        require_revision(self.source_revision, "source_revision")
        if not isinstance(self.source_contract_kind, SpeechSourceContractKind):
            raise ValueError("元Owner契約の型が不正です")
        if self.resolution_kind is ExecutiveSpeechResolutionKind.UPSTREAM_FACT:
            if (
                self.fact_id != self.selected_ref
                or not isinstance(self.fact_kind, ExecutiveFactKind)
                or type(self.fact_revision) is not int
                or self.fact_revision != self.source_revision
            ):
                raise ValueError("Fact参照の識別とリビジョンが一致しません")
            expected = {
                SpeechSourceContractKind.GOAL: (ExecutiveFactKind.GOAL,),
                SpeechSourceContractKind.COMMITMENT: (ExecutiveFactKind.COMMITMENT,),
                SpeechSourceContractKind.EXECUTION: (
                    ExecutiveFactKind.EXECUTION,
                    ExecutiveFactKind.ACTIVITY,
                ),
                SpeechSourceContractKind.MEMORY: (ExecutiveFactKind.MEMORY_EVIDENCE,),
                SpeechSourceContractKind.ATTENTION: (ExecutiveFactKind.ATTENTION,),
            }
            if self.fact_kind not in expected.get(self.source_contract_kind, ()):
                raise SpeechSemanticContextError(
                    SpeechSemanticContextFailureCode.SOURCE_KIND_MISMATCH
                )
        elif self.resolution_kind is ExecutiveSpeechResolutionKind.TYPED_CONSTRAINT:
            if self.source_contract_kind is not SpeechSourceContractKind.TRUTH_CONSTRAINT:
                raise ValueError("専用制約のsource契約が不正です")
            if any(x is not None for x in (self.fact_id, self.fact_kind, self.fact_revision)):
                raise ValueError("専用制約はFact fieldを持てません")
        else:
            raise ValueError("source bindingの種類が不正です")
        if type(self.source_tokens) is not tuple or any(
            not isinstance(t, AuthorityGenerationToken) for t in self.source_tokens
        ):
            raise ValueError("source tokenが不正です")

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "selected_ref": self.selected_ref,
            "resolution_kind": self.resolution_kind.value,
            "source_owner": self.source_owner,
            "source_contract_kind": self.source_contract_kind.value,
            "source_identity": self.source_identity,
            "source_revision": self.source_revision,
        }
        if self.resolution_kind is ExecutiveSpeechResolutionKind.UPSTREAM_FACT:
            assert self.fact_kind is not None
            value.update(
                fact_id=self.fact_id,
                fact_kind=self.fact_kind.value,
                fact_revision=self.fact_revision,
            )
        return value


@dataclass(frozen=True, slots=True)
class ExecutiveSpeechReferenceResolution:
    intent_id: str
    role: ExecutiveSpeechReferenceRole
    selected_ref: str
    resolution_kind: ExecutiveSpeechResolutionKind
    source: ExecutiveSpeechSourceBinding | None = None
    definition_id: str | None = None
    definition_revision: int | None = None
    meaning_policy_id: str | None = None
    meaning_policy_revision: int | None = None

    def __post_init__(self) -> None:
        require_identifier(self.intent_id, "intent_id")
        require_identifier(self.selected_ref, "selected_ref")
        if not isinstance(self.role, ExecutiveSpeechReferenceRole):
            raise ValueError("Speech参照roleが不正です")
        if self.resolution_kind is ExecutiveSpeechResolutionKind.COMMUNICATIVE_ACT_DEFINITION:
            if (
                self.role is not ExecutiveSpeechReferenceRole.SEMANTIC_GOAL
                or self.source is not None
                or self.definition_id != self.selected_ref
            ):
                raise ValueError("definition参照のroleと識別が不正です")
            if not isinstance(self.meaning_policy_id, str):
                raise ValueError("意味方針識別子が必要です")
            require_identifier(self.meaning_policy_id, "meaning_policy_id")
            require_revision(self.meaning_policy_revision, "meaning_policy_revision")
            require_revision(self.definition_revision, "definition_revision")
        else:
            if (
                not isinstance(self.source, ExecutiveSpeechSourceBinding)
                or self.source.selected_ref != self.selected_ref
                or self.source.resolution_kind is not self.resolution_kind
            ):
                raise ValueError("元source参照が不一致です")
            if (
                self.resolution_kind is ExecutiveSpeechResolutionKind.TYPED_CONSTRAINT
                and self.role is not ExecutiveSpeechReferenceRole.CONSTRAINT
            ):
                raise ValueError("専用制約はCONSTRAINTだけに使用できます")
            if any(
                x is not None
                for x in (
                    self.definition_id,
                    self.definition_revision,
                    self.meaning_policy_id,
                    self.meaning_policy_revision,
                )
            ):
                raise ValueError("source参照へdefinitionを混在できません")

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "intent_id": self.intent_id,
            "role": self.role.value,
            "selected_ref": self.selected_ref,
            "resolution_kind": self.resolution_kind.value,
        }
        if self.source is not None:
            value.update(self.source.to_dict())
        else:
            value.update(
                definition_id=self.definition_id,
                definition_revision=self.definition_revision,
                meaning_policy_id=self.meaning_policy_id,
                meaning_policy_revision=self.meaning_policy_revision,
            )
        return value


def required_speech_references(
    candidate: ExecutiveDecisionCandidate,
) -> tuple[tuple[str, ExecutiveSpeechReferenceRole, str], ...]:
    from .contracts import ExecutiveIntentKind, SpeechIntentPayload

    roles = ExecutiveSpeechReferenceRole
    result = []
    for intent in candidate.intents:
        if intent.kind is not ExecutiveIntentKind.SPEECH:
            continue
        assert isinstance(intent.payload, SpeechIntentPayload)
        payload = intent.payload
        result.append((intent.intent_id, roles.SEMANTIC_GOAL, payload.semantic_goal_ref))
        if payload.target_ref is not None:
            result.append((intent.intent_id, roles.TARGET, payload.target_ref))
        for role, refs in (
            (roles.EVIDENCE, intent.evidence_refs),
            (roles.FORBIDDEN_CLAIM, intent.forbidden_claim_refs),
            (roles.CONSTRAINT, payload.constraint_refs),
        ):
            result.extend((intent.intent_id, role, ref) for ref in refs)
    return tuple(result)


def validate_resolution_keys(
    candidate: ExecutiveDecisionCandidate,
    resolutions: tuple[ExecutiveSpeechReferenceResolution, ...],
) -> None:
    if (
        type(resolutions) is not tuple
        or any(not isinstance(r, ExecutiveSpeechReferenceResolution) for r in resolutions)
        or tuple((r.intent_id, r.role, r.selected_ref) for r in resolutions)
        != required_speech_references(candidate)
    ):
        raise SpeechSemanticContextError(SpeechSemanticContextFailureCode.SOURCE_IDENTITY_MISMATCH)


def resolve_speech_references(
    candidate: ExecutiveDecisionCandidate,
    snapshot: ExecutiveContextSnapshot,
    current: ExecutiveCommitState,
) -> tuple[ExecutiveSpeechReferenceResolution, ...]:
    error = SpeechSemanticContextError
    codes = SpeechSemanticContextFailureCode
    captured = {x.selected_ref: x for x in snapshot.speech_source_bindings}
    live = {x.selected_ref: x for x in current.speech_source_bindings}
    if len(captured) != len(snapshot.speech_source_bindings) or len(live) != len(
        current.speech_source_bindings
    ):
        raise error(codes.SOURCE_IDENTITY_MISMATCH)
    catalog = snapshot.communicative_goal_catalog
    definitions = {} if catalog is None else {x.definition_id: x for x in catalog.definitions}
    facts = {x.fact_id: x for x in snapshot.facts}
    if set(definitions) & (set(facts) | set(captured)):
        raise error(codes.SOURCE_IDENTITY_MISMATCH)
    result = []
    for intent_id, role, ref in required_speech_references(candidate):
        if ref in definitions:
            if role is not ExecutiveSpeechReferenceRole.SEMANTIC_GOAL:
                raise error(codes.SOURCE_KIND_MISMATCH)
            if catalog != current.communicative_goal_catalog or catalog is None:
                raise error(codes.SEMANTIC_POLICY_STALE)
            definition = definitions[ref]
            result.append(
                ExecutiveSpeechReferenceResolution(
                    intent_id,
                    role,
                    ref,
                    ExecutiveSpeechResolutionKind.COMMUNICATIVE_ACT_DEFINITION,
                    definition_id=ref,
                    definition_revision=definition.definition_revision,
                    meaning_policy_id=catalog.policy_id,
                    meaning_policy_revision=catalog.policy_revision,
                )
            )
            continue
        source = captured.get(ref)
        if source is None:
            raise error(codes.SOURCE_NOT_FOUND)
        if live.get(ref) != source:
            raise error(codes.SOURCE_REVISION_MISMATCH)
        if source.resolution_kind is ExecutiveSpeechResolutionKind.UPSTREAM_FACT:
            fact = facts.get(ref)
            if fact is None or (fact.kind, fact.revision) != (
                source.fact_kind,
                source.fact_revision,
            ):
                raise error(codes.SOURCE_KIND_MISMATCH)
        result.append(
            ExecutiveSpeechReferenceResolution(intent_id, role, ref, source.resolution_kind, source)
        )
    answer = tuple(result)
    validate_resolution_keys(candidate, answer)
    return answer


class ExecutiveContextFailureCode(str, Enum):
    EXECUTIVE_CONTEXT_TOO_LARGE = "EXECUTIVE_CONTEXT_TOO_LARGE"


class ExecutiveContextError(ValueError):
    def __init__(self, code: ExecutiveContextFailureCode) -> None:
        self.code = code
        super().__init__(f"Executive文脈を構築できません: {code.value}")


def speech_source_tokens(
    resolutions: tuple[ExecutiveSpeechReferenceResolution, ...], current: ExecutiveCommitState
) -> tuple[AuthorityGenerationToken, ...]:
    tokens: list[AuthorityGenerationToken] = []
    for resolution in resolutions:
        if resolution.source is not None:
            if not resolution.source.source_tokens:
                raise SpeechSemanticContextError(
                    SpeechSemanticContextFailureCode.UNSUPPORTED_SOURCE_CONTRACT
                )
            if any(
                t.owner_identity != resolution.source.source_owner
                for t in resolution.source.source_tokens
            ):
                raise SpeechSemanticContextError(
                    SpeechSemanticContextFailureCode.SOURCE_OWNER_MISMATCH
                )
            tokens.extend(resolution.source.source_tokens)
        else:
            catalog = current.communicative_goal_catalog
            if catalog is None or not catalog.publication_tokens:
                raise SpeechSemanticContextError(
                    SpeechSemanticContextFailureCode.UNSUPPORTED_SOURCE_CONTRACT
                )
            tokens.extend(catalog.publication_tokens)
    return tuple(tokens)
