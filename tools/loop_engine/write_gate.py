"""Pure Write Gate; adapters must perform mutations only after this check."""

from __future__ import annotations

from collections.abc import Mapping

from .models import ConflictKind, WriteGateResult, WriteIntent


def validate(
    intent: WriteIntent,
    fresh_preconditions: Mapping[str, str],
    readback_effect: Mapping[str, str] | None = None,
) -> WriteGateResult:
    if intent.target_kind == "project" and intent.target_identity != "7":
        return WriteGateResult(False, ConflictKind.FORBIDDEN_PROJECT_IDENTITY)
    if intent.target_kind == "branch" and intent.target_identity == "rebuild/v2-foundation":
        return WriteGateResult(False, ConflictKind.DIRECT_TRUNK_WRITE_FORBIDDEN)
    if intent.target_kind == "branch" and intent.mutation_kind == "content":
        required = {"branch_ref", "pr_number", "head_sha"}
        if required.difference(dict(intent.expected_preconditions)):
            return WriteGateResult(False, ConflictKind.UNKNOWN_WRITE_IDENTITY_FORBIDDEN)
    if intent.mutation_kind != "verify_effect" and not intent.expected_preconditions:
        return WriteGateResult(False, ConflictKind.NO_OP_MUTATION_FORBIDDEN)
    if intent.mutation_kind != "verify_effect" and not intent.expected_effect:
        return WriteGateResult(False, ConflictKind.NO_OP_MUTATION_FORBIDDEN)
    if any(fresh_preconditions.get(key) != value for key, value in intent.expected_preconditions):
        return WriteGateResult(False, ConflictKind.STALE_WRITE_GATE)
    if readback_effect is not None and any(
        readback_effect.get(key) != value for key, value in intent.expected_effect
    ):
        return WriteGateResult(False, ConflictKind.MUTATION_EFFECT_MISMATCH)
    return WriteGateResult(True, None)
