from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class InputSpeechAct(str, Enum):
    GREETING = "greeting"
    STATEMENT = "statement"
    QUESTION = "question"
    ANSWER = "answer"
    ACKNOWLEDGEMENT = "acknowledgement"
    CLOSING = "closing"
    REQUEST = "request"
    PROPOSAL = "proposal"
    COMMAND = "command"


class ExpectedResponse(str, Enum):
    DIRECT_ANSWER = "direct_answer"
    ACKNOWLEDGEMENT = "acknowledgement"
    CONTINUE_LISTENING = "continue_listening"
    ACTION = "action"
    CLARIFICATION = "clarification"
    NO_RESPONSE = "no_response"


class ConversationPhaseSignal(str, Enum):
    GREETING = "greeting"
    OPENING = "opening"
    CONTINUE = "continue"
    WINDING_DOWN = "winding_down"


@dataclass(frozen=True, slots=True)
class InputTarget:
    target_type: str
    target_id: str

    def __post_init__(self) -> None:
        target_type = self.target_type.strip()
        target_id = self.target_id.strip()
        if not target_type:
            raise ValueError("target_type must not be empty")
        if not target_id:
            raise ValueError("target_id must not be empty")
        object.__setattr__(self, "target_type", target_type)
        object.__setattr__(self, "target_id", target_id)

    def as_context(self) -> dict[str, str]:
        return {"type": self.target_type, "id": self.target_id}


@dataclass(frozen=True, slots=True)
class StructuredInputMeaning:
    input_speech_act: InputSpeechAct
    primary_intent: str
    expected_response: ExpectedResponse
    target: InputTarget | None
    entities: tuple[dict[str, object], ...] = ()
    references: tuple[dict[str, object], ...] = ()
    information_provided: tuple[str, ...] = ()
    negated: bool = False
    hypothetical: bool = False
    past_reference: bool = False
    conversation_phase_signal: ConversationPhaseSignal = (
        ConversationPhaseSignal.CONTINUE
    )
    confidence: float = 1.0
    reason: str = ""
    source_text: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        intent = self.primary_intent.strip()
        if not intent:
            raise ValueError("primary_intent must not be empty")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        object.__setattr__(self, "primary_intent", intent)
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "reason", self.reason.strip()[:300])
        object.__setattr__(
            self,
            "information_provided",
            tuple(value.strip() for value in self.information_provided if value.strip()),
        )

    def as_context(self, *, include_raw_input: bool = False) -> dict[str, object]:
        context: dict[str, object] = {
            "input_speech_act": self.input_speech_act.value,
            "primary_intent": self.primary_intent,
            "expected_response": self.expected_response.value,
            "target": self.target.as_context() if self.target is not None else None,
            "entities": [dict(value) for value in self.entities],
            "references": [dict(value) for value in self.references],
            "information_provided": list(self.information_provided),
            "negated": self.negated,
            "hypothetical": self.hypothetical,
            "past_reference": self.past_reference,
            "conversation_phase_signal": self.conversation_phase_signal.value,
            "confidence": self.confidence,
            "reason": self.reason,
        }
        if include_raw_input:
            context["source_text"] = self.source_text
        return context


class ResponseMode(str, Enum):
    ANSWER = "answer"
    LISTEN = "listen"
    REACT = "react"
    ASK = "ask"
    SPEAK = "speak"
    OBSERVE = "observe"


class InterestChange(str, Enum):
    INCREASE = "increase"
    SLIGHTLY_INCREASE = "slightly_increase"
    UNCHANGED = "unchanged"
    SLIGHTLY_DECREASE = "slightly_decrease"
    DECREASE = "decrease"


@dataclass(frozen=True, slots=True)
class ActivityIntent:
    activity_type: str
    operation: str
    constraints: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        activity_type = self.activity_type.strip()
        operation = self.operation.strip()
        if not activity_type:
            raise ValueError("activity_type must not be empty")
        if operation not in {"start", "continue", "stop", "explain", "discuss"}:
            raise ValueError("unsupported activity operation")
        object.__setattr__(self, "activity_type", activity_type)
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "constraints", dict(self.constraints))

    def as_context(self) -> dict[str, object]:
        return {
            "activity_type": self.activity_type,
            "operation": self.operation,
            "constraints": dict(self.constraints),
        }


