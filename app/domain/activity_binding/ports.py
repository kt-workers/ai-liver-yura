"""実値・schema・操作の正規Ownerが自身の同期境界で公開する契約。"""

from dataclasses import dataclass
from typing import Protocol

from app.domain.contracts import CapabilityDescriptor
from app.domain.contracts.common import require_identifier
from app.domain.contracts.finalization import (
    AuthorityFinalizationParticipant,
    AuthorityReadPublication,
)

from .contracts import ArgumentSourceFact, OperationInputContract


@dataclass(frozen=True, slots=True)
class ActivityOperation:
    descriptor: CapabilityDescriptor
    operation_ref: str
    input_schema_ref: str

    def __post_init__(self) -> None:
        require_identifier(self.operation_ref, "operation_ref")
        require_identifier(self.input_schema_ref, "input_schema_ref")
        if self.operation_ref not in self.descriptor.operations:
            raise ValueError("操作がCapabilityの宣言に存在しません")


class ActivityOperationPublicationPort(Protocol):
    @property
    def finalization_participant(self) -> AuthorityFinalizationParticipant: ...

    def operation_publication(
        self, capability_id: str, operation_ref: str
    ) -> AuthorityReadPublication[ActivityOperation]: ...


class ArgumentSourceOwnerPort(Protocol):
    @property
    def owner_id(self) -> str: ...

    @property
    def finalization_participant(self) -> AuthorityFinalizationParticipant: ...

    def capture(self) -> AuthorityReadPublication[tuple[ArgumentSourceFact, ...]]: ...


class InputSchemaOwnerPort(Protocol):
    @property
    def finalization_participant(self) -> AuthorityFinalizationParticipant: ...

    def capture(self) -> AuthorityReadPublication[OperationInputContract]: ...
