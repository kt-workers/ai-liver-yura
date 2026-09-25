"""本番構成を既存Executive Ownerへ結び付け、世代の由来を保持する。"""

from collections.abc import Mapping
from dataclasses import dataclass

from app.config.executive import (
    CONFIG_SOURCE,
    ExecutiveConfigurationError,
    ExecutiveConfigurationFailureCode,
    ExecutiveProductionConfig,
)
from app.domain.activity_binding import ActivityBindingAuthority
from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.executive import (
    DirectActivityRequirementsOwner,
    ExecutiveRequirementsOwner,
    RequirementsGeneration,
)
from app.domain.executive.deliberator import ExecutivePolicy


@dataclass(frozen=True, slots=True)
class ExecutiveConfigurationProvenance:
    source_config_ref: str
    schema_id: str
    config_id: str
    config_revision: int
    execution_policy_id: str
    execution_policy_revision: int
    requirements_policy_id: str
    requirements_policy_revision: int
    rule_revisions: tuple[tuple[str, int], ...]
    direct_record_revisions: tuple[tuple[str, int], ...]
    bounds_policy_id: str
    bounds_policy_revision: int
    initial_generation_serial: int

    def to_dict(self) -> dict[str, object]:
        """初期構築時の安全な由来だけを公開する。"""
        from dataclasses import asdict

        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExecutiveProductionBinding:
    config: ExecutiveProductionConfig
    executive_policy: ExecutivePolicy
    requirements_owner: ExecutiveRequirementsOwner
    direct_owners: tuple[DirectActivityRequirementsOwner, ...]
    initial_generation: RequirementsGeneration
    provenance: ExecutiveConfigurationProvenance

    def close(self) -> None:
        """このfactoryで構築したOwnerだけを終了する。"""
        self.requirements_owner.finalization_participant.retire()
        for owner in self.direct_owners:
            owner.close()


def create_executive_configuration(
    config: ExecutiveProductionConfig,
    *,
    bounds: BrainOperationalBoundsPolicy,
    activity_bindings: Mapping[str, ActivityBindingAuthority],
) -> ExecutiveProductionBinding:
    """注入Ownerを再生成せず、失敗時には半構築物を返さない。"""
    if not isinstance(config, ExecutiveProductionConfig) or not isinstance(
        bounds, BrainOperationalBoundsPolicy
    ):
        raise ExecutiveConfigurationError(ExecutiveConfigurationFailureCode.INVALID_CONFIG)
    direct_owners: list[DirectActivityRequirementsOwner] = []
    requirements_owner: ExecutiveRequirementsOwner | None = None
    try:
        bindings = dict(activity_bindings)
        if set(bindings) != {record.binding_ref for record in config.direct_records}:
            raise ExecutiveConfigurationError(ExecutiveConfigurationFailureCode.BINDING_MISMATCH)
        for record in config.direct_records:
            binding = bindings[record.binding_ref]
            if (
                not isinstance(binding, ActivityBindingAuthority)
                or binding.binding_id != record.binding_ref
            ):
                raise ExecutiveConfigurationError(
                    ExecutiveConfigurationFailureCode.BINDING_MISMATCH
                )
            publication = binding.capture()
            value = publication.value
            if (
                record.binding_ref,
                record.binding_revision,
                record.activity_type,
                record.target_ref,
            ) != (value.binding_id, value.revision, value.activity_type, value.target_ref):
                raise ExecutiveConfigurationError(
                    ExecutiveConfigurationFailureCode.BINDING_MISMATCH
                )
        for record in config.direct_records:
            owner = DirectActivityRequirementsOwner(
                record.owner_id, bindings[record.binding_ref], bounds
            )
            direct_owners.append(owner)
            owner.publish(record)
        requirements_owner = ExecutiveRequirementsOwner(
            bounds,
            direct_routes={
                config.direct_route_id: {o.binding.binding_id: o for o in direct_owners}
            },
        )
        generation = requirements_owner.publish(config.requirements)
        policy = ExecutivePolicy(config.execution, bounds)
        provenance = ExecutiveConfigurationProvenance(
            CONFIG_SOURCE,
            config.schema_id,
            config.config_id,
            config.config_revision,
            config.execution.policy_id,
            config.execution.policy_revision,
            config.requirements.policy_id,
            config.requirements.revision,
            tuple((r.rule_id, r.revision) for r in config.requirements.rules),
            tuple((r.record_id, r.revision) for r in config.direct_records),
            bounds.policy_id,
            bounds.policy_revision,
            generation.serial,
        )
        return ExecutiveProductionBinding(
            config, policy, requirements_owner, tuple(direct_owners), generation, provenance
        )
    except Exception as error:
        if requirements_owner is not None:
            requirements_owner.finalization_participant.retire()
        for owner in direct_owners:
            owner.close()
        if isinstance(error, ExecutiveConfigurationError):
            raise
        raise ExecutiveConfigurationError(
            ExecutiveConfigurationFailureCode.INITIALIZATION_FAILED
        ) from None
