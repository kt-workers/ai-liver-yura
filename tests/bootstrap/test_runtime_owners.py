"""起動Ownerの責務分離と公開互換性を確認する。"""

from types import MappingProxyType

import pytest

from app.application import (
    CoreRuntimeOwners as PublicRuntimeOwners,
    CoreSpeechOwners as PublicSpeechOwners,
    default_core_runtime_owners as public_default_owners,
)
from app.bootstrap.runtime_owners import (
    CoreRuntimeOwners,
    CoreSpeechOwners,
    default_core_runtime_owners,
)
from app.domain.plugin_registry import PluginRegistryAuthority


def test_bootstrap_owns_runtime_types_without_changing_public_identity() -> None:
    assert PublicRuntimeOwners is CoreRuntimeOwners
    assert PublicSpeechOwners is CoreSpeechOwners
    assert public_default_owners is default_core_runtime_owners


def test_default_runtime_owners_keep_explicit_empty_bindings() -> None:
    owners = default_core_runtime_owners()

    assert isinstance(owners.registry, PluginRegistryAuthority)
    assert owners.precondition_bindings == ()
    assert owners.fast_rules == ()
    assert isinstance(owners.activity_bindings, MappingProxyType)
    assert dict(owners.activity_bindings) == {}
    assert owners.speech is None


def test_runtime_owners_reject_missing_registry() -> None:
    existing = default_core_runtime_owners()

    with pytest.raises(ValueError, match="既存Runtime Owner"):
        CoreRuntimeOwners(
            registry=None,  # type: ignore[arg-type]
            precondition_router=existing.precondition_router,
            precondition_bindings=(),
            activity_bindings={},
            fast_rules=(),
        )
