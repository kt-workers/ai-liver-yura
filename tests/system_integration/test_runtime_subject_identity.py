"""同じproductionロードから主体identityを公開し、表記やpathを推測に使わない。"""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from app import application as bootstrap
from app.bootstrap import runtime_assembly
from app.adapters.character.yaml_loader import load_character_definition_yaml
from app.adapters.llm.production import UnavailableLLMRolePort
from app.domain.character.projector import project_character_definition
from tests.helpers.full_core import full_cognition

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("alternate", [False, True])
@pytest.mark.parametrize("rename", [False, True])
def test_production_identity_single_load(tmp_path: Path, alternate: bool, rename: bool) -> None:
    document = yaml.safe_load((ROOT / "config/character/yura.yaml").read_text())
    if alternate:
        document["character_id"] = "alternate-character"
        document["definition_revision"] += 1
    if rename:
        for group in ["identity", "language", "self_model"]:
            for facet in document.get(group, []):
                if (
                    facet.get("id") in ["display_name", "name_reading", "first_person"]
                    or group == "self_model"
                ):
                    if isinstance(facet.get("value"), str):
                        facet["value"] = "別の表記"
    config = yaml.safe_load((ROOT / "config/core.yaml").read_text())
    config["character_definition"]["character_id"] = document["character_id"]
    config["character_definition"]["definition_revision"] = document["definition_revision"]
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    with (
        patch.object(
            runtime_assembly, "create_openai_port_from_environment", side_effect=UnavailableLLMRolePort
        ),
        patch.object(
            runtime_assembly,
            "load_character_definition_yaml",
            side_effect=lambda _source: load_character_definition_yaml(
                yaml.safe_dump(document, allow_unicode=True).encode("utf-8")
            ),
        ) as load,
    ):
        app = bootstrap.build_core_runtime(config_path, cognition=full_cognition())
    assert load.call_count == 1
    identity = app.runtime_subject_identity
    loaded = app.character_definition
    assert (
        identity.self_subject_ref
        == identity.character_id
        == loaded.character_id
        == document["character_id"]
    )
    assert identity.character_schema_version == loaded.schema_version == document["schema_version"]
    assert (
        identity.character_definition_revision
        == loaded.definition_revision
        == document["definition_revision"]
    )
    assert project_character_definition(loaded).language.character_id == identity.character_id
    config_path.write_text("不正な置換")
    assert app.runtime_subject_identity is identity


@pytest.mark.parametrize("missing", [True, False])
def test_missing_invalid_character_has_no_identity_fallback(tmp_path: Path, missing: bool) -> None:
    path = tmp_path / "character.yaml"
    if not missing:
        path.write_text("character_id: yura")
    config = yaml.safe_load((ROOT / "config/core.yaml").read_text())
    config["character_definition.resource_ref"] = str(path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    with patch.object(bootstrap, "create_openai_port_from_environment") as provider:
        with pytest.raises((FileNotFoundError, ValueError)):
            bootstrap.build_core_runtime(config_path, cognition=full_cognition())
    provider.assert_not_called()
