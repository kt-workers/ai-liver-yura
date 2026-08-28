from tools.loop_engine.models import ConflictKind, WriteIntent
from tools.loop_engine.write_gate import validate


def test_write_gate_rejects_project_six_stale_head_stale_field_and_trunk() -> None:
    project_six = WriteIntent("i", "project", "6", "edit", (), (), "epoch")
    stale = WriteIntent(
        "i", "project", "7", "edit", (("head", "old"),), (("effect", "x"),), "epoch"
    )
    stale_field = WriteIntent(
        "i", "project", "7", "edit", (("field_id", "old"),), (("effect", "x"),), "epoch"
    )
    trunk = WriteIntent(
        "i", "branch", "rebuild/v2-foundation", "content",
        (("branch_ref", "rebuild/v2-foundation"),), (("effect", "x"),), "epoch",
    )
    assert validate(project_six, {}).conflict is ConflictKind.FORBIDDEN_PROJECT_IDENTITY
    assert validate(stale, {"head": "new"}).conflict is ConflictKind.STALE_WRITE_GATE
    assert validate(stale_field, {"field_id": "new"}).conflict is ConflictKind.STALE_WRITE_GATE
    assert validate(trunk, {}).conflict is ConflictKind.DIRECT_TRUNK_WRITE_FORBIDDEN


def test_write_gate_requires_exact_precondition_and_effect_readback() -> None:
    intent = WriteIntent(
        "i", "project", "7", "edit", (("head", "h"),), (("status", "Done"),), "epoch"
    )
    mismatch = validate(intent, {"head": "h"}, {"status": "In progress"})
    passed = validate(intent, {"head": "h"}, {"status": "Done"})
    missing = validate(intent, {"head": "h"})
    assert mismatch.conflict is ConflictKind.MUTATION_EFFECT_MISMATCH
    assert missing.conflict is ConflictKind.MUTATION_EFFECT_MISMATCH
    assert passed.allowed


def test_write_gate_rejects_noop_and_content_without_exact_identity() -> None:
    noop = WriteIntent("i", "project", "7", "edit", (), (), "epoch")
    unknown_branch = WriteIntent(
        "i", "branch", "feature/x", "content", (("branch_ref", "feature/x"),),
        (("effect", "x"),), "epoch",
    )
    assert validate(noop, {}).conflict is ConflictKind.NO_OP_MUTATION_FORBIDDEN
    assert (
        validate(unknown_branch, {"branch_ref": "feature/x"}).conflict
        is ConflictKind.UNKNOWN_WRITE_IDENTITY_FORBIDDEN
    )
