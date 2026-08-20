from __future__ import annotations

from app.domain.semantic_verification import (
    BlindSemanticUnit,
    BlindSemanticUnitKind,
    BlindUnitAccounting,
    BlindUnitAccountingRelation,
    UtteranceEvidenceRef,
)
from app.domain.semantic_verification.authority import _has_plan_extra_material
from app.domain.semantic_verification.schemas import relation_instructions


def _evidence() -> UtteranceEvidenceRef:
    return UtteranceEvidenceRef("segment-1", "まだ分からないんだ。", 0)


def _material_unit(unit_id: str = "unit-1") -> BlindSemanticUnit:
    return BlindSemanticUnit(
        unit_id,
        BlindSemanticUnitKind.MATERIAL_SEMANTIC_CONTENT,
        (),
        (_evidence(),),
    )


def _style_unit(unit_id: str = "style-1") -> BlindSemanticUnit:
    return BlindSemanticUnit(
        unit_id,
        BlindSemanticUnitKind.NON_MATERIAL_STYLE,
        (),
        (_evidence(),),
    )


def _accounting(
    unit_id: str,
    relation: BlindUnitAccountingRelation,
) -> BlindUnitAccounting:
    proposition_ids = (
        ("p1",) if relation is BlindUnitAccountingRelation.SUPPORTED_BY_PLAN else ()
    )
    return BlindUnitAccounting(
        unit_id,
        relation,
        proposition_ids,
        (_evidence(),),
    )


def test_fully_plan_supported_material_is_not_self_disclosure_excess_basis() -> None:
    units = (_material_unit(),)
    accounting = {
        "unit-1": _accounting(
            "unit-1",
            BlindUnitAccountingRelation.SUPPORTED_BY_PLAN,
        )
    }

    assert _has_plan_extra_material(units, accounting) is False


def test_unsupported_extra_material_can_ground_self_disclosure_excess() -> None:
    units = (_material_unit(),)
    accounting = {
        "unit-1": _accounting(
            "unit-1",
            BlindUnitAccountingRelation.UNSUPPORTED_EXTRA,
        )
    }

    assert _has_plan_extra_material(units, accounting) is True


def test_ambiguous_material_can_ground_self_disclosure_excess() -> None:
    units = (_material_unit(),)
    accounting = {
        "unit-1": _accounting(
            "unit-1",
            BlindUnitAccountingRelation.AMBIGUOUS,
        )
    }

    assert _has_plan_extra_material(units, accounting) is True


def test_non_material_style_cannot_ground_self_disclosure_excess() -> None:
    units = (_style_unit(),)
    accounting = {
        "style-1": _accounting(
            "style-1",
            BlindUnitAccountingRelation.PERMITTED_NON_MATERIAL_STYLE,
        )
    }

    assert _has_plan_extra_material(units, accounting) is False


def test_relation_prompt_keeps_self_disclosure_as_additional_content_boundary() -> None:
    instructions = relation_instructions()

    assert "self_disclosure_relationはPlan-supported contentの再解釈ではありません" in instructions
    assert "SUPPORTED_BY_PLANのmaterial contentだけを根拠にEXCEEDEDへしてはいけません" in instructions
    assert "UNSUPPORTED_EXTRAまたはAMBIGUOUS" in instructions
    assert "first-personやepistemicな表面表現だけでEXCEEDEDへしてはいけません" in instructions
