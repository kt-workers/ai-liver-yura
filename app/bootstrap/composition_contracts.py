"""起動結果に記録する不変の型付き契約（外部I/Oを持たない）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.bootstrap.appraisal_assembly import AppraisalInitializationProvenance
from app.bootstrap.executive_assembly import ExecutiveConfigurationProvenance
from app.bootstrap.speech_production_configuration import SpeechComponentProvenance
from app.config.core_contracts import identity


@dataclass(frozen=True, slots=True)
class CoreRunIdentity:
    runtime_epoch: str
    system_run_id: str

    def __post_init__(self) -> None:
        identity(self.runtime_epoch)
        identity(self.system_run_id)


@dataclass(frozen=True, slots=True)
class ComponentBindings:
    core_config_id: str
    core_config_revision: int
    appraisal: AppraisalInitializationProvenance
    executive: ExecutiveConfigurationProvenance
    attention_policy_id: str
    attention_policy_revision: int
    speech: SpeechComponentProvenance | None = None


@dataclass(frozen=True, slots=True)
class SubsystemBinding:
    subsystem_id: str
    revision: int


@dataclass(frozen=True, slots=True)
class LLMConnectionBinding:
    """本体が採用した接続IDだけを、Roleの実行内容なしに記録する。"""

    role_id: str
    connection_id: str


@dataclass(frozen=True, slots=True)
class SystemCompositionSnapshot:
    composition_id: str
    composition_revision: int
    config_id: str
    config_revision: int
    activation_id: str
    runtime_epoch: str
    system_run_id: str
    created_at: datetime
    character_id: str
    character_definition_revision: int
    component_bindings: tuple[ComponentBindings, ...]
    llm_connection_bindings: tuple[LLMConnectionBinding, ...]
    subsystem_bindings: tuple[SubsystemBinding, ...]
    requirements_generation: tuple[tuple[str, str | int], ...]
