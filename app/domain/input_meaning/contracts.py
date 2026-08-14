from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from app.domain.contracts.common import require_identifier, require_revision


class SpeechAct(str, Enum):
    STATEMENT = "statement"
    QUESTION = "question"
    REQUEST = "request"
    COMMAND = "command"
    CONFIRMATION = "confirmation"
    DENIAL = "denial"
    GREETING = "greeting"
    FAREWELL = "farewell"
    OTHER = "other"


class PrimaryIntent(str, Enum):
    PROVIDE_INFORMATION = "provide_information"
    REQUEST_INFORMATION = "request_information"
    REQUEST_ACTION = "request_action"
    CONFIRM = "confirm"
    DENY = "deny"
    START_ACTIVITY = "start_activity"
    STOP_ACTIVITY = "stop_activity"
    ASK_INTERNAL_STATE = "ask_internal_state"
    SOCIAL = "social"
    OTHER = "other"


class ExpectedResponse(str, Enum):
    NONE = "none"
    ACKNOWLEDGEMENT = "acknowledgement"
    ANSWER = "answer"
    ACTION = "action"
    CLARIFICATION = "clarification"
    CONTINUATION = "continuation"


class TemporalRelation(str, Enum):
    PAST = "past"
    PRESENT = "present"
    FUTURE = "future"
    RELATIVE = "relative"
    UNSPECIFIED = "unspecified"


class MeaningResolution(str, Enum):
    RESOLVED = "resolved"
    CLARIFICATION_REQUIRED = "clarification_required"


class ReferenceContextKind(str, Enum):
    RECENT_SPEECH = "recent_speech"
    PRESENTATION_FACT = "presentation_fact"
    EXECUTIVE_DECISION = "executive_decision"
    GOAL_COMMITMENT = "goal_commitment"
    ACTIVITY_FACT = "activity_fact"
    ACTUAL_EXECUTION_FACT = "actual_execution_fact"
    CURRENT_TOPIC = "current_topic"
    MEMORY_EVIDENCE = "memory_evidence"


@dataclass(frozen=True, slots=True)
class ReferenceContextEntry:
    reference_id: str
    kind: ReferenceContextKind
    subject_ref: str
    revision: int

    def __post_init__(self) -> None:
        require_identifier(self.reference_id, "reference_id")
        require_identifier(self.subject_ref, "subject_ref")
        require_revision(self.revision, "revision")

    def to_dict(self) -> dict[str, object]:
        return {
            "reference_id": self.reference_id,
            "kind": self.kind.value,
            "subject_ref": self.subject_ref,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class ReferenceContext:
    source_context_revision: int
    entries: tuple[ReferenceContextEntry, ...] = ()
    max_entries: int = 32

    def __post_init__(self) -> None:
        require_revision(self.source_context_revision, "source_context_revision")
        if type(self.max_entries) is not int or self.max_entries < 1:
            raise ValueError("max_entries must be a positive int")
        entries = tuple(self.entries)
        if len(entries) > self.max_entries:
            raise ValueError("reference context exceeds max_entries")
        ids = [item.reference_id for item in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("reference context ids must be unique")
        if any(item.revision > self.source_context_revision for item in entries):
            raise ValueError("reference entry cannot be newer than context")
        object.__setattr__(self, "entries", entries)

    def to_dict(self) -> dict[str, object]:
        return {
            "source_context_revision": self.source_context_revision,
            "entries": [item.to_dict() for item in self.entries],
        }


@dataclass(frozen=True, slots=True)
class MeaningEntity:
    entity_id: str
    entity_type: str
    canonical_ref: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.entity_id, "entity_id")
        require_identifier(self.entity_type, "entity_type")
        if self.canonical_ref is not None:
            require_identifier(self.canonical_ref, "canonical_ref")

    def to_dict(self) -> dict[str, object]:
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "canonical_ref": self.canonical_ref,
        }


@dataclass(frozen=True, slots=True)
class MeaningReference:
    mention_id: str
    resolved_ref: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.mention_id, "mention_id")
        if self.resolved_ref is not None:
            require_identifier(self.resolved_ref, "resolved_ref")

    def to_dict(self) -> dict[str, object]:
        return {"mention_id": self.mention_id, "resolved_ref": self.resolved_ref}


