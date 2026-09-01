import asyncio
from dataclasses import replace

import pytest

from app.domain.brain_operational_bounds import (
    V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    BrainOperationalBoundsPolicy,
)
from app.domain.character.contracts import (
    CharacterLanguageProfile,
    RuntimeAvailability,
    RuntimeCharacterFacet,
)
from app.domain.character_language import (
    CharacterLanguageBoundsError,
    CharacterLanguageBoundsFailureCode,
    CharacterLanguageCommitState,
    CharacterLanguageContextSnapshot,
    CharacterLanguageRealizer,
    CharacterUtteranceCandidate,
    CharacterUtteranceSegment,
    LinguisticBoundary,
    LinguisticEmphasis,
    LinguisticHesitation,
    build_request,
    parse_candidate,
    validate_character_language_context_bounds,
    validate_character_language_output_bounds,
)
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from tests.domain.character_language.test_character_language import (
    NOW,
    candidate,
    candidate_payload,
    constraints,
    context,
    current,
    policy,
    profile,
    result_for,
)


def confirmed_profile(count: int) -> CharacterLanguageProfile:
    return CharacterLanguageProfile(
        "yura",
        1,
        3,
        tuple(
            RuntimeCharacterFacet(
                f"confirmed-{index:03d}",
                RuntimeAvailability.CONFIRMED,
                f"style-{index:03d}",
            )
            for index in range(count)
        ),
    )


def segment(
    index: int,
    *,
    text: str = "ゆ",
    refs: tuple[str, ...] = ("proposition-required",),
) -> CharacterUtteranceSegment:
    return CharacterUtteranceSegment(
        f"segment-{index:03d}",
        text,
        refs,
        LinguisticBoundary.SENTENCE,
        LinguisticEmphasis.NEUTRAL,
        LinguisticHesitation.NONE,
    )


def test_constraint_views_equal_and_above_policy_boundary_fail_closed() -> None:
    snapshot = context()
    equal_policy = replace(
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        character_language=replace(
            V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.character_language,
            max_constraint_views=len(snapshot.constraints),
        ),
    )
    validate_character_language_context_bounds(snapshot, equal_policy)

    above_policy = replace(
        equal_policy,
        character_language=replace(equal_policy.character_language, max_constraint_views=1),
    )
    with pytest.raises(CharacterLanguageBoundsError) as error:
        validate_character_language_context_bounds(snapshot, above_policy)
    assert error.value.code is CharacterLanguageBoundsFailureCode.CONTEXT_TOO_LARGE
    assert snapshot.constraints == constraints()


@pytest.mark.parametrize("count", [128, 129])
def test_confirmed_profile_128_129_boundary_never_first_n_projects(count: int) -> None:
    item_profile = confirmed_profile(count)
    snapshot = context(item_profile=item_profile)
    if count == 128:
        validate_character_language_context_bounds(
            snapshot, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
        )
    else:
        with pytest.raises(CharacterLanguageBoundsError) as error:
            validate_character_language_context_bounds(
                snapshot, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
            )
        assert error.value.code is CharacterLanguageBoundsFailureCode.CONTEXT_TOO_LARGE
        assert len(snapshot.confirmed_facets) == 129
        assert snapshot.character_profile == item_profile


def test_build_request_binds_policy_generation_and_rejects_profile_overflow() -> None:
    request = build_request(context(), created_at=NOW, policy=policy())
    payload = request.input.value
    assert isinstance(payload, dict)
    assert payload["bounds_policy_id"] == V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_id
    assert (
        payload["bounds_policy_revision"]
        == V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_revision
    )

    oversized = context(item_profile=confirmed_profile(129))
    with pytest.raises(CharacterLanguageBoundsError):
        build_request(oversized, created_at=NOW, policy=policy())
    assert len(oversized.confirmed_facets) == 129


@pytest.mark.parametrize("count", [64, 65])
def test_segments_64_65_boundary(count: int) -> None:
    snapshot = context()
    value = replace(
        candidate(snapshot),
        segments=tuple(segment(index) for index in range(count)),
    )
    if count == 64:
        validate_character_language_output_bounds(
            value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
        )
    else:
        with pytest.raises(CharacterLanguageBoundsError) as error:
            validate_character_language_output_bounds(
                value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
            )
        assert error.value.code is CharacterLanguageBoundsFailureCode.OUTPUT_TOO_LARGE


