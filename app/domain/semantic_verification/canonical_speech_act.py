from __future__ import annotations

from .schemas import blind_instructions as _legacy_blind_instructions


_NEW_DIRECTION_CONTRACT = """
NEW_DIRECTIONは、actual utteranceが現在のtopic / discourse objective / initiativeから、
別の会話継続先を新しく開く、又は切り替える場合だけ成立します。
同じentity / event / topicの属性追加、説明、理由、根拠、例、補足、具体化は、
それだけではNEW_DIRECTIONではありません。
material contentがPlan外かどうかとNEW_DIRECTIONは別の意味軸です。
Plan外material contentやUNSUPPORTED_EXTRAであることだけを理由にNEW_DIRECTIONへ分類してはいけません。
文数、transition phrase、discourse marker、keyword等の表層形だけでも分類してはいけません。
""".strip()

_SELF_DISCLOSURE_CONTRACT = """
self_disclosure_relationは、actual utteranceが話者自身についてのmaterial contentを
開示している場合だけPlanのself_disclosure policyと比較してください。
話者自身の状態、嗜好、経験・履歴、能力・限界、意図・欲求・commitment等は
self-disclosureになり得ますが、semantic ownershipを意味として判断し、
一人称語やsubject IDの有限リストで判定してはいけません。
外部entity / eventの事実は、Plan外であってもself-disclosureではありません。
self-disclosure material contentがなければNOT_APPLICABLE、存在してpolicy内ならWITHIN_POLICY、
開示自体がpolicyを超える場合だけEXCEEDED、判断不能ならAMBIGUOUSを返してください。
FORBIDDENではmaterial self-disclosureはEXCEEDED、FACT_GROUNDEDではPlanにgroundされた
self-related contentの範囲内ならWITHIN_POLICY、ALLOWEDではself-disclosureであること自体を
EXCEEDEDにしません。ただしPlan外material contentは別軸のUNSUPPORTED_EXTRAになり得ます。
UNSUPPORTED_EXTRAを理由にself_disclosure_relationを自動的にEXCEEDEDへしてはいけません。
""".strip()


def blind_instructions() -> str:
    """Role AへNEW_DIRECTIONのopen-ended semantic boundaryを追加する。"""

    return f"{_legacy_blind_instructions()}\n{_NEW_DIRECTION_CONTRACT}"


def augment_relation_instructions(instructions: str) -> str:
    """Role Bへbudget/self-disclosureの直交意味境界を追加する。"""

    return (
        f"{instructions}\n{_NEW_DIRECTION_CONTRACT}\n{_SELF_DISCLOSURE_CONTRACT}"
    )


__all__ = ["augment_relation_instructions", "blind_instructions"]