@dataclass(frozen=True, slots=True)
class StructuredInputMeaning:
    source_event_id: str
    source_context_revision: int
    speech_act: SpeechAct
    primary_intent: PrimaryIntent
    expected_response: ExpectedResponse
    target_ref: str | None
    entities: tuple[MeaningEntity, ...]
    references: tuple[MeaningReference, ...]
    information: tuple[str, ...]
    negated: bool
    hypothetical: bool
    temporal_relation: TemporalRelation
    confidence: float
    unresolved_fields: tuple[str, ...]
    resolution: MeaningResolution

    def __post_init__(self) -> None:
        require_identifier(self.source_event_id, "source_event_id")
        require_revision(self.source_context_revision, "source_context_revision")
        if self.target_ref is not None:
            require_identifier(self.target_ref, "target_ref")
        if type(self.confidence) not in (int, float) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        for name in ("entities", "references", "information", "unresolved_fields"):
            values = tuple(getattr(self, name))
            object.__setattr__(self, name, values)
        if any(not isinstance(item, str) or not item.strip() for item in self.information):
            raise ValueError("information must contain non-empty strings")
        if any(not isinstance(item, str) or not item.strip() for item in self.unresolved_fields):
            raise ValueError("unresolved_fields must contain non-empty strings")
        if len(set(self.unresolved_fields)) != len(self.unresolved_fields):
            raise ValueError("unresolved_fields must be unique")
        expected = (
            MeaningResolution.CLARIFICATION_REQUIRED
            if self.unresolved_fields
            else MeaningResolution.RESOLVED
        )
        if self.resolution is not expected:
            raise ValueError("resolution must agree with unresolved_fields")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_event_id": self.source_event_id,
            "source_context_revision": self.source_context_revision,
            "speech_act": self.speech_act.value,
            "primary_intent": self.primary_intent.value,
            "expected_response": self.expected_response.value,
            "target_ref": self.target_ref,
            "entities": [item.to_dict() for item in self.entities],
            "references": [item.to_dict() for item in self.references],
            "information": list(self.information),
            "negated": self.negated,
            "hypothetical": self.hypothetical,
            "temporal_relation": self.temporal_relation.value,
            "confidence": self.confidence,
            "unresolved_fields": list(self.unresolved_fields),
            "resolution": self.resolution.value,
        }


def meaning_from_json(
    value: object, *, source_event_id: str, source_context_revision: int, minimum_confidence: float
) -> StructuredInputMeaning:
    if not isinstance(value, Mapping):
        raise ValueError("meaning output must be an object")
    required = {
        "speech_act",
        "primary_intent",
        "expected_response",
        "target_ref",
        "entities",
        "references",
        "information",
        "negated",
        "hypothetical",
        "temporal_relation",
        "confidence",
        "unresolved_fields",
    }
    if set(value) != required:
        raise ValueError("meaning output fields do not match schema")
    entities_raw, references_raw = value["entities"], value["references"]
    if not isinstance(entities_raw, (list, tuple)) or not isinstance(references_raw, (list, tuple)):
        raise ValueError("entities and references must be arrays")
    entities = tuple(_entity(item) for item in entities_raw)
    references = tuple(_reference(item) for item in references_raw)
    information = _strings(value["information"], "information")
    unresolved = list(_strings(value["unresolved_fields"], "unresolved_fields"))
    confidence = value["confidence"]
    if type(confidence) not in (int, float):
        raise ValueError("confidence must be a number")
    target = value["target_ref"]
    if target is not None and not isinstance(target, str):
        raise ValueError("target_ref must be a string or null")
    if confidence < minimum_confidence and "confidence" not in unresolved:
        unresolved.append("confidence")
    target_required = value["primary_intent"] in {
        PrimaryIntent.REQUEST_ACTION.value,
        PrimaryIntent.START_ACTIVITY.value,
        PrimaryIntent.STOP_ACTIVITY.value,
    }
    if target_required and target is None and "target_ref" not in unresolved:
        unresolved.append("target_ref")
    if any(item.resolved_ref is None for item in references) and "references" not in unresolved:
        unresolved.append("references")
    return StructuredInputMeaning(
        source_event_id,
        source_context_revision,
        SpeechAct(value["speech_act"]),
        PrimaryIntent(value["primary_intent"]),
        ExpectedResponse(value["expected_response"]),
        target,
        entities,
        references,
        information,
        _bool(value["negated"], "negated"),
        _bool(value["hypothetical"], "hypothetical"),
        TemporalRelation(value["temporal_relation"]),
        confidence,
        tuple(unresolved),
        MeaningResolution.CLARIFICATION_REQUIRED if unresolved else MeaningResolution.RESOLVED,
    )


def _strings(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(x, str) or not x.strip() for x in value
    ):
        raise ValueError(f"{name} must be an array of non-empty strings")
    return tuple(value)


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean")
    return value


def _entity(value: object) -> MeaningEntity:
    if not isinstance(value, Mapping) or set(value) != {
        "entity_id",
        "entity_type",
        "canonical_ref",
    }:
        raise ValueError("entity fields do not match schema")
    return MeaningEntity(value["entity_id"], value["entity_type"], value["canonical_ref"])


def _reference(value: object) -> MeaningReference:
    if not isinstance(value, Mapping) or set(value) != {"mention_id", "resolved_ref"}:
        raise ValueError("reference fields do not match schema")
    return MeaningReference(value["mention_id"], value["resolved_ref"])
