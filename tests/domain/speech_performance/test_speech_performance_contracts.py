from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.domain.appraisal import FacetRef, InternalStateFacet, InternalStateSnapshot, StateFacetKind
from app.domain.character import RuntimeAvailability
from app.domain.character.contracts import CharacterVoiceStyleProfile, RuntimeCharacterFacet
from app.domain.speech_performance import (
    ExpressionAxis,
    LinguisticPerformancePolicy,
    PerformanceAxis,
    PerformanceIntentDelta,
    PerformanceIntentVector,
    PitchAnchor,
    SpeechExpressionContext,
    SpeechPerformanceConstraintView,
    SpeechPerformanceContextSnapshot,
    SpeechPerformanceDegradationReason,
    SpeechPerformanceSegment,
)
from app.domain.speech_performance.planner import SpeechPerformancePlanner, project_expression
from app.domain.speech_performance.policy import yura_revision_1_policy
from tests.domain.semantic_verification.test_semantic_verification import _utterance


def test_normalized_contracts_reject_bool_nan_and_infinity() -> None:
    with pytest.raises(ValueError):
        PitchAnchor(True, 0.0, 0.0)
    with pytest.raises(ValueError):
        PitchAnchor(0.0, math.nan, 0.0)
    with pytest.raises(ValueError):
        PitchAnchor(0.0, 0.0, math.inf)


def test_pitch_anchor_bounds_and_ordering_are_fail_closed() -> None:
    with pytest.raises(ValueError):
        PitchAnchor(1.1, 0.0, 0.0)
    delta = PerformanceIntentDelta(())
    with pytest.raises(ValueError):
        SpeechPerformanceSegment(
            "performance-segment",
            "utterance-segment",
            0.5,
            0.5,
            0.0,
            0.5,
            0.0,
            delta,
            (PitchAnchor(0.8, 0.0, 0.0), PitchAnchor(0.2, 0.0, 0.0)),
        )


def test_intent_is_complete_engine_independent_normalized_space() -> None:
    intent = PerformanceIntentVector.neutral()
    assert {axis for axis, _ in intent.values} == set(PerformanceAxis)
    assert all(value == 0.0 for _, value in intent.values)


def test_linguistic_policy_preserves_monotonic_boundary_and_emphasis() -> None:
    with pytest.raises(ValueError):
        LinguisticPerformancePolicy(0.8, 0.5, 0.2, 0.8, 0.2, 0.5)
    with pytest.raises(ValueError):
        LinguisticPerformancePolicy(0.2, 0.5, 0.8, 0.2, 0.8, 0.5)


def test_expression_context_uses_typed_axes_only() -> None:
    context = SpeechExpressionContext(
        expression_context_id="expression",
        source_context_revision=1,
        internal_state_revision=1,
        attention_revision=None,
        source_refs=("energy",),
        axes=((ExpressionAxis.ENERGY, 0.5),),
        diagnostics=(),
        updated_at=datetime.now(timezone.utc),
    )
    assert context.axes == ((ExpressionAxis.ENERGY, 0.5),)


def test_domain_has_no_provider_or_free_text_interpretation_authority() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("app/domain/speech_performance").glob("*.py")
    ).casefold()
    for forbidden in ("voicevox", "speaker_id", "speed_scale", "re.compile", "substring"):
        assert forbidden not in source
    assert "StateFacetKind.EMOTION" not in source


def test_planner_preserves_committed_utterance_text_and_segment_identity() -> None:
    utterance = _utterance(text="そのままの言葉")
    voice = CharacterVoiceStyleProfile(
        "yura",
        1,
        1,
        (
            RuntimeCharacterFacet(
                "baseline_softness", RuntimeAvailability.CONFIRMED, "柔らかく親しみがある"
            ),
        ),
    )
    plan = SpeechPerformancePlanner(yura_revision_1_policy()).plan(
        "performance-plan", utterance, voice, None, datetime.now(timezone.utc)
    )
    assert utterance.candidate.segments[0].text == "そのままの言葉"
    assert plan.segments[0].utterance_segment_id == utterance.candidate.segments[0].segment_id


def test_planner_rejects_voice_style_provenance_mismatch() -> None:
    utterance = _utterance()
    voice = CharacterVoiceStyleProfile("other", 1, 1, ())
    with pytest.raises(ValueError, match="provenance"):
        SpeechPerformancePlanner(yura_revision_1_policy()).plan(
            "performance-plan", utterance, voice, None, datetime.now(timezone.utc)
        )


