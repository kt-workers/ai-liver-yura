from __future__ import annotations

import json
from dataclasses import asdict, replace
from typing import Any

from app.domain.activities import Activity, ActivityType
from app.domain.activity_constraints import ActivityConstraintValidator
from app.domain.behavior import (
    ActivityDefinition,
    ActivityOperation,
    BehaviorPlanningContext,
    OngoingInputDecision,
    SituationAnalysis,
)
from app.domain.morals import (
    ActivityCandidateSemanticEquivalenceEvidence,
    MoralActivityCandidatePreferenceShadow,
    SemanticEquivalenceDimension,
)
from app.ports.llm_roles import SituationEvaluationModel
from app.ports.prompt_builder import SituationPromptBuilder
from app.runtime.moral_activity_candidate_limited_activation import (
    MoralActivityCandidateLimitedActivationApplier,
)
from app.runtime.situation_semantic_equivalence_shadow_observer import (
    SituationSemanticEquivalenceShadowObserver,
)
from app.utils.trace import TraceLogger


class SituationEvaluator:
    """Eventのtyped意味だけを評価し、raw textの有限語彙再解釈を行わない。"""

    def __init__(
        self,
        model: SituationEvaluationModel,
        *,
        prompt_builder: SituationPromptBuilder,
        confidence_threshold: float = 0.85,
        max_attempts: int = 1,
        constraint_validator: ActivityConstraintValidator | None = None,
        semantic_equivalence_shadow_observer: (
            SituationSemanticEquivalenceShadowObserver | None
        ) = None,
        limited_activation_applier: (
            MoralActivityCandidateLimitedActivationApplier | None
        ) = None,
    ) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError(
                "confidence_threshold は0.0以上1.0以下で指定してください。"
            )
        if max_attempts < 1:
            raise ValueError("max_attempts は1以上で指定してください。")
        self._model = model
        self._confidence_threshold = confidence_threshold
        self._max_attempts = max_attempts
        self._prompt_builder = prompt_builder
        self._constraint_validator = (
            constraint_validator or ActivityConstraintValidator()
        )
        self._semantic_equivalence_shadow_observer = (
            semantic_equivalence_shadow_observer
            or SituationSemanticEquivalenceShadowObserver()
        )
        self._limited_activation_applier = (
            limited_activation_applier
            or MoralActivityCandidateLimitedActivationApplier()
        )
        self._trace_logger = TraceLogger()

    async def evaluate(self, context: BehaviorPlanningContext) -> SituationAnalysis:
        self._trace_logger.debug(
            "situation_evaluator:evaluation_started",
            source_event_id=context.source_event_id,
            candidate_activity_types=[
                item.activity_type for item in context.activity_definitions
            ],
            ongoing_activity_type=context.ongoing_activity_type,
        )
        definitions = self._candidate_definitions(context)
        semantic = await self._evaluate_with_llm(
            replace(
                context,
                request_kind=None,
                activity_definitions=definitions,
            )
        )
        if semantic is not None:
            return semantic

        if context.event_type == "user_text":
            if (
                context.ongoing_activity is not None
                or context.ongoing_activity_type is not None
                or context.active_activity_definition is not None
            ):
                return SituationAnalysis(
                    activity_candidate=None,
                    operation=None,
                    goal="進行中Activityに対するユーザー意図を再確認する",
                    confidence=0.0,
                    reason="ongoing_input_semantics_unresolved",
                    evaluator_type="semantic_unresolved",
                    ongoing_input_decision=OngoingInputDecision.ASK_CONFIRMATION,
                )
            return SituationAnalysis(
                activity_candidate=None,
                operation=ActivityOperation.DISCUSS,
                goal="ユーザー入力の意味を再確認する",
                confidence=0.0,
                reason="user_input_semantics_unresolved",
                evaluator_type="semantic_unresolved",
            )

        return SituationAnalysis(
            activity_candidate=(
                definitions[0].activity_type if len(definitions) == 1 else None
            ),
            operation=ActivityOperation.START,
            goal="現在状態に応じたActivityを開始する",
            confidence=0.0,
            reason="system_event_evaluation_failed",
            evaluator_type="fallback",
        )

    async def _evaluate_with_llm(
        self, context: BehaviorPlanningContext
    ) -> SituationAnalysis | None:
        prompt = self._prompt_builder.build(context)
        self._trace_logger.debug(
            "behavior_planner:llm_candidates",
            source_event_id=context.source_event_id,
            candidates=[item.activity_type for item in context.activity_definitions],
        )
        for attempt in range(self._max_attempts):
            activity = Activity(
                activity_type=ActivityType.BEHAVIOR_PLANNING,
                goal="ユーザー入力の状況と意味を構造化する",
                context={
                    "plugin_prompt_override": prompt,
                    "llm_role": "situation_evaluator",
                    "event_id": context.source_event_id,
                    "user_input": context.user_text,
                    "planner_state": {
                        "ongoing_activity_type": context.ongoing_activity_type,
                        "ongoing_activity": (
                            asdict(context.ongoing_activity)
                            if context.ongoing_activity is not None
                            else None
                        ),
                        "active_activity_definition": (
                            {
                                "activity_type": context.active_activity_definition.activity_type,
                                "supported_operations": [
                                    operation.value
                                    for operation in (
                                        context.active_activity_definition.supported_operations
                                    )
                                ],
                            }
                            if context.active_activity_definition is not None
                            else None
                        ),
                        "drive": context.drive,
                        "emotion": context.emotion,
                        "last_activity_result": context.last_activity_result,
                    },
                    "constraints": [
                        "発話本文を生成しない",
                        "Capabilityの可用性や実行成功を判断しない",
                        "候補外のActivityを生成しない",
                        "raw user textをRuntime側の有限語彙規則で再解釈しない",
                    ],
                    "trace_context": context.trace_context,
                    "llm_attempt": attempt + 1,
                },
                source_event_id=context.source_event_id,
            )
            try:
                raw = await self._model.evaluate(activity)
            except Exception as error:
                self._trace_logger.warning(
                    "situation_evaluator:model_failed",
                    error_type=type(error).__name__,
                    attempt=attempt,
                )
                return None
            analysis = self.parse(
                raw,
                context.activity_definitions,
                intent_flags_can_cancel_activity=context.event_type
                != "curiosity_peak",
                semantic_evidence_source="situation_evaluator_llm",
                semantic_evidence_id=(
                    f"{context.source_event_id}:semantic-equivalence:{attempt + 1}"
                ),
            )
            self._trace_logger.llm_response(
                purpose="behavior_planning",
                provider="situation_evaluator",
                model=type(self._model).__name__,
                activity_id=activity.activity_id,
                raw_response=raw,
                parsed_response=(
                    {
                        **asdict(analysis),
                        "activity_type": analysis.activity_candidate or "conversation",
                    }
                    if analysis is not None
                    else None
                ),
                fallback_used=analysis is None,
                stage="parsed" if analysis is not None else "schema_validation_failed",
                llm_role="situation_evaluator",
                service="situation_evaluator",
                trace_id=(
                    context.trace_context.trace_id if context.trace_context else None
                ),
                parent_trace_id=(
                    context.trace_context.parent_trace_id
                    if context.trace_context
                    else None
                ),
                source_event_id=context.source_event_id,
                activity_turn_id=(
                    context.trace_context.activity_turn_id
                    if context.trace_context
                    else None
                ),
                attempt=attempt + 1,
            )
            if analysis is None:
                continue
            if analysis.confidence < self._confidence_threshold:
                if analysis.semantic_equivalence_evidence is not None:
                    self._trace_logger.debug(
                        "situation_evaluator:semantic_equivalence_evidence_discarded",
                        source_event_id=context.source_event_id,
                        evidence_id=(
                            analysis.semantic_equivalence_evidence.evidence_id
                        ),
                        reason="semantic_confidence_below_threshold",
                    )
                return replace(
                    analysis,
                    reason="semantic_confidence_below_threshold",
                    semantic_equivalence_evidence=None,
                )
            shadow = self._observe_semantic_equivalence(context, analysis)
            analysis, _ = self._limited_activation_applier.apply(
                context,
                analysis,
                shadow,
            )
            return analysis
        return None

    def parse(
        self,
        raw: str,
        definitions: tuple[ActivityDefinition, ...] = (),
        *,
        intent_flags_can_cancel_activity: bool = True,
        semantic_evidence_source: str | None = None,
        semantic_evidence_id: str | None = None,
    ) -> SituationAnalysis | None:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) < 3 or lines[-1].strip() != "```":
                return None
            text = "\n".join(lines[1:-1]).strip()
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            payload: Any = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        required = {
            "activity_type",
            "operation",
            "goal",
            "constraints",
            "speech_act",
            "negated",
            "hypothetical",
            "past_reference",
            "knowledge_question",
            "confidence",
            "reason",
        }
        if not isinstance(payload, dict) or not required.issubset(payload):
            return None
        try:
            operation = (
                ActivityOperation(str(payload["operation"]))
                if payload["operation"] is not None
                else None
            )
            speech_act = SpeechAct(str(payload["speech_act"]))
            ongoing_input_decision = (
                OngoingInputDecision(str(payload["ongoing_input_decision"]))
                if payload.get("ongoing_input_decision") is not None
                else None
            )
        except ValueError:
            return None
        conversation_phase_value = payload.get("conversation_phase")
        conversation_phase = (
            str(conversation_phase_value)
            if conversation_phase_value is not None
            else None
        )
        if conversation_phase not in {
            None,
            "greeting",
            "opening",
            "active",
            "winding_down",
        }:
            return None
        initiative_value = payload.get("initiative_level")
        if initiative_value is None:
            initiative_level = None
        elif (
            isinstance(initiative_value, (int, float))
            and not isinstance(initiative_value, bool)
            and 0.0 <= float(initiative_value) <= 1.0
        ):
            initiative_level = float(initiative_value)
        else:
            return None
        constraints = payload["constraints"]
        confidence = payload["confidence"]
        flags = (
            "negated",
            "hypothetical",
            "past_reference",
            "knowledge_question",
        )
        if not isinstance(constraints, dict) or not all(
            isinstance(key, str) for key in constraints
        ):
            return None
        if not all(isinstance(payload[field], bool) for field in flags):
            return None
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            return None
        if not 0.0 <= float(confidence) <= 1.0:
            return None
        activity_type = str(payload["activity_type"])
        flags_force_conversation = intent_flags_can_cancel_activity and any(
            bool(payload[field]) for field in flags
        )
        candidate = (
            None
            if activity_type == "conversation" or flags_force_conversation
            else activity_type
        )
        definition = next(
            (item for item in definitions if item.activity_type == candidate), None
        )
        if candidate is not None and definition is None:
            return None
        if definition is not None and operation not in definition.supported_operations:
            return None
        if flags_force_conversation:
            if bool(payload["negated"]) or bool(payload["past_reference"]):
                operation = None
            elif operation not in {
                ActivityOperation.EXPLAIN,
                ActivityOperation.DISCUSS,
            }:
                operation = ActivityOperation.DISCUSS
        elif candidate is None and operation not in {
            None,
            ActivityOperation.EXPLAIN,
            ActivityOperation.DISCUSS,
        }:
            return None
        validation = (
            self._constraint_validator.validate(
                constraints,
                definition.constraints_schema,
                schema_version=definition.constraints_schema_version,
            )
            if definition is not None
            else None
        )
        if validation is not None:
            self._trace_logger.debug(
                "activity_constraints:validated",
                activity_type=(
                    definition.activity_type if definition is not None else None
                ),
                validation_stage="situation_analysis",
                source="llm",
                schema_version=validation.schema_version,
                valid=validation.valid,
                normalized_constraints=validation.normalized_constraints,
                error_paths=[error.path for error in validation.errors],
                error_codes=[error.code for error in validation.errors],
                applied_defaults=validation.applied_defaults,
                warnings=list(validation.warnings),
            )
        semantic_equivalence_evidence = self._parse_semantic_equivalence_evidence(
            payload,
            definitions,
            source=semantic_evidence_source,
            evidence_id=semantic_evidence_id,
        )
        return SituationAnalysis(
            activity_candidate=candidate,
            operation=operation,
            goal=str(payload["goal"]),
            constraints=(
                dict(validation.normalized_constraints)
                if validation is not None
                else dict(constraints)
            ),
            speech_act=speech_act,
            conversation_phase=conversation_phase,
            initiative_level=initiative_level,
            negated=bool(payload["negated"]),
            hypothetical=bool(payload["hypothetical"]),
            past_reference=bool(payload["past_reference"]),
            knowledge_question=bool(payload["knowledge_question"]),
            confidence=float(confidence),
            reason=str(payload["reason"]),
            evaluator_type="llm",
            ongoing_input_decision=ongoing_input_decision,
            constraint_errors=validation.errors if validation is not None else (),
            constraints_schema_version=(
                validation.schema_version if validation is not None else None
            ),
            semantic_equivalence_evidence=semantic_equivalence_evidence,
        )

    @staticmethod
    def _parse_semantic_equivalence_evidence(
        payload: dict[str, object],
        definitions: tuple[ActivityDefinition, ...],
        *,
        source: str | None,
        evidence_id: str | None,
    ) -> ActivityCandidateSemanticEquivalenceEvidence | None:
        normalized_source = source.strip() if isinstance(source, str) else ""
        normalized_evidence_id = (
            evidence_id.strip() if isinstance(evidence_id, str) else ""
        )
        if not normalized_source or not normalized_evidence_id:
            return None
        raw = payload.get("semantic_equivalence")
        if not isinstance(raw, dict):
            return None
        raw_group = raw.get("candidate_group")
        if not isinstance(raw_group, (list, tuple)) or not all(
            isinstance(activity_type, str) for activity_type in raw_group
        ):
            return None
        candidate_group = tuple(
            activity_type.strip()
            for activity_type in raw_group
            if activity_type.strip()
        )
        known_activity_types = {
            definition.activity_type for definition in definitions
        }
        if any(
            activity_type not in known_activity_types
            for activity_type in candidate_group
        ):
            return None
        try:
            intent = SemanticEquivalenceDimension(str(raw["intent"]))
            operation = SemanticEquivalenceDimension(str(raw["operation"]))
            goal = SemanticEquivalenceDimension(str(raw["goal"]))
        except (KeyError, ValueError):
            return None
        raw_reasons = raw.get("reasons", [])
        if not isinstance(raw_reasons, (list, tuple)) or not all(
            isinstance(reason, str) for reason in raw_reasons
        ):
            return None
        reasons = tuple(
            reason.strip()[:120]
            for reason in raw_reasons[:8]
            if reason.strip()
        )
        try:
            return ActivityCandidateSemanticEquivalenceEvidence(
                candidate_group=candidate_group,
                intent=intent,
                operation=operation,
                goal=goal,
                source=normalized_source,
                evidence_id=normalized_evidence_id,
                reasons=reasons,
            )
        except ValueError:
            return None

    def _observe_semantic_equivalence(
        self,
        context: BehaviorPlanningContext,
        analysis: SituationAnalysis,
    ) -> MoralActivityCandidatePreferenceShadow | None:
        if analysis.semantic_equivalence_evidence is None:
            return None
        try:
            return self._semantic_equivalence_shadow_observer.observe(
                context,
                analysis,
            )
        except Exception as error:
            self._trace_logger.warning(
                "situation_evaluator:semantic_equivalence_shadow_failed",
                source_event_id=context.source_event_id,
                evidence_id=analysis.semantic_equivalence_evidence.evidence_id,
                error_type=type(error).__name__,
            )
            return None

    @staticmethod
    def _candidate_definitions(
        context: BehaviorPlanningContext,
    ) -> tuple[ActivityDefinition, ...]:
        definitions = list(context.activity_definitions)
        active = context.active_activity_definition
        if active is not None and not any(
            item.activity_type == active.activity_type for item in definitions
        ):
            definitions.insert(0, active)
        return tuple(definitions)
