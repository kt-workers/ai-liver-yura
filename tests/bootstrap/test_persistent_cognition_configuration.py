"""保存Goalを復元した後の本番認知構成を検証する。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.bootstrap.cognition_configuration import CoreCognitionConfiguration
from app.bootstrap.persistent_cognition_configuration import (
    create_persistent_cognition_configuration,
)
from app.config.core import load_core_config
from app.config.core_contracts import CoreConfigurationError
from app.domain.activity_execution import ActivityExecutionAuthority
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.goals import GoalCommitmentStore
from app.usecases.goal_persistence import CoreGoalPersistenceBinding
from app.usecases.input_reference_context import CoreInputReferenceContextBinding

ROOT = Path(__file__).resolve().parents[2]


class _UnusedPersistence:
    async def restore_goals(self) -> Any:
        raise AssertionError("この試験は保存接続を呼び出さない")

    def persist_goals(
        self, snapshot: Any, *, request_id: str, runtime_epoch: str
    ) -> Any:
        raise AssertionError("この試験は保存接続を呼び出さない")


def _restored_goals() -> CoreGoalPersistenceBinding:
    return CoreGoalPersistenceBinding(
        GoalCommitmentStore(), _UnusedPersistence(), runtime_epoch="test-epoch"
    )


def test_persistent_cognition_uses_restored_goal_reference_generation() -> None:
    config = load_core_config((ROOT / "config/core.yaml").read_bytes())
    goals = _restored_goals()
    cognition = create_persistent_cognition_configuration(config, goals, "test-epoch")
    expected = CoreInputReferenceContextBinding(
        goals,
        ActivityExecutionAuthority(),
        config.input_meaning_policy,
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    ).snapshot().context.source_context_revision
    assert isinstance(cognition, CoreCognitionConfiguration)
    assert cognition.state.snapshot().source_context_revision == expected
    assert cognition.decay_policy is not None
    assert cognition.requirements.current_generation() is not None


def test_persistent_cognition_rejects_appraisal_configuration_revision_mismatch() -> None:
    config = load_core_config((ROOT / "config/core.yaml").read_bytes())
    altered = replace(
        config,
        appraisal_config=replace(
            config.appraisal_config,
            config_revision=config.appraisal_config.config_revision + 1,
        ),
    )
    with pytest.raises(CoreConfigurationError):
        create_persistent_cognition_configuration(altered, _restored_goals(), "test-epoch")