def test_changed_confirmed_voice_wording_never_reuses_old_exact_binding() -> None:
    utterance = _utterance()
    voice = CharacterVoiceStyleProfile(
        "yura",
        1,
        1,
        (
            RuntimeCharacterFacet(
                "baseline_softness", RuntimeAvailability.CONFIRMED, "柔らかく親しみがある改訂"
            ),
        ),
    )
    plan = SpeechPerformancePlanner(yura_revision_1_policy()).plan(
        "performance-plan", utterance, voice, None, datetime.now(timezone.utc)
    )
    assert (
        SpeechPerformanceDegradationReason.UNMAPPED_CHARACTER_VOICE_STYLE
        in plan.degradation_reasons
    )
    assert plan.global_intent.get(PerformanceAxis.SOFTNESS) == 0.0


def test_energy_and_arousal_are_the_only_initial_dynamic_state_families() -> None:
    policy = yura_revision_1_policy()
    assert {rule.facet_kind for rule in policy.state_rules} == {
        StateFacetKind.ENERGY,
        StateFacetKind.AROUSAL,
    }
    now = datetime.now(timezone.utc)
    state = InternalStateSnapshot(
        4,
        10,
        (
            InternalStateFacet(
                FacetRef(StateFacetKind.ENERGY, "energy"), 0.8, 0.0, 0.8, 0.5, ("e1",), now
            ),
            InternalStateFacet(
                FacetRef(StateFacetKind.EMOTION, "joy"), 1.0, 0.0, 1.0, 1.0, ("e2",), now
            ),
        ),
        now,
    )
    context = project_expression("expression", state, policy)
    assert context.diagnostics == ("unmapped_state:emotion",)
    assert dict(context.axes)[ExpressionAxis.ENERGY] == pytest.approx(0.2)


def test_snapshot_rejects_mixed_expression_generation() -> None:
    utterance = _utterance()
    expression = SpeechExpressionContext(
        expression_context_id="expression",
        source_context_revision=999,
        internal_state_revision=1,
        attention_revision=utterance.candidate.revisions.attention_revision,
        source_refs=(),
        axes=(),
        diagnostics=(),
        updated_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ValueError, match="revision"):
        SpeechPerformanceContextSnapshot(
            "request",
            utterance,
            None,
            expression,
            (),
            utterance.candidate.revisions.source_context_revision,
            utterance.candidate.revisions.goal_revision,
            utterance.candidate.revisions.attention_revision,
            datetime.now(timezone.utc),
            "trace",
        )


def test_unknown_constraint_is_fail_closed() -> None:
    utterance = _utterance()
    snapshot = SpeechPerformanceContextSnapshot(
        "request",
        utterance,
        None,
        None,
        (SpeechPerformanceConstraintView("constraint", "test", "ref", 1, "unknown", 0.1),),
        utterance.candidate.revisions.source_context_revision,
        utterance.candidate.revisions.goal_revision,
        utterance.candidate.revisions.attention_revision,
        datetime.now(timezone.utc),
        "trace",
    )
    with pytest.raises(ValueError, match="未知"):
        SpeechPerformancePlanner(yura_revision_1_policy()).plan_snapshot(
            snapshot, "performance-plan", datetime.now(timezone.utc)
        )


def test_confirmed_style_and_expression_change_only_performance_intent() -> None:
    utterance = _utterance(text="意味を変えない")
    voice = CharacterVoiceStyleProfile(
        "yura",
        1,
        1,
        (
            RuntimeCharacterFacet(
                "baseline_softness", RuntimeAvailability.CONFIRMED, "柔らかく親しみがある"
            ),
            RuntimeCharacterFacet(
                "calmness_tendency", RuntimeAvailability.CONFIRMED, "比較的落ち着いた基調"
            ),
        ),
    )
    expression = SpeechExpressionContext(
        "expression",
        utterance.candidate.revisions.source_context_revision,
        5,
        utterance.candidate.revisions.attention_revision,
        ("energy",),
        ((ExpressionAxis.ENERGY, 0.8),),
        (),
        datetime.now(timezone.utc),
    )
    planner = SpeechPerformancePlanner(yura_revision_1_policy())
    neutral = planner.plan("neutral", utterance, voice, None, datetime.now(timezone.utc))
    dynamic = planner.plan("dynamic", utterance, voice, expression, datetime.now(timezone.utc))
    assert neutral.global_intent != dynamic.global_intent
    assert utterance.candidate.segments[0].text == "意味を変えない"
    assert not hasattr(dynamic, "propositions")


def test_unconfirmed_voice_style_is_not_character_fact() -> None:
    utterance = _utterance()
    candidate_only = CharacterVoiceStyleProfile(
        "yura",
        1,
        1,
        (RuntimeCharacterFacet("baseline_softness", RuntimeAvailability.UNRESOLVED),),
    )
    plan = SpeechPerformancePlanner(yura_revision_1_policy()).plan(
        "performance-plan", utterance, candidate_only, None, datetime.now(timezone.utc)
    )
    assert (
        SpeechPerformanceDegradationReason.CHARACTER_VOICE_STYLE_UNAVAILABLE
        in plan.degradation_reasons
    )
