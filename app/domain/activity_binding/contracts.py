"""操作と型付き引数の公開契約。意味の選択や値の補完は行わない。"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts.common import (
    JsonValue,
    freeze_json,
    require_identifier,
    require_revision,
    thaw_json,
)
from app.domain.contracts.finalization import (
    AuthorityGenerationToken,
    FinalizationError,
    authority_read_set,
)


def canonical(value: object) -> str:
    return json.dumps(
        thaw_json(freeze_json(value)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


class ArgumentKind(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"
    NULL = "null"

    def accepts(self, value: JsonValue) -> bool:
        return {
            self.STRING: isinstance(value, str),
            self.INTEGER: type(value) is int,
            self.NUMBER: type(value) in (int, float),
            self.BOOLEAN: type(value) is bool,
            self.OBJECT: isinstance(value, Mapping),
            self.ARRAY: isinstance(value, tuple),
            self.NULL: value is None,
        }[self]


@dataclass(frozen=True, slots=True)
class OperationInputContract:
    """信頼済み登録者がschemaの必須引数を明示する。空集合は引数不要を表す。"""

    schema_ref: str
    revision: int
    fields: tuple[tuple[str, ArgumentKind], ...]

    def __post_init__(self) -> None:
        require_identifier(self.schema_ref, "schema_ref")
        require_revision(self.revision, "revision")
        fields = tuple(tuple(x) for x in self.fields)
        if len(fields) > V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.executive.max_refs_per_intent:
            raise ValueError("入力契約の引数上限を超えています")
        if len({name for name, _ in fields}) != len(fields):
            raise ValueError("入力契約の引数名が重複しています")
        for name, kind in fields:
            require_identifier(name, "argument")
            if not isinstance(kind, ArgumentKind):
                raise ValueError("入力契約には明示的なJSON型が必要です")
        object.__setattr__(self, "fields", fields)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_ref": self.schema_ref,
            "revision": self.revision,
            "fields": {name: kind.value for name, kind in self.fields},
        }


@dataclass(frozen=True, slots=True)
class ArgumentSourceFact:
    """実値の供給Ownerが公開する事実。引数への意味変換は含まない。"""

    reference_id: str
    owner_id: str
    revision: int
    schema_ref: str
    value: JsonValue

    def __post_init__(self) -> None:
        for name in ("reference_id", "owner_id", "schema_ref"):
            require_identifier(getattr(self, name), name)
        require_revision(self.revision, "revision")
        object.__setattr__(self, "value", freeze_json(self.value))
        if (
            len(canonical(self.value).encode())
            > V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.executive.max_fact_payload_json_bytes
        ):
            raise ValueError("引数事実の容量上限を超えています")

    def to_dict(self) -> dict[str, object]:
        return {
            "reference_id": self.reference_id,
            "owner_id": self.owner_id,
            "revision": self.revision,
            "schema_ref": self.schema_ref,
            "value": thaw_json(self.value),
        }


@dataclass(frozen=True, slots=True)
class ArgumentSourceRelation:
    argument_name: str
    fact_ref: str

    def __post_init__(self) -> None:
        require_identifier(self.argument_name, "argument_name")
        require_identifier(self.fact_ref, "fact_ref")


@dataclass(frozen=True, slots=True)
class ActivityExecutionBinding:
    binding_id: str
    revision: int
    activity_type: str
    operation_ref: str
    target_ref: str | None
    capability_id: str
    capability_revision: int
    input_contract: OperationInputContract
    relations: tuple[ArgumentSourceRelation, ...]
    sources: tuple[ArgumentSourceFact, ...]
    arguments: JsonValue

    def __post_init__(self) -> None:
        for name in ("binding_id", "activity_type", "operation_ref", "capability_id"):
            require_identifier(getattr(self, name), name)
        if self.target_ref is not None:
            require_identifier(self.target_ref, "target_ref")
        require_revision(self.revision, "revision")
        require_revision(self.capability_revision, "capability_revision")
        object.__setattr__(self, "relations", tuple(self.relations))
        object.__setattr__(self, "sources", tuple(self.sources))
        object.__setattr__(self, "arguments", freeze_json(self.arguments))
        bounds = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.executive
        if (
            len(self.relations) > bounds.max_refs_per_intent
            or len(self.sources) > bounds.max_fact_refs
        ):
            raise ValueError("束縛の由来件数上限を超えています")
        facts = {f.reference_id: f for f in self.sources}
        rels = {r.argument_name: r.fact_ref for r in self.relations}
        if len(facts) != len(self.sources) or len(rels) != len(self.relations):
            raise ValueError("束縛の識別子が重複しています")
        if set(rels.values()) != set(facts) or set(rels) != {
            n for n, _ in self.input_contract.fields
        }:
            raise ValueError("入力契約・由来・引数の集合が一致しません")
        args = {name: facts[ref].value for name, ref in rels.items()}
        if canonical(args) != canonical(self.arguments):
            raise ValueError("引数が正規事実と一致しません")
        for name, kind in self.input_contract.fields:
            if (
                not kind.accepts(args[name])
                or facts[rels[name]].schema_ref != self.input_contract.schema_ref
            ):
                raise ValueError("引数の型またはschema由来が一致しません")
        if len(canonical(self.to_dict()).encode()) > bounds.max_fact_payload_json_bytes:
            raise ValueError("束縛公開の容量上限を超えています")

    def to_dict(self) -> dict[str, object]:
        return {
            "binding_id": self.binding_id,
            "revision": self.revision,
            "activity_type": self.activity_type,
            "operation_ref": self.operation_ref,
            "target_ref": self.target_ref,
            "capability_id": self.capability_id,
            "capability_revision": self.capability_revision,
            "input_contract": self.input_contract.to_dict(),
            "relations": tuple(
                {"argument_name": r.argument_name, "fact_ref": r.fact_ref} for r in self.relations
            ),
            "sources": tuple(f.to_dict() for f in self.sources),
            "arguments": thaw_json(self.arguments),
        }


def require_current(tokens: tuple[AuthorityGenerationToken, ...]) -> None:
    if not tokens:
        raise ValueError("束縛には正規の世代証拠が必要です")
    with authority_read_set(tuple(t._participant for t in tokens)):
        for token in tokens:
            failure = token._participant._validate(token)
            if failure is not None:
                raise FinalizationError(failure)
