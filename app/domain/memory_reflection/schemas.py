"""Reflection V1の唯一の出力schemaと、所有境界を守るinstructions。"""

from enum import Enum
from typing import cast

from app.domain.memory.contracts import (
    MemoryAssertionCertainty,
    MemoryAssertionPolarity,
    MemoryAssertionTemporalMeaning,
    MemoryFreshnessState,
    MemoryKind,
    MemoryRelationKind,
)

from .contracts import ReflectionPersistenceHint, ReflectionSupportRelation


def _object(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _enum(kind: type[Enum]) -> dict[str, object]:
    return {"type": "string", "enum": [entry.value for entry in kind]}


def _refs() -> dict[str, object]:
    return {"type": "array", "items": {"type": "string", "minLength": 1}}


def proposal_output_schema() -> dict[str, object]:
    unit = {"type": "number", "minimum": 0, "maximum": 1}
    nullable = {"type": ["string", "null"]}
    proposal = _object(
        {
            "proposal_id": {"type": "string", "minLength": 1},
            "proposed_kind": _enum(MemoryKind),
            "content": _object(
                {
                    "predicate": {"type": "string", "minLength": 1},
                    "value_json": {"type": "string"},
                    "subject_ref": nullable,
                    "temporal_scope_ref": nullable,
                    "qualifiers": _refs(),
                }
            ),
            "source_refs": _refs(),
            "confidence_hint": unit,
            "importance_hint": unit,
            "persistence_hint": _enum(ReflectionPersistenceHint),
            "novelty_hint": unit,
            "temporal": _object(
                {
                    "freshness": _enum(MemoryFreshnessState),
                    "valid_from": nullable,
                    "valid_until": nullable,
                    "observed_at": nullable,
                }
            ),
            "suggested_related_memory_ids": _refs(),
            "relation_hints": {
                "type": "array",
                "items": _object(
                    {
                        "related_memory_id": {"type": "string", "minLength": 1},
                        "related_memory_revision": {"type": "integer", "minimum": 0},
                        "relation_kind": _enum(MemoryRelationKind),
                        "evidence_refs": _refs(),
                        "confidence": unit,
                    }
                ),
            },
            "rationale_evidence_refs": _refs(),
        }
    )
    return _object({"proposals": {"type": "array", "items": proposal}})


def support_output_schema() -> dict[str, object]:
    return _object(
        {
            "proposal_id": {"type": "string", "minLength": 1},
            "support_relation": _enum(ReflectionSupportRelation),
            "evidence_refs": _refs(),
            "unsupported_content_refs": _refs(),
            "contradiction_refs": _refs(),
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        }
    )


def proposal_instructions() -> str:
    return (
        "frozen ReflectionContextSnapshotだけを根拠にMemory候補を提案する。"
        "何も残さないzero candidateは正常。source_refsはprimary_sources内、"
        "relation targetとrevisionはrelated_memory_view内に限定する。"
        "importance/novelty/confidence/persistenceはhintでありMemory Store決定ではない。"
        "prepared speechをactual_speech、planned activityをexecuted_activityへ昇格させない。"
        "free-form rationaleをtruth proofにせず、rationale_evidence_refsだけを参照する。"
        "deterministic captureを自己宣言しない。assertion_semanticsを出力しない。"
        "content.value_jsonはUTF-8のcanonical JSON文字列であり、JSON値の型を保持する。"
        "schema外のfieldや説明文を出力しない。"
    )


def support_instructions() -> str:
    return (
        "frozen contextとcanonical proposalだけを使い、exact proposal全体のsupportを観測する。"
        "proposalを書き換えず、Memory Store dispositionやfinal truthを決めない。"
        "generatorのfree-form rationaleをAuthorityにしない。"
        "evidence/unsupported/contradiction refsはfrozen primary_sources内に限定する。"
        "evidence_refsはproposal.source_refsの範囲内とする。"
        "proposal_idをexact保持し、既存closed support relationとevidenceを返す。"
        "assertion_semanticsやschema外の説明を出力しない。"
    )


# V1互換入口は固定し、current generationのschemaは明示名で選ぶ。
proposal_output_schema_v1 = proposal_output_schema


def proposal_output_schema_v2() -> dict[str, object]:
    schema = proposal_output_schema_v1()
    root = cast(dict[str, object], schema["properties"])
    array = cast(dict[str, object], root["proposals"])
    item = cast(dict[str, object], array["items"])
    properties = cast(dict[str, object], item["properties"])
    properties["assertion_semantics"] = {
        "anyOf": [
            {"type": "null"},
            _object(
                {
                    "polarity": _enum(MemoryAssertionPolarity),
                    "certainty": _enum(MemoryAssertionCertainty),
                    "temporal_meaning": _enum(MemoryAssertionTemporalMeaning),
                }
            ),
        ]
    }
    item["required"] = list(properties)
    return schema


def proposal_instructions_v2() -> str:
    return proposal_instructions().replace(
        "assertion_semanticsを出力しない。",
        "assertion_semanticsはfrozen evidenceがpolarity/certainty/temporal_meaningの全facetを"
        "安全に支える場合だけ明示し、不明ならnullとする。confidence_hintのthreshold、"
        "predicate名、MemoryKind、value_jsonの型、keyword/regex/substringからfacetを推測しない。"
        "confidenceとassertion certaintyは別Authorityである。",
    )


def support_instructions_v2() -> str:
    return support_instructions() + (
        "入力のcontentとassertion_semanticsを含むexact proposal全体を検証する。"
        "explicit semanticsがevidenceにsupportされない場合はSUPPORTEDにしない。"
        "意味に応じPARTIALLY_SUPPORTED/UNSUPPORTED/AMBIGUOUS/CONTRADICTEDを使用する。"
        "unsupported semanticsをNoneへ書き換えてacceptしない。output shapeはv1を維持する。"
    )
