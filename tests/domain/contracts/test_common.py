from dataclasses import FrozenInstanceError

import pytest

from app.domain.contracts import (
    AuthorityRef,
    IntentKind,
    IntentRef,
    PreconditionRef,
    RevisionVector,
)


@pytest.mark.parametrize("value", [-1, True, False, 1.0, "1"])
def test_revision_rejects_non_concrete_non_negative_int(value: object) -> None:
    with pytest.raises(ValueError):
        RevisionVector(source_context_revision=value)  # type: ignore[arg-type]


def test_revision_serializes_optional_owner_revisions() -> None:
    revisions = RevisionVector(3, goal_revision=4)
    assert revisions.to_dict() == {
        "source_context_revision": 3,
        "goal_revision": 4,
        "attention_revision": None,
    }


def test_precondition_owns_and_serializes_nested_json_snapshot() -> None:
    values = [1, {"ready": True}]
    precondition = PreconditionRef(
        "pre-1",
        "revision_matches",
        "goal-1",
        {"values": values},  # type: ignore[dict-item]
    )
    values.append(2)

    assert precondition.to_dict()["expected"] == {"values": [1, {"ready": True}]}


@pytest.mark.parametrize("value", [{1: "bad"}, {"nested": {1: "bad"}}])
def test_precondition_rejects_non_string_json_keys(value: object) -> None:
    with pytest.raises(ValueError, match="keys must be strings"):
        PreconditionRef("pre-1", "equals", "subject", value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_precondition_rejects_non_finite_json_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        PreconditionRef("pre-1", "equals", "subject", {"value": value})


def test_reference_contracts_are_immutable_and_serializable() -> None:
    authority = AuthorityRef("executive", "activity", "decision-1")
    intent = IntentRef(IntentKind.ACTIVITY, "intent-1")

    assert authority.to_dict()["owner"] == "executive"
    assert intent.to_dict() == {"kind": "activity", "intent_id": "intent-1"}
    with pytest.raises(FrozenInstanceError):
        authority.owner = "plugin"  # type: ignore[misc]
