from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from .contracts import (
    AttentionClaimRelation,
    AttentionCooldown,
    AttentionFocusState,
    AttentionFocusView,
    AttentionIngressOperation,
    AttentionIngressSignal,
    AttentionInterruptionDecision,
    AttentionPriority,
    AttentionSchedulingPolicy,
    AttentionSource,
    AttentionSourceKind,
    AttentionTransition,
    AttentionTransitionOperation,
    ExecutiveTriggerEligibility,
)


class AttentionTurnStore:
    """#333が所有する短時間・同期的なAttention scheduling state。"""

    def __init__(self, policy: AttentionSchedulingPolicy | None = None) -> None:
        self._policy = policy or AttentionSchedulingPolicy.production()
        self._state = AttentionFocusState(
            0,
            0,
            self._policy.policy_id,
            self._policy.policy_revision,
            None,
            None,
            (),
            None,
            None,
            (),
            0,
            None,
            0,
            None,
            0,
            (),
            datetime.min.replace(tzinfo=timezone.utc),
        )
        self._transition_ids: set[str] = set()
        self._lock = Lock()

    @property
    def policy(self) -> AttentionSchedulingPolicy:
        return self._policy

    def snapshot(self) -> AttentionFocusState:
        with self._lock:
            return self._state

    def focus_view(self) -> AttentionFocusView:
        with self._lock:
            return AttentionFocusView.from_state(self._state)

    def offer(self, signal: AttentionIngressSignal) -> AttentionFocusState:
        if not isinstance(signal, AttentionIngressSignal) or signal.operation not in {
            AttentionIngressOperation.OFFER,
            AttentionIngressOperation.REFRESH,
        }:
            raise ValueError("offerはoffer又はrefresh ingress signalだけを受理します")
        with self._lock:
            state = self._state
            self._validate_global_context(state, signal.source_context_revision)
            source_by_ref = {source.source_ref: source for source in state.sources}
            current = source_by_ref.get(signal.source_ref)
            if signal.operation is AttentionIngressOperation.OFFER and current is not None:
                raise ValueError("既知sourceにはrefresh signalが必要です")
            if signal.operation is AttentionIngressOperation.REFRESH and current is None:
                raise ValueError("未知sourceはrefreshできません")
            self._validate_lifecycle_offer_or_refresh(signal, current)
            effective = self._effective_priority(signal)
            if current is not None:
                if current.kind is not signal.source_kind:
                    raise ValueError("refreshはsource kindを変更できません")
                if signal.occurred_at < current.last_refreshed_at:
                    raise ValueError("refresh時刻を巻き戻せません")
                if signal.source_context_revision < current.source_context_revision:
                    raise ValueError("source context revisionを巻き戻せません")
                source_by_ref[signal.source_ref] = AttentionSource(
                    current.source_ref,
                    current.kind,
                    effective,
                    signal.source_context_revision,
                    current.occurred_at,
                    signal.occurred_at,
                    signal.source_revision
                    if signal.source_revision is not None
                    else current.source_revision,
                    signal.expires_at,
                    current.coalesced_count + 1,
                )
            else:
                incoming = AttentionSource(
                    signal.source_ref,
                    signal.source_kind,
                    effective,
                    signal.source_context_revision,
                    signal.occurred_at,
                    signal.occurred_at,
                    signal.source_revision,
                    signal.expires_at,
                )
                if not self._admit(source_by_ref, incoming, state):
                    return state
            self._state = self._replace(
                state,
                signal.source_context_revision,
                signal.occurred_at,
                sources=tuple(source_by_ref.values()),
            )
            return self._state

    def resolve(self, signal: AttentionIngressSignal) -> AttentionFocusState:
        if (
            not isinstance(signal, AttentionIngressSignal)
            or signal.operation is not AttentionIngressOperation.RESOLVE
        ):
            raise ValueError("resolveはresolve ingress signalだけを受理します")
        with self._lock:
            state = self._state
            self._validate_global_context(state, signal.source_context_revision)
            if signal.source_ref not in {source.source_ref for source in state.sources}:
                if self._is_versioned_stable(signal.source_kind):
                    raise ValueError("versioned stable sourceのresolve対象が存在しません")
                return state
            source = next(
                source for source in state.sources if source.source_ref == signal.source_ref
            )
            if source.kind is not signal.source_kind:
                raise ValueError("resolveはsource kindを変更できません")
            if self._is_versioned_stable(source.kind):
                current_source_revision = source.source_revision
                if (
                    signal.source_revision is None
                    or current_source_revision is None
                    or signal.expected_source_revision != current_source_revision
                    or signal.source_revision <= current_source_revision
                ):
                    raise ValueError("resolve source revisionがstaleです")
            elif source.source_revision is not None:
                if signal.expected_source_revision != source.source_revision:
                    raise ValueError("resolve source revisionがstaleです")
            elif signal.occurred_at < source.last_refreshed_at:
                raise ValueError("resolve時刻がstaleです")
            sources = tuple(
                source for source in state.sources if source.source_ref != signal.source_ref
            )
            monitors = tuple(
                ref for ref in state.secondary_monitor_refs if ref != signal.source_ref
            )
            foreground = (
                None
                if state.foreground_focus_ref == signal.source_ref
                else state.foreground_focus_ref
            )
            self._state = self._replace(
                state,
                signal.source_context_revision,
                signal.occurred_at,
                sources=sources,
                foreground_focus_ref=foreground,
                active_focus_intent_ref=None
                if foreground is None
                else state.active_focus_intent_ref,
                secondary_monitor_refs=monitors,
                current_turn_owner=None
                if state.current_turn_owner == signal.source_ref
                else state.current_turn_owner,
                response_obligation=None
                if state.response_obligation == signal.source_ref
                else state.response_obligation,
                cooldowns=tuple(
                    item for item in state.cooldowns if item.source_ref != signal.source_ref
                ),
            )
            return self._state

    def expire(self, source_context_revision: int, now: datetime) -> AttentionFocusState:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("nowはtimezone-awareでなければなりません")
        with self._lock:
            state = self._state
            self._validate_global_context(state, source_context_revision)
            expired = {
                source.source_ref
                for source in state.sources
                if source.expires_at is not None and source.expires_at <= now
            }
            if not expired:
                return state
            sources = tuple(source for source in state.sources if source.source_ref not in expired)
            foreground = (
                None if state.foreground_focus_ref in expired else state.foreground_focus_ref
            )
            self._state = self._replace(
                state,
                source_context_revision,
                now,
                sources=sources,
                foreground_focus_ref=foreground,
                active_focus_intent_ref=None
                if foreground is None
                else state.active_focus_intent_ref,
                secondary_monitor_refs=tuple(
                    ref for ref in state.secondary_monitor_refs if ref not in expired
                ),
                current_turn_owner=None
                if state.current_turn_owner in expired
                else state.current_turn_owner,
                response_obligation=None
                if state.response_obligation in expired
                else state.response_obligation,
                cooldowns=tuple(item for item in state.cooldowns if item.source_ref not in expired),
            )
            return self._state

    def apply(
        self, source_context_revision: int, transitions: tuple[AttentionTransition, ...]
    ) -> AttentionFocusState:
        values = tuple(transitions)
        if (
            not values
            or any(not isinstance(item, AttentionTransition) for item in values)
            or len({item.transition_id for item in values}) != len(values)
        ):
            raise ValueError(
                "transitionsは空でない一意なAttentionTransition配列でなければなりません"
            )
        with self._lock:
            state = self._state
            self._validate_global_context(state, source_context_revision)
            if {item.transition_id for item in values}.intersection(self._transition_ids):
                raise ValueError("transitionは既に適用済みです")
            if any(item.expected_attention_revision != state.revision for item in values) or any(
                item.expected_source_context_revision != state.source_context_revision
                or item.expected_source_context_revision != source_context_revision
                for item in values
            ):
                raise ValueError("attention transitionはstaleです")
            if any(item.occurred_at < state.updated_at for item in values):
                raise ValueError("transition時刻がcurrent stateより過去です")
            next_state = state
            for item in values:
                next_state = self._apply_one(next_state, item)
            self._state = self._replace(
                next_state,
                source_context_revision,
                max(item.occurred_at for item in values),
            )
            self._transition_ids.update(item.transition_id for item in values)
            return self._state

    def peek_eligibility(
        self, current_goal_revision: int, now: datetime, limit: int = 1
    ) -> tuple[ExecutiveTriggerEligibility, ...]:
        if type(limit) is not int or limit < 1:
            raise ValueError("limitは正の整数でなければなりません")
        with self._lock:
            state = self._state
            sources = self._ordered_eligible(state, now)[:limit]
            return tuple(
                self._trigger(
                    source, state, current_goal_revision, now, f"peek-{state.selection_epoch}"
                )
                for source in sources
            )

    def claim_next(
        self, current_goal_revision: int, now: datetime
    ) -> ExecutiveTriggerEligibility | None:
        with self._lock:
            state = self._state
            ordered = self._ordered_claimable(state, now)
            if not ordered:
                return None
            selected = ordered[0]
            next_epoch = state.selection_epoch + 1
            same_burst = (
                state.same_source_burst + 1
                if state.last_selected_source_ref == selected.source_ref
                else 1
            )
            priority_burst = (
                state.priority_burst + 1
                if state.last_selected_priority is selected.effective_priority
                else 1
            )
            cooldowns = [item for item in state.cooldowns if item.source_ref != selected.source_ref]
            if same_burst >= self._policy.max_same_source_burst:
                cooldowns.append(
                    AttentionCooldown(
                        selected.source_ref, next_epoch + self._policy.cooldown_claims
                    )
                )
            next_state = self._replace(
                state,
                state.source_context_revision,
                now,
                selection_epoch=next_epoch,
                last_selected_source_ref=selected.source_ref,
                same_source_burst=same_burst,
                last_selected_priority=selected.effective_priority,
                priority_burst=priority_burst,
                cooldowns=tuple(cooldowns),
            )
            self._state = next_state
            return self._trigger(selected, next_state, current_goal_revision, now, str(next_epoch))

    def interruption_decision(
        self, challenger_ref: str, now: datetime
    ) -> AttentionInterruptionDecision:
        with self._lock:
            return self._interruption_decision(self._state, challenger_ref, now)

    def _effective_priority(self, signal: AttentionIngressSignal) -> AttentionPriority:
        rule = self._policy.priority_rule_for(signal.source_kind)
        requested = signal.requested_priority or rule.default_priority
        if requested > rule.maximum_priority or requested < rule.default_priority:
            raise ValueError("requested priorityはpolicy許可範囲外です")
        if requested is AttentionPriority.DIRECT_USER and (
            signal.source_kind is not AttentionSourceKind.USER_INTERACTION
            or not signal.trusted_direct_user
        ):
            raise ValueError(
                "DIRECT_USERはtrusted Input Gateway user interactionだけに許可されます"
            )
        return requested

    @staticmethod
    def _is_versioned_stable(kind: AttentionSourceKind) -> bool:
        return kind in {
            AttentionSourceKind.GOAL,
            AttentionSourceKind.COMMITMENT,
            AttentionSourceKind.ACTIVITY,
        }

    def _validate_lifecycle_offer_or_refresh(
        self, signal: AttentionIngressSignal, current: AttentionSource | None
    ) -> None:
        if not self._is_versioned_stable(signal.source_kind):
            return
        if signal.operation is AttentionIngressOperation.OFFER:
            if (
                current is not None
                or signal.source_revision is None
                or signal.expected_source_revision is not None
            ):
                raise ValueError("versioned stable sourceのopenが不正です")
            return
        if (
            current is None
            or current.source_revision is None
            or signal.source_revision is None
            or signal.expected_source_revision != current.source_revision
            or signal.source_revision <= current.source_revision
        ):
            raise ValueError("versioned stable sourceのrefreshがstaleです")

    def _admit(
        self,
        sources: dict[str, AttentionSource],
        incoming: AttentionSource,
        state: AttentionFocusState,
    ) -> bool:
        protected = self._protected_refs(state)
        kind_sources = [source for source in sources.values() if source.kind is incoming.kind]
        if len(kind_sources) >= self._policy.budget_for(incoming.kind):
            if not self._replace_weakest(sources, kind_sources, incoming, protected):
                return False
        if len(sources) >= self._policy.attention_budget:
            if not self._replace_weakest(sources, list(sources.values()), incoming, protected):
                return False
        sources[incoming.source_ref] = incoming
        return True

    @staticmethod
    def _replace_weakest(
        sources: dict[str, AttentionSource],
        candidates: list[AttentionSource],
        incoming: AttentionSource,
        protected: set[str],
    ) -> bool:
        evictable = [source for source in candidates if source.source_ref not in protected]
        if not evictable:
            return False
        weakest = min(
            evictable,
            key=lambda source: (source.effective_priority, source.occurred_at, source.source_ref),
        )
        if incoming.effective_priority <= weakest.effective_priority:
            return False
        del sources[weakest.source_ref]
        return True

    def _ordered_eligible(self, state: AttentionFocusState, now: datetime) -> list[AttentionSource]:
        active = [source for source in state.sources if self._active(source, now)]
        protected = self._protected_direct_user(state, now)
        if protected:
            active = [
                source
                for source in active
                if source.effective_priority is not AttentionPriority.BACKGROUND
            ]
        cooldown_refs = {
            item.source_ref
            for item in state.cooldowns
            if item.eligible_after_epoch > state.selection_epoch
        }
        without_cooldown = [source for source in active if source.source_ref not in cooldown_refs]
        candidates = without_cooldown or active
        candidates = self._apply_priority_fairness(state, candidates)
        return sorted(
            candidates,
            key=lambda source: (-source.effective_priority, source.occurred_at, source.source_ref),
        )

    def _ordered_claimable(
        self, state: AttentionFocusState, now: datetime
    ) -> list[AttentionSource]:
        active = [source for source in state.sources if self._active(source, now)]
        claimable = [
            source
            for source in active
            if self._claim_relation(state, source, now)
            is not AttentionClaimRelation.CHALLENGER_INTERRUPT
            or self._interruption_decision(state, source.source_ref, now).allowed
        ]
        cooldown_refs = {
            item.source_ref
            for item in state.cooldowns
            if item.eligible_after_epoch > state.selection_epoch
        }
        without_cooldown = [
            source for source in claimable if source.source_ref not in cooldown_refs
        ]
        candidates = without_cooldown or claimable
        candidates = self._apply_priority_fairness(state, candidates)
        return sorted(
            candidates,
            key=lambda source: (-source.effective_priority, source.occurred_at, source.source_ref),
        )

    def _apply_priority_fairness(
        self, state: AttentionFocusState, candidates: list[AttentionSource]
    ) -> list[AttentionSource]:
        if (
            state.last_selected_priority is None
            or state.priority_burst < self._policy.max_priority_burst
        ):
            return candidates
        lower = [
            source
            for source in candidates
            if source.effective_priority < state.last_selected_priority
        ]
        if not lower:
            return candidates
        highest_lower = max(source.effective_priority for source in lower)
        return [source for source in lower if source.effective_priority is highest_lower]

    @staticmethod
    def _active(source: AttentionSource, now: datetime) -> bool:
        return source.expires_at is None or source.expires_at > now

    def _protected_direct_user(self, state: AttentionFocusState, now: datetime) -> bool:
        refs = {state.current_turn_owner, state.response_obligation}
        return any(
            source.source_ref in refs
            and self._active(source, now)
            and source.effective_priority is AttentionPriority.DIRECT_USER
            for source in state.sources
        )

    @staticmethod
    def _protected_refs(state: AttentionFocusState) -> set[str]:
        return {
            ref
            for ref in (
                state.foreground_focus_ref,
                state.current_turn_owner,
                state.response_obligation,
            )
            if ref is not None
        }

    def _trigger(
        self,
        source: AttentionSource,
        state: AttentionFocusState,
        goal_revision: int,
        now: datetime,
        epoch: str,
    ) -> ExecutiveTriggerEligibility:
        relation = self._claim_relation(state, source, now)
        decision = self._interruption_decision(state, source.source_ref, now)
        return ExecutiveTriggerEligibility(
            f"attention-{epoch}-{source.source_ref}",
            source.source_ref,
            source.kind,
            source.effective_priority,
            state.source_context_revision,
            goal_revision,
            state.revision,
            now,
            source.source_revision,
            decision.allowed if relation is AttentionClaimRelation.CHALLENGER_INTERRUPT else False,
            relation,
        )

    def _claim_relation(
        self, state: AttentionFocusState, source: AttentionSource, now: datetime
    ) -> AttentionClaimRelation:
        if source.source_ref in {state.current_turn_owner, state.response_obligation}:
            return AttentionClaimRelation.OBLIGATION_CONTINUATION
        if self._protected_direct_user(state, now):
            return AttentionClaimRelation.CHALLENGER_INTERRUPT
        if source.source_ref == state.foreground_focus_ref:
            return AttentionClaimRelation.FOREGROUND_CONTINUATION
        if state.foreground_focus_ref is None:
            return AttentionClaimRelation.IDLE_START
        return AttentionClaimRelation.CHALLENGER_INTERRUPT

    def _interruption_decision(
        self, state: AttentionFocusState, challenger_ref: str, now: datetime
    ) -> AttentionInterruptionDecision:
        source = next((item for item in state.sources if item.source_ref == challenger_ref), None)
        if source is None or not self._active(source, now):
            raise ValueError("challenger sourceはactiveでなければなりません")
        protected_refs = {
            ref
            for ref in (
                state.foreground_focus_ref,
                state.current_turn_owner,
                state.response_obligation,
            )
            if ref is not None and ref != challenger_ref
        }
        protected_priorities = [
            item.effective_priority
            for item in state.sources
            if item.source_ref in protected_refs and self._active(item, now)
        ]
        protected_priority = max(protected_priorities, default=None)
        minimum = self._policy.interruption_minimum_for(
            protected_priority
        )
        protected_user = self._protected_direct_user(state, now)
        if protected_user:
            minimum = AttentionPriority.DIRECT_USER
        allowed = source.effective_priority >= minimum
        return AttentionInterruptionDecision(challenger_ref, allowed, minimum)

    @staticmethod
    def _validate_global_context(state: AttentionFocusState, source_context_revision: int) -> None:
        if (
            type(source_context_revision) is not int
            or source_context_revision < state.source_context_revision
        ):
            raise ValueError("source context revisionを巻き戻せません")

    def _replace(
        self,
        state: AttentionFocusState,
        source_context_revision: int,
        updated_at: datetime,
        **changes: Any,
    ) -> AttentionFocusState:
        return replace(
            state,
            revision=state.revision + 1,
            source_context_revision=source_context_revision,
            updated_at=updated_at,
            **changes,
        )

    @staticmethod
    def _apply_one(
        state: AttentionFocusState, transition: AttentionTransition
    ) -> AttentionFocusState:
        op = transition.operation
        if op is AttentionTransitionOperation.ACQUIRE_FOREGROUND:
            if transition.target_ref not in {source.source_ref for source in state.sources}:
                raise ValueError(
                    "foreground acquire targetはcurrent sourceとして既知でなければなりません"
                )
            return replace(
                state,
                foreground_focus_ref=transition.target_ref,
                active_focus_intent_ref=transition.source_intent_ref,
            )
        if op is AttentionTransitionOperation.RELEASE_FOREGROUND:
            return replace(state, foreground_focus_ref=None, active_focus_intent_ref=None)
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
                    ref for ref in state.secondary_monitor_refs if ref != transition.target_ref
                ),
            )
        if op is AttentionTransitionOperation.ASSIGN_TURN:
            return replace(state, current_turn_owner=transition.value)
        if op is AttentionTransitionOperation.RELEASE_TURN:
            return replace(state, current_turn_owner=None)
        if op is AttentionTransitionOperation.SET_RESPONSE_OBLIGATION:
            return replace(state, response_obligation=transition.value)
        return replace(state, response_obligation=None)
