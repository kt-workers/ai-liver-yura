from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from app.domain.emotions import (
    EmotionAppraisal,
    EmotionCause,
    EmotionState,
    RelationalMeaning,
)
from app.domain.events import AgentEvent, AgentEventType
from app.domain.relationships import RelationshipState
from app.runtime.contact_appraisal import ContactAppraiser
from app.shared.contracts.memory import EmotionHistoryRecord


class EmotionAppraiser:
    """Eventの確定事実と構造化済み意味評価を感情変化へ変換する。"""

    STRUCTURED_APPRAISAL_KEY = "emotion_appraisal"

    def __init__(self, contact_appraiser: ContactAppraiser | None = None) -> None:
        self._contact_appraiser = contact_appraiser or ContactAppraiser()

    def appraise(
        self,
        event: AgentEvent,
        *,
        current_emotion: EmotionState | None = None,
        relationship: RelationshipState | None = None,
        recent_history: Sequence[EmotionHistoryRecord] = (),
    ) -> EmotionAppraisal:
        structured = event.payload.get(self.STRUCTURED_APPRAISAL_KEY)
        if isinstance(structured, Mapping):
            return self._apply_relational_meaning(
                self._from_mapping(structured, event),
                event=event,
                current=current_emotion or EmotionState(),
                recent_history=recent_history,
            )
        if event.event_type == AgentEventType.USER_INTERACTION:
            return self._from_mapping(
                self._interaction_values(
                    event,
                    current_emotion or EmotionState(),
                    relationship,
                    recent_history,
                ),
                event,
            )

        values = {
            AgentEventType.USER_TEXT: {
                "arousal_delta": 0.02,
                "talkativeness_delta": 0.03,
                "reason": "user_attention_received",
                "cause_summary": "ユーザーから注意を向けられた",
            },
            AgentEventType.USER_SPEECH: {
                "arousal_delta": 0.03,
                "talkativeness_delta": 0.03,
                "reason": "user_attention_received",
                "cause_summary": "ユーザーから声をかけられた",
            },
            AgentEventType.YOUTUBE_COMMENT: {
                "arousal_delta": 0.02,
                "talkativeness_delta": 0.02,
                "reason": "viewer_attention_received",
                "cause_summary": "視聴者からコメントを受け取った",
            },
            AgentEventType.ACTION_FAILED: {
                "anger_delta": 0.05,
                "sadness_delta": 0.04,
                "discomfort_delta": 0.10,
                "pressure_delta": 0.04,
                "arousal_delta": 0.08,
                "valence_delta": -0.08,
                "talkativeness_delta": -0.02,
                "reason": "action_failed",
                "cause_summary": "実行しようとした行動が失敗した",
            },
            AgentEventType.STREAM_STARTED: {
                "joy_delta": 0.05,
                "surprise_delta": 0.03,
                "arousal_delta": 0.05,
                "valence_delta": 0.03,
                "talkativeness_delta": 0.02,
                "reason": "stream_started",
                "cause_summary": "配信が開始された",
            },
            AgentEventType.STREAM_ENDED: {
                "sadness_delta": 0.03,
                "arousal_delta": -0.04,
                "talkativeness_delta": -0.02,
                "reason": "stream_ended",
                "cause_summary": "配信が終了した",
            },
        }.get(event.event_type)
        if values is None:
            return EmotionAppraisal(source_event_id=event.event_id)
        return self._from_mapping(values, event)

    def _interaction_values(
        self,
        event: AgentEvent,
        current: EmotionState,
        relationship: RelationshipState | None,
        recent_history: Sequence[EmotionHistoryRecord],
    ) -> Mapping[str, object]:
        region = str(event.payload.get("contact_region") or "center")
        contact = self._contact_appraiser.appraise(
            event,
            current=current,
            relationship=relationship,
            recent_history=recent_history,
        )
        surprise = max(0.005, 0.04 * (1.0 - contact.overstimulation * 0.65))
        meaning_values: dict[str, dict[str, object]] = {
            "comforting": {
                "joy_delta": 0.045,
                "amusement_delta": 0.01,
                "surprise_delta": surprise * 0.4,
                "discomfort_delta": -min(0.08, current.reactive.discomfort),
                "pressure_delta": -min(
                    0.07,
                    current.reactive.emotional_pressure,
                ),
                "arousal_delta": (0.5 - current.arousal) * 0.18 + 0.005,
                "valence_delta": 0.055,
                "talkativeness_delta": 0.005,
                "reason": "contact_comfort_received",
                "cause_summary": "信頼する相手との触れ合いに安心した",
            },
            "affectionate": {
                "joy_delta": 0.035,
                "amusement_delta": 0.02,
                "surprise_delta": surprise * 0.65,
                "discomfort_delta": -min(0.04, current.reactive.discomfort),
                "pressure_delta": -min(
                    0.035,
                    current.reactive.emotional_pressure,
                ),
                "arousal_delta": 0.015,
                "valence_delta": 0.04,
                "talkativeness_delta": 0.01,
                "reason": "contact_affection_received",
                "cause_summary": "触れ合いに親しさを感じた",
            },
            "playful": {
                "amusement_delta": 0.04,
                "surprise_delta": surprise,
                "arousal_delta": 0.025,
                "valence_delta": 0.025,
                "talkativeness_delta": 0.01,
                "reason": "contact_playful_received",
                "cause_summary": "触れ合いを軽いじゃれ合いとして受け取った",
            },
            "ambiguous": {
                "surprise_delta": surprise,
                "arousal_delta": 0.015,
                "reason": "contact_ambiguous_received",
                "cause_summary": "触れられた意図を測りかねた",
            },
            "guarded": {
                "pressure_delta": 0.02,
                "arousal_delta": 0.005,
                "valence_delta": -0.005,
                "talkativeness_delta": -0.005,
                "reason": "contact_guarded_received",
                "cause_summary": "気持ちに余裕がなく、触れ合いに身構えた",
            },
            "overstimulating": {
                "discomfort_delta": 0.025 + contact.overstimulation * 0.05,
                "pressure_delta": 0.015 + contact.overstimulation * 0.025,
                "arousal_delta": 0.02,
                "valence_delta": -0.02 - contact.overstimulation * 0.025,
                "talkativeness_delta": -0.01,
                "reason": "contact_overstimulating",
                "cause_summary": "触れ合いを少し負担に感じた",
            },
            "boundary_requested": {
                "discomfort_delta": 0.05,
                "pressure_delta": 0.045,
                "arousal_delta": 0.025,
                "valence_delta": -0.04,
                "talkativeness_delta": -0.025,
                "reason": "contact_boundary_requested",
                "cause_summary": "触れ続けられて、やめてほしいと感じた",
            },
            "boundary_guarded": {
                "discomfort_delta": 0.0,
                "pressure_delta": 0.02,
                "arousal_delta": 0.005,
                "valence_delta": -0.008,
                "talkativeness_delta": -0.005,
                "reason": "contact_boundary_guarded",
                "cause_summary": "境界を伝えた後で、まだ触れ合いに身構えた",
            },
            "boundary_ignored": {
                "anger_delta": min(
                    0.10,
                    max(0, contact.boundary_violation_count - 1) * 0.035,
                ),
                "discomfort_delta": 0.04,
                "pressure_delta": min(
                    0.10,
                    0.055 + contact.boundary_violation_count * 0.012,
                ),
                "arousal_delta": 0.035,
                "valence_delta": -0.05,
                "talkativeness_delta": -0.03,
                "reason": "contact_boundary_ignored",
                "cause_summary": "やめてほしいという境界を無視された",
            },
        }
        values = meaning_values[contact.meaning]
        if event.payload.get("continuous_contact"):
            interval_ms = event.payload.get("contact_sample_interval_ms")
            interval = (
                float(interval_ms)
                if isinstance(interval_ms, (int, float)) and not isinstance(interval_ms, bool)
                else 0.0
            )
            sampling_weight = (
                0.35
                if event.payload.get("contact_phase") == "start"
                else max(0.05, min(0.35, interval / 750.0))
            )
            for key, value in tuple(values.items()):
                if (
                    key.endswith("_delta")
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                ):
                    values[key] = float(value) * sampling_weight
        values["cause"] = {
            "category": values["reason"],
            "summary": values["cause_summary"],
            "target": region,
        }
        return values

    def _apply_relational_meaning(
        self,
        appraisal: EmotionAppraisal,
        *,
        event: AgentEvent,
        current: EmotionState,
        recent_history: Sequence[EmotionHistoryRecord],
    ) -> EmotionAppraisal:
        if appraisal.relational_meaning != RelationalMeaning.REPAIR_ATTEMPT:
            return appraisal
        cutoff = event.occurred_at.timestamp() - 300.0
        latest_boundary = next(
            (
                item
                for item in reversed(recent_history)
                if (
                    item.reason
                    in {
                        "contact_boundary_requested",
                        "contact_boundary_guarded",
                        "contact_boundary_ignored",
                    }
                    and item.recorded_at.timestamp() >= cutoff
                )
            ),
            None,
        )
        if latest_boundary is None:
            return appraisal
        latest_repair = next(
            (
                item
                for item in reversed(recent_history)
                if item.relational_meaning == RelationalMeaning.REPAIR_ATTEMPT.value
            ),
            None,
        )
        if latest_repair is not None and latest_repair.recorded_at >= latest_boundary.recorded_at:
            return appraisal
        return replace(
            appraisal,
            anger_delta=-min(0.25, current.reactive.anger),
            discomfort_delta=-min(0.22, current.reactive.discomfort),
            pressure_delta=-min(
                0.28,
                current.reactive.emotional_pressure,
            ),
            arousal_delta=-min(0.12, max(0.0, current.arousal - 0.5)),
            valence_delta=max(0.08, appraisal.valence_delta),
            talkativeness_delta=max(0.04, appraisal.talkativeness_delta),
            reason="contact_repair_received",
            cause=EmotionCause(
                category="contact_repair_received",
                summary="関係を修復しようとする働きかけを受け、緊張が少しほどけた",
                target=latest_boundary.target_id,
                source_event_id=event.event_id,
            ),
        )

    def _from_mapping(self, values: Mapping[str, object], event: AgentEvent) -> EmotionAppraisal:
        reason = self._text(values.get("reason"), "structured_appraisal")
        cause_value = values.get("cause")
        cause_mapping = cause_value if isinstance(cause_value, Mapping) else values
        cause = EmotionCause(
            category=self._text(cause_mapping.get("category"), reason),
            summary=self._text(cause_mapping.get("summary"), "")
            or self._text(cause_mapping.get("cause_summary"), ""),
            target=self._optional_text(
                cause_mapping.get("target") or cause_mapping.get("target_id")
            ),
            source_event_id=event.event_id,
        )
        return EmotionAppraisal(
            joy_delta=self._number(values.get("joy_delta")),
            amusement_delta=self._number(values.get("amusement_delta")),
            anger_delta=self._number(values.get("anger_delta")),
            sadness_delta=self._number(values.get("sadness_delta")),
            fear_delta=self._number(values.get("fear_delta")),
            surprise_delta=self._number(values.get("surprise_delta")),
            discomfort_delta=self._number(values.get("discomfort_delta")),
            pressure_delta=self._number(values.get("pressure_delta")),
            arousal_delta=self._number(values.get("arousal_delta")),
            valence_delta=self._number(values.get("valence_delta")),
            talkativeness_delta=self._number(values.get("talkativeness_delta")),
            reason=reason,
            cause=cause,
            relational_meaning=self._relational_meaning(values.get("relational_meaning")),
            confidence=self._bounded_number(values.get("confidence"), default=1.0),
            source_event_id=event.event_id,
        )

    @staticmethod
    def _number(value: object, default: float = 0.0) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return default

    @classmethod
    def _bounded_number(cls, value: object, *, default: float) -> float:
        return max(0.0, min(1.0, cls._number(value, default)))

    @staticmethod
    def _relational_meaning(value: object) -> RelationalMeaning:
        try:
            return RelationalMeaning(str(value or RelationalMeaning.NONE.value))
        except ValueError:
            return RelationalMeaning.NONE

    @staticmethod
    def _text(value: object, default: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default

    @classmethod
    def _optional_text(cls, value: object) -> str | None:
        text = cls._text(value, "")
        return text or None
