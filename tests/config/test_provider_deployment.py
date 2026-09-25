"""Role集合と未構成の意味を補完せずに読み込む。"""

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config.provider_deployment import ROLE_IDS, load_provider_deployment
from app.config.s2_contracts import S2ConfigurationError

SOURCE = Path("resources/config/v2/provider_deployment_s2.yaml").read_text()
REF = {"source_id": "deployment", "identity": "role-mapping", "revision": 1}


def test_unconfigured_manifest() -> None:
    config = load_provider_deployment(SOURCE)
    assert {b.role_id for b in config.role_bindings} == ROLE_IDS
    assert all(
        b.availability_mode == "unconfigured"
        and b.mapping_ref is None
        and b.role_config_ref is None
        for b in config.role_bindings
    )
    with pytest.raises(FrozenInstanceError):
        config.role_bindings = ()  # type: ignore[misc]


def configured_data() -> dict[str, Any]:
    data = yaml.safe_load(SOURCE)
    for row in data["role_bindings"]:
        row.update(availability_mode="configured", mapping_ref=REF, role_config_ref=REF)
    return dict(data)


def test_configured_references_are_preserved() -> None:
    config = load_provider_deployment(yaml.safe_dump(configured_data()))
    assert config.role_bindings[0].mapping_ref is not None
    assert config.role_bindings[0].mapping_ref.identity == "role-mapping"


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "duplicate",
        "unknown",
        "mixed",
        "extra",
        "refs",
        "configured-missing",
        "bool",
        "path",
        "secret-field",
    ],
)
def test_manifest_rejects_inconsistent_or_unsafe_values(change: str) -> None:
    data = yaml.safe_load(SOURCE)
    row = data["role_bindings"][0]
    if change == "missing":
        data["role_bindings"].pop()
    elif change == "duplicate":
        data["role_bindings"].append(row.copy())
    elif change == "unknown":
        row["role_id"] = "unknown"
    elif change == "mixed":
        row.update(availability_mode="configured", mapping_ref=REF, role_config_ref=REF)
    elif change == "extra":
        row["unknown"] = 1
    elif change == "refs":
        row["mapping_ref"] = REF
    elif change == "configured-missing":
        row["availability_mode"] = "configured"
    elif change == "bool":
        data["deployment_revision"] = True
    elif change == "path":
        data["deployment_id"] = "/private/source"
    elif change == "secret-field":
        data["credential"] = "forbidden-test-value"
    with pytest.raises(S2ConfigurationError):
        load_provider_deployment(yaml.safe_dump(data))
