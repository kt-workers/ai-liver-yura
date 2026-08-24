from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.domain.appraisal import FacetRef, InternalStateFacet, InternalStateSnapshot, StateFacetKind
from app.domain.character import RuntimeAvailability
from app.domain.character.contracts import (
    CharacterLanguageProfile,
    CharacterVoiceStyleProfile,
    RuntimeCharacterFacet,
)
from app.domain.character_language import (
    CharacterLanguageAuthority,
    CharacterLanguageCommitState,
    CharacterLanguageContextSnapshot,
    CharacterUtterance,
    CharacterUtteranceCandidate,
    CharacterUtteranceSegment,
    LinguisticBoundary,
    LinguisticEmphasis,
    LinguisticHesitation,
)
from app.domain.llm import LLMInterruptibility, LLMPriority
from app.domain.speech_performance import (
    ConstraintValueSchema,
    ExpressionAxis,
    LinguisticPerformancePolicy,
    NeutralFallbackPolicy,
    PerformanceAxis,
    PerformanceIntentDelta,
    PerformanceIntentVector,
    PitchAnchor,
    SpeechExpressionContext,
    SpeechPerformanceConstraintView,
    SpeechPerformanceContextSnapshot,
    SpeechPerformanceDegradationReason,
    SpeechPerformanceSegment,
    validate_plan_segments,
)
from app.domain.speech_performance.planner import SpeechPerformancePlanner, project_expression
from app.domain.speech_performance.policy import yura_revision_1_policy
from tests.domain.semantic_verification.test_semantic_verification import (
    NOW,
    REVISIONS,
    _semantic_plan,
    _utterance,
)


def _utterance_with_linguistics(
    *, emphasis: LinguisticEmphasis, hesitation: LinguisticHesitation
) -> CharacterUtterance:
    plan = _semantic_plan()
    profile = CharacterLanguageProfile("yura", 1, 1, ())
    context = CharacterLanguageContextSnapshot(
        "performance-character-request",
        plan,
        profile,
        (),
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        NOW,
        "performance-character-trace",
    )
    source = plan.candidate
    candidate = CharacterUtteranceCandidate(
        "performance-utterance-candidate",
        context.request_id,
        plan.plan_id,
        source.decision_id,
        source.intent_id,
        source.source_event_ids,
        source.revisions,
        profile.character_id,
        profile.schema_version,
        profile.definition_revision,
        (
            CharacterUtteranceSegment(
                "performance-segment",
                "そのままの発話です。",
                ("prop-required",),
                LinguisticBoundary.SENTENCE,
                emphasis,
                hesitation,
            ),
        ),
        0,
        0,
        NOW + timedelta(seconds=1),
    )
    return CharacterLanguageAuthority().commit(
        candidate,
        context,
        current=CharacterLanguageCommitState(REVISIONS, plan, True, profile, ()),
        utterance_id="performance-utterance",
        committed_at=NOW + timedelta(seconds=1),
    )


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
            "yura-speech-performance",
            1,
        )


