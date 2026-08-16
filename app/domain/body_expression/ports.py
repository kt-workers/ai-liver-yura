from __future__ import annotations

from typing import Protocol

from app.domain.appraisal import InternalStateSnapshot
from app.domain.attention import AttentionFocusView
from app.domain.character.contracts import CharacterBodyStyleProfile

from .contracts import BodyExpressionProjectionPolicy


class InternalStateReadPort(Protocol):
    def current_snapshot(self) -> InternalStateSnapshot: ...


class AttentionFocusReadPort(Protocol):
    def current_view(self) -> AttentionFocusView: ...


class CharacterBodyStyleReadPort(Protocol):
    def current_profile(self) -> CharacterBodyStyleProfile: ...


class BodyExpressionPolicyReadPort(Protocol):
    def current_policy(self) -> BodyExpressionProjectionPolicy: ...


class BodyExpressionLiveContextPort(Protocol):
    def current_source_context_revision(self) -> int: ...
