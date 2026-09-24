"""正規bindingに対応する明示要件を所有し、意味参照とは分離して公開する。"""

from __future__ import annotations

from dataclasses import InitVar, dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from app.domain.activity_binding import (
    ActivityBindingAuthority,
    ActivityExecutionBindingPublication,
)
from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts import CapabilityRequirement
from app.domain.contracts.common import require_identifier, require_revision
from app.domain.contracts.finalization import (
    AuthorityFinalizationFence,
    AuthorityFinalizationParticipant,
    AuthorityFinalizationRequest,
    AuthorityGenerationToken,
    FinalizationError,
    FinalizationFailure,
    authority_read_set,
)

from .contracts import ExecutivePreconditionRequirement

if TYPE_CHECKING:
    from .requirements import RequirementSourcePublication

DIRECT_ACTIVITY_REQUIREMENTS_CONTRACT = "executive.direct-activity-requirements.v1"
_PROOF = object()


@dataclass(frozen=True, slots=True)
class DirectActivityRequirementRecord:
    owner_id: str
    contract_id: str
    record_id: str
    revision: int
    binding_ref: str
    binding_revision: int
    activity_type: str
    target_ref: str | None
    capabilities: tuple[CapabilityRequirement, ...]
    preconditions: tuple[ExecutivePreconditionRequirement, ...]

    def __post_init__(self) -> None:
        from .requirements import RequirementsFailureCode, _requirements_key, reject

        for name in ("owner_id", "contract_id", "record_id", "binding_ref", "activity_type"):
            require_identifier(getattr(self, name), name)
        require_revision(self.revision, "revision")
        require_revision(self.binding_revision, "binding_revision")
        if self.target_ref is not None:
            require_identifier(self.target_ref, "target_ref")
        if self.contract_id != DIRECT_ACTIVITY_REQUIREMENTS_CONTRACT:
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "preconditions", tuple(self.preconditions))
        _requirements_key(self.capabilities, self.preconditions)


@dataclass(frozen=True, slots=True)
class DirectActivityRequirementSourceSpec:
    route_id: str
    contract_id: str = DIRECT_ACTIVITY_REQUIREMENTS_CONTRACT
    reference_field: str = "binding_ref"

    def __post_init__(self) -> None:
        require_identifier(self.route_id, "route_id")
        if self.contract_id != DIRECT_ACTIVITY_REQUIREMENTS_CONTRACT or (
            self.reference_field != "binding_ref"
        ):
            raise ValueError("Direct要件の出典契約が一致しません")


@dataclass(frozen=True, slots=True)
class DirectActivityRequirementSource:
    record: DirectActivityRequirementRecord
    binding_publication: ActivityExecutionBindingPublication
    tokens: tuple[AuthorityGenerationToken, ...]
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        if _proof is not _PROOF:
            raise ValueError("Direct要件sourceは正規Ownerから取得してください")

    def to_dict(self) -> dict[str, object]:
        from .requirements import project

        return {
            "record": project(self.record),
            "binding_publication": self.binding_publication.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class _PublicationInput:
    record: DirectActivityRequirementRecord
    binding: ActivityExecutionBindingPublication


class DirectActivityRequirementsOwner:
    """1 bindingの明示要件とそのリビジョンだけを所有する。"""

    def __init__(
        self,
        owner_id: str,
        binding: ActivityBindingAuthority,
        bounds: BrainOperationalBoundsPolicy,
    ) -> None:
        require_identifier(owner_id, "owner_id")
        if not isinstance(binding, ActivityBindingAuthority):
            raise ValueError("正規binding Ownerが必要です")
        self.owner_id = owner_id
        self.binding = binding
        self._bounds = bounds.executive
        self._participant = AuthorityFinalizationParticipant(self, owner_id, 80)
        self._value: _PublicationInput | None = None
        self._operation = self._participant.register_operation(self, "publish", self._commit)

    @property
    def finalization_participant(self) -> AuthorityFinalizationParticipant:
        return self._participant

    def _publication(self, value: _PublicationInput) -> RequirementSourcePublication:
        import json

        from .requirements import (
            RequirementsFailureCode,
            RequirementSourcePublication,
            project,
            reject,
        )

        tokens = (self._participant.token(), *value.binding.tokens)
        source = DirectActivityRequirementSource(value.record, value.binding, tokens, _PROOF)
        result = RequirementSourcePublication(
            value.record.record_id, value.record.revision, source, tokens
        )
        if len(json.dumps(project(result), ensure_ascii=False, allow_nan=False).encode()) > (
            self._bounds.max_fact_payload_json_bytes
        ):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        return result

    def publish(self, record: DirectActivityRequirementRecord) -> RequirementSourcePublication:
        from .requirements import RequirementsFailureCode, reject

        with self._participant.mutation():
            target = self._participant.token()
        if not isinstance(record, DirectActivityRequirementRecord):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        binding = self.binding.capture()
        value = binding.value
        if (
            record.owner_id != self.owner_id
            or record.binding_ref != self.binding.binding_id
            or (
                record.binding_ref,
                record.binding_revision,
                record.activity_type,
                record.target_ref,
            )
            != (value.binding_id, value.revision, value.activity_type, value.target_ref)
            or sum(
                c.capability_type == value.activity_type and c.operation == value.operation_ref
                for c in record.capabilities
            )
            != 1
            or len(record.capabilities) + len(record.preconditions)
            > self._bounds.max_refs_per_intent
        ):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        result = AuthorityFinalizationFence().finalize(
            AuthorityFinalizationRequest(
                (target, *binding.tokens),
                self._participant,
                self._operation,
                _PublicationInput(record, binding),
            )
        )
        if result.failure is not None:
            raise FinalizationError(result.failure)
        assert result.value is not None
        return result.value

    def _commit(
        self, value: _PublicationInput, committed_at: datetime
    ) -> RequirementSourcePublication:
        from .requirements import _same_public_value

        if self._value is not None:
            old, new = self._value.record, value.record
            if (
                old.record_id != new.record_id
                or new.revision < old.revision
                or (new.revision == old.revision and not _same_public_value(old, new))
            ):
                raise FinalizationError(FinalizationFailure.TARGET_REJECTED)
        publication = self._publication(value)
        self._value = value
        return publication

    def capture(self) -> RequirementSourcePublication:
        from .requirements import RequirementsFailureCode, reject

        with self._participant:
            value = self._value
        if value is None:
            reject(RequirementsFailureCode.SOURCE_UNAVAILABLE)
        with authority_read_set(
            (self._participant, *(t._participant for t in value.binding.tokens))
        ):
            if value is not self._value:
                reject(RequirementsFailureCode.STALE_SOURCE)
            value.binding.require_current()
            return self._publication(value)

    def close(self) -> None:
        self._participant.retire()
