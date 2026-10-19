"""統合本体設定の参照、境界外参照、欠落を検証する。"""

from pathlib import Path

import pytest

from app.config.core import ConfigurationReference
from app.config.core_contracts import CoreConfigurationError, CoreFailureCode
from app.config.core_resources import match_core_reference, read_core_resource


def test_core_resource_reads_file_under_config_root(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "core.yaml").write_bytes(b"schema: yura.core-config.v1")
    assert read_core_resource(tmp_path, "config/core.yaml") == b"schema: yura.core-config.v1"


@pytest.mark.parametrize(
    ("reference", "failure"),
    (
        ("config/absent.yaml", CoreFailureCode.MISSING_SYSTEM_CONFIG),
        ("../secret.yaml", CoreFailureCode.INVALID_SYSTEM_CONFIG),
        ("config/../secret.yaml", CoreFailureCode.INVALID_SYSTEM_CONFIG),
    ),
)
def test_core_resource_rejects_missing_and_invalid_references(
    tmp_path: Path, reference: str, failure: CoreFailureCode
) -> None:
    with pytest.raises(CoreConfigurationError) as captured:
        read_core_resource(tmp_path, reference)
    assert captured.value.code is failure


def test_core_resource_rejects_symlink_outside_config_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "private.yaml"
    secret.write_bytes(b"do-not-expose")
    (root / "linked.yaml").symlink_to(secret)
    with pytest.raises(CoreConfigurationError) as captured:
        read_core_resource(root, "linked.yaml")
    assert captured.value.code is CoreFailureCode.INVALID_SYSTEM_CONFIG


def test_core_reference_must_match_identity_and_revision() -> None:
    reference = ConfigurationReference("config/appraisal.yaml", "yura.appraisal", 1)
    match_core_reference(reference, "yura.appraisal", 1)
    for config_id, config_revision in (("other", 1), ("yura.appraisal", 2)):
        with pytest.raises(CoreConfigurationError) as captured:
            match_core_reference(reference, config_id, config_revision)
        assert captured.value.code is CoreFailureCode.INVALID_SYSTEM_CONFIG
