"""確定済みOwnerの情報だけを構成Snapshotへ射影する。"""

from __future__ import annotations

from datetime import datetime, timezone

from app.bootstrap.composition_contracts import (
    ComponentBindings,
    CoreRunIdentity,
    LLMConnectionBinding,
    SystemCompositionSnapshot,
)
from app.bootstrap.speech_production_configuration import SpeechComponentProvenance
from app.config.appraisal_assembly import AppraisalInitializationProvenance
from app.config.core import CoreConfig
from app.config.executive_assembly import ExecutiveConfigurationProvenance
from app.domain.attention import AttentionSchedulingPolicy


def _snapshot(
    config: CoreConfig,
    run: CoreRunIdentity,
    created_at: datetime,
    character_id: str,
    character_revision: int,
    core_config_id: str,
    core_config_revision: int,
    appraisal: AppraisalInitializationProvenance,
    executive: ExecutiveConfigurationProvenance,
    attention: AttentionSchedulingPolicy,
    llm_connections: tuple[LLMConnectionBinding, ...],
    speech: SpeechComponentProvenance | None = None,
) -> SystemCompositionSnapshot:
    return SystemCompositionSnapshot(
        config.composition_id,
        config.composition_revision,
        config.config_id,
        config.config_revision,
        config.activation_id,
        run.runtime_epoch,
        run.system_run_id,
        created_at.astimezone(timezone.utc),
        character_id,
        character_revision,
        (
            ComponentBindings(
                core_config_id,
                core_config_revision,
                appraisal,
                executive,
                attention.policy_id,
                attention.policy_revision,
                speech,
            ),
        ),
        llm_connections,
        (),
        executive.initial_generation_identity,
    )