@dataclass(frozen=True, slots=True)
class TargetInterestUpdate:
    target_type: str
    target_id: str
    interest_change: InterestChange
    resolved_knowledge_gaps: tuple[str, ...] = ()
    new_knowledge_gaps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        target_type = self.target_type.strip()
        target_id = self.target_id.strip()
        if not target_type or not target_id:
            raise ValueError("target interest identity must not be empty")
        object.__setattr__(self, "target_type", target_type)
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(
            self,
            "resolved_knowledge_gaps",
            tuple(value.strip() for value in self.resolved_knowledge_gaps if value.strip()),
        )
        object.__setattr__(
            self,
            "new_knowledge_gaps",
            tuple(value.strip() for value in self.new_knowledge_gaps if value.strip()),
        )

    def as_context(self) -> dict[str, object]:
        return {
            "target_type": self.target_type,
            "target_id": self.target_id,
            "interest_change": self.interest_change.value,
            "resolved_knowledge_gaps": list(self.resolved_knowledge_gaps),
            "new_knowledge_gaps": list(self.new_knowledge_gaps),
        }


@dataclass(frozen=True, slots=True)
class InternalDirective:
    response_mode: ResponseMode
    response_goal: str
    activity_intent: ActivityIntent | None
    initiative_level: float
    question_budget: int
    new_direction_budget: int
    self_disclosure_level: float
    content_requirements: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    target_interest_updates: tuple[TargetInterestUpdate, ...] = ()
    state_update_proposals: tuple[dict[str, object], ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        goal = self.response_goal.strip()
        if not goal:
            raise ValueError("response_goal must not be empty")
        if not 0.0 <= float(self.initiative_level) <= 1.0:
            raise ValueError("initiative_level must be between 0.0 and 1.0")
        if not 0 <= int(self.question_budget) <= 3:
            raise ValueError("question_budget must be between 0 and 3")
        if not 0 <= int(self.new_direction_budget) <= 3:
            raise ValueError("new_direction_budget must be between 0 and 3")
        if not 0.0 <= float(self.self_disclosure_level) <= 1.0:
            raise ValueError("self_disclosure_level must be between 0.0 and 1.0")
        object.__setattr__(self, "response_goal", goal)
        object.__setattr__(self, "initiative_level", float(self.initiative_level))
        object.__setattr__(self, "question_budget", int(self.question_budget))
        object.__setattr__(self, "new_direction_budget", int(self.new_direction_budget))
        object.__setattr__(
            self, "self_disclosure_level", float(self.self_disclosure_level)
        )
        object.__setattr__(
            self,
            "content_requirements",
            tuple(value.strip() for value in self.content_requirements if value.strip()),
        )
        object.__setattr__(
            self,
            "forbidden_claims",
            tuple(value.strip() for value in self.forbidden_claims if value.strip()),
        )
        object.__setattr__(self, "reason", self.reason.strip()[:300])

    def as_context(self) -> dict[str, object]:
        return {
            "response_mode": self.response_mode.value,
            "response_goal": self.response_goal,
            "activity_intent": (
                self.activity_intent.as_context()
                if self.activity_intent is not None
                else None
            ),
            "initiative_level": self.initiative_level,
            "question_budget": self.question_budget,
            "new_direction_budget": self.new_direction_budget,
            "self_disclosure_level": self.self_disclosure_level,
            "content_requirements": list(self.content_requirements),
            "forbidden_claims": list(self.forbidden_claims),
            "target_interest_updates": [
                update.as_context() for update in self.target_interest_updates
            ],
            "state_update_proposals": [
                dict(proposal) for proposal in self.state_update_proposals
            ],
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ValidatedActionPlan:
    meaning: StructuredInputMeaning
    directive: InternalDirective
    validation_notes: tuple[str, ...] = ()
    character_profile: dict[str, object] = field(default_factory=dict)
    existence_boundaries: tuple[str, ...] = ()

    def as_context(self) -> dict[str, object]:
        return {
            "structured_input_meaning": self.meaning.as_context(),
            "internal_directive": self.directive.as_context(),
            "validation_notes": list(self.validation_notes),
            "character_profile": dict(self.character_profile),
            "existence_boundaries": list(self.existence_boundaries),
        }