def test_unknown_constraint_is_fail_closed() -> None:
    utterance = _utterance()
    snapshot = SpeechPerformanceContextSnapshot(
        "request",
        utterance,
        None,
        None,
        (
            SpeechPerformanceConstraintView(
                "constraint",
                "test",
                "ref",
                1,
                "unknown",
                ConstraintValueSchema.NORMALIZED_SCALAR,
                0.1,
            ),
        ),
        utterance.candidate.revisions.source_context_revision,
        utterance.candidate.revisions.goal_revision,
        utterance.candidate.revisions.attention_revision,
        datetime.now(timezone.utc),
        "trace",
        "yura-speech-performance",
        1,
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


def test_policy_compatibility_revision_and_explicit_fallback_are_observable() -> None:
    policy = yura_revision_1_policy()
    assert policy.compatible_character_schema_versions == (1,)
    assert policy.neutral_fallback_policy is NeutralFallbackPolicy.ALLOW_SYSTEM_NEUTRAL
    assert policy.policy_revision == 1
    utterance = _utterance()
    incompatible = replace(policy, compatible_character_schema_versions=(2,))
    with pytest.raises(ValueError, match="互換"):
        SpeechPerformancePlanner(incompatible).plan(
            "performance-plan", utterance, None, None, datetime.now(timezone.utc)
        )
    no_fallback = replace(policy, neutral_fallback_policy=NeutralFallbackPolicy.FORBID)
    with pytest.raises(ValueError, match="fallback"):
        SpeechPerformancePlanner(no_fallback).plan(
            "performance-plan", utterance, None, None, datetime.now(timezone.utc)
        )


def test_emphasis_bias_is_explicitly_projected_without_text_mutation() -> None:
    utterance = _utterance(text="変えない")
    expression = SpeechExpressionContext(
        "expression",
        utterance.candidate.revisions.source_context_revision,
        1,
        utterance.candidate.revisions.attention_revision,
        ("arousal",),
        ((ExpressionAxis.EMPHASIS_BIAS, 0.5),),
        (),
        datetime.now(timezone.utc),
    )
    plan = SpeechPerformancePlanner(yura_revision_1_policy()).plan(
        "performance-plan", utterance, None, expression, datetime.now(timezone.utc)
    )
    assert plan.segments[0].emphasis_strength == pytest.approx(0.75)
    assert utterance.candidate.segments[0].text == "変えない"


def test_invalid_policy_definition_and_constraint_schema_fail_closed() -> None:
    with pytest.raises(ValueError):
        replace(yura_revision_1_policy(), compatible_character_schema_versions=())
    utterance = _utterance()
    snapshot = SpeechPerformanceContextSnapshot(
        "request",
        utterance,
        None,
        None,
        (
            SpeechPerformanceConstraintView(
                "constraint",
                "test",
                "ref",
                1,
                "unknown",
                ConstraintValueSchema.NORMALIZED_SCALAR,
                0.1,
            ),
        ),
        utterance.candidate.revisions.source_context_revision,
        utterance.candidate.revisions.goal_revision,
        utterance.candidate.revisions.attention_revision,
        datetime.now(timezone.utc),
        "trace",
        "yura-speech-performance",
        1,
    )
    with pytest.raises(ValueError, match="未知"):
        SpeechPerformancePlanner(yura_revision_1_policy()).plan_snapshot(
            snapshot, "performance-plan", datetime.now(timezone.utc)
        )


def test_segment_mapping_rejects_unknown_and_duplicate_utterance_refs() -> None:
    utterance = _utterance()
    plan = SpeechPerformancePlanner(yura_revision_1_policy()).plan(
        "performance-plan", utterance, None, None, datetime.now(timezone.utc)
    )
    unknown = replace(plan.segments[0], utterance_segment_id="unknown-segment")
    with pytest.raises(ValueError, match="一致"):
        validate_plan_segments(utterance, replace(plan, segments=(unknown,)))
    with pytest.raises(ValueError, match="一対一"):
        replace(plan, segments=(plan.segments[0], plan.segments[0]))


def test_policy_revision_is_retained_in_performance_plan() -> None:
    utterance = _utterance()
    revised_policy = replace(yura_revision_1_policy(), policy_revision=2)
    plan = SpeechPerformancePlanner(revised_policy).plan(
        "performance-plan", utterance, None, None, datetime.now(timezone.utc)
    )
    assert plan.policy_id == revised_policy.policy_id
    assert plan.policy_revision == 2


def test_planner_has_no_verifier_or_playback_prerequisite() -> None:
    source = Path("app/domain/speech_performance/planner.py").read_text(encoding="utf-8")
    assert "semantic_verification" not in source
    assert "presentation" not in source.casefold()
    assert "playback" not in source.casefold()


def test_mixed_generation_snapshot_is_rejected_before_performance_composition() -> None:
    utterance = _utterance()
    policy = yura_revision_1_policy()
    snapshot = SpeechPerformanceContextSnapshot(
        "request",
        utterance,
        None,
        None,
        (),
        utterance.candidate.revisions.source_context_revision,
        utterance.candidate.revisions.goal_revision,
        utterance.candidate.revisions.attention_revision,
        datetime.now(timezone.utc),
        "trace",
        policy.policy_id,
        policy.policy_revision,
    )
    with pytest.raises(ValueError, match="policy generation"):
        SpeechPerformancePlanner(replace(policy, policy_revision=2)).plan_snapshot(
            snapshot, "performance-plan", datetime.now(timezone.utc)
        )
    with pytest.raises(ValueError, match="provenance"):
        SpeechPerformanceContextSnapshot(
            "request",
            utterance,
            CharacterVoiceStyleProfile("other", 1, 1, ()),
            None,
            (),
            utterance.candidate.revisions.source_context_revision,
            utterance.candidate.revisions.goal_revision,
            utterance.candidate.revisions.attention_revision,
            datetime.now(timezone.utc),
            "trace",
            policy.policy_id,
            policy.policy_revision,
        )


def test_planner_keeps_emphasized_segment_at_linguistic_minimum() -> None:
    utterance = _utterance_with_linguistics(
        emphasis=LinguisticEmphasis.EMPHASIZED,
        hesitation=LinguisticHesitation.NONE,
    )
    policy = yura_revision_1_policy()
    plan = SpeechPerformancePlanner(policy).plan(
        "performance-plan", utterance, None, None, datetime.now(timezone.utc)
    )
    assert plan.segments[0].emphasis_strength >= policy.linguistic_rules.emphasized_min_strength


def test_planner_never_inverts_deemphasized_segment_under_positive_bias() -> None:
    utterance = _utterance_with_linguistics(
        emphasis=LinguisticEmphasis.DEEMPHASIZED,
        hesitation=LinguisticHesitation.NONE,
    )
    policy = yura_revision_1_policy()
    expression = SpeechExpressionContext(
        "expression",
        utterance.candidate.revisions.source_context_revision,
        1,
        utterance.candidate.revisions.attention_revision,
        ("state",),
        ((ExpressionAxis.EMPHASIS_BIAS, 1.0),),
        (),
        datetime.now(timezone.utc),
    )
    plan = SpeechPerformancePlanner(policy).plan(
        "performance-plan", utterance, None, expression, datetime.now(timezone.utc)
    )
    assert plan.segments[0].emphasis_strength <= policy.linguistic_rules.deemphasized_max_strength


def test_planner_preserves_hesitant_text_without_filler_or_extra_segments() -> None:
    utterance = _utterance_with_linguistics(
        emphasis=LinguisticEmphasis.NEUTRAL,
        hesitation=LinguisticHesitation.HESITANT,
    )
    original_text = utterance.candidate.segments[0].text
    plan = SpeechPerformancePlanner(yura_revision_1_policy()).plan(
        "performance-plan", utterance, None, None, datetime.now(timezone.utc)
    )
    assert plan.segments[0].hesitation_strength > 0.0
    assert utterance.candidate.segments[0].text == original_text
    assert len(plan.segments) == len(utterance.candidate.segments) == 1
    assert all(filler not in original_text for filler in ("えっと", "あの"))


def test_same_text_different_confirmed_voice_style_changes_only_performance_intent() -> None:
    utterance = _utterance(text="同じ言葉")
    policy = yura_revision_1_policy()
    first_rule = policy.character_style_rules[0]
    alternate_rule = replace(
        first_rule,
        rule_id="yura-alternate-softness",
        expected_confirmed_value="硬質で張りがある",
        baseline_delta=PerformanceIntentDelta(((PerformanceAxis.ENERGY, 0.5),)),
    )
    planner = SpeechPerformancePlanner(
        replace(policy, character_style_rules=(first_rule, alternate_rule))
    )
    soft = CharacterVoiceStyleProfile(
        "yura",
        1,
        1,
        (
            RuntimeCharacterFacet(
                "baseline_softness", RuntimeAvailability.CONFIRMED, "柔らかく親しみがある"
            ),
        ),
    )
    alternate = CharacterVoiceStyleProfile(
        "yura",
        1,
        1,
        (
            RuntimeCharacterFacet(
                "baseline_softness", RuntimeAvailability.CONFIRMED, "硬質で張りがある"
            ),
        ),
    )
    soft_plan = planner.plan("soft-plan", utterance, soft, None, datetime.now(timezone.utc))
    alternate_plan = planner.plan(
        "alternate-plan", utterance, alternate, None, datetime.now(timezone.utc)
    )
    assert soft_plan.global_intent != alternate_plan.global_intent
    assert utterance.candidate.segments[0].text == "同じ言葉"
    assert soft_plan.utterance_id == alternate_plan.utterance_id == utterance.utterance_id
