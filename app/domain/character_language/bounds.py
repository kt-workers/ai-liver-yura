from __future__ import annotations

from enum import Enum
from typing import Protocol

from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy

from .contracts import CharacterLanguageContextSnapshot, CharacterUtteranceCandidate


class CharacterLanguageBoundsFailureCode(str, Enum):
    CONTEXT_TOO_LARGE = "character_context_too_large"
    OUTPUT_TOO_LARGE = "character_output_too_large"
    POLICY_STALE = "character_policy_stale"


class CharacterLanguageBoundsError(ValueError):
    def __init__(self, code: CharacterLanguageBoundsFailureCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")


class CharacterLanguageBoundsPolicyPort(Protocol):
    async def current_policy(
        self, snapshot: CharacterLanguageContextSnapshot
    ) -> BrainOperationalBoundsPolicy: ...


def _require_policy(bounds_policy: BrainOperationalBoundsPolicy) -> BrainOperationalBoundsPolicy:
    if not isinstance(bounds_policy, BrainOperationalBoundsPolicy):
        raise ValueError("容量方針はBrainOperationalBoundsPolicyでなければなりません")
    return bounds_policy


def assert_character_language_policy_generation(
    expected: BrainOperationalBoundsPolicy,
    current: BrainOperationalBoundsPolicy,
) -> None:
    expected_policy = _require_policy(expected)
    current_policy = _require_policy(current)
    if (
        expected_policy.policy_id != current_policy.policy_id
        or expected_policy.policy_revision != current_policy.policy_revision
    ):
        raise CharacterLanguageBoundsError(
            CharacterLanguageBoundsFailureCode.POLICY_STALE,
            "Character Language request generationとcurrent policy generationが一致しません",
        )


def validate_character_language_context_bounds(
    snapshot: CharacterLanguageContextSnapshot,
    bounds_policy: BrainOperationalBoundsPolicy,
) -> None:
    if not isinstance(snapshot, CharacterLanguageContextSnapshot):
        raise ValueError("snapshotはCharacterLanguageContextSnapshotでなければなりません")
    bounds = _require_policy(bounds_policy).character_language
    constraint_count = len(snapshot.constraints)
    if constraint_count > bounds.max_constraint_views:
        raise CharacterLanguageBoundsError(
            CharacterLanguageBoundsFailureCode.CONTEXT_TOO_LARGE,
            f"constraint_views count={constraint_count} limit={bounds.max_constraint_views}",
        )
    confirmed_count = len(snapshot.confirmed_facets)
    if confirmed_count > bounds.max_confirmed_profile_facets:
        raise CharacterLanguageBoundsError(
            CharacterLanguageBoundsFailureCode.CONTEXT_TOO_LARGE,
            (
                f"confirmed_profile_facets count={confirmed_count} "
                f"limit={bounds.max_confirmed_profile_facets}"
            ),
        )


def validate_character_language_output_bounds(
    candidate: CharacterUtteranceCandidate,
    bounds_policy: BrainOperationalBoundsPolicy,
) -> None:
    if not isinstance(candidate, CharacterUtteranceCandidate):
        raise ValueError("candidateはCharacterUtteranceCandidateでなければなりません")
    bounds = _require_policy(bounds_policy).character_language
    segment_count = len(candidate.segments)
    if segment_count > bounds.max_segments:
        raise CharacterLanguageBoundsError(
            CharacterLanguageBoundsFailureCode.OUTPUT_TOO_LARGE,
            f"segments count={segment_count} limit={bounds.max_segments}",
        )
    total_codepoints = 0
    for segment in candidate.segments:
        segment_codepoints = len(segment.text)
        if segment_codepoints > bounds.max_segment_codepoints:
            raise CharacterLanguageBoundsError(
                CharacterLanguageBoundsFailureCode.OUTPUT_TOO_LARGE,
                (
                    f"segment={segment.segment_id} codepoints={segment_codepoints} "
                    f"limit={bounds.max_segment_codepoints}"
                ),
            )
        realization_ref_count = len(segment.realization_refs)
        if realization_ref_count > bounds.max_realization_refs_per_segment:
            raise CharacterLanguageBoundsError(
                CharacterLanguageBoundsFailureCode.OUTPUT_TOO_LARGE,
                (
                    f"segment={segment.segment_id} realization_refs={realization_ref_count} "
                    f"limit={bounds.max_realization_refs_per_segment}"
                ),
            )
        total_codepoints += segment_codepoints
    if total_codepoints > bounds.max_total_utterance_codepoints:
        raise CharacterLanguageBoundsError(
            CharacterLanguageBoundsFailureCode.OUTPUT_TOO_LARGE,
            (
                f"total_utterance_codepoints={total_codepoints} "
                f"limit={bounds.max_total_utterance_codepoints}"
            ),
        )
