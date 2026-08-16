from __future__ import annotations

from datetime import datetime

from app.domain.appraisal import InternalStateSnapshot
from app.domain.attention import AttentionFocusView
from app.domain.character.contracts import CharacterBodyStyleProfile
from app.domain.contracts.common import require_revision

from .contracts import (
    BodyExpressionContext,
    BodyExpressionFailureCode,
    BodyExpressionProjectionError,
    BodyExpressionProjectionPolicy,
)
from .ports import (
    AttentionFocusReadPort,
    BodyExpressionLiveContextPort,
    BodyExpressionPolicyReadPort,
    CharacterBodyStyleReadPort,
    InternalStateReadPort,
)
from .projector import project
from .store import BodyExpressionStore


class BodyExpressionCoordinator:
    def __init__(
        self,
        internal_state_port: InternalStateReadPort,
        attention_port: AttentionFocusReadPort,
        character_port: CharacterBodyStyleReadPort,
        policy_port: BodyExpressionPolicyReadPort,
        live_context_port: BodyExpressionLiveContextPort,
        store: BodyExpressionStore,
        *,
        max_stable_read_attempts: int = 2,
    ) -> None:
        if type(max_stable_read_attempts) is not int or max_stable_read_attempts < 1:
            raise ValueError("max_stable_read_attempts は正の整数でなければなりません")
        self._internal_state_port = internal_state_port
        self._attention_port = attention_port
        self._character_port = character_port
        self._policy_port = policy_port
        self._live_context_port = live_context_port
        self._store = store
        self._max_stable_read_attempts = max_stable_read_attempts

    def refresh(self, generated_at: datetime) -> BodyExpressionContext:
        for _ in range(self._max_stable_read_attempts):
            source_context_revision = self._live_context_port.current_source_context_revision()
            require_revision(source_context_revision, "source_context_revision")
            first = self._read_sources()
            second = self._read_sources()
            final_source_context_revision = (
                self._live_context_port.current_source_context_revision()
            )
            if source_context_revision != final_source_context_revision:
                continue
            if first != second:
                continue
            snapshot, attention, style, policy = first
            if (
                snapshot.source_context_revision > source_context_revision
                or attention.source_context_revision > source_context_revision
            ):
                raise BodyExpressionProjectionError(BodyExpressionFailureCode.STALE)
            candidate = project(
                snapshot,
                attention,
                style,
                policy,
                revision=self._store.revision + 1,
                capture_source_context_revision=source_context_revision,
                generated_at=generated_at,
            )
            return self._store.commit(self._store.revision, candidate)
        raise BodyExpressionProjectionError(BodyExpressionFailureCode.INCOHERENT)

    def _read_sources(
        self,
    ) -> tuple[
        InternalStateSnapshot,
        AttentionFocusView,
        CharacterBodyStyleProfile,
        BodyExpressionProjectionPolicy,
    ]:
        return (
            self._internal_state_port.current_snapshot(),
            self._attention_port.current_view(),
            self._character_port.current_profile(),
            self._policy_port.current_policy(),
        )
