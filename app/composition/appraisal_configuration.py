"""復元対象のない新しい実行世代へAppraisal構成を結び付ける。"""

from dataclasses import dataclass
from datetime import datetime

from app.config.appraisal import AppraisalProductionConfig
from app.domain.appraisal.contracts import DecayPolicy, InternalStateSnapshot
from app.domain.appraisal.deep import DeepAppraisalPolicy
from app.domain.appraisal.reducer import InternalStateReducer
from app.domain.contracts.common import require_aware, require_identifier, require_revision


@dataclass(frozen=True, slots=True)
class AppraisalInitializationProvenance:
    config_id: str
    config_revision: int
    schema_id: str
    execution_policy_id: str
    execution_policy_revision: int
    decay_policy_id: str
    decay_policy_revision: int
    initialization_mode: str
    initial_state_revision: int
    source_context_revision: int
    initialized_at: datetime
    runtime_epoch: str
    source_config_ref: str


@dataclass(frozen=True, slots=True)
class AppraisalProductionBinding:
    reducer: InternalStateReducer
    appraisal_policy: DeepAppraisalPolicy
    decay_policy: DecayPolicy
    provenance: AppraisalInitializationProvenance


def build_appraisal_configuration(
    config: AppraisalProductionConfig,
    *,
    fresh_start: bool,
    source_context_revision: int,
    initialized_at: datetime,
    runtime_epoch: str,
) -> AppraisalProductionBinding:
    """呼出側が明示したfresh-startだけを生成し、resumeを代作しない。"""
    if not isinstance(config, AppraisalProductionConfig) or fresh_start is not True:
        raise ValueError("検証済みAppraisal構成と明示的なfresh-start指定が必要です")
    require_revision(source_context_revision, "source_context_revision")
    require_aware(initialized_at, "initialized_at")
    require_identifier(runtime_epoch, "runtime_epoch")
    execution = config.appraisal_policy.execution
    provenance = AppraisalInitializationProvenance(
        config.config_id,
        config.config_revision,
        config.schema_id,
        execution.policy_id,
        execution.policy_revision,
        config.decay_policy.policy_id,
        config.decay_policy.policy_revision,
        config.initialization_mode,
        config.initial_state_revision,
        source_context_revision,
        initialized_at,
        runtime_epoch,
        "resources/config/v2/appraisal.yaml",
    )
    return AppraisalProductionBinding(
        InternalStateReducer(
            InternalStateSnapshot(
                config.initial_state_revision,
                source_context_revision,
                (),
                initialized_at,
            )
        ),
        config.appraisal_policy,
        config.decay_policy,
        provenance,
    )
