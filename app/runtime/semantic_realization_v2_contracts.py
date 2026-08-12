from __future__ import annotations

from app.ports.structured_output import StructuredOutputContract


_PREDICATE_RELATIONS = ["preserved", "omitted", "changed", "unrelated", "ambiguous"]
_VALUE_STATUS_RELATIONS = [
    "preserved",
    "committed_when_unknown",
    "unknown_when_known",
    "omitted",
    "ambiguous",
    "not_applicable",
]
_POLARITY_RELATIONS = [
    "preserved",
    "contradicted",
    "omitted",
    "ambiguous",
    "not_applicable",
]
_DEGREE_RELATIONS = [
    "preserved",
    "weaker",
    "stronger",
    "omitted",
    "ambiguous",
    "not_applicable",
]
_CERTAINTY_RELATIONS = [
    "preserved",
    "stronger",
    "weaker",
    "ambiguous",
    "not_applicable",
]
_CONCEPT_RELATIONS = [
    "preserved",
    "omitted",
    "changed",
    "ambiguous",
    "not_applicable",
]
_SUMMARY_RELATIONS = [
    "preserved",
    "collapsed",
    "omitted",
    "ambiguous",
    "not_applicable",
]


def character_utterance_v2_contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="character_utterance_v2",
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["speech", "linguistic_performance", "realizations"],
            "properties": {
                "speech": {"type": "string", "minLength": 1},
                "linguistic_performance": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["phrasing", "emphasis", "delivery_tags"],
                    "properties": {
                        "phrasing": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 12,
                        },
                        "emphasis": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 12,
                        },
                        "delivery_tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 8,
                        },
                    },
                },
                "realizations": {
                    "type": "array",
                    "maxItems": 24,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["proposition_id", "evidence_spans"],
                        "properties": {
                            "proposition_id": {"type": "string", "minLength": 1},
                            "evidence_spans": {
                                "type": "array",
                                "maxItems": 12,
                                "items": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                },
            },
        },
        strict=True,
    )


def character_semantic_verification_v2_contract() -> StructuredOutputContract:
    proposition_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "proposition_id",
            "realized",
            "predicate_relation",
            "value_status_relation",
            "polarity_relation",
            "degree_relation",
            "certainty_relation",
            "concept_relation",
            "summary_relation",
            "evidence_spans",
        ],
        "properties": {
            "proposition_id": {"type": "string", "minLength": 1},
            "realized": {"type": "boolean"},
            "predicate_relation": {"type": "string", "enum": _PREDICATE_RELATIONS},
            "value_status_relation": {
                "type": "string",
                "enum": _VALUE_STATUS_RELATIONS,
            },
            "polarity_relation": {"type": "string", "enum": _POLARITY_RELATIONS},
            "degree_relation": {"type": "string", "enum": _DEGREE_RELATIONS},
            "certainty_relation": {"type": "string", "enum": _CERTAINTY_RELATIONS},
            "concept_relation": {"type": "string", "enum": _CONCEPT_RELATIONS},
            "summary_relation": {"type": "string", "enum": _SUMMARY_RELATIONS},
            "evidence_spans": {
                "type": "array",
                "maxItems": 12,
                "items": {"type": "string", "minLength": 1},
            },
        },
    }
    return StructuredOutputContract(
        name="character_semantic_verification_v2",
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "propositions",
                "required_content_preserved",
                "forbidden_additions_absent",
                "unsupported_new_fact_absent",
                "existence_boundary_preserved",
                "budget_preserved",
                "global_evidence_spans",
            ],
            "properties": {
                "propositions": {
                    "type": "array",
                    "maxItems": 24,
                    "items": proposition_schema,
                },
                "required_content_preserved": {"type": "boolean"},
                "forbidden_additions_absent": {"type": "boolean"},
                "unsupported_new_fact_absent": {"type": "boolean"},
                "existence_boundary_preserved": {"type": "boolean"},
                "budget_preserved": {"type": "boolean"},
                "global_evidence_spans": {
                    "type": "array",
                    "maxItems": 24,
                    "items": {"type": "string", "minLength": 1},
                },
            },
        },
        strict=True,
    )
