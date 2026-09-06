"""記憶間の関係を保存方式に依存しないJSONへ変換する。"""

import json
from datetime import datetime

from app.domain.memory.contracts import MemoryRelation, MemoryRelationKind

from .contracts import PersistenceError, PersistenceFailureCode


def encode_relation(relation: MemoryRelation) -> str:
    return json.dumps(
        {
            "relation_id": relation.relation_id,
            "left_memory_id": relation.left_memory_id,
            "right_memory_id": relation.right_memory_id,
            "kind": relation.kind.value,
            "evidence_refs": list(relation.evidence_refs),
            "created_at": relation.created_at.isoformat(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def decode_relation(raw: str) -> MemoryRelation:
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError
        created_at = datetime.fromisoformat(value["created_at"])
        return MemoryRelation(
            value["relation_id"],
            value["left_memory_id"],
            value["right_memory_id"],
            MemoryRelationKind(value["kind"]),
            tuple(value["evidence_refs"]),
            created_at,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise PersistenceError(
            PersistenceFailureCode.CORRUPT_RECORD,
            "記憶間の関係の保存内容が不正です",
        ) from error
