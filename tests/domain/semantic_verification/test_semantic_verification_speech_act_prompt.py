from __future__ import annotations

from app.domain.semantic_verification import blind_instructions, relation_instructions


def test_blind_role_defines_directed_question_by_response_obligation() -> None:
    instructions = blind_instructions()

    assert "response obligation" in instructions
    assert "表層形だけで" in instructions
    assert "shared-stance" in instructions
    assert "現在の発話自身が相手へ返答を要求しない限り質問ではありません" in instructions


def test_relation_role_uses_same_directed_question_semantics() -> None:
    instructions = relation_instructions()

    assert "response obligation" in instructions
    assert "表層形だけで数えず" in instructions
    assert "shared-stance" in instructions
    assert "Planのquestion_budget値にcountを合わせず" in instructions
