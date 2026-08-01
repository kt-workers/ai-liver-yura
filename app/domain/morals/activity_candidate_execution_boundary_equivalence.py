from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

from app.shared.contracts.activity import (
    ActivityAuthorityRequirement,
    ActivityDefinition,
    ActivitySafetyRequirement,
)


class ExecutionBoundaryEquivalenceStatus(str, Enum):
    """Activity候補間の実行境界同等性評価状態。"""

    UNCONFIRMED = "unconfirmed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AuthorityCandidateAssessment:
    """候補別Authority要件と現在入力に対する充足状態。"""

    activity_type: str
    policy_id: str | None = None
    allowed_roles: tuple[str, ...] = ()
    trusted_instruction_required: bool | None = None
    current_request_authorized: bool | None = None

    def as_context(self) -> dict[str, object]:
        return {
            "activity_type": self.activity_type,
            "policy_id": self.policy_id,
            "allowed_roles": list(self.allowed_roles),
            "trusted_instruction_required": self.trusted_instruction_required,
            "current_request_authorized": self.current_request_authorized,
        }


@dataclass(frozen=True, slots=True)
class AuthorityEquivalenceAssessment:
    """候補間Authority要件の同等性評価。"""

    status: ExecutionBoundaryEquivalenceStatus = (
        ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    )
    authority_role: str = "unknown"
    instruction_trusted: bool = False
    candidate_requirement_contract_available: bool = False
    candidates: tuple[AuthorityCandidateAssessment, ...] = ()
    reasons: tuple[str, ...] = ()

    def as_context(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "authority_role": self.authority_role,
            "instruction_trusted": self.instruction_trusted,
            "candidate_requirement_contract_available": (
                self.candidate_requirement_contract_available
            ),
            "candidates": [candidate.as_context() for candidate in self.candidates],
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
class SafetyCandidateAssessment:
    """候補別Safety要件の宣言内容。"""

    activity_type: str
    policy_id: str | None = None
    risk_class: str | None = None

    def as_context(self) -> dict[str, object]:
        return {
            "activity_type": self.activity_type,
            "policy_id": self.policy_id,
            "risk_class": self.risk_class,
        }


@dataclass(frozen=True, slots=True)
class SafetyEquivalenceAssessment:
    """候補間Safety policy要件の同等性評価。"""

    status: ExecutionBoundaryEquivalenceStatus = (
        ExecutionBoundaryEquivalenceStatus.UNCONFIRMED
    )
    candidate_policy_contract_available: bool = False
    candidates: tuple[SafetyCandidateAssessment, ...] = ()
    reasons: tuple[str, ...] = ()

    def as_context(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "candidate_policy_contract_available": (
                self.candidate_policy_contract_available
            ),
            "candidates": [candidate.as_context() for candidate in self.candidates],
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
        normalized_role = authority_role.strip().lower() or "unknown"
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
        authority = self._evaluate_authority(
            selected,
            authority_role=normalized_role,
            instruction_trusted=instruction_trusted,
        )
        capability = self._evaluate_capability(
            selected,
            available_capabilities,
        )
        constraint = self._evaluate_constraint(selected)
        safety = self._evaluate_safety(selected)
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
    def _evaluate_authority(
        definitions: Sequence[ActivityDefinition],
        *,
        authority_role: str,
        instruction_trusted: bool,
    ) -> AuthorityEquivalenceAssessment:
        candidate_assessments = tuple(
            ActivityCandidateExecutionBoundaryEquivalenceEvaluator._authority_candidate(
                definition,
                authority_role=authority_role,
                instruction_trusted=instruction_trusted,
            )
            for definition in definitions
        )
        requirements = tuple(
            definition.authority_requirement for definition in definitions
        )
        if any(requirement is None for requirement in requirements):
            return AuthorityEquivalenceAssessment(
                authority_role=authority_role,
                instruction_trusted=instruction_trusted,
                candidate_requirement_contract_available=False,
                candidates=candidate_assessments,
                reasons=("authority_requirement_contract_missing",),
            )

        typed_requirements = tuple(
            requirement
            for requirement in requirements
            if isinstance(requirement, ActivityAuthorityRequirement)
        )
        signatures = {
            (
                requirement.policy_id,
                requirement.allowed_roles,
                requirement.trusted_instruction_required,
            )
            for requirement in typed_requirements
        }
        if len(signatures) == 1:
            return AuthorityEquivalenceAssessment(
                status=ExecutionBoundaryEquivalenceStatus.CONFIRMED,
                authority_role=authority_role,
                instruction_trusted=instruction_trusted,
                candidate_requirement_contract_available=True,
                candidates=candidate_assessments,
                reasons=("authority_requirement_equivalent",),
            )
        return AuthorityEquivalenceAssessment(
            status=ExecutionBoundaryEquivalenceStatus.REJECTED,
            authority_role=authority_role,
            instruction_trusted=instruction_trusted,
            candidate_requirement_contract_available=True,
            candidates=candidate_assessments,
            reasons=("authority_requirement_differs",),
        )

    @staticmethod
    def _authority_candidate(
        definition: ActivityDefinition,
        *,
        authority_role: str,
        instruction_trusted: bool,
    ) -> AuthorityCandidateAssessment:
        requirement = definition.authority_requirement
        if requirement is None:
            return AuthorityCandidateAssessment(activity_type=definition.activity_type)
        return AuthorityCandidateAssessment(
            activity_type=definition.activity_type,
            policy_id=requirement.policy_id,
            allowed_roles=requirement.allowed_roles,
            trusted_instruction_required=requirement.trusted_instruction_required,
            current_request_authorized=requirement.permits(
                authority_role,
                instruction_trusted,
            ),
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
    def _evaluate_safety(
        definitions: Sequence[ActivityDefinition],
    ) -> SafetyEquivalenceAssessment:
        candidate_assessments = tuple(
            ActivityCandidateExecutionBoundaryEquivalenceEvaluator._safety_candidate(
                definition
            )
            for definition in definitions
        )
        requirements = tuple(
            definition.safety_requirement for definition in definitions
        )
        if any(requirement is None for requirement in requirements):
            return SafetyEquivalenceAssessment(
                candidate_policy_contract_available=False,
                candidates=candidate_assessments,
                reasons=("safety_requirement_contract_missing",),
            )
        if not all(
            isinstance(requirement, ActivitySafetyRequirement)
            for requirement in requirements
        ):
            return SafetyEquivalenceAssessment(
                candidate_policy_contract_available=False,
                candidates=candidate_assessments,
                reasons=("safety_requirement_contract_invalid",),
            )

        typed_requirements = tuple(
            requirement
            for requirement in requirements
            if isinstance(requirement, ActivitySafetyRequirement)
        )
        signatures = {
            (requirement.policy_id, requirement.risk_class)
            for requirement in typed_requirements
        }
        if len(signatures) == 1:
            return SafetyEquivalenceAssessment(
                status=ExecutionBoundaryEquivalenceStatus.CONFIRMED,
                candidate_policy_contract_available=True,
                candidates=candidate_assessments,
                reasons=("safety_requirement_equivalent",),
            )
        return SafetyEquivalenceAssessment(
            status=ExecutionBoundaryEquivalenceStatus.REJECTED,
            candidate_policy_contract_available=True,
            candidates=candidate_assessments,
            reasons=("safety_requirement_differs",),
        )

    @staticmethod
    def _safety_candidate(
        definition: ActivityDefinition,
    ) -> SafetyCandidateAssessment:
        requirement = definition.safety_requirement
        if not isinstance(requirement, ActivitySafetyRequirement):
            return SafetyCandidateAssessment(activity_type=definition.activity_type)
        return SafetyCandidateAssessment(
            activity_type=definition.activity_type,
            policy_id=requirement.policy_id,
            risk_class=requirement.risk_class.value,
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
