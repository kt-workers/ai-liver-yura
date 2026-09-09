"""意味Ownerの明示入力だけを束縛し、実値と世代を同時に公開する。"""

from collections.abc import Mapping
from dataclasses import InitVar, dataclass
from typing import Generic, TypeVar

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts import CapabilityDescriptor
from app.domain.contracts.common import require_identifier
from app.domain.contracts.finalization import (
    AuthorityFinalizationParticipant,
    AuthorityGenerationToken,
    AuthorityReadPublication,
    authority_read_set,
)
from app.domain.plugin_registry.authority import PluginRegistryAuthority

from .contracts import (
    ActivityExecutionBinding,
    ArgumentSourceFact,
    ArgumentSourceRelation,
    OperationInputContract,
    canonical,
    require_current,
)

T = TypeVar("T", ArgumentSourceFact, OperationInputContract)
_PROOF = object()


class BindingInputPublicationOwner(Generic[T]):
    """信頼済み構成で実値Ownerに付属する単一公開枠。値の意味を生成しない。"""

    def __init__(self, owner_id: str, value: T) -> None:
        require_identifier(owner_id, "owner_id")
        if not isinstance(value, (ArgumentSourceFact, OperationInputContract)):
            raise ValueError("引数事実または入力契約の公開が必要です")
        self.owner_id = owner_id
        self.participant = AuthorityFinalizationParticipant(self, owner_id, 12)
        self._value: T = value
        if isinstance(value, ArgumentSourceFact) and value.owner_id != owner_id:
            raise ValueError("事実のOwnerが公開枠と一致しません")

    def publish(self, value: T) -> None:
        with self.participant.mutation():
            old = self._value
            if type(value) is not type(old):
                raise ValueError("公開する契約型を変更できません")
            if isinstance(value, ArgumentSourceFact) and isinstance(old, ArgumentSourceFact):
                if (value.owner_id, value.reference_id) != (old.owner_id, old.reference_id):
                    raise ValueError("事実のOwnerまたはidentityを変更できません")
            if isinstance(value, OperationInputContract) and isinstance(
                old, OperationInputContract
            ):
                if value.schema_ref != old.schema_ref:
                    raise ValueError("入力契約のidentityを変更できません")
            if value.revision < old.revision or (
                value.revision == old.revision
                and canonical(value.to_dict()) != canonical(old.to_dict())
            ):
                raise ValueError("同じrevisionで内容を変更したりrevisionを戻したりできません")
            self._value = value

    def capture(self) -> AuthorityReadPublication[T]:
        with self.participant:
            return AuthorityReadPublication(self._value, (self.participant.token(),))

    def close(self) -> None:
        self.participant.retire()


@dataclass(frozen=True, slots=True)
class ActivityExecutionBindingPublication:
    value: ActivityExecutionBinding
    descriptor: CapabilityDescriptor
    tokens: tuple[AuthorityGenerationToken, ...]
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        if _proof is not _PROOF:
            raise ValueError("束縛公開は正規Ownerから取得してください")
        object.__setattr__(self, "tokens", tuple(self.tokens))
        if (
            len(canonical(self.to_dict()).encode())
            > V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.executive.max_fact_payload_json_bytes
        ):
            raise ValueError("束縛の全公開payloadが容量上限を超えています")

    def to_dict(self) -> dict[str, object]:
        return {
            "binding": self.value.to_dict(),
            "capability": self.descriptor.to_dict(),
            "generations": tuple(
                {
                    "owner_identity": t.owner_identity,
                    "owner_instance_key": t.owner_instance_key,
                    "participant_identity": t.participant_identity,
                    "generation": t.generation,
                }
                for t in self.tokens
            ),
        }

    def require_current(self) -> None:
        require_current(self.tokens)


