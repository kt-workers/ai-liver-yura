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


def test_blind_role_separates_new_direction_from_same_topic_extra_content() -> None:
    instructions = blind_instructions()

    assert "別の会話継続先を新しく開く" in instructions
    assert "同じentity / event / topicの属性追加" in instructions
    assert "Plan外material contentやUNSUPPORTED_EXTRAであることだけを理由" in instructions
    assert "表層形だけでも分類してはいけません" in instructions


def test_relation_role_keeps_unsupported_extra_and_new_direction_orthogonal() -> None:
    instructions = relation_instructions()

    assert "別の会話継続先を新しく開く" in instructions
    assert "Plan外material contentやUNSUPPORTED_EXTRAであることだけを理由" in instructions
    assert "NEW_DIRECTIONへ分類してはいけません" in instructions


def test_relation_role_limits_self_disclosure_to_speaker_owned_content() -> None:
    instructions = relation_instructions()

    assert "話者自身についてのmaterial content" in instructions
    assert (
        "外部entity / eventの事実は、Plan外であってもself-disclosureではありません"
        in instructions
    )
    assert "self-disclosure material contentがなければNOT_APPLICABLE" in instructions
    assert "UNSUPPORTED_EXTRAを理由にself_disclosure_relationを自動的にEXCEEDED" in instructions


def test_relation_role_defines_self_disclosure_policy_relations() -> None:
    instructions = relation_instructions()

    assert "FORBIDDENではmaterial self-disclosureはEXCEEDED" in instructions
    assert "FACT_GROUNDEDではPlanにgroundされた" in instructions
    assert "ALLOWEDではself-disclosureであること自体を" in instructions
