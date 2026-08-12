from __future__ import annotations

from app.ports.structured_output import StructuredOutputContract


CHARACTER_UTTERANCE_V2_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["speech", "linguistic_performance", "realizations"],
    "properties": {
        "speech": {"type": "string"},
        "linguistic_performance": {
            "type": "object",
            "additionalProperties": False,
            "required": ["phrasing", "emphasis", "delivery_tags"],
            "properties": {
                "phrasing": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "emphasis": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "delivery_tags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
        "realizations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["proposition_id", "evidence_spans"],
                "properties": {
                    "proposition_id": {"type": "string"},
                    "evidence_spans": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    },
}


CHARACTER_UTTERANCE_V2_CONTRACT = StructuredOutputContract(
    name="character_utterance_v2",
    schema=CHARACTER_UTTERANCE_V2_SCHEMA,
    strict=True,
)