class ActivityBindingAuthority:
    """一つの明示binding identityを所有する。別bindingの更新で失効させない。"""

    def __init__(
        self,
        binding_id: str,
        registry: PluginRegistryAuthority,
        schema: BindingInputPublicationOwner[OperationInputContract],
        sources: tuple[BindingInputPublicationOwner[ArgumentSourceFact], ...],
    ) -> None:
        require_identifier(binding_id, "binding_id")
        if len(sources) > V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.executive.max_refs_per_intent:
            raise ValueError("引数出典の登録上限を超えています")
        self.binding_id = binding_id
        self.registry = registry
        self.schema = schema
        self.sources = tuple(sources)
        refs = [s.capture().value.reference_id for s in sources]
        if len(set(refs)) != len(refs):
            raise ValueError("引数出典の登録が重複しています")
        self.participant = AuthorityFinalizationParticipant(self, "ActivityBindingAuthority", 10)
        self._publication: ActivityExecutionBindingPublication | None = None

    def publish(
        self,
        *,
        revision: int,
        activity_type: str,
        operation_ref: str,
        target_ref: str | None,
        capability_id: str,
        relations: tuple[ArgumentSourceRelation, ...],
    ) -> ActivityExecutionBindingPublication:
        participants = (
            self.participant,
            self.registry.finalization_participant,
            self.schema.participant,
            *(s.participant for s in self.sources),
        )
        with authority_read_set(participants), self.participant.mutation():
            capability = self.registry.capability_publication()
            matches = [c for c in capability.value if c.capability_id == capability_id]
            if len(matches) != 1:
                raise ValueError("操作の正規Capabilityが一意に存在しません")
            descriptor = matches[0]
            schema = self.schema.capture()
            if (
                descriptor.capability_type != activity_type
                or operation_ref not in descriptor.operations
            ):
                raise ValueError("操作または活動型がCapability宣言と一致しません")
            attributes = descriptor.attributes
            if not isinstance(attributes, Mapping):
                raise ValueError("操作宣言がありません")
            operations = attributes.get("operations")
            if not isinstance(operations, tuple):
                raise ValueError("操作宣言がありません")
            operations = tuple(
                op
                for op in operations
                if isinstance(op, Mapping)
                and op.get("operation_id") == operation_ref
                and op.get("input_schema_ref") == schema.value.schema_ref
            )
            if len(operations) != 1:
                raise ValueError("現在の操作宣言と入力契約が一致しません")
            sources = tuple(s.capture() for s in self.sources)
            facts = {p.value.reference_id: p.value for p in sources}
            try:
                args = {r.argument_name: facts[r.fact_ref].value for r in relations}
            except KeyError:
                raise ValueError("引数事実が登録されていません") from None
            value = ActivityExecutionBinding(
                self.binding_id,
                revision,
                activity_type,
                operation_ref,
                target_ref,
                capability_id,
                descriptor.revision,
                schema.value,
                relations,
                tuple(p.value for p in sources),
                args,
            )
            old = self._publication
            if old is not None and (
                revision < old.value.revision
                or (
                    revision == old.value.revision
                    and canonical(value.to_dict()) != canonical(old.value.to_dict())
                )
            ):
                raise ValueError("束縛のrevisionが古いか、同じrevisionで内容が異なります")
            publication = ActivityExecutionBindingPublication(
                value,
                descriptor,
                (
                    self.participant.token(),
                    *capability.tokens,
                    *schema.tokens,
                    *(t for p in sources for t in p.tokens),
                ),
                _PROOF,
            )
            self._publication = publication
            return publication

    def capture(self) -> ActivityExecutionBindingPublication:
        participants = (
            self.participant,
            self.registry.finalization_participant,
            self.schema.participant,
            *(s.participant for s in self.sources),
        )
        with authority_read_set(participants):
            if self._publication is None:
                raise ValueError("束縛が未公開です")
            require_current(self._publication.tokens[1:])
            return ActivityExecutionBindingPublication(
                self._publication.value,
                self._publication.descriptor,
                (self.participant.token(), *self._publication.tokens[1:]),
                _PROOF,
            )

    def close(self) -> None:
        self.participant.retire()
