"""本体起動で借用する既存Ownerの型付き入力と初期構成。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from app.domain.activity_binding import ActivityBindingAuthority
from app.domain.appraisal import DeterministicAppraisalRule
from app.domain.contracts.preconditions import PreconditionSourceBinding, PreconditionSourceRouter
from app.domain.plugin_registry import PluginRegistryAuthority
from app.domain.speech_semantics.production import SpeechSemanticPolicyOwner
from app.usecases.memory_persistence import CoreMemoryPersistenceBinding

if TYPE_CHECKING:
    from app.usecases.speech_pipeline_deployment import SpeechDeploymentRegistry


@dataclass(frozen=True, slots=True)
class CoreSpeechOwners:
    """Speech有効時だけ起動rootへ明示注入する既存の本番Owner集合。"""

    semantic_owner: SpeechSemanticPolicyOwner
    memory: CoreMemoryPersistenceBinding
    registry: SpeechDeploymentRegistry


@dataclass(frozen=True, slots=True)
class CoreRuntimeOwners:
    """本体起動rootが生成又は借用する既存Runtime Ownerの入力。"""

    registry: PluginRegistryAuthority
    precondition_router: PreconditionSourceRouter
    precondition_bindings: tuple[PreconditionSourceBinding, ...]
    activity_bindings: Mapping[str, ActivityBindingAuthority]
    fast_rules: tuple[DeterministicAppraisalRule, ...]
    speech: CoreSpeechOwners | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.registry, PluginRegistryAuthority) or not isinstance(
            self.precondition_router, PreconditionSourceRouter
        ):
            raise ValueError("本体起動には既存Runtime Ownerの明示入力が必要です")
        object.__setattr__(self, "precondition_bindings", tuple(self.precondition_bindings))
        object.__setattr__(self, "fast_rules", tuple(self.fast_rules))
        object.__setattr__(
            self,
            "activity_bindings",
            MappingProxyType(dict(self.activity_bindings)),
        )
        if self.speech is not None and not isinstance(self.speech, CoreSpeechOwners):
            raise ValueError("Speech起動には既存Speech Ownerの明示入力が必要です")


def default_core_runtime_owners() -> CoreRuntimeOwners:
    """外部能力を補作せず、空の既存Owner集合を新runへ供給する。"""
    return CoreRuntimeOwners(
        registry=PluginRegistryAuthority(),
        precondition_router=PreconditionSourceRouter(()),
        precondition_bindings=(),
        activity_bindings={},
        fast_rules=(),
    )
