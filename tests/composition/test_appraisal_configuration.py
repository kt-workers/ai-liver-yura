from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from typing import Any, cast

import pytest

from app.composition.appraisal_configuration import build_appraisal_configuration
from app.config.appraisal import load_appraisal_config
from tests.config.test_appraisal import SOURCE

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def test_fresh_binding_preserves_owner_and_provenance() -> None:
    config = load_appraisal_config(SOURCE)
    binding = build_appraisal_configuration(
        config,
        fresh_start=True,
        source_context_revision=42,
        initialized_at=NOW,
        runtime_epoch="runtime:42",
    )
    snapshot = binding.reducer.snapshot()
    assert (
        snapshot.revision,
        snapshot.source_context_revision,
        snapshot.facets,
        snapshot.updated_at,
    ) == (0, 42, (), NOW)
    assert binding.appraisal_policy is config.appraisal_policy
    assert binding.decay_policy is config.decay_policy
    provenance = binding.provenance
    assert (provenance.config_id, provenance.config_revision, provenance.schema_id) == (
        config.config_id,
        1,
        config.schema_id,
    )
    assert (
        provenance.execution_policy_id,
        provenance.execution_policy_revision,
        provenance.decay_policy_id,
        provenance.decay_policy_revision,
    ) == (
        "yura.appraisal.execution",
        1,
        "yura.appraisal.decay",
        1,
    )
    assert (
        provenance.initialization_mode,
        provenance.initial_state_revision,
        provenance.source_context_revision,
        provenance.initialized_at,
        provenance.runtime_epoch,
        provenance.source_config_ref,
    ) == (
        "fresh_empty",
        0,
        42,
        NOW,
        "runtime:42",
        "resources/config/v2/appraisal.yaml",
    )
    with pytest.raises(FrozenInstanceError):
        cast(Any, provenance).runtime_epoch = "changed"
    second = build_appraisal_configuration(
        config,
        fresh_start=True,
        source_context_revision=43,
        initialized_at=NOW,
        runtime_epoch="runtime:43",
    )
    assert second.reducer is not binding.reducer
    assert binding.reducer.snapshot() is snapshot


@pytest.mark.parametrize(
    "name,value",
    [
        ("fresh_start", False),
        ("fresh_start", 1),
        ("source_context_revision", True),
        ("source_context_revision", -1),
        ("initialized_at", datetime(2026, 9, 24)),
        ("initialized_at", None),
        ("runtime_epoch", ""),
        ("runtime_epoch", None),
    ],
)
def test_invalid_provenance(name: str, value: object) -> None:
    arguments: dict[str, Any] = dict(
        fresh_start=True, source_context_revision=42, initialized_at=NOW, runtime_epoch="runtime:42"
    )
    arguments[name] = value
    with pytest.raises((ValueError, TypeError)):
        build_appraisal_configuration(load_appraisal_config(SOURCE), **arguments)


@pytest.mark.parametrize(
    "name", ["fresh_start", "source_context_revision", "initialized_at", "runtime_epoch"]
)
def test_all_inputs_required(name: str) -> None:
    arguments: dict[str, Any] = dict(
        fresh_start=True, source_context_revision=42, initialized_at=NOW, runtime_epoch="runtime:42"
    )
    del arguments[name]
    with pytest.raises(TypeError):
        build_appraisal_configuration(load_appraisal_config(SOURCE), **arguments)
