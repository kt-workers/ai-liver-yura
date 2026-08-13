import json
from types import MappingProxyType

import pytest

from app.domain.contracts import (
    AuthorityRef,
    IntentKind,
    IntentRef,
    JsonInput,
    PreconditionRef,
    RevisionKind,
    RevisionVector,
)


def test_revision_vector_exposes_only_requested_revisions() -> None:
    revisions = RevisionVector(
        source_context_revision=12,
        goal_revision=4,
        attention_revision=None,
    )

    assert revisions.revision_for(RevisionKind.SOURCE_CONTEXT) == 12
    assert revisions.revision_for(RevisionKind.GOAL) == 4
    assert revisions.revision_for(RevisionKind.ATTENTION) is None
    assert revisions.to_dict() == {
        "source_context_revision": 12,
        "goal_revision": 4,
        "attention_revision": None,
    }


def test_revision_vector_rejects_negative_revision() -> None:
    with pytest.raises(ValueError, match="goal_revision must be non-negative"):
        RevisionVector(source_context_revision=0, goal_revision=-1)


def test_precondition_freezes_nested_json_and_serializes() -> None:
    revision_values = [1, 2]
    source: dict[str, JsonInput] = {"revisions": revision_values, "active": True}
    precondition = PreconditionRef(
        precondition_id="pc-1",
        predicate="goal_revision_matches",
        subject_ref="goal:g-1",
        expected=source,
    )

    revision_values.append(3)

    assert isinstance(precondition.expected, MappingProxyType)
    assert precondition.to_dict()["expected"] == {"revisions": [1, 2], "active": True}
    json.dumps(precondition.to_dict())


@pytest.mark.parametrize("non_finite", [float("nan"), float("inf"), float("-inf")])
def test_precondition_rejects_non_finite_json_numbers(non_finite: float) -> None:
    with pytest.raises(ValueError, match="JSON float values must be finite"):
        PreconditionRef(
            precondition_id="pc-non-finite",
            predicate="value_matches",
            subject_ref="value:1",
            expected={"nested": [non_finite]},
        )


def test_authority_and_intent_refs_require_explicit_non_empty_identity() -> None:
    authority = AuthorityRef(owner="executive", scope="conscious_goal_action_selection")
    intent = IntentRef(intent_id="speech-42", kind=IntentKind.SPEECH)

    assert authority.to_dict()["owner"] == "executive"
    assert intent.to_dict() == {"intent_id": "speech-42", "kind": "speech"}

    with pytest.raises(ValueError):
        AuthorityRef(owner=" ", scope="decision")