@pytest.mark.parametrize("count", [2048, 2049])
def test_segment_text_2048_2049_unicode_codepoint_boundary(count: int) -> None:
    snapshot = context()
    text = "ゆ" * count
    value = replace(candidate(snapshot), segments=(segment(0, text=text),))
    assert len(text.encode("utf-8")) > count
    if count == 2048:
        validate_character_language_output_bounds(
            value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
        )
    else:
        with pytest.raises(CharacterLanguageBoundsError):
            validate_character_language_output_bounds(
                value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
            )
        assert value.segments[0].text == text


@pytest.mark.parametrize("total", [8192, 8193])
def test_total_utterance_8192_8193_codepoint_boundary(total: int) -> None:
    snapshot = context()
    parts = [segment(index, text="ゆ" * 2048) for index in range(4)]
    if total == 8193:
        parts.append(segment(4, text="ゆ"))
    value = replace(candidate(snapshot), segments=tuple(parts))
    if total == 8192:
        validate_character_language_output_bounds(
            value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
        )
    else:
        with pytest.raises(CharacterLanguageBoundsError):
            validate_character_language_output_bounds(
                value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
            )


@pytest.mark.parametrize("count", [32, 33])
def test_realization_refs_32_33_boundary(count: int) -> None:
    snapshot = context()
    refs = tuple(f"proposition-{index:03d}" for index in range(count))
    value = replace(candidate(snapshot), segments=(segment(0, refs=refs),))
    if count == 32:
        validate_character_language_output_bounds(
            value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
        )
    else:
        with pytest.raises(CharacterLanguageBoundsError):
            validate_character_language_output_bounds(
                value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
            )


def test_provider_65_segments_are_not_first_n_accepted() -> None:
    snapshot = context()
    payload = candidate_payload(candidate(snapshot))
    raw_segments = payload["segments"]
    assert isinstance(raw_segments, list)
    first = raw_segments[0]
    assert isinstance(first, dict)
    payload["segments"] = [
        {**first, "segment_id": f"provider-segment-{index:03d}"}
        for index in range(65)
    ]
    with pytest.raises(CharacterLanguageBoundsError) as error:
        parse_candidate(payload, created_at=NOW)
    assert error.value.code is CharacterLanguageBoundsFailureCode.OUTPUT_TOO_LARGE
    assert len(payload["segments"]) == 65


class MutableBoundsPolicyState:
    def __init__(self) -> None:
        self.current = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY

    async def current_policy(
        self, snapshot: CharacterLanguageContextSnapshot
    ) -> BrainOperationalBoundsPolicy:
        return self.current


class DelayedPort:
    def __init__(self, invoked: asyncio.Event, release: asyncio.Event) -> None:
        self._invoked = invoked
        self._release = release

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self._invoked.set()
        await self._release.wait()
        snapshot = context()
        return result_for(request, candidate_payload(candidate(snapshot)))


class LiveState:
    async def current_state(
        self, snapshot: CharacterLanguageContextSnapshot
    ) -> CharacterLanguageCommitState:
        return current(snapshot)


@pytest.mark.asyncio
async def test_late_result_rejects_changed_policy_generation() -> None:
    invoked = asyncio.Event()
    release = asyncio.Event()
    bounds_state = MutableBoundsPolicyState()
    snapshot = context()
    realizer = CharacterLanguageRealizer(
        DelayedPort(invoked, release),
        LiveState(),
        __import__(
            "app.domain.character_language", fromlist=["CharacterLanguageAuthority"]
        ).CharacterLanguageAuthority(),
        policy(),
        bounds_state,
    )
    task = asyncio.create_task(
        realizer.realize(
            snapshot,
            utterance_id="utterance-policy-stale",
            created_at=NOW,
        )
    )
    await invoked.wait()
    bounds_state.current = replace(
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        policy_revision=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_revision + 1,
    )
    release.set()
    with pytest.raises(CharacterLanguageBoundsError) as error:
        await task
    assert error.value.code is CharacterLanguageBoundsFailureCode.POLICY_STALE


def test_existing_small_profile_still_passes_context_bound() -> None:
    snapshot = context(item_profile=profile())
    validate_character_language_context_bounds(snapshot, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
