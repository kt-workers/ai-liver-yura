from copy import deepcopy

import pytest
from jsonschema import ValidationError, validate

from app.domain.character_language import (
    character_language_instructions,
    character_language_output_schema,
)


def _valid_payload() -> dict[str, object]:
    return {
        "candidate_id": "candidate-1",
        "request_id": "request-1",
        "semantic_plan_id": "plan-1",
        "source_decision_id": "decision-1",
        "source_intent_id": "intent-1",
        "source_event_ids": ["event-1"],
        "revisions": {
            "source_context_revision": 1,
            "goal_revision": None,
            "attention_revision": 2,
        },
        "character_id": "yura",
        "character_schema_version": 1,
        "character_definition_revision": 7,
        "segments": [
            {
                "segment_id": "segment-1",
                "text": "ありがと、助かった。",
                "realization_refs": ["p1"],
                "boundary_after": "sentence",
                "emphasis": "neutral",
                "hesitation": "none",
            }
        ],
        "question_budget_used": 0,
        "new_direction_budget_used": 0,
    }


def test_output_schema_accepts_exact_candidate_shape_and_nullable_revisions() -> None:
    validate(instance=_valid_payload(), schema=character_language_output_schema())


@pytest.mark.parametrize(
    ("scope", "field", "value"),
    [
        ("top", "unexpected", True),
        ("revision", "unexpected", 1),
        ("segment", "unexpected", "x"),
        ("segment", "boundary_after", "unknown"),
        ("segment", "emphasis", "unknown"),
        ("segment", "hesitation", "unknown"),
        ("top", "question_budget_used", -1),
        ("top", "new_direction_budget_used", -1),
        ("revision", "source_context_revision", -1),
        ("top", "polarity", "affirm"),
        ("top", "execution_status", "completed"),
    ],
)
def test_output_schema_rejects_unknown_semantic_override_or_invalid_values(
    scope: str,
    field: str,
    value: object,
) -> None:
    payload = deepcopy(_valid_payload())
    if scope == "top":
        payload[field] = value
    elif scope == "revision":
        revisions = payload["revisions"]
        assert isinstance(revisions, dict)
        revisions[field] = value
    else:
        segments = payload["segments"]
        assert isinstance(segments, list)
        segment = segments[0]
        assert isinstance(segment, dict)
        segment[field] = value

    with pytest.raises(ValidationError):
        validate(instance=payload, schema=character_language_output_schema())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("segments", []),
        ("source_event_ids", []),
        ("candidate_id", ""),
        ("request_id", ""),
    ],
)
def test_output_schema_rejects_empty_required_content(field: str, value: object) -> None:
    payload = deepcopy(_valid_payload())
    payload[field] = value
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=character_language_output_schema())


def test_output_schema_rejects_empty_segment_text() -> None:
    payload = deepcopy(_valid_payload())
    segments = payload["segments"]
    assert isinstance(segments, list)
    segment = segments[0]
    assert isinstance(segment, dict)
    segment["text"] = ""
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=character_language_output_schema())


def test_production_instructions_keep_authority_boundaries_explicit() -> None:
    instructions = character_language_instructions()
    for required_text in (
        "semantic_planだけが発話内容のWhat-to-say Authority",
        "Character Profileを新しいFact sourceとして扱ってはいけません",
        "FORBIDDEN propositionは実現してはいけません",
        "Planにないmaterial claim",
        "realization_refsは意味保持の証明ではなく",
        "後段#363が独立検証",
        "TTS parameter、SSML、Body gesture、motion",
    ):
        assert required_text in instructions


def test_production_instructions_use_weak_repetition_awareness() -> None:
    instructions = character_language_instructions()

    for required_text in (
        "意味保持、自然さ、Characterらしさ、反復回避の順で優先",
        "weak repetition-awareness reference",
        "自然で意味安全な別表現が明らかにある場合だけ避けても構いません",
        "同じ表現が最も自然で意味安全なら、そのまま再使用して構いません",
        "exact duplicate自体をfailureとして扱わない",
        "uniqueな表現を作ること自体を目的にしてはいけません",
        "actual meaningはcurrent semantic_planだけから決めてください",
        "Fact source、会話履歴、追加propositionとして扱ってはいけません",
    ):
        assert required_text in instructions

    for forbidden_text in (
        "negative reference",
        "感じ",
        "みたい",
        "synonym dictionary",
        "sentence-ending rotation",
    ):
        assert forbidden_text not in instructions
