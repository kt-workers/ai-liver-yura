from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.activities import Activity


@dataclass(frozen=True, slots=True)
class ResolvedContextualReference:
    """会話文脈から解決された省略参照。

    特定のActivityやBody命令には依存せず、参照元の発話・構造化意味・実行情報を
    後段へ渡す。後段は能力や権限を改めて検証してから再実行する。
    """

    relation: str
    source_text: str
    source_role: str = "user"
    source_turn_id: str | None = None
    source_index: int | None = None
    resolved_from: str = "conversation_history"
    structured_input_meaning: dict[str, object] | None = None
    executed_operation: dict[str, object] | None = None
    execution_status: str | None = None
    confidence: float = 0.8
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        relation = self.relation.strip().lower()
        source_text = self.source_text.strip()
        if not relation:
            raise ValueError("relation must not be empty")
        if not source_text and self.executed_operation is None:
            raise ValueError("source_text or executed_operation is required")
        object.__setattr__(self, "relation", relation)
        object.__setattr__(self, "source_text", source_text)
        object.__setattr__(self, "source_role", self.source_role.strip().lower() or "user")
        object.__setattr__(self, "resolved_from", self.resolved_from.strip() or "unknown")
        object.__setattr__(self, "confidence", min(1.0, max(0.0, float(self.confidence))))
        object.__setattr__(
            self,
            "structured_input_meaning",
            (
                dict(self.structured_input_meaning)
                if isinstance(self.structured_input_meaning, dict)
                else None
            ),
        )
        object.__setattr__(
            self,
            "executed_operation",
            dict(self.executed_operation) if isinstance(self.executed_operation, dict) else None,
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def as_context(self) -> dict[str, object]:
        return {
            "relation": self.relation,
            "source_text": self.source_text,
            "source_role": self.source_role,
            "source_turn_id": self.source_turn_id,
            "source_index": self.source_index,
            "resolved_from": self.resolved_from,
            "structured_input_meaning": (
                dict(self.structured_input_meaning)
                if self.structured_input_meaning is not None
                else None
            ),
            "executed_operation": (
                dict(self.executed_operation)
                if self.executed_operation is not None
                else None
            ),
            "execution_status": self.execution_status,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


class ContextualReferenceResolver:
    """会話履歴から「もう一回」「さっきの続き」等の参照先を解決する。

    現段階ではrepeat関係を扱う。解決順は、入力意味解析LLMが返した解決済み参照、
    実行情報付き会話ターン、構造化意味付き会話ターン、通常の直近ユーザー発話。
    Body、発話、説明、Activityのどれを再実行するかはこのResolverでは決めない。
    """

    _REPEAT_INTENTS = {
        "repeat_previous_action",
        "repeat_previous",
        "repeat_last_action",
        "repeat_last_operation",
        "repeat_previous_response",
    }
    _REPEAT_MARKERS = (
        "もう一回",
        "もう1回",
        "もう一度",
        "同じのをもう一回",
        "同じことをもう一回",
        "さっきのをもう一回",
        "さっきの動きをもう一回",
        "repeat_previous_action",
    )
    _REFERENCE_RELATIONS = {
        "repeat",
        "repeat_previous",
        "repeat_previous_action",
        "same_as_before",
        "previous_action",
        "previous_turn",
    }
    _HISTORY_KEYS = {
        "conversation_history",
        "recent_conversation",
        "conversation_turns",
        "turn_history",
    }
    _SUCCESS_STATUSES = {
        "completed",
        "succeeded",
        "success",
        "done",
        "executed",
    }
    _FAILED_STATUSES = {
        "failed",
        "error",
        "canceled",
        "cancelled",
        "rejected",
    }

    def resolve(self, activity: Activity) -> ResolvedContextualReference | None:
        meaning = self._structured_input_meaning(activity)
        if not self._is_repeat_request(activity, meaning):
            return None

        explicit = self._explicit_reference(meaning)
        if explicit is not None:
            return explicit

        current_text = self._current_text(activity, meaning).casefold().strip()
        candidates = self._conversation_candidates(activity)
        if not candidates:
            return None

        ranked: list[tuple[int, int, ResolvedContextualReference]] = []
        for index, item in enumerate(candidates):
            candidate = self._reference_from_history_item(item, index=index)
            if candidate is None:
                continue
            normalized = candidate.source_text.casefold().strip()
            if normalized and normalized == current_text:
                continue
            if normalized and self._contains_repeat_marker(normalized):
                continue
            score = self._candidate_score(candidate)
            ranked.append((score, index, candidate))

        if not ranked:
            return None
        ranked.sort(key=lambda value: (value[0], value[1]))
        return ranked[-1][2]

    def is_repeat_request(self, activity: Activity) -> bool:
        return self._is_repeat_request(
            activity,
            self._structured_input_meaning(activity),
        )

    @classmethod
    def _explicit_reference(
        cls,
        meaning: dict[str, object] | None,
    ) -> ResolvedContextualReference | None:
        if meaning is None:
            return None
        references = meaning.get("references")
        if not isinstance(references, list):
            return None
        for reference in reversed(references):
            if not isinstance(reference, dict):
                continue
            relation = str(
                reference.get("relation")
                or reference.get("type")
                or reference.get("reference_type")
                or ""
            ).strip().lower()
            if relation not in cls._REFERENCE_RELATIONS:
                continue
            resolved_turn = reference.get("resolved_turn")
            turn = dict(resolved_turn) if isinstance(resolved_turn, dict) else {}
            source_text = cls._first_text(
                reference,
                turn,
                keys=("resolved_text", "source_text", "text", "utterance", "user_text"),
            )
            executed_operation = cls._first_dict(
                reference.get("executed_operation"),
                reference.get("resolved_operation"),
                turn.get("executed_operation"),
            )
            if not source_text and executed_operation is None:
                continue
            return ResolvedContextualReference(
                relation="repeat",
                source_text=source_text,
                source_role=str(turn.get("role") or reference.get("source_role") or "user"),
                source_turn_id=cls._optional_text(
                    turn.get("turn_id")
                    or reference.get("resolved_turn_id")
                    or reference.get("source_turn_id")
                ),
                resolved_from="structured_input_meaning",
                structured_input_meaning=cls._first_dict(
                    reference.get("structured_input_meaning"),
                    turn.get("structured_input_meaning"),
                ),
                executed_operation=executed_operation,
                execution_status=cls._optional_text(
                    reference.get("execution_status") or turn.get("execution_status")
                ),
                confidence=cls._number(reference.get("confidence"), default=0.95),
                metadata={"raw_reference": dict(reference)},
            )
        return None

    @classmethod
    def _reference_from_history_item(
        cls,
        item: dict[str, object],
        *,
        index: int,
    ) -> ResolvedContextualReference | None:
        role = str(item.get("role") or item.get("speaker") or "").strip().lower()
        if role not in {"user", "human", "counterpart"}:
            return None
        if item.get("repeatable") is False:
            return None

        source_text = cls._first_text(
            item,
            keys=("text", "user_text", "input_text", "source_text", "utterance"),
        )
        operation = cls._first_dict(
            item.get("executed_operation"),
            item.get("operation"),
            item.get("action"),
        )
        if not source_text and operation is None:
            return None

        status = cls._optional_text(
            item.get("execution_status")
            or item.get("status")
            or (
                operation.get("status")
                if isinstance(operation, dict)
                else None
            )
        )
        if status is not None and status.casefold() in cls._FAILED_STATUSES:
            return None

        return ResolvedContextualReference(
            relation="repeat",
            source_text=source_text,
            source_role=role,
            source_turn_id=cls._optional_text(
                item.get("turn_id")
                or item.get("activity_turn_id")
                or item.get("source_event_id")
            ),
            source_index=index,
            resolved_from=(
                "execution_history"
                if operation is not None
                else "conversation_history"
            ),
            structured_input_meaning=cls._first_dict(
                item.get("structured_input_meaning"),
                item.get("input_meaning"),
            ),
            executed_operation=operation,
            execution_status=status,
            confidence=0.92 if operation is not None else 0.78,
            metadata={
                key: item[key]
                for key in ("created_at", "display_name", "counterpart_id")
                if key in item
            },
        )

    @classmethod
    def _candidate_score(cls, candidate: ResolvedContextualReference) -> int:
        score = 0
        if candidate.executed_operation is not None:
            score += 100
        if candidate.execution_status is not None:
            status = candidate.execution_status.casefold()
            if status in cls._SUCCESS_STATUSES:
                score += 40
        meaning = candidate.structured_input_meaning
        if isinstance(meaning, dict):
            if str(meaning.get("expected_response") or "").casefold() == "action":
                score += 30
            score += 10
        if candidate.source_text:
            score += 1
        return score

    @classmethod
    def _is_repeat_request(
        cls,
        activity: Activity,
        meaning: dict[str, object] | None,
    ) -> bool:
        if meaning is not None:
            intent = str(meaning.get("primary_intent") or "").strip().lower()
            if intent in cls._REPEAT_INTENTS:
                return True
            references = meaning.get("references")
            if isinstance(references, list):
                for reference in references:
                    if not isinstance(reference, dict):
                        continue
                    relation = str(
                        reference.get("relation")
                        or reference.get("type")
                        or reference.get("reference_type")
                        or ""
                    ).strip().lower()
                    if relation in cls._REFERENCE_RELATIONS:
                        return True
        return cls._contains_repeat_marker(cls._current_text(activity, meaning))

    @classmethod
    def _contains_repeat_marker(cls, text: str) -> bool:
        normalized = text.casefold()
        return any(marker.casefold() in normalized for marker in cls._REPEAT_MARKERS)

    @classmethod
    def _conversation_candidates(cls, activity: Activity) -> list[dict[str, object]]:
        histories: list[list[dict[str, object]]] = []
        cls._collect_histories(activity.context, histories, depth=0)
        if not histories:
            return []

        # 同じ履歴がevent_payloadとplanner_stateの両方に含まれることがあるため重複排除する。
        result: list[dict[str, object]] = []
        seen: set[tuple[str, str, str]] = set()
        for history in histories:
            for item in history:
                role = str(item.get("role") or item.get("speaker") or "")
                text = cls._first_text(
                    item,
                    keys=("text", "user_text", "input_text", "source_text", "utterance"),
                )
                turn_id = str(
                    item.get("turn_id")
                    or item.get("activity_turn_id")
                    or item.get("source_event_id")
                    or ""
                )
                key = (role, text, turn_id)
                if key in seen:
                    continue
                seen.add(key)
                result.append(dict(item))
        return result

    @classmethod
    def _collect_histories(
        cls,
        value: object,
        histories: list[list[dict[str, object]]],
        *,
        depth: int,
    ) -> None:
        if depth > 7:
            return
        if isinstance(value, dict):
            for key, nested in value.items():
                if key in cls._HISTORY_KEYS and isinstance(nested, (list, tuple)):
                    entries = [dict(item) for item in nested if isinstance(item, dict)]
                    if entries:
                        histories.append(entries)
                    continue
                if isinstance(nested, (dict, list, tuple)):
                    cls._collect_histories(nested, histories, depth=depth + 1)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                if isinstance(nested, (dict, list, tuple)):
                    cls._collect_histories(nested, histories, depth=depth + 1)

    @classmethod
    def _structured_input_meaning(
        cls,
        activity: Activity,
    ) -> dict[str, object] | None:
        return cls._find_meaning(activity.context, depth=0)

    @classmethod
    def _find_meaning(
        cls,
        value: object,
        *,
        depth: int,
    ) -> dict[str, object] | None:
        if depth > 7 or not isinstance(value, dict):
            return None
        direct = value.get("structured_input_meaning")
        if isinstance(direct, dict):
            return dict(direct)
        for nested in value.values():
            if isinstance(nested, dict):
                found = cls._find_meaning(nested, depth=depth + 1)
                if found is not None:
                    return found
        return None

    @classmethod
    def _current_text(
        cls,
        activity: Activity,
        meaning: dict[str, object] | None,
    ) -> str:
        if meaning is not None:
            source_text = meaning.get("source_text")
            if isinstance(source_text, str) and source_text.strip():
                return source_text.strip()
        for container in (activity.context, activity.context.get("event_payload")):
            if not isinstance(container, dict):
                continue
            for key in ("text", "user_input", "input_text", "raw_text", "source_text"):
                value = container.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def _first_text(
        *values: object,
        keys: tuple[str, ...],
    ) -> str:
        for value in values:
            if not isinstance(value, dict):
                continue
            for key in keys:
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
        return ""

    @staticmethod
    def _first_dict(*values: object) -> dict[str, object] | None:
        for value in values:
            if isinstance(value, dict):
                return dict(value)
        return None

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _number(value: object, *, default: float) -> float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return default
