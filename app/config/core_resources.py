"""本体設定のファイル参照を検証し、設定rootから安全に読み出す。"""

from __future__ import annotations

from pathlib import Path

from app.config.core import ConfigurationReference
from app.config.core_contracts import CoreConfigurationError, CoreFailureCode, resource


def read_core_resource(root: Path, ref: str) -> bytes:
    """設定rootの外部参照を拒否し、構成失敗を公開コードに正規化する。"""
    resource(ref)
    path = (root / ref).resolve()
    if not path.is_relative_to(root.resolve()):
        raise CoreConfigurationError(CoreFailureCode.INVALID_SYSTEM_CONFIG)
    try:
        return path.read_bytes()
    except OSError:
        raise CoreConfigurationError(CoreFailureCode.MISSING_SYSTEM_CONFIG) from None


def match_core_reference(
    ref: ConfigurationReference, config_id: str, config_revision: int
) -> None:
    """参照に固定された構成IDと改訂番号の一致を検証する。"""
    if (ref.config_id, ref.config_revision) != (config_id, config_revision):
        raise CoreConfigurationError(CoreFailureCode.INVALID_SYSTEM_CONFIG)
