from __future__ import annotations

from enum import Enum

from .contracts import (
    BlindSemanticUnitKind,
    BlindUnitAccountingRelation,
    CertaintyRelation,
    DegreeRelation,
    ExecutionRelation,
    PolarityRelation,
    PropositionRelation,
    SelfDisclosureRelation,
)


def _enum_values(enum_type: type[Enum]) -> list[str]:
    return [str(item.value) for item in enum_type]


def _evidence_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["segment_id", "quote", "occurrence_index"],
        "properties": {
            "segment_id": {"type": "string", "minLength": 1},
            "quote": {"type": "string", "minLength": 1, "maxLength": 1000},
            "occurrence_index": {"type": "integer", "minimum": 0},
        },
    }


def blind_output_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidate_id", "request_id", "utterance_id", "units"],
        "properties": {
            "candidate_id": {"type": "string", "minLength": 1},
            "request_id": {"type": "string", "minLength": 1},
            "utterance_id": {"type": "string", "minLength": 1},
            "units": {
                "type": "array",
                "maxItems": 64,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["unit_id", "kind", "evidence_refs"],
                    "properties": {
                        "unit_id": {"type": "string", "minLength": 1},
                        "kind": {
                            "type": "string",
                            "enum": _enum_values(BlindSemanticUnitKind),
                        },
                        "evidence_refs": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 8,
                            "items": _evidence_schema(),
                        },
                    },
                },
            },
        },
    }


def relation_output_schema() -> dict[str, object]:
    proposition_observation: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "proposition_id",
            "relation",
            "polarity_relation",
            "certainty_relation",
            "degree_relation",
            "execution_relation",
            "evidence_refs",
            "supporting_blind_unit_ids",
        ],
        "properties": {
            "proposition_id": {"type": "string", "minLength": 1},
            "relation": {"type": "string", "enum": _enum_values(PropositionRelation)},
            "polarity_relation": {
                "type": "string",
                "enum": _enum_values(PolarityRelation),
            },
            "certainty_relation": {
                "type": "string",
                "enum": _enum_values(CertaintyRelation),
            },
            "degree_relation": {
                "type": "string",
                "enum": _enum_values(DegreeRelation),
            },
            "execution_relation": {
                "type": "string",
                "enum": _enum_values(ExecutionRelation),
            },
            "evidence_refs": {
                "type": "array",
                "maxItems": 8,
                "items": _evidence_schema(),
            },
            "supporting_blind_unit_ids": {
                "type": "array",
                "maxItems": 16,
                "items": {"type": "string", "minLength": 1},
            },
        },
    }
    accounting: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["blind_unit_id", "relation", "proposition_ids", "evidence_refs"],
        "properties": {
            "blind_unit_id": {"type": "string", "minLength": 1},
            "relation": {
                "type": "string",
                "enum": _enum_values(BlindUnitAccountingRelation),
            },
            "proposition_ids": {
                "type": "array",
                "maxItems": 16,
                "items": {"type": "string", "minLength": 1},
            },
            "evidence_refs": {
                "type": "array",
                "maxItems": 8,
                "items": _evidence_schema(),
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "candidate_id",
            "request_id",
            "semantic_plan_id",
            "utterance_id",
            "blind_observation_id",
            "proposition_observations",
            "blind_unit_accounting",
            "budget_observation",
            "self_disclosure_relation",
        ],
        "properties": {
            "candidate_id": {"type": "string", "minLength": 1},
            "request_id": {"type": "string", "minLength": 1},
            "semantic_plan_id": {"type": "string", "minLength": 1},
            "utterance_id": {"type": "string", "minLength": 1},
            "blind_observation_id": {"type": "string", "minLength": 1},
            "proposition_observations": {
                "type": "array",
                "maxItems": 64,
                "items": proposition_observation,
            },
            "blind_unit_accounting": {
                "type": "array",
                "maxItems": 64,
                "items": accounting,
            },
            "budget_observation": {
                "type": "object",
                "additionalProperties": False,
                "required": ["directed_question_count", "new_direction_count"],
                "properties": {
                    "directed_question_count": {"type": "integer", "minimum": 0},
                    "new_direction_count": {"type": "integer", "minimum": 0},
                },
            },
            "self_disclosure_relation": {
                "type": "string",
                "enum": _enum_values(SelfDisclosureRelation),
            },
        },
    }


def blind_instructions() -> str:
    return """あなたは発話の独立Semantic Inventory Observerです。
SpeechSemanticPlanや期待する正解は与えられません。
actual utteranceだけを読みます。
発話中の意味を持つ単位を、次のclosed kindへ分けて列挙してください。
MATERIAL_CLAIM / DIRECTED_QUESTION / NEW_DIRECTION /
NON_PROPOSITIONAL_STYLE / AMBIGUOUS
元のPlan DTO、polarity、certainty、degree等を推測復元しないでください。
各unitはactual segmentに存在するexact quoteと0-based occurrence_indexを
`evidence_refs`へ返してください。
同じ文の中に独立した事実主張が複数ある場合は、可能な範囲で別unitに分けてください。
語尾・言い淀み等で独立した命題を持たないものはNON_PROPOSITIONAL_STYLEです。
意味単位か判断できない場合はAMBIGUOUSにしてください。
最終PASS/FAIL、修正文、正解文は出力しないでください。"""


def relation_instructions() -> str:
    return """あなたはPlan Relation Observerです。
入力には確定済みSpeechSemanticPlan、actual utterance、
Planを見ずに先行確定したBlindUtteranceObservationがあります。
Blind unitを削除・改名・無視してはいけません。
各blind unitをexactly one accounting recordで説明してください。
MATERIAL_CLAIMを単なるstyleへ降格してはいけません。
各Plan propositionについてactual utteranceとのrelationを
ENTAILED / MISSING / CONTRADICTED / AMBIGUOUSで観測してください。
polarity/certainty/degree/executionは入力Planに対する相対relationとして返してください。
SpeechからPlan DTO全体を再構築しないでください。
Character realization_refsやcandidate自己申告値はsemantic proofとして使わないでください。
ENTAILED relationはactual segmentのexact quote evidenceと、
その意味を担うblind unit IDを示してください。
Plan外のmaterial claimはUNSUPPORTED_EXTRA、判断不能はAMBIGUOUSとしてaccountしてください。
実際のdirected question数/new direction数もutterance意味から数えてください。
最終PASS/FAIL、accepted、score、修正文、replacement utteranceは出力しないでください。"""
