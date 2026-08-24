from __future__ import annotations

from datetime import datetime

from app.domain.appraisal import InternalStateSnapshot
from app.domain.character import RuntimeAvailability
from app.domain.character.contracts import CharacterVoiceStyleProfile
from app.domain.character_language import (
    CharacterUtterance,
    LinguisticBoundary,
    LinguisticEmphasis,
    LinguisticHesitation,
)

from .contracts import (
    ExpressionAxis,
    NeutralFallbackPolicy,
    PerformanceAxis,
    PerformanceIntentDelta,
    PerformanceIntentVector,
    SpeechExpressionContext,
    SpeechPerformanceContextSnapshot,
    SpeechPerformanceDegradationReason,
    SpeechPerformancePlan,
    SpeechPerformanceProjectionPolicy,
    SpeechPerformanceSegment,
    VoiceStyleDisposition,
)


def project_expression(
    context_id: str,
    state: InternalStateSnapshot,
    policy: SpeechPerformanceProjectionPolicy,
) -> SpeechExpressionContext:
    values: dict[str, float] = {}
    diagnostics: list[str] = []
    for facet in state.facets:
        matches = [
            rule
            for rule in policy.state_rules
            if rule.facet_kind is facet.ref.kind
            and (rule.state_key is None or rule.state_key == facet.ref.state_key)
        ]
        if not matches:
            diagnostics.append(f"unmapped_state:{facet.ref.kind.value}")
            continue
        for rule in matches:
            source = facet.current if rule.component.value == "current" else facet.last_delta
            if rule.transform.value == "magnitude":
                source = abs(source)
            elif rule.transform.value == "positive_only":
                source = max(0.0, source)
            elif rule.transform.value == "negative_magnitude":
                source = -abs(source)
            for axis, weight in rule.expression_delta:
                values[axis.value] = max(
                    -1.0,
                    min(1.0, values.get(axis.value, 0.0) + source * facet.confidence * weight),
                )
    return SpeechExpressionContext(
        expression_context_id=context_id,
        source_context_revision=state.source_context_revision,
        internal_state_revision=state.revision,
        attention_revision=None,
        source_refs=tuple(facet.ref.state_key for facet in state.facets),
        axes=tuple((ExpressionAxis(name), value) for name, value in values.items()),
        diagnostics=tuple(diagnostics),
        updated_at=state.updated_at,
    )


def _apply(
    intent: PerformanceIntentVector, delta: PerformanceIntentDelta
) -> PerformanceIntentVector:
    changes = dict(delta.values)
    return PerformanceIntentVector(
        tuple(
            (axis, max(-1.0, min(1.0, intent.get(axis) + changes.get(axis, 0.0))))
            for axis in PerformanceAxis
        )
    )


