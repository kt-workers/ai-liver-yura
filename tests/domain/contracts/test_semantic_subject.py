"""主体identityの型・衝突・provenanceと不変性を検証する。"""

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from app.domain.contracts import (
    RuntimeSubjectIdentity,
    SemanticSubjectIdentity,
    SemanticSubjectKind,
)


def test_runtime_subjects_and_provenance() -> None:
    runtime = RuntimeSubjectIdentity("alternate-character", "alternate-character", 2, 7)
    assert runtime.self_subject_ref == runtime.character_id == "alternate-character"
    assert runtime.character_schema_version == 2
    assert runtime.character_definition_revision == 7
    runtime.validate(runtime.self_subject())
    assert runtime.self_subject().kind is SemanticSubjectKind.SELF
    assert runtime.reference_subject("external-owner").kind is SemanticSubjectKind.REFERENCE
    for value, attribute in [(runtime, "character_id"), (runtime.self_subject(), "subject_ref")]:
        with pytest.raises(FrozenInstanceError):
            setattr(value, attribute, "changed")


@pytest.mark.parametrize("ref", ["", " ", None, 123])
def test_invalid_subject_ref(ref: Any) -> None:
    with pytest.raises(ValueError):
        SemanticSubjectIdentity(SemanticSubjectKind.SELF, ref)


@pytest.mark.parametrize("kind", ["SELF", "REFERENCE", "unknown", None, 0])
def test_invalid_kind(kind: Any) -> None:
    with pytest.raises(ValueError):
        SemanticSubjectIdentity(kind, "id")


@pytest.mark.parametrize(
    "values",
    [
        ("", "", 1, 0),
        ("x", "y", 1, 0),
        ("x", "x", 0, 0),
        ("x", "x", True, 0),
        ("x", "x", 1, -1),
        ("x", "x", 1, True),
        ("x", "x", "1", 0),
        ("x", "x", 1, None),
    ],
)
def test_invalid_runtime(values: tuple[Any, Any, Any, Any]) -> None:
    with pytest.raises(ValueError):
        RuntimeSubjectIdentity(*values)


def test_mismatch_collision_and_untyped_input() -> None:
    runtime = RuntimeSubjectIdentity("active", "active", 1, 0)
    with pytest.raises(ValueError):
        runtime.validate(SemanticSubjectIdentity(SemanticSubjectKind.SELF, "other"))
    with pytest.raises(ValueError):
        runtime.reference_subject("active")
    with pytest.raises(ValueError):
        runtime.validate(SemanticSubjectIdentity(SemanticSubjectKind.REFERENCE, "active"))
    invalid: Any = "active"
    with pytest.raises(ValueError):
        runtime.validate(invalid)


@pytest.mark.parametrize("ref", ["私", "自分", "ゆら", "self:active", "active-alias"])
def test_no_alias_or_prefix_inference(ref: str) -> None:
    runtime = RuntimeSubjectIdentity("active", "active", 1, 0)
    assert runtime.reference_subject(ref) == SemanticSubjectIdentity(
        SemanticSubjectKind.REFERENCE, ref
    )
    with pytest.raises(ValueError):
        runtime.validate(SemanticSubjectIdentity(SemanticSubjectKind.SELF, ref))
