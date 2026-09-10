"""意味Ownerの明示入力だけを束縛し、実値と世代を同時に公開する。"""

from dataclasses import InitVar, dataclass
from datetime import datetime
from typing import TypeVar

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts import CapabilityDescriptor
from app.domain.contracts.common import require_identifier
from app.domain.contracts.finalization import (
    AuthorityFinalizationFence,
    AuthorityFinalizationParticipant,
    AuthorityFinalizationRequest,
    AuthorityGenerationToken,
    AuthorityReadPublication,
    FinalizationError,
    FinalizationFailure,
    authority_read_set,
)

from .contracts import (
    ActivityExecutionBinding,
    ArgumentSourceFact,
    ArgumentSourceRelation,
    OperationInputContract,
    canonical,
    require_current,
)
from .ports import ActivityOperationPublicationPort, ArgumentSourceOwnerPort, InputSchemaOwnerPort

T = TypeVar("T")
_PROOF = object()


def _owned(
    publication: AuthorityReadPublication[T], participant: AuthorityFinalizationParticipant
) -> T:
    if len(publication.tokens) != 1 or publication.tokens[0]._participant is not participant:
        raise ValueError("公開値には正規Owner自身の単一tokenが必要です")
    require_current(publication.tokens)
    return publication.value


class BindingInputPublicationOwner:
    """入力schemaを所有する単一Owner。実値のコピー集約には使用しない。"""

    def __init__(self, owner_id: str, value: OperationInputContract) -> None:
        require_identifier(owner_id, "owner_id")
        if not isinstance(value, OperationInputContract):
            raise ValueError("入力schema契約が必要です")
        self.owner_id = owner_id
        self.participant = AuthorityFinalizationParticipant(self, owner_id, 12)
        self._value = value

    @property
    def finalization_participant(self) -> AuthorityFinalizationParticipant:
        return self.participant

    def publish(self, value: OperationInputContract) -> None:
        with self.participant.mutation():
            old = self._value
            if not isinstance(value, OperationInputContract) or value.schema_ref != old.schema_ref:
                raise ValueError("入力契約のidentityを変更できません")
            if value.revision < old.revision or (
                value.revision == old.revision
                and canonical(value.to_dict()) != canonical(old.to_dict())
            ):
                raise ValueError("同じrevisionで内容を変更したりrevisionを戻したりできません")
            self._value = value

    def capture(self) -> AuthorityReadPublication[OperationInputContract]:
        with self.participant:
            return AuthorityReadPublication(self._value, (self.participant.token(),))

    def close(self) -> None:
        self.participant.retire()


class ArgumentSourceOwner:
    """自身が実値を所有するboundedな事実集合。全更新は同じOwner lockを使う。"""

    def __init__(self, owner_id: str, facts: tuple[ArgumentSourceFact, ...]) -> None:
        require_identifier(owner_id, "owner_id")
        self.owner_id = owner_id
        self.participant = AuthorityFinalizationParticipant(self, owner_id, 12)
        self._facts = self._validate(facts)

    @property
    def finalization_participant(self) -> AuthorityFinalizationParticipant:
        return self.participant

    def _validate(self, facts: tuple[ArgumentSourceFact, ...]) -> tuple[ArgumentSourceFact, ...]:
        facts = tuple(facts)
        bounds = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.executive
        if len(facts) > bounds.max_fact_refs or len({f.reference_id for f in facts}) != len(facts):
            raise ValueError("事実集合の上限超過またはidentity重複です")
        if any(f.owner_id != self.owner_id for f in facts):
            raise ValueError("事実は実値Owner自身に所属する必要があります")
        if (
            len(canonical([f.to_dict() for f in facts]).encode())
            > bounds.max_fact_payload_json_bytes
        ):
            raise ValueError("事実集合のpayload容量上限を超えています")
        return facts

    def publish(self, facts: tuple[ArgumentSourceFact, ...]) -> None:
        with self.participant.mutation():
            facts = self._validate(facts)
            old = {f.reference_id: f for f in self._facts}
            for fact in facts:
                previous = old.get(fact.reference_id)
                if previous is not None and (
                    fact.revision < previous.revision
                    or (
                        fact.revision == previous.revision
                        and canonical(fact.to_dict()) != canonical(previous.to_dict())
                    )
                ):
                    raise ValueError("同じrevisionの内容変更または古い事実です")
            self._facts = facts

    def capture(self) -> AuthorityReadPublication[tuple[ArgumentSourceFact, ...]]:
        with self.participant:
            return AuthorityReadPublication(self._facts, (self.participant.token(),))

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


@dataclass(frozen=True, slots=True)
class _BindingCommit:
    value: ActivityExecutionBinding
    descriptor: CapabilityDescriptor
    tokens: tuple[AuthorityGenerationToken, ...]


