"""Registryの操作宣言をprovider非依存境界へ投影する。別の状態は所有しない。"""

from collections.abc import Mapping

from app.domain.activity_binding.ports import ActivityOperation
from app.domain.contracts.finalization import (
    AuthorityFinalizationParticipant,
    AuthorityReadPublication,
)

from .authority import PluginRegistryAuthority


class PluginActivityOperationAdapter:
    def __init__(self, registry: PluginRegistryAuthority) -> None:
        self.registry = registry

    @property
    def finalization_participant(self) -> AuthorityFinalizationParticipant:
        return self.registry.finalization_participant

    def operation_publication(
        self, capability_id: str, operation_ref: str
    ) -> AuthorityReadPublication[ActivityOperation]:
        with self.finalization_participant:
            publication = self.registry.capability_publication()
            matches = [c for c in publication.value if c.capability_id == capability_id]
            if len(matches) != 1:
                raise ValueError("操作の正規Capabilityが一意に存在しません")
            descriptor = matches[0]
            attrs = descriptor.attributes
            operations = attrs.get("operations") if isinstance(attrs, Mapping) else None
            if not isinstance(operations, tuple):
                raise ValueError("操作宣言がありません")
            schemas = [
                op.get("input_schema_ref")
                for op in operations
                if isinstance(op, Mapping) and op.get("operation_id") == operation_ref
            ]
            if len(schemas) != 1 or not isinstance(schemas[0], str):
                raise ValueError("操作宣言のschemaが一意に存在しません")
            return AuthorityReadPublication(
                ActivityOperation(descriptor, operation_ref, schemas[0]), publication.tokens
            )
