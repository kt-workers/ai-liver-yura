from __future__ import annotations

from datetime import datetime
from threading import Lock

from app.domain.brain_operational_bounds import (
    V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    BrainOperationalBoundsPolicy,
)
from app.domain.contracts.common import require_aware, require_identifier

from .bounds import (
    validate_character_language_context_bounds,
    validate_character_language_output_bounds,
)
from .contracts import (
    _UTTERANCE_PROOF,
    CharacterLanguageCommitState,
    CharacterLanguageContextSnapshot,
    CharacterLanguageError,
    CharacterLanguageFailureCode,
    CharacterUtterance,
    CharacterUtteranceCandidate,
    validate_candidate_structure,
)


class CharacterLanguageAuthority:
    """How-to-say候補を現在のPlan/Profile/constraintへ構造的にcommitする。"""

    def __init__(self) -> None:
        self._utterances: dict[str, CharacterUtterance] = {}
        self._candidate_ids: set[str] = set()
        self._request_ids: set[str] = set()
        self._lock = Lock()

    def commit(
        self,
        candidate: CharacterUtteranceCandidate,
        snapshot: CharacterLanguageContextSnapshot,
        *,
        current: CharacterLanguageCommitState,
        utterance_id: str,
        committed_at: datetime,
        bounds_policy: BrainOperationalBoundsPolicy = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    ) -> CharacterUtterance:
        if not isinstance(candidate, CharacterUtteranceCandidate):
            raise ValueError("candidate は CharacterUtteranceCandidate でなければなりません")
        if not isinstance(snapshot, CharacterLanguageContextSnapshot):
            raise ValueError("snapshot は CharacterLanguageContextSnapshot でなければなりません")
        if not isinstance(current, CharacterLanguageCommitState):
            raise ValueError("current は CharacterLanguageCommitState でなければなりません")
        validate_character_language_context_bounds(snapshot, bounds_policy)
        validate_character_language_output_bounds(candidate, bounds_policy)
        require_identifier(utterance_id, "utterance_id")
        require_aware(committed_at, "committed_at")
        validate_candidate_structure(candidate, snapshot)
        self._validate_live_state(snapshot, current)
        with self._lock:
            if utterance_id in self._utterances:
                raise ValueError("utterance_id はすでにcommitされています")
            if candidate.candidate_id in self._candidate_ids:
                raise ValueError("candidate_id はすでにcommitされています")
            if candidate.request_id in self._request_ids:
                raise ValueError("request_id はすでにcommitされています")
            utterance = CharacterUtterance(
                utterance_id,
                candidate,
                committed_at,
                _proof=_UTTERANCE_PROOF,
            )
            self._utterances[utterance_id] = utterance
            self._candidate_ids.add(candidate.candidate_id)
            self._request_ids.add(candidate.request_id)
            return utterance

    def snapshot(self, utterance_id: str) -> CharacterUtterance | None:
        with self._lock:
            return self._utterances.get(utterance_id)

    @staticmethod
    def _validate_live_state(
        snapshot: CharacterLanguageContextSnapshot,
        current: CharacterLanguageCommitState,
    ) -> None:
        if current.revisions != snapshot.revisions:
            raise CharacterLanguageError(
                CharacterLanguageFailureCode.STALE, "revisionが更新されています"
            )
        if (
            current.semantic_plan is None
            or current.semantic_plan.plan_id != snapshot.semantic_plan.plan_id
        ):
            raise CharacterLanguageError(
                CharacterLanguageFailureCode.STALE, "Semantic Planが更新されています"
            )
        if not current.semantic_plan_eligible:
            raise CharacterLanguageError(
                CharacterLanguageFailureCode.SUPERSEDED, "Semantic Planは現在eligibleではありません"
            )
        if current.semantic_plan != snapshot.semantic_plan:
            raise CharacterLanguageError(
                CharacterLanguageFailureCode.STALE, "Semantic Plan payloadが更新されています"
            )
        if current.character_profile is None:
            raise CharacterLanguageError(
                CharacterLanguageFailureCode.UNAVAILABLE, "Character Profileを取得できません"
            )
        if current.character_profile != snapshot.character_profile:
            raise CharacterLanguageError(
                CharacterLanguageFailureCode.PROFILE_STALE,
                "Character Profileが更新されています",
            )
        if current.constraints != snapshot.constraints:
            raise CharacterLanguageError(
                CharacterLanguageFailureCode.CONSTRAINT_STALE,
                "Character constraintが更新されています",
            )