class ActivityBindingAuthority:
    """明示bindingを既存Fenceで確定する。意味と実値は出典Ownerに残す。"""

    def __init__(
        self,
        binding_id: str,
        operation_owner: ActivityOperationPublicationPort,
        schema: InputSchemaOwnerPort,
        sources: tuple[ArgumentSourceOwnerPort, ...],
    ) -> None:
        require_identifier(binding_id, "binding_id")
        if len(sources) > V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.executive.max_fact_refs:
            raise ValueError("引数出典の登録上限を超えています")
        if len({s.owner_id for s in sources}) != len(sources):
            raise ValueError("出典Ownerのidentityが重複しています")
        if len({s.finalization_participant for s in sources}) != len(sources):
            raise ValueError("独立Ownerを同じparticipantへ集約できません")
        self.binding_id = binding_id
        self.operation_owner = operation_owner
        self.schema = schema
        self.sources = tuple(sources)
        self.participant = AuthorityFinalizationParticipant(self, "ActivityBindingAuthority", 10)
        self._publication: ActivityExecutionBindingPublication | None = None
        self._operation = self.participant.register_operation(self, "publish", self._commit)

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
        # 検査失敗・busy・容量拒否でも、更新可能操作への進入で旧世代を失効する。
        with self.participant.mutation():
            target_token = self.participant.token()
        participants = (
            self.operation_owner.finalization_participant,
            self.schema.finalization_participant,
            *(s.finalization_participant for s in self.sources),
        )
        with authority_read_set(participants):
            operation_pub = self.operation_owner.operation_publication(capability_id, operation_ref)
            operation = _owned(operation_pub, self.operation_owner.finalization_participant)
            schema_pub = self.schema.capture()
            schema = _owned(schema_pub, self.schema.finalization_participant)
            descriptor = operation.descriptor
            if (
                descriptor.capability_id != capability_id
                or descriptor.capability_type != activity_type
                or operation.operation_ref != operation_ref
                or operation.input_schema_ref != schema.schema_ref
            ):
                raise ValueError("操作の正規宣言と入力契約が一致しません")
            wanted = {r.fact_ref for r in relations}
            facts: dict[str, ArgumentSourceFact] = {}
            tokens = [*operation_pub.tokens, *schema_pub.tokens]
            for source in self.sources:
                captured = source.capture()
                values = _owned(captured, source.finalization_participant)
                bounds = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.executive
                if len(values) > bounds.max_fact_refs or len(
                    {f.reference_id for f in values}
                ) != len(values):
                    raise ValueError("出典公開の件数超過または重複です")
                if (
                    len(canonical([f.to_dict() for f in values]).encode())
                    > bounds.max_fact_payload_json_bytes
                ):
                    raise ValueError("出典公開のpayload容量超過です")
                if any(f.owner_id != source.owner_id for f in values):
                    raise ValueError("出典公開のOwnerが一致しません")
                selected = [f for f in values if f.reference_id in wanted]
                for fact in selected:
                    if fact.reference_id in facts:
                        raise ValueError("複数Ownerの事実参照が衝突しています")
                    facts[fact.reference_id] = fact
                if selected:
                    tokens.extend(captured.tokens)
            if set(facts) != wanted:
                raise ValueError("引数事実が登録されていません")
            value = ActivityExecutionBinding(
                self.binding_id,
                revision,
                activity_type,
                operation_ref,
                target_ref,
                capability_id,
                descriptor.revision,
                schema,
                relations,
                tuple(facts.values()),
                {r.argument_name: facts[r.fact_ref].value for r in relations},
            )
        result = AuthorityFinalizationFence().finalize(
            AuthorityFinalizationRequest(
                (target_token, *tokens),
                self.participant,
                self._operation,
                _BindingCommit(value, descriptor, tuple(tokens)),
            )
        )
        if result.failure is not None:
            raise FinalizationError(result.failure)
        assert result.value is not None
        return result.value

    def _commit(
        self, payload: _BindingCommit, committed_at: datetime
    ) -> ActivityExecutionBindingPublication:
        old = self._publication
        value = payload.value
        if old is not None and (
            value.revision < old.value.revision
            or (
                value.revision == old.value.revision
                and canonical(value.to_dict()) != canonical(old.value.to_dict())
            )
        ):
            raise FinalizationError(FinalizationFailure.TARGET_REJECTED)
        try:
            publication = ActivityExecutionBindingPublication(
                value, payload.descriptor, (self.participant.token(), *payload.tokens), _PROOF
            )
        except ValueError:
            raise FinalizationError(FinalizationFailure.TARGET_REJECTED) from None
        self._publication = publication
        return publication

    def capture(self) -> ActivityExecutionBindingPublication:
        with self.participant:
            old = self._publication
        if old is None:
            raise ValueError("束縛が未公開です")
        with authority_read_set((self.participant, *(t._participant for t in old.tokens[1:]))):
            if self._publication is not old:
                raise ValueError("読取中に束縛が変更されています")
            require_current(old.tokens[1:])
            return ActivityExecutionBindingPublication(
                old.value, old.descriptor, (self.participant.token(), *old.tokens[1:]), _PROOF
            )

    def close(self) -> None:
        self.participant.retire()
