"""統合Coreのすべての認知Ownerを登録する試験専用構成。"""

from dataclasses import replace

from app.bootstrap.cognition_configuration import CoreCognitionConfiguration

from app.domain.appraisal import InternalStateReducer
from app.domain.attention import AttentionSchedulingPolicy, AttentionTurnStore
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts.preconditions import PreconditionSourceRouter
from app.domain.executive import ExecutiveIntentRequirementsPolicy, ExecutiveRequirementsOwner
from app.domain.plugin_registry import PluginRegistryAuthority
from tests.domain.appraisal.test_appraisal_paths import policy, state
from tests.domain.executive.test_executive import policy as executive_policy


def full_cognition() -> CoreCognitionConfiguration:
    """製品の必須Brain役割を省略しない試験用Ownerセット。"""
    requirements = ExecutiveRequirementsOwner(V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    requirements.publish(ExecutiveIntentRequirementsPolicy("test-wait", 1, ()))
    return CoreCognitionConfiguration(
        policy(),
        executive_policy(),
        InternalStateReducer(replace(state(), source_context_revision=0)),
        AttentionTurnStore(AttentionSchedulingPolicy.production()),
        requirements,
        PluginRegistryAuthority(),
        PreconditionSourceRouter(()),
        (),
        (),
    )
