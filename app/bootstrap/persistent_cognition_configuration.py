"""復元済みGoalの世代に合わせて本番認知のOwnerを組み立てる。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.bootstrap.appraisal_assembly import build_appraisal_configuration
from app.bootstrap.cognition_configuration import CoreCognitionConfiguration
from app.bootstrap.executive_assembly import create_executive_configuration
from app.config.appraisal import load_appraisal_config
from app.config.core import CoreConfig
from app.config.core_contracts import CoreConfigurationError, CoreFailureCode, resource
from app.config.executive import load_executive_config
from app.domain.activity_execution import ActivityExecutionAuthority
from app.domain.attention import AttentionSchedulingPolicy, AttentionTurnStore
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts.preconditions import PreconditionSourceRouter
from app.domain.plugin_registry import PluginRegistryAuthority
from app.usecases.goal_persistence import CoreGoalPersistenceBinding
from app.usecases.input_reference_context import CoreInputReferenceContextBinding


def _read_config(reference: str) -> bytes:
    """登録済みの正規構成rootからのみ設定を読み取る。"""
    resource(reference)
    root = Path(__file__).resolve().parents[2]
    location = (root / reference).resolve()
    if not location.is_relative_to(root):
        raise CoreConfigurationError(CoreFailureCode.INVALID_SYSTEM_CONFIG)
    try:
        return location.read_bytes()
    except OSError:
        raise CoreConfigurationError(CoreFailureCode.MISSING_SYSTEM_CONFIG) from None


def create_persistent_cognition_configuration(
    config: CoreConfig,
    goals: CoreGoalPersistenceBinding,
    runtime_epoch: str,
) -> CoreCognitionConfiguration:
    """Goal復元の完了後、実際の方針とOwnerを使って認知構成を生成する。"""
    if not isinstance(config, CoreConfig) or not isinstance(
        goals, CoreGoalPersistenceBinding
    ):
        raise ValueError("復元済みGoalと本番Core構成の明示登録が必要です")

    appraisal_config = load_appraisal_config(_read_config(config.appraisal_config.resource_ref))
    if (appraisal_config.config_id, appraisal_config.config_revision) != (
        config.appraisal_config.config_id, config.appraisal_config.config_revision
    ):
        raise CoreConfigurationError(CoreFailureCode.INVALID_SYSTEM_CONFIG)
    executive_config = load_executive_config(_read_config(config.executive_config.resource_ref))
    if (executive_config.config_id, executive_config.config_revision) != (
        config.executive_config.config_id, config.executive_config.config_revision
    ):
        raise CoreConfigurationError(CoreFailureCode.INVALID_SYSTEM_CONFIG)
    attention_policy = AttentionSchedulingPolicy.production()
    if (attention_policy.policy_id, attention_policy.policy_revision) != (
        config.attention_policy.policy_id, config.attention_policy.policy_revision
    ):
        raise CoreConfigurationError(CoreFailureCode.INVALID_SYSTEM_CONFIG)

    reference = CoreInputReferenceContextBinding(
        goals, ActivityExecutionAuthority(), config.input_meaning_policy, BOUNDS
    )
    appraisal = build_appraisal_configuration(
        appraisal_config,
        fresh_start=True,
        source_context_revision=reference.snapshot().context.source_context_revision,
        initialized_at=datetime.now(timezone.utc),
        runtime_epoch=runtime_epoch,
    )
    executive = create_executive_configuration(
        executive_config, bounds=BOUNDS, activity_bindings={}
    )
    try:
        return CoreCognitionConfiguration(
            appraisal.appraisal_policy,
            executive.executive_policy,
            appraisal.reducer,
            AttentionTurnStore(attention_policy),
            executive.requirements_owner,
            PluginRegistryAuthority(),
            PreconditionSourceRouter(()),
            (),
            (),
            decay_policy=appraisal.decay_policy,
        )
    except BaseException:
        executive.close()
        raise
