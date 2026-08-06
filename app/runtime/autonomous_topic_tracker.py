from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from difflib import SequenceMatcher
from uuid import uuid4

from app.domain.autonomous_continuation import (
    AutonomousContinuationAction,
    AutonomousContinuationEvaluation,
)
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState
from app.domain.topic import InterruptedTopic, TopicLifecycleStatus
from app.runtime.causal_decision_observer import CausalDecisionObserver


class AutonomousTopicTracker:
    """自律発話の話題状態と継続指標を管理する。

    Agentの状態遷移全体から話題固有の責務を分離し、既存の評価式を
    変更せずに集約する。スレッドやI/Oには依存しない。
    """

    _QUESTION_ENDING = re.compile(
        r"(?:[？?]|ですか|ますか|でしょうか|だろうか|かな|かい)[。！!]*$"
    )

    def __init__(
        self,
        uuid_factory: Callable[[], str] | None = None,
        *,
        maximum_autonomous_turns: int = 3,
        causal_observer: CausalDecisionObserver | None = None,
    ) -> None:
        if (
            isinstance(maximum_autonomous_turns, bool)
            or not isinstance(maximum_autonomous_turns, int)
            or maximum_autonomous_turns < 1
        ):
            raise ValueError("maximum_autonomous_turnsは1以上の整数にしてください。")
        self._uuid_factory = uuid_factory or (lambda: str(uuid4()))
        self._maximum_autonomous_turns = maximum_autonomous_turns
        self._causal_observer = causal_observer or CausalDecisionObserver()
        self._topic: InterruptedTopic | None = None
        self._recent_autonomous_texts: list[str] = []

    @property
    def current_topic(self) -> InterruptedTopic | None:
        return self._topic

    @property
    def recent_autonomous_texts(self) -> tuple[str, ...]:
        return tuple(self._recent_autonomous_texts)

    @property
    def maximum_autonomous_turns(self) -> int:
        return self._maximum_autonomous_turns

    def replace(self, topic: InterruptedTopic | None) -> InterruptedTopic | None:
        self._topic = topic
        return self._topic

    def record_output(
        self,
        *,
        activity_id: str,
        text: str,
        drive: DriveState,
        emotion: EmotionState,
        context: dict[str, object] | None = None,
    ) -> InterruptedTopic:
        metrics = (context or {}).get("topic_metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}

        existing = self._topic
        same_activity = (
            existing is not None and existing.source_activity_id == activity_id
        )
        observed_interest = self._metric(
            metrics,
            "interest",
            (drive.curiosity * 0.6) + (drive.engagement * 0.4),
        )
        observed_incompleteness = self._metric(
            metrics,
            "incompleteness",
            self._estimate_incompleteness(text),
        )
        observed_exhaustion = self._metric(
            metrics,
            "exhaustion",
            self._estimate_exhaustion(text),
        )

        if same_activity and existing is not None:
            similarity = SequenceMatcher(
                None,
                self._normalize_text(existing.original_text),
                self._normalize_text(text),
            ).ratio()
            interest = self._clamp01(
                (existing.interest * 0.78)
                + (observed_interest * 0.22)
                - 0.04
                - (similarity * 0.05)
            )
            incompleteness = self._clamp01(
                (existing.incompleteness * 0.70)
                + (observed_incompleteness * 0.30)
                - 0.08
            )
            exhaustion = self._clamp01(
                existing.exhaustion
                + 0.10
                + ((1.0 - emotion.talkativeness) * 0.05)
                + ((1.0 - drive.energy) * 0.04)
                + (similarity * 0.06)
            )
            turn_count = existing.turn_count + 1
        else:
            interest = observed_interest
            incompleteness = observed_incompleteness
            exhaustion = observed_exhaustion
            turn_count = 1

        topic = InterruptedTopic(
            topic_id=(
                existing.topic_id
                if same_activity and existing is not None
                else self._uuid_factory()
            ),
            source_activity_id=activity_id,
            original_text=text,
            status=(
                existing.status
                if same_activity and existing is not None
                else TopicLifecycleStatus.ACTIVE
            ),
            importance=self._metric(
                metrics,
                "importance",
                self._estimate_importance(text),
            ),
            interest=interest,
            incompleteness=incompleteness,
            exhaustion=exhaustion,
            turn_count=turn_count,
            interrupted_at=(
                existing.interrupted_at if same_activity and existing else None
            ),
            interruption_turns=(
                existing.interruption_turns if same_activity and existing else 0
            ),
            interruption_topics=(
                existing.interruption_topics if same_activity and existing else ()
            ),
        )
        self._topic = topic
        return topic

    def evaluate_completion(
        self,
        *,
        activity_id: str,
        drive: DriveState,
        emotion: EmotionState,
    ) -> AutonomousContinuationEvaluation | None:
        """話題の継続・終了を有限な理由付きで返す。"""

        topic = self._topic
        if topic is None or topic.source_activity_id != activity_id:
            return None

        continuation_strength = (
            topic.interest * 0.35
            + topic.incompleteness * 0.35
            + emotion.talkativeness * 0.15
            + emotion.arousal * 0.05
            + drive.curiosity * 0.10
            - topic.exhaustion * 0.35
        )
        waiting_for_user = self._expects_user_response(topic.original_text)
        hard_limit_reached = topic.turn_count >= self._maximum_autonomous_turns
        if waiting_for_user:
            return self._observe(
                AutonomousContinuationEvaluation(
                    action=AutonomousContinuationAction.COMPLETE,
                    reason="user_response_expected_after_question",
                    continuation_strength=continuation_strength,
                    turn_count=topic.turn_count,
                    waiting_for_user=True,
                    hard_limit_reached=hard_limit_reached,
                )
            )
        if hard_limit_reached:
            return self._observe(
                AutonomousContinuationEvaluation(
                    action=AutonomousContinuationAction.COMPLETE,
                    reason="maximum_autonomous_turns_reached",
                    continuation_strength=continuation_strength,
                    turn_count=topic.turn_count,
                    hard_limit_reached=True,
                )
            )
        if topic.turn_count >= 2 and continuation_strength <= 0.20:
            return self._observe(
                AutonomousContinuationEvaluation(
                    action=AutonomousContinuationAction.COMPLETE,
                    reason="topic_continuation_strength_exhausted",
                    continuation_strength=continuation_strength,
                    turn_count=topic.turn_count,
                )
            )
        return self._observe(
            AutonomousContinuationEvaluation(
                action=AutonomousContinuationAction.CONTINUE,
                reason="topic_still_has_causal_continuation_strength",
                continuation_strength=continuation_strength,
                turn_count=topic.turn_count,
            )
        )

    def should_complete(
        self,
        *,
        activity_id: str,
        drive: DriveState,
        emotion: EmotionState,
    ) -> tuple[bool, float | None]:
        """既存呼出し向けCompatibility API。内部判断はevaluate_completionを使う。"""

        evaluation = self.evaluate_completion(
            activity_id=activity_id,
            drive=drive,
            emotion=emotion,
        )
        if evaluation is None:
            return False, None
        return evaluation.should_complete, evaluation.continuation_strength

    def interrupt(
        self,
        *,
        activity_id: str,
        fallback_text: str,
        now: datetime | None = None,
    ) -> InterruptedTopic:
        topic = self._topic
        if topic is None or topic.source_activity_id != activity_id:
            topic = InterruptedTopic(
                topic_id=self._uuid_factory(),
                source_activity_id=activity_id,
                original_text=fallback_text,
            )
        interrupted = topic.with_status(
            TopicLifecycleStatus.INTERRUPTED,
            interrupted_at=now or datetime.now(timezone.utc),
        )
        self._topic = interrupted
        return interrupted

    def complete(self, *, activity_id: str) -> InterruptedTopic | None:
        topic = self._topic
        if (
            topic is None
            or topic.source_activity_id != activity_id
            or topic.status
            in {TopicLifecycleStatus.INTERRUPTED, TopicLifecycleStatus.SUSPENDED}
        ):
            return topic

        completed = topic.with_status(TopicLifecycleStatus.COMPLETED)
        self._topic = completed
        self._recent_autonomous_texts = [
            *self._recent_autonomous_texts[-4:],
            topic.original_text,
        ]
        self._causal_observer.observe_autonomous_completion(
            topic_status=completed.status.value,
            reason="autonomous_topic_marked_completed",
        )
        return completed

    def add_interruption_topic(self, text: str) -> InterruptedTopic | None:
        if self._topic is not None:
            self._topic = self._topic.add_interruption_topic(text)
        return self._topic

    def _observe(
        self,
        evaluation: AutonomousContinuationEvaluation,
    ) -> AutonomousContinuationEvaluation:
        self._causal_observer.observe_autonomous_continuation(evaluation)
        return evaluation

    @classmethod
    def _expects_user_response(cls, text: str) -> bool:
        normalized = text.strip()
        return bool(normalized and cls._QUESTION_ENDING.search(normalized))

    @staticmethod
    def _metric(metrics: dict[object, object], key: str, default: float) -> float:
        value = metrics.get(key, default)
        if not isinstance(value, (int, float)):
            return max(0.0, min(1.0, default))
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _normalize_text(text: str) -> str:
        return "".join(character for character in text if not character.isspace())

    @staticmethod
    def _estimate_importance(text: str) -> float:
        important_markers = ("大事", "将来", "目標", "価値", "約束", "やってみたい")
        return 0.75 if any(marker in text for marker in important_markers) else 0.4

    @staticmethod
    def _estimate_incompleteness(text: str) -> float:
        unfinished_markers = ("まず", "一つ目", "続き", "まだ", "……", "...")
        return 0.85 if any(marker in text for marker in unfinished_markers) else 0.25

    def _estimate_exhaustion(self, text: str) -> float:
        if not self._recent_autonomous_texts:
            return 0.0
        similarity = max(
            SequenceMatcher(None, text, previous).ratio()
            for previous in self._recent_autonomous_texts
        )
        return max(0.0, min(1.0, (similarity - 0.45) / 0.45))