class SpeechPerformancePlanner:
    def __init__(self, policy: SpeechPerformanceProjectionPolicy) -> None:
        self._policy = policy

    def plan(
        self,
        performance_plan_id: str,
        utterance: CharacterUtterance,
        voice_style: CharacterVoiceStyleProfile | None,
        expression: SpeechExpressionContext | None,
        created_at: datetime,
    ) -> SpeechPerformancePlan:
        snapshot = SpeechPerformanceContextSnapshot(
            performance_request_id=performance_plan_id,
            utterance=utterance,
            voice_style=voice_style,
            expression=expression,
            performance_constraints=(),
            source_context_revision=utterance.candidate.revisions.source_context_revision,
            goal_revision=utterance.candidate.revisions.goal_revision,
            attention_revision=utterance.candidate.revisions.attention_revision,
            captured_at=created_at,
            trace_id=performance_plan_id,
        )
        return self.plan_snapshot(snapshot, performance_plan_id, created_at)

    def plan_snapshot(
        self,
        snapshot: SpeechPerformanceContextSnapshot,
        performance_plan_id: str,
        created_at: datetime,
    ) -> SpeechPerformancePlan:
        utterance = snapshot.utterance
        voice_style = snapshot.voice_style
        expression = snapshot.expression
        candidate = utterance.candidate
        if (
            candidate.character_schema_version
            not in self._policy.compatible_character_schema_versions
        ):
            raise ValueError("Character schemaがpolicyと互換ではありません")
        reasons: list[SpeechPerformanceDegradationReason] = []
        intent = PerformanceIntentVector.neutral()
        dynamic_gains: dict[str, float] = {}
        if voice_style is None:
            if self._policy.neutral_fallback_policy is NeutralFallbackPolicy.FORBID:
                raise ValueError("system neutral fallbackはpolicyで禁止されています")
            reasons += [
                SpeechPerformanceDegradationReason.CHARACTER_VOICE_STYLE_UNAVAILABLE,
                SpeechPerformanceDegradationReason.SYSTEM_NEUTRAL_FALLBACK,
            ]
        else:
            actual = (
                voice_style.character_id,
                voice_style.schema_version,
                voice_style.definition_revision,
            )
            expected = (
                candidate.character_id,
                candidate.character_schema_version,
                candidate.character_definition_revision,
            )
            if actual != expected:
                raise ValueError("Character Voice Style provenanceがutteranceと一致しません")
            confirmed_facets = tuple(
                facet
                for facet in voice_style.facets
                if facet.availability is RuntimeAvailability.CONFIRMED
            )
            if not confirmed_facets:
                if self._policy.neutral_fallback_policy is NeutralFallbackPolicy.FORBID:
                    raise ValueError("system neutral fallbackはpolicyで禁止されています")
                reasons += [
                    SpeechPerformanceDegradationReason.CHARACTER_VOICE_STYLE_UNAVAILABLE,
                    SpeechPerformanceDegradationReason.SYSTEM_NEUTRAL_FALLBACK,
                ]
            for facet in confirmed_facets:
                rules = [
                    rule
                    for rule in self._policy.character_style_rules
                    if rule.character_id == voice_style.character_id
                    and rule.facet_id == facet.facet_id
                    and rule.expected_confirmed_value == facet.value
                ]
                if not rules:
                    reasons.append(
                        SpeechPerformanceDegradationReason.UNMAPPED_CHARACTER_VOICE_STYLE
                    )
                    continue
                style_rule = rules[0]
                if style_rule.disposition is VoiceStyleDisposition.APPLY:
                    intent = _apply(intent, style_rule.baseline_delta)
                    dynamic_gains.update(style_rule.dynamic_gains)
                elif style_rule.disposition is VoiceStyleDisposition.NO_BASELINE_ONLY_DYNAMIC:
                    dynamic_gains.update(style_rule.dynamic_gains)
        if expression is None:
            reasons.append(SpeechPerformanceDegradationReason.EXPRESSION_CONTEXT_UNAVAILABLE)
        else:
            for expression_rule in self._policy.expression_rules:
                amount = dict(expression.axes).get(expression_rule.expression_axis, 0.0)
                amount *= dynamic_gains.get(expression_rule.expression_axis, 1.0)
                intent = _apply(
                    intent,
                    PerformanceIntentDelta(
                        tuple(
                            (axis, value * amount)
                            for axis, value in expression_rule.performance_delta.values
                        )
                    ),
                )
        intent = self._apply_constraints(intent, snapshot)
        boundaries = {
            LinguisticBoundary.CONTINUE: self._policy.linguistic_rules.continue_boundary_min,
            LinguisticBoundary.PHRASE: self._policy.linguistic_rules.phrase_boundary_min,
            LinguisticBoundary.SENTENCE: self._policy.linguistic_rules.sentence_boundary_min,
        }
        emphases = {
            LinguisticEmphasis.DEEMPHASIZED: (
                self._policy.linguistic_rules.deemphasized_max_strength
            ),
            LinguisticEmphasis.NEUTRAL: 0.5,
            LinguisticEmphasis.EMPHASIZED: self._policy.linguistic_rules.emphasized_min_strength,
        }
        emphasis_bias = 0.0
        if expression is not None:
            for expression_rule in self._policy.expression_rules:
                if expression_rule.expression_axis is ExpressionAxis.EMPHASIS_BIAS:
                    emphasis_bias += (
                        dict(expression.axes).get(ExpressionAxis.EMPHASIS_BIAS, 0.0)
                        * expression_rule.segment_emphasis_gain
                    )
        segments = tuple(
            SpeechPerformanceSegment(
                f"{performance_plan_id}-{index}",
                segment.segment_id,
                boundaries[segment.boundary_after],
                boundaries[segment.boundary_after],
                0.0,
                self._segment_emphasis(segment.emphasis, emphases, emphasis_bias),
                self._policy.linguistic_rules.hesitant_min_strength
                if segment.hesitation is LinguisticHesitation.HESITANT
                else 0.0,
                PerformanceIntentDelta(()),
            )
            for index, segment in enumerate(candidate.segments, 1)
        )
        return SpeechPerformancePlan(
            performance_plan_id,
            utterance.utterance_id,
            candidate.source_decision_id,
            candidate.source_event_ids,
            candidate.revisions,
            candidate.character_id,
            candidate.character_schema_version,
            candidate.character_definition_revision,
            None if expression is None else expression.expression_context_id,
            intent,
            segments,
            bool(reasons),
            tuple(dict.fromkeys(reasons)),
            self._policy.policy_id,
            self._policy.policy_revision,
            created_at,
        )

    def _segment_emphasis(
        self,
        emphasis: LinguisticEmphasis,
        values: dict[LinguisticEmphasis, float],
        bias: float,
    ) -> float:
        result = max(0.0, min(1.0, values[emphasis] + bias))
        if emphasis is LinguisticEmphasis.EMPHASIZED:
            return max(self._policy.linguistic_rules.emphasized_min_strength, result)
        if emphasis is LinguisticEmphasis.DEEMPHASIZED:
            return min(self._policy.linguistic_rules.deemphasized_max_strength, result)
        return result

    def _apply_constraints(
        self,
        intent: PerformanceIntentVector,
        snapshot: SpeechPerformanceContextSnapshot,
    ) -> PerformanceIntentVector:
        rules = {rule.kind: rule for rule in self._policy.constraint_rules}
        for constraint in snapshot.performance_constraints:
            rule = rules.get(constraint.kind)
            if rule is None:
                raise ValueError("未知のperformance constraintは受理できません")
            if constraint.value_schema is not rule.accepted_typed_value_schema:
                raise ValueError("performance constraint value schemaが一致しません")
            delta = PerformanceIntentDelta(
                tuple((axis, constraint.value) for axis in rule.affected_axes)
            )
            if rule.combination_mode.value == "minimum":
                intent = PerformanceIntentVector(
                    tuple(
                        (axis, max(intent.get(axis), dict(delta.values).get(axis, -1.0)))
                        for axis in PerformanceAxis
                    )
                )
            else:
                intent = PerformanceIntentVector(
                    tuple(
                        (axis, min(intent.get(axis), dict(delta.values).get(axis, 1.0)))
                        for axis in PerformanceAxis
                    )
                )
        return intent
