from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

from app.shared.contracts.activity import ActivityDefinition


class ExecutionBoundaryEquivalenceStatus(str, Enum):
    """Activity候補間の実行境界同等性評価状態。"""

    UNCONFIRMED = "unconfirmed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AuthorityEquivalenceAssessment:
    """候補間Authority要件の同等性評価。"""

    status: ExecutionBoundaryEquivalenceStatus = (
        ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    )
    authority_role: str = "unknown"
    instruction_trusted: bool = False
    candidate_requirement_contract_available: bool = False
    reasons: tuple[str, ...] = ()

    def as_context(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "authority_role": self.authority_role,
            "instruction_trusted": self.instruction_trusted,
            "candidate_requirement_contract_available": (
                self.candidate_requirement_contract_available
            ),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class CapabilityEquivalenceAssessment:
    """候補間required capabilityの同等性評価。"""

    status: ExecutionBoundaryEquivalenceStatus = (
        ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    )
    requirements: tuple[tuple[str, str | None], ...] = ()
    availability: tuple[tuple[str, bool], ...] = ()
    reasons: tuple[str, ...] = ()

    def as_context(self) -> dict[str, object]:
        availability_by_activity = dict(self.availability)
        return {
            "status": self.status.value,
            "candidates": [
                {
                    "activity_type": activity_type,
                    "required_capability": required_capability,
                    "available": availability_by_activity.get(activity_type, False),
                }
                for activity_type, required_capability in self.requirements
            ],
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class ConstraintEquivalenceAssessment:
    """候補間Constraint schemaの同等性評価。"""

    status: ExecutionBoundaryEquivalenceStatus = (
        ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    )
    schema_versions: tuple[tuple[str, str], ...] = ()
    schema_fingerprints: tuple[tuple[str, str], ...] = ()
    reasons: tuple[str, ...] = ()

    def as_context(self) -> dict[str, object]:
        version_by_activity = dict(self.schema_versions)
        fingerprint_by_activity = dict(self.schema_fingerprints)
        activity_types = tuple(
            dict.fromkeys(
                activity_type
                for activity_type, _ in (
                    self.schema_versions + self.schema_fingerprints
                )
            )
        )
        return {
            "status": self.status.value,
            "candidates": [
                {
                    "activity_type": activity_type,
                    "schema_version": version_by_activity.get(activity_type),
                    "schema_fingerprint": fingerprint_by_activity.get(activity_type),
                }
                for activity_type in activity_types
            ],
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class SafetyEquivalenceAssessment:
    """候補間Safety policyの同等性評価。"""

    status: ExecutionBoundaryEquivalenceStatus = (
        ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    )
    candidate_policy_contract_available: bool = False
    reasons: tuple[str, ...] = ()

    def as_context(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "candidate_policy_contract_available": (
                self.candidate_policy_contract_available
            ),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class ActivityCandidateExecutionBoundaryEquivalenceAssessment:
    """4種の実行境界同等性を保持するShadow診断結果。"""

    candidate_group: tuple[str, ...] = ()
    status: ExecutionBoundaryEquivalenceStatus = (
        ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    )
    authority: AuthorityEquivalenceAssessment = field(
        default_factory=AuthorityEquivalenceAssessment
    )
    capability: CapabilityEquivalenceAssessment = field(
        default_factory=CapabilityEquivalenceAssessment
    )
    constraint: ConstraintEquivalenceAssessment = field(
        default_factory=ConstraintEquivalenceAssessment
    )
    safety: SafetyEquivalenceAssessment = field(
        default_factory=SafetyEquivalenceAssessment
    )
    reasons: tuple[str, ...] = ()

    @property
    def confirmed(self) -> bool:
        return self.status is ExecutionBoundaryEquivalenceStatus.CONFIRMED

    def as_context(self) -> dict[str, object]:
        return {
            "candidate_group": list(self.candidate_group),
            "status": self.status.value,
            "confirmed": self.confirmed,
            "authority": self.authority.as_context(),
            "capability": self.capability.as_context(),
            "constraint": self.constraint.as_context(),
            "safety": self.safety.as_context(),
            "reasons": list(self.reasons),
        }


class ActivityCandidateExecutionBoundaryEquivalenceEvaluator:
    """既存の型付き情報だけで候補間の実行境界差を評価する。"""

    def evaluate(
        self,
        definitions: Sequence[ActivityDefinition],
        candidate_group: Sequence[str],
        *,
        authority_role: str,
        instruction_trusted: bool,
        available_capabilities: frozenset[str],
    ) -> ActivityCandidateExecutionBoundaryEquivalenceAssessment:
        normalized_group = tuple(
            activity_type.strip()
            for activity_type in candidate_group
            if isinstance(activity_type, str) and activity_type.strip()
        )
        normalized_role = authority_role.strip() or "unknown"
        if len(normalized_group) < 2 or len(set(normalized_group)) != len(
            normalized_group
        ):
            return self._unconfirmed(
                normalized_group,
                authority_role=normalized_role,
                instruction_trusted=instruction_trusted,
                reason="execution_boundary_candidate_group_invalid",
            )

        definition_by_activity = {
            definition.activity_type: definition for definition in definitions
        }
        missing = tuple(
            activity_type
            for activity_type in normalized_group
            if activity_type not in definition_by_activity
        )
        if missing:
            return self._unconfirmed(
                normalized_group,
                authority_role=normalized_role,
                instruction_trusted=instruction_trusted,
                reason="execution_boundary_candidate_definition_missing",
            )

        selected = tuple(
            definition_by_activity[activity_type]
            for activity_type in normalized_group
        )
        authority = AuthorityEquivalenceAssessment(
            authority_role=normalized_role,
            instruction_trusted=instruction_trusted,
            candidate_requirement_contract_available=False,
            reasons=("authority_requirement_contract_unavailable",),
        )
        capability = self._evaluate_capability(
            selected,
            available_capabilities,
        )
        constraint = self._evaluate_constraint(selected)
        safety = SafetyEquivalenceAssessment(
            candidate_policy_contract_available=False,
            reasons=("safety_policy_contract_unavailable",),
        )
        statuses = (
            authority.status,
            capability.status,
            constraint.status,
            safety.status,
        )
        if ExecutionBoundaryEquivalenceStatus.REJECTED in statuses:
            status = ExecutionBoundaryEquivalenceStatus.REJECTED
            reason = "execution_boundary_equivalence_rejected"
        elif all(
            item is ExecutionBoundaryEquivalenceStatus.CONFIRMED
            for item in statuses
        ):
            status = ExecutionBoundaryEquivalenceStatus.CONFIRMED
            reason = "execution_boundary_equivalence_confirmed"
        else:
            status = ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
            reason = "execution_boundary_equivalence_unconfirmed"
        return ActivityCandidateExecutionBoundaryEquivalenceAssessment(
            candidate_group=normalized_group,
            status=status,
            authority=authority,
            capability=capability,
            constraint=constraint,
            safety=safety,
            reasons=(reason,),
        )

    @staticmethod
    def _evaluate_capability(
        definitions: Sequence[ActivityDefinition],
        available_capabilities: frozenset[str],
    ) -> CapabilityEquivalenceAssessment:
        requirements = tuple(
            (definition.activity_type, definition.required_capability)
            for definition in definitions
        )
        availability = tuple(
            (
                definition.activity_type,
                definition.required_capability is None
                or definition.required_capability in available_capabilities,
            )
            for definition in definitions
        )
        unique_requirements = {
            definition.required_capability for definition in definitions
        }
        if len(unique_requirements) == 1:
            return CapabilityEquivalenceAssessment(
                status=ExecutionBoundaryEquivalenceStatus.CONFIRMED,
                requirements=requirements,
                availability=availability,
                reasons=("capability_requirement_equivalent",),
            )
        return CapabilityEquivalenceAssessment(
            status=ExecutionBoundaryEquivalenceStatus.REJECTED,
            requirements=requirements,
            availability=availability,
            reasons=("capability_requirement_differs",),
        )

    @classmethod
    def _evaluate_constraint(
        cls,
        definitions: Sequence[ActivityDefinition],
    ) -> ConstraintEquivalenceAssessment:
        versions = tuple(
            (
                definition.activity_type,
                definition.constraints_schema_version,
            )
            for definition in definitions
        )
        fingerprints: list[tuple[str, str]] = []
        for definition in definitions:
            fingerprint = cls._schema_fingerprint(
                definition.constraints_schema_version,
                definition.constraints_schema,
            )
            if fingerprint is None:
                return ConstraintEquivalenceAssessment(
                    schema_versions=versions,
                    schema_fingerprints=tuple(fingerprints),
                    reasons=("constraint_schema_not_canonicalizable",),
                )
            fingerprints.append((definition.activity_type, fingerprint))
        signatures = {
            (
                definition.constraints_schema_version,
                fingerprint,
            )
            for definition, (_, fingerprint) in zip(definitions, fingerprints)
        }
        if len(signatures) == 1:
            return ConstraintEquivalenceAssessment(
                status=ExecutionBoundaryEquivalenceStatus.CONFIRMED,
                schema_versions=versions,
                schema_fingerprints=tuple(fingerprints),
                reasons=("constraint_schema_equivalent",),
            )
        return ConstraintEquivalenceAssessment(
            status=ExecutionBoundaryEquivalenceStatus.REJECTED,
            schema_versions=versions,
            schema_fingerprints=tuple(fingerprints),
            reasons=("constraint_schema_differs",),
        )

    @staticmethod
    def _schema_fingerprint(
        schema_version: str,
        schema: Mapping[str, object],
    ) -> str | None:
        try:
            canonical = json.dumps(
                {
                    "schema_version": schema_version,
                    "schema": schema,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            return None
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _unconfirmed(
        candidate_group: tuple[str, ...],
        *,
        authority_role: str,
        instruction_trusted: bool,
        reason: str,
    ) -> ActivityCandidateExecutionBoundaryEquivalenceAssessment:
        return ActivityCandidateExecutionBoundaryEquivalenceAssessment(
            candidate_group=candidate_group,
            authority=AuthorityEquivalenceAssessment(
                authority_role=authority_role,
                instruction_trusted=instruction_trusted,
                reasons=(reason,),
            ),
            capability=CapabilityEquivalenceAssessment(reasons=(reason,)),
            constraint=ConstraintEquivalenceAssessment(reasons=(reason,)),
            safety=SafetyEquivalenceAssessment(reasons=(reason,)),
            reasons=(reason,),
        )
