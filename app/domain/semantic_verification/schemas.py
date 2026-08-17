from __future__ import annotations

from enum import Enum

from .contracts import (
    BlindInteractionAct,
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
                    "required": [
                        "unit_id",
                        "kind",
                        "interaction_acts",
                        "evidence_refs",
                    ],
                    "properties": {
                        "unit_id": {"type": "string", "minLength": 1},
                        "kind": {
                            "type": "string",
                            "enum": _enum_values(BlindSemanticUnitKind),
                        },
                        "interaction_acts": {
                            "type": "array",
                            "maxItems": 2,
                            "items": {
                                "type": "string",
                                "enum": _enum_values(BlindInteractionAct),
                            },
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
SpeechSemanticPlanや期待する正解は与えられません。actual utteranceだけを読みます。
入力のrequest_idとutterance_idはtrusted transport identityです。
出力のrequest_idとutterance_idには入力値をexactにそのまま返し、新しいIDを生成しないでください。
各unitは、意味内容kindとinteraction actを別々に観測してください。
kindは MATERIAL_SEMANTIC_CONTENT / NON_MATERIAL_STYLE / AMBIGUOUS のいずれかです。
interaction_actsは DIRECTED_QUESTION / NEW_DIRECTION を0個以上持てます。
命題、挨拶、謝意、依頼、約束など、変更すると伝達意味が変わる内容は
MATERIAL_SEMANTIC_CONTENTです。語尾や言い淀みだけならNON_MATERIAL_STYLEです。
「今日は雨だよね？」のように意味内容と質問行為が同時成立する場合、
kind=MATERIAL_SEMANTIC_CONTENTかつinteraction_acts=[DIRECTED_QUESTION]としてください。
独立して真偽・行為・話題内容を持つ意味が複数ある場合は最小のatomic unitへ分けてください。
1つに分離できず複数の独立意味を抱える場合はAMBIGUOUSにしてください。
元Plan DTO、polarity、certainty、degree等を推測復元しないでください。
各unitはactual segmentに存在するexact quoteと0-based occurrence_indexを返してください。
最終PASS/FAIL、修正文、正解文は出力しないでください。"""


def relation_instructions() -> str:
    return """あなたはPlan Relation Observerです。
入力には確定済みSpeechSemanticPlan、actual utterance、
Planを見ずに先行確定したBlindUtteranceObservationがあります。
入力のrequest_id、semantic_plan.plan_id、utterance.utterance_id、blind_observation.observation_idはtrusted identityです。
出力のrequest_id / semantic_plan_id / utterance_id / blind_observation_idには対応する入力値をexactにそのまま返し、新しいIDを生成しないでください。
Blind unitを削除・改名・結合して消してはいけません。
各blind unitをexactly one accounting recordで説明してください。
MATERIAL_SEMANTIC_CONTENTを単なるstyleへ降格してはいけません。
各Plan propositionについてactual utteranceとのrelationを
ENTAILED / MISSING / CONTRADICTED / AMBIGUOUSで観測してください。
polarity/certainty/degree/executionは入力Planに対する相対relationとして返してください。
SpeechからPlan DTO全体を再構築しないでください。
Character realization_refsやcandidate自己申告値はsemantic proofとして使わないでください。
ENTAILED relationはactual segmentのexact quote evidenceと、
その意味を担うblind unit IDを示してください。
SUPPORTED_BY_PLAN accountingは、対応proposition側も同じblind unitをsupportとして
ENTAILEDしている場合だけ使用してください。
Plan外のmaterial contentはUNSUPPORTED_EXTRA、判断不能はAMBIGUOUSです。
1 blind unitにPlan-supported意味とPlan外意味が混在している場合、
SUPPORTED_BY_PLANだけで覆わずUNSUPPORTED_EXTRAまたはAMBIGUOUSにしてください。
interaction_actsはAで固定済みですが、actual utteranceを独立に読み、
directed question数/new direction数を別途返してください。
最終PASS/FAIL、accepted、score、修正文、replacement utteranceは出力しないでください。"""
