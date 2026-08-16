from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from threading import Lock

from app.domain.contracts.common import utc_instant

from .contracts import (
    AttentionFocusState,
    AttentionPriority,
    AttentionSource,
    AttentionTransition,
    AttentionTransitionOperation,
    ExecutiveTriggerEligibility,
)


class AttentionTurnStore:
    def __init__(self, attention_budget: int = 8) -> None:
        self._state = AttentionFocusState(
            0,
            0,
            None,
            (),
            None,
            None,
            attention_budget,
            (),
            datetime.min.replace(tzinfo=timezone.utc),
        )
        self._transition_ids: set[str] = set()
        self._lock = Lock()

    def snapshot(self) -> AttentionFocusState:
        with self._lock:
            return self._state

    def apply(
        self, source_context_revision: int, transitions: tuple[AttentionTransition, ...]
    ) -> AttentionFocusState:
        if not isinstance(transitions, (tuple, list)) or not transitions:
            raise ValueError("transitions は空でない配列でなければなりません")
        values = tuple(transitions)
        if any(not isinstance(item, AttentionTransition) for item in values) or len(
            {item.transition_id for item in values}
        ) != len(values):
            raise ValueError("transitions は一意な AttentionTransition でなければなりません")
        with self._lock:
            state = self._state
            if {item.transition_id for item in values}.intersection(self._transition_ids):
                raise ValueError("transitionは既に適用済みです")
            if any(item.expected_attention_revision != state.revision for item in values):
                raise ValueError("attention transitionはstaleです")
            if any(
                utc_instant(item.occurred_at) < utc_instant(state.updated_at) for item in values
            ):
                raise ValueError("transition時刻がcurrent stateより過去です")
            next_state = state
            for item in values:
                next_state = self._apply_one(next_state, item)
            next_state = replace(
                next_state,
                revision=state.revision + 1,
                source_context_revision=source_context_revision,
                updated_at=max(item.occurred_at for item in values),
            )
            self._state = next_state
            self._transition_ids.update(item.transition_id for item in values)
            return next_state

    def offer(self, source_context_revision: int, source: AttentionSource) -> AttentionFocusState:
        if not isinstance(source, AttentionSource):
            raise ValueError("source は AttentionSource でなければなりません")
        with self._lock:
            state = self._state
            by_ref = {item.source_ref: item for item in state.sources}
            existing = by_ref.get(source.source_ref)
            if existing is not None:
                by_ref[source.source_ref] = replace(
                    existing,
                    priority=max(existing.priority, source.priority),
                    occurred_at=source.occurred_at,
                    coalesced_count=existing.coalesced_count + source.coalesced_count,
                )
            elif len(by_ref) < state.attention_budget:
                by_ref[source.source_ref] = source
            else:
                weakest = min(by_ref.values(), key=lambda item: (item.priority, item.occurred_at))
                if source.priority <= weakest.priority:
                    return state
                del by_ref[weakest.source_ref]
                by_ref[source.source_ref] = source
            self._state = replace(
                state,
                revision=state.revision + 1,
                source_context_revision=source_context_revision,
                sources=tuple(sorted(by_ref.values(), key=lambda item: item.source_ref)),
                updated_at=max(state.updated_at, source.occurred_at),
            )
            return self._state

    def eligibility(
        self, goal_revision: int, created_at: datetime, limit: int = 1
    ) -> tuple[ExecutiveTriggerEligibility, ...]:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit は正の整数でなければなりません")
        with self._lock:
            state = self._state
            source_values = state.sources
            if state.current_turn_owner is not None or state.response_obligation is not None:
                source_values = tuple(
                    item
                    for item in source_values
                    if item.priority is not AttentionPriority.BACKGROUND
                )
            sources = sorted(
                source_values, key=lambda item: (-item.priority, item.occurred_at, item.source_ref)
            )[:limit]
            return tuple(
                ExecutiveTriggerEligibility(
                    f"attention-{state.revision}-{item.source_ref}",
                    item.source_ref,
                    item.kind,
                    item.priority,
                    state.source_context_revision,
                    goal_revision,
                    state.revision,
                    created_at,
                )
                for item in sources
            )

    @staticmethod
    def _apply_one(
        state: AttentionFocusState, transition: AttentionTransition
    ) -> AttentionFocusState:
        op = transition.operation
        if op is AttentionTransitionOperation.ACQUIRE_FOREGROUND:
            return replace(state, foreground_focus_ref=transition.target_ref)
        if op is AttentionTransitionOperation.RELEASE_FOREGROUND:
            return replace(state, foreground_focus_ref=None)
        if op is AttentionTransitionOperation.ADD_MONITOR:
            assert transition.target_ref is not None
            return replace(
                state,
                secondary_monitor_refs=state.secondary_monitor_refs + (transition.target_ref,),
            )
        if op is AttentionTransitionOperation.REMOVE_MONITOR:
            if transition.target_ref not in state.secondary_monitor_refs:
                raise ValueError("monitorが存在しません")
            return replace(
                state,
                secondary_monitor_refs=tuple(
                    item for item in state.secondary_monitor_refs if item != transition.target_ref
                ),
            )
        if op is AttentionTransitionOperation.ASSIGN_TURN:
            return replace(state, current_turn_owner=transition.value)
        if op is AttentionTransitionOperation.RELEASE_TURN:
            return replace(state, current_turn_owner=None)
        if op is AttentionTransitionOperation.SET_RESPONSE_OBLIGATION:
            return replace(state, response_obligation=transition.value)
        return replace(state, response_obligation=None)
