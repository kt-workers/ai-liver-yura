"""S2正本の明示参照と不正なYAMLの拒否を検証する。"""

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.config.cognition_s2 import load_s2_config
from app.config.s2_contracts import S2ConfigurationError

SOURCE = Path("resources/config/v2/cognition_s2.yaml").read_text()


def test_canonical_references_are_explicit_and_frozen() -> None:
    config = load_s2_config(SOURCE)
    assert config.config_id == "yura.cognition-s2.production"
    assert config.config_revision == config.composition_revision == 1
    for name in ("minimum", "appraisal", "executive"):
        ref = getattr(config, name + "_config")
        file = "minimum_brain" if name == "minimum" else name
        assert ref.resource_ref == f"resources/config/v2/{file}.yaml"
        assert ref.config_revision == 1
    assert config.attention_policy.policy_id == "attention-scheduling-production"
    assert config.character_definition.character_id == "yura"
    with pytest.raises(FrozenInstanceError):
        config.config_id = "changed"  # type: ignore[misc]
    with pytest.raises(S2ConfigurationError):
        replace(config, config_revision=True)


@pytest.mark.parametrize("field", list(yaml.safe_load(SOURCE)))
@pytest.mark.parametrize("operation", ["missing", "unknown"])
def test_closed_shape(field: str, operation: str) -> None:
    data = yaml.safe_load(SOURCE)
    if operation == "missing":
        del data[field]
    else:
        data[field + "_unknown"] = data[field]
    with pytest.raises(S2ConfigurationError):
        load_s2_config(yaml.safe_dump(data))


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "1", None])
def test_revision_rejects_invalid_values(value: Any) -> None:
    data = yaml.safe_load(SOURCE)
    data["config_revision"] = value
    with pytest.raises(S2ConfigurationError):
        load_s2_config(yaml.safe_dump(data))


@pytest.mark.parametrize(
    "value",
    [
        "/private/config",
        "../config",
        "a/../b",
        "https://host/x",
        "file:///path",
        "a//b",
        "C:\\secret",
        "",
        "a/./b",
    ],
)
def test_unsafe_resource_reference(value: str) -> None:
    data = yaml.safe_load(SOURCE)
    data["appraisal_config"]["resource_ref"] = value
    with pytest.raises(S2ConfigurationError) as caught:
        load_s2_config(yaml.safe_dump(data))
    assert value not in str(caught.value) or not value


@pytest.mark.parametrize(
    "source",
    [
        SOURCE + "\nconfig_revision: 1",
        "a: &a [*a]",
        "!!python/object:danger {}",
        "[",
        "1: a",
        SOURCE.replace("config_revision: 1", "config_revision: .nan", 1),
    ],
)
def test_malformed_duplicate_cycle_and_tag_are_safe(source: str) -> None:
    with pytest.raises(S2ConfigurationError) as caught:
        load_s2_config(source)
    assert str(caught.value) == "S2構成を使用できません: INVALID_SYSTEM_CONFIG"
