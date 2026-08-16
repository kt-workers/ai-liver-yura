import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from app.domain.character.contracts import (
    CharacterLanguageProfile,
    RuntimeAvailability,
    RuntimeCharacterFacet,
)
from app.domain.character_language import (
    CharacterLanguageAuthority,
    CharacterLanguageCommitState,
    CharacterLanguageConstraintKind,
    CharacterLanguageConstraintView,
    CharacterLanguageContextSnapshot,
    CharacterLanguageError,
    CharacterLanguageFailureCode,
    CharacterLanguagePolicy,
    CharacterLanguageRealizer,
    CharacterUtterance,
    CharacterUtteranceCandidate,
    CharacterUtteranceSegment,
    LinguisticBoundary,
    LinguisticEmphasis,
    LinguisticHesitation,
    build_request,
    commit_result,
    parse_candidate,
)
from app.domain.contracts import RevisionVector
from app.domain.contracts.common import JsonValue
from app.domain.executive import (
    CommittedExecutiveDecision,
    ExecutiveDecisionCandidate,
    ExecutiveIntent,
    ExecutiveIntentKind,
    ExecutiveInterruptibility,
    ExecutiveOutcome,
    ExecutivePriority,
    SpeechIntentPayload,
)
from app.domain.llm import (
    LLMExecutionPolicy,
    LLMFailureCode,
    LLMInterruptibility,
    LLMModelClass,
    LLMPriority,
    LLMReasoningEffort,
    LLMRoleFailure,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)
from app.domain.speech_semantics import (
    SelfDisclosurePolicy,
    SemanticCertainty,
    SemanticPolarity,
    SpeechProposition,
    SpeechPropositionDisposition,
    SpeechSemanticAuthority,
    SpeechSemanticCandidate,
    SpeechSemanticContextSnapshot,
    SpeechSemanticFact,
    SpeechSemanticFactKind,
    SpeechSemanticPlan,
)

NOW = datetime(2026, 8, 17, tzinfo=timezone.utc)
REVISIONS = RevisionVector(11, 7, 4)


def policy() -> CharacterLanguagePolicy:
    return CharacterLanguagePolicy(
        LLMExecutionPolicy(
            LLMModelClass.BALANCED,
            LLMReasoningEffort.MEDIUM,
            10,
            1,
            1000,
        )
    )


def decision() -> CommittedExecutiveDecision:
    assert REVISIONS.goal_revision is not None
    assert REVISIONS.attention_revision is not None
    intent = ExecutiveIntent(
        "intent-speech",
        ExecutiveIntentKind.SPEECH,
        "利用者への応答を伝える",
        SpeechIntentPayload(
            "fact-goal",
            constraint_refs=("relationship-soft", "discourse-answer"),
        ),
        (),
        (),
        (),
        (),
    )
    candidate = ExecutiveDecisionCandidate(
        "decision-candidate",
        "trigger-1",
        ("event-1",),
        REVISIONS.source_context_revision,
        REVISIONS.goal_revision,
        REVISIONS.attention_revision,
        ExecutiveOutcome.RESPOND,
        ExecutivePriority.FOREGROUND,
        ExecutiveInterruptibility.INTERRUPTIBLE,
        (intent,),
        (),
        (),
        ("fact-goal",),
        NOW,
    )
    return CommittedExecutiveDecision("decision-1", candidate, (), NOW)


def semantic_plan() -> SpeechSemanticPlan:
    fact = SpeechSemanticFact(
        "fact-goal",
        SpeechSemanticFactKind.GENERAL,
        "user-1",
        "answer",
        {"topic_ref": "topic-1"},
    )
    forbidden_fact = SpeechSemanticFact(
        "fact-forbidden",
        SpeechSemanticFactKind.GENERAL,
        "user-1",
        "unsupported",
        {"value": True},
    )
    optional_fact = SpeechSemanticFact(
        "fact-optional",
        SpeechSemanticFactKind.GENERAL,
        "yura",
        "context",
        {"topic_ref": "topic-1"},
    )
    context = SpeechSemanticContextSnapshot(
        decision(),
        "intent-speech",
        (fact, forbidden_fact, optional_fact),
        (),
        ("relationship-soft", "discourse-answer"),
        SelfDisclosurePolicy.FORBIDDEN,
        1,
        1,
        NOW,
    )
    proposition = SpeechProposition(
        "proposition-required",
        "user-1",
        "answer",
        {"topic_ref": "topic-1"},
        SpeechPropositionDisposition.REQUIRED,
        SemanticPolarity.AFFIRM,
        SemanticCertainty.CERTAIN,
        ("fact-goal",),
    )
    forbidden_proposition = SpeechProposition(
        "forbidden-proposition",
        "user-1",
        "unsupported",
        {"value": True},
        SpeechPropositionDisposition.FORBIDDEN,
        SemanticPolarity.AFFIRM,
        SemanticCertainty.CERTAIN,
        ("fact-forbidden",),
    )
    optional_proposition = SpeechProposition(
        "proposition-optional",
        "yura",
        "context",
        {"topic_ref": "topic-1"},
        SpeechPropositionDisposition.OPTIONAL,
        SemanticPolarity.AFFIRM,
        SemanticCertainty.CERTAIN,
        ("fact-optional",),
    )
    candidate = SpeechSemanticCandidate(
        "semantic-candidate-1",
        "decision-1",
        "intent-speech",
        ("event-1",),
        REVISIONS,
        (proposition, forbidden_proposition, optional_proposition),
        SelfDisclosurePolicy.FORBIDDEN,
        1,
        1,
        (),
        ("relationship-soft",),
        ("discourse-answer",),
        NOW,
    )
    return SpeechSemanticAuthority().commit(
        candidate,
        context,
        current_revisions=REVISIONS,
        plan_id="semantic-plan-1",
        committed_at=NOW,
    )


def profile(*, revision: int = 3) -> CharacterLanguageProfile:
    return CharacterLanguageProfile(
        "yura",
        1,
        revision,
        (
            RuntimeCharacterFacet(
                "register", RuntimeAvailability.CONFIRMED, "やわらかく親しみのある語り口"
            ),
            RuntimeCharacterFacet("pending_style", RuntimeAvailability.UNRESOLVED),
            RuntimeCharacterFacet("optional_style", RuntimeAvailability.NOT_CONFIGURED),
        ),
    )


def constraints(*, revision: int = 5) -> tuple[CharacterLanguageConstraintView, ...]:
    return (
        CharacterLanguageConstraintView(
            "relationship-soft",
            CharacterLanguageConstraintKind.RELATIONSHIP,
            "relationship",
            "user-1",
            revision,
            "親しみを保つ",
        ),
        CharacterLanguageConstraintView(
            "discourse-answer",
            CharacterLanguageConstraintKind.DISCOURSE,
            "discourse",
            "turn-1",
            revision,
            "質問へ直接応答する",
        ),
    )


def context(
    *,
    request_id: str = "request-1",
    item_plan: SpeechSemanticPlan | None = None,
    item_profile: CharacterLanguageProfile | None = None,
    item_constraints: tuple[CharacterLanguageConstraintView, ...] | None = None,
    llm_priority: LLMPriority = LLMPriority.FOREGROUND,
    interruptibility: LLMInterruptibility = LLMInterruptibility.INTERRUPTIBLE,
) -> CharacterLanguageContextSnapshot:
    return CharacterLanguageContextSnapshot(
        request_id,
        item_plan or semantic_plan(),
        item_profile or profile(),
        item_constraints or constraints(),
        llm_priority,
        interruptibility,
        NOW,
        "trace-1",
    )


def candidate(
    snapshot: CharacterLanguageContextSnapshot,
    *,
    candidate_id: str = "candidate-1",
    request_id: str | None = None,
    text: str = "もちろん、いっしょに進めよう。",
    refs: tuple[str, ...] = ("proposition-required",),
) -> CharacterUtteranceCandidate:
    source = snapshot.candidate
    profile_value = snapshot.character_profile
    return CharacterUtteranceCandidate(
        candidate_id,
        request_id or snapshot.request_id,
        snapshot.semantic_plan.plan_id,
        source.decision_id,
        source.intent_id,
        source.source_event_ids,
        source.revisions,
        profile_value.character_id,
        profile_value.schema_version,
        profile_value.definition_revision,
        (
            CharacterUtteranceSegment(
                "segment-1",
                text,
                refs,
                LinguisticBoundary.SENTENCE,
                LinguisticEmphasis.NEUTRAL,
                LinguisticHesitation.NONE,
            ),
        ),
        0,
        0,
        NOW + timedelta(seconds=1),
    )


def current(snapshot: CharacterLanguageContextSnapshot) -> CharacterLanguageCommitState:
    return CharacterLanguageCommitState(
        snapshot.revisions,
        snapshot.semantic_plan,
        True,
        snapshot.character_profile,
        snapshot.constraints,
    )


def candidate_payload(item: CharacterUtteranceCandidate) -> dict[str, object]:
    value = item.to_dict()
    value.pop("created_at")
    return value


def result_for(request: LLMRoleRequest, value: object) -> LLMRoleResult:
    return LLMRoleResult(
        request.request_id,
        request.role_id,
        LLMRoleStatus.SUCCEEDED,
        request.revisions,
        NOW + timedelta(seconds=2),
        request.trace_id,
        LLMModelClass.BALANCED,
        1,
        LLMTokenUsage(10, 10),
        StructuredPayload("character.language.candidate.v1", cast(JsonValue, value)),
        started_at=NOW + timedelta(seconds=1),
    )


def failed_result_for(
    request: LLMRoleRequest,
    status: LLMRoleStatus,
    code: LLMFailureCode,
) -> LLMRoleResult:
    return LLMRoleResult(
        request.request_id,
        request.role_id,
        status,
        request.revisions,
        NOW + timedelta(seconds=2),
        request.trace_id,
        LLMModelClass.BALANCED,
        1,
        LLMTokenUsage(10, 0),
        failure=LLMRoleFailure(code, "Provider失敗"),
        started_at=NOW + timedelta(seconds=1),
    )


def test_snapshot_filters_unresolved_profile_values_and_exactly_grounds_constraints() -> None:
    snapshot = context()
    payload = snapshot.to_dict()
    facets = cast(
        list[dict[str, object]], cast(dict[str, object], payload["character_profile"])["facets"]
    )
    assert facets == [
        {
            "facet_id": "register",
            "value": "やわらかく親しみのある語り口",
            "basis_refs": [],
        }
    ]
    assert "raw_user_text" not in payload
    assert "history" not in payload
    with pytest.raises(ValueError, match="完全一致"):
        context(item_constraints=constraints()[:1])


def test_confirmed_profile_only_changes_request_payload() -> None:
    snapshot = context()
    changed = CharacterLanguageProfile(
        "yura",
        1,
        3,
        (
            RuntimeCharacterFacet(
                "register", RuntimeAvailability.CONFIRMED, "端的で落ち着いた語り口"
            ),
            RuntimeCharacterFacet("pending_style", RuntimeAvailability.UNRESOLVED),
        ),
    )
    changed_snapshot = context(item_profile=changed)
    original_payload = build_request(snapshot, created_at=NOW, policy=policy()).input.value
    changed_payload = build_request(changed_snapshot, created_at=NOW, policy=policy()).input.value
    assert original_payload != changed_payload
    assert "pending_style" not in str(changed_payload)


@pytest.mark.parametrize(
    ("priority", "interruptibility"),
    [
        (LLMPriority.FOREGROUND, LLMInterruptibility.INTERRUPTIBLE),
        (LLMPriority.BACKGROUND, LLMInterruptibility.NON_INTERRUPTIBLE),
    ],
)
def test_build_request_propagates_trusted_scheduling_metadata(
    priority: LLMPriority, interruptibility: LLMInterruptibility
) -> None:
    snapshot = context(llm_priority=priority, interruptibility=interruptibility)
    request = build_request(snapshot, created_at=NOW, policy=policy())
    assert request.priority is priority
    assert request.interruptibility is interruptibility


def test_same_plan_scheduling_difference_changes_request_metadata_not_candidate_schema() -> None:
    plan = semantic_plan()
    foreground = context(item_plan=plan, llm_priority=LLMPriority.FOREGROUND)
    background = context(
        request_id="request-background",
        item_plan=plan,
        llm_priority=LLMPriority.BACKGROUND,
        interruptibility=LLMInterruptibility.NON_INTERRUPTIBLE,
    )
    foreground_request = build_request(foreground, created_at=NOW, policy=policy())
    background_request = build_request(background, created_at=NOW, policy=policy())
    assert foreground_request.priority is LLMPriority.FOREGROUND
    assert background_request.priority is LLMPriority.BACKGROUND
    assert background_request.interruptibility is LLMInterruptibility.NON_INTERRUPTIBLE
    payload = candidate_payload(candidate(background, candidate_id="candidate-background"))
    assert "llm_priority" not in payload
    assert "interruptibility" not in payload
    payload["llm_priority"] = "foreground"
    with pytest.raises(ValueError, match="schema"):
        parse_candidate(payload, created_at=NOW + timedelta(seconds=2))


def test_candidate_and_utterance_are_immutable_and_authority_only() -> None:
    snapshot = context()
    item = candidate(snapshot)
    with pytest.raises(ValueError, match="CharacterLanguageAuthority"):
        CharacterUtterance("utterance-1", item, NOW + timedelta(seconds=2))
    with pytest.raises(ValueError, match="non-empty"):
        replace(item.segments[0], text="")
    with pytest.raises(ValueError, match="一意"):
        replace(item, segments=(item.segments[0], item.segments[0]))


def test_authority_requires_required_refs_rejects_forbidden_refs_and_budget_overrides() -> None:
    snapshot = context()
    authority = CharacterLanguageAuthority()
    with pytest.raises(CharacterLanguageError, match="REQUIRED"):
        authority.commit(
            candidate(snapshot, refs=()),
            snapshot,
            current=current(snapshot),
            utterance_id="utterance-1",
            committed_at=NOW + timedelta(seconds=2),
        )
    with pytest.raises(CharacterLanguageError, match="FORBIDDEN"):
        authority.commit(
            candidate(snapshot, refs=("forbidden-proposition",)),
            snapshot,
            current=current(snapshot),
            utterance_id="utterance-forbidden",
            committed_at=NOW + timedelta(seconds=2),
        )
    with pytest.raises(CharacterLanguageError, match="question budget"):
        authority.commit(
            replace(candidate(snapshot), question_budget_used=2),
            snapshot,
            current=current(snapshot),
            utterance_id="utterance-2",
            committed_at=NOW + timedelta(seconds=2),
        )
    with pytest.raises(CharacterLanguageError, match="new direction budget"):
        authority.commit(
            replace(candidate(snapshot), new_direction_budget_used=2),
            snapshot,
            current=current(snapshot),
            utterance_id="utterance-3",
            committed_at=NOW + timedelta(seconds=2),
        )


def test_optional_proposition_omission_and_budget_boundary_are_valid() -> None:
    snapshot = context()
    item = replace(
        candidate(snapshot),
        question_budget_used=1,
        new_direction_budget_used=1,
    )
    utterance = CharacterLanguageAuthority().commit(
        item,
        snapshot,
        current=current(snapshot),
        utterance_id="utterance-optional-omitted",
        committed_at=NOW + timedelta(seconds=2),
    )
    assert utterance.candidate.realization_refs == ("proposition-required",)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("question_budget_used", -1),
        ("question_budget_used", True),
        ("new_direction_budget_used", -1),
        ("new_direction_budget_used", True),
    ],
)
def test_candidate_rejects_negative_and_bool_budgets(field: str, value: object) -> None:
    item = candidate(context())
    with pytest.raises(ValueError, match="0以上"):
        if field == "question_budget_used":
            replace(item, question_budget_used=cast(int, value))
        else:
            replace(item, new_direction_budget_used=cast(int, value))


def test_same_plan_allows_multiple_variants_but_rejects_duplicate_candidate_and_request() -> None:
    snapshot = context()
    authority = CharacterLanguageAuthority()
    first = candidate(snapshot)
    assert (
        authority.commit(
            first,
            snapshot,
            current=current(snapshot),
            utterance_id="utterance-1",
            committed_at=NOW + timedelta(seconds=2),
        ).candidate
        == first
    )
    second_snapshot = context(request_id="request-2")
    second = candidate(
        second_snapshot,
        candidate_id="candidate-2",
        text="うん、いっしょに進めよう。",
    )
    assert (
        authority.commit(
            second,
            second_snapshot,
            current=current(second_snapshot),
            utterance_id="utterance-2",
            committed_at=NOW + timedelta(seconds=2),
        ).candidate
        == second
    )
    with pytest.raises(ValueError, match="candidate_id"):
        authority.commit(
            first,
            snapshot,
            current=current(snapshot),
            utterance_id="utterance-3",
            committed_at=NOW + timedelta(seconds=2),
        )


@pytest.mark.parametrize(
    ("changed", "code"),
    [
        ("source_revision", CharacterLanguageFailureCode.STALE),
        ("goal_revision", CharacterLanguageFailureCode.STALE),
        ("attention_revision", CharacterLanguageFailureCode.STALE),
        ("eligible", CharacterLanguageFailureCode.SUPERSEDED),
        ("profile", CharacterLanguageFailureCode.PROFILE_STALE),
        ("profile_payload", CharacterLanguageFailureCode.PROFILE_STALE),
        ("constraints", CharacterLanguageFailureCode.CONSTRAINT_STALE),
        ("constraint_payload", CharacterLanguageFailureCode.CONSTRAINT_STALE),
    ],
)
def test_authority_rejects_live_staleness_without_commit(
    changed: str, code: CharacterLanguageFailureCode
) -> None:
    snapshot = context()
    state = current(snapshot)
    if changed == "source_revision":
        state = replace(state, revisions=RevisionVector(12, 7, 4))
    elif changed == "goal_revision":
        state = replace(state, revisions=RevisionVector(11, 8, 4))
    elif changed == "attention_revision":
        state = replace(state, revisions=RevisionVector(11, 7, 5))
    elif changed == "eligible":
        state = replace(state, semantic_plan_eligible=False)
    elif changed == "profile":
        state = replace(state, character_profile=profile(revision=4))
    elif changed == "profile_payload":
        state = replace(
            state,
            character_profile=CharacterLanguageProfile(
                "yura",
                1,
                3,
                (RuntimeCharacterFacet("register", RuntimeAvailability.CONFIRMED, "別の語り口"),),
            ),
        )
    elif changed == "constraint_payload":
        changed_constraint = replace(constraints()[0], language_guidance="別の制約")
        state = replace(state, constraints=(changed_constraint, constraints()[1]))
    else:
        state = replace(state, constraints=constraints(revision=6))
    authority = CharacterLanguageAuthority()
    with pytest.raises(CharacterLanguageError) as error:
        authority.commit(
            candidate(snapshot),
            snapshot,
            current=state,
            utterance_id="utterance-1",
            committed_at=NOW + timedelta(seconds=2),
        )
    assert error.value.code is code
    assert authority.snapshot("utterance-1") is None


def test_parser_rejects_unknown_fields_and_preserves_strict_candidate_schema() -> None:
    snapshot = context()
    value = candidate_payload(candidate(snapshot))
    assert (
        parse_candidate(value, created_at=NOW + timedelta(seconds=2)).semantic_plan_id
        == "semantic-plan-1"
    )
    value["raw_user_text"] = "漏洩してはならない"
    with pytest.raises(ValueError, match="schema"):
        parse_candidate(value, created_at=NOW + timedelta(seconds=2))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("boundary_after", "unknown"),
        ("emphasis", "unknown"),
        ("hesitation", "unknown"),
    ],
)
def test_parser_rejects_unknown_linguistic_enum(field: str, value: str) -> None:
    payload = candidate_payload(candidate(context()))
    segments = cast(list[dict[str, object]], payload["segments"])
    segments[0][field] = value
    with pytest.raises(ValueError, match="不正"):
        parse_candidate(payload, created_at=NOW + timedelta(seconds=2))


def test_authority_rejects_unknown_proposition_ref() -> None:
    snapshot = context()
    with pytest.raises(CharacterLanguageError, match="未知"):
        CharacterLanguageAuthority().commit(
            candidate(snapshot, refs=("unknown-proposition",)),
            snapshot,
            current=current(snapshot),
            utterance_id="utterance-unknown-proposition",
            committed_at=NOW + timedelta(seconds=2),
        )


def test_snapshot_rejects_duplicate_unknown_and_wrong_kind_constraints() -> None:
    known = constraints()
    with pytest.raises(ValueError, match="一意"):
        context(item_constraints=(*known, known[0]))
    with pytest.raises(ValueError, match="完全一致"):
        context(
            item_constraints=(
                replace(known[0], kind=CharacterLanguageConstraintKind.DISCOURSE),
                known[1],
            )
        )
    unknown = CharacterLanguageConstraintView(
        "relationship-unknown",
        CharacterLanguageConstraintKind.RELATIONSHIP,
        "relationship",
        "user-1",
        5,
        "未知のconstraint",
    )
    with pytest.raises(ValueError, match="完全一致"):
        context(item_constraints=(known[0], known[1], unknown))


@pytest.mark.parametrize(
    ("override_name", "override_value"),
    [
        ("polarity", "affirm"),
        ("certainty", "certain"),
        ("degree", 1),
        ("execution_status", "completed"),
    ],
)
def test_candidate_schema_rejects_semantic_override_fields(
    override_name: str, override_value: object
) -> None:
    payload = candidate_payload(candidate(context()))
    payload[override_name] = override_value
    with pytest.raises(ValueError, match="schema"):
        parse_candidate(payload, created_at=NOW + timedelta(seconds=2))


def test_commit_result_rejects_profile_and_constraint_payload_drift() -> None:
    snapshot = context()
    request = build_request(snapshot, created_at=NOW, policy=policy())
    result = result_for(request, candidate_payload(candidate(snapshot)))
    with pytest.raises(CharacterLanguageError) as profile_error:
        commit_result(
            request,
            result,
            snapshot=snapshot,
            current=replace(current(snapshot), character_profile=profile(revision=4)),
            authority=CharacterLanguageAuthority(),
            utterance_id="utterance-1",
            policy=policy(),
        )
    assert profile_error.value.code is CharacterLanguageFailureCode.PROFILE_STALE
    with pytest.raises(CharacterLanguageError) as constraint_error:
        commit_result(
            request,
            result,
            snapshot=snapshot,
            current=replace(current(snapshot), constraints=constraints(revision=6)),
            authority=CharacterLanguageAuthority(),
            utterance_id="utterance-1",
            policy=policy(),
        )
    assert constraint_error.value.code is CharacterLanguageFailureCode.CONSTRAINT_STALE


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (LLMRoleStatus.FAILED, LLMFailureCode.PROVIDER_ERROR),
        (LLMRoleStatus.TIMED_OUT, LLMFailureCode.TIMEOUT),
    ],
)
def test_provider_failure_or_timeout_never_commits_a_fixed_fallback(
    status: LLMRoleStatus, code: LLMFailureCode
) -> None:
    snapshot = context()
    request = build_request(snapshot, created_at=NOW, policy=policy())
    authority = CharacterLanguageAuthority()
    with pytest.raises(ValueError, match="commit"):
        commit_result(
            request,
            failed_result_for(request, status, code),
            snapshot=snapshot,
            current=current(snapshot),
            authority=authority,
            utterance_id="utterance-provider-failure",
            policy=policy(),
        )
    assert authority.snapshot("utterance-provider-failure") is None


def test_invalid_output_schema_never_commits() -> None:
    snapshot = context()
    request = build_request(snapshot, created_at=NOW, policy=policy())
    valid = result_for(request, candidate_payload(candidate(snapshot)))
    assert valid.output is not None
    invalid = replace(
        valid,
        output=StructuredPayload("invalid.character.language.schema", valid.output.value),
    )
    authority = CharacterLanguageAuthority()
    with pytest.raises(ValueError, match="schema_invalid"):
        commit_result(
            request,
            invalid,
            snapshot=snapshot,
            current=current(snapshot),
            authority=authority,
            utterance_id="utterance-invalid-schema",
            policy=policy(),
        )
    assert authority.snapshot("utterance-invalid-schema") is None


class _LiveState:
    def __init__(self, state: CharacterLanguageCommitState) -> None:
        self.state = state

    async def current_state(
        self, snapshot: CharacterLanguageContextSnapshot
    ) -> CharacterLanguageCommitState:
        assert isinstance(snapshot, CharacterLanguageContextSnapshot)
        return self.state


class _DelayedPort:
    def __init__(self, value: object, started: asyncio.Event, release: asyncio.Event) -> None:
        self._value = value
        self._started = started
        self._release = release

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self._started.set()
        await self._release.wait()
        return result_for(request, self._value)


class _ImmediatePort:
    def __init__(self, value: object) -> None:
        self._value = value

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        return result_for(request, self._value)


@pytest.mark.asyncio
async def test_slow_realizer_does_not_block_unrelated_work_and_reads_live_state_after_await() -> (
    None
):
    snapshot = context()
    started = asyncio.Event()
    release = asyncio.Event()
    port = _DelayedPort(candidate_payload(candidate(snapshot)), started, release)
    realizer = CharacterLanguageRealizer(
        port,
        _LiveState(current(snapshot)),
        CharacterLanguageAuthority(),
        policy(),
    )
    task = asyncio.create_task(
        realizer.realize(snapshot, utterance_id="utterance-1", created_at=NOW)
    )
    await started.wait()
    speech_presentation_heartbeat: list[int] = []
    body_realtime_heartbeat: list[int] = []

    async def heartbeat(values: list[int]) -> None:
        for tick in range(3):
            values.append(tick)
            await asyncio.sleep(0)

    await asyncio.wait_for(
        asyncio.gather(
            heartbeat(speech_presentation_heartbeat),
            heartbeat(body_realtime_heartbeat),
        ),
        timeout=1,
    )
    assert speech_presentation_heartbeat == [0, 1, 2]
    assert body_realtime_heartbeat == [0, 1, 2]
    release.set()
    assert (await task).utterance_id == "utterance-1"


@pytest.mark.asyncio
async def test_realizer_rejects_stale_plan_after_provider_await() -> None:
    snapshot = context()
    started = asyncio.Event()
    release = asyncio.Event()
    port = _DelayedPort(candidate_payload(candidate(snapshot)), started, release)
    realizer = CharacterLanguageRealizer(
        port,
        _LiveState(replace(current(snapshot), revisions=RevisionVector(12, 7, 4))),
        CharacterLanguageAuthority(),
        policy(),
    )
    task = asyncio.create_task(
        realizer.realize(snapshot, utterance_id="utterance-1", created_at=NOW)
    )
    await started.wait()
    release.set()
    with pytest.raises(CharacterLanguageError) as error:
        await task
    assert error.value.code is CharacterLanguageFailureCode.STALE


@pytest.mark.asyncio
async def test_separate_plan_generations_are_not_serialized_by_a_global_plan_slot() -> None:
    first_snapshot = context()
    second_snapshot = context(request_id="request-2")
    authority = CharacterLanguageAuthority()
    first = CharacterLanguageRealizer(
        _ImmediatePort(candidate_payload(candidate(first_snapshot))),
        _LiveState(current(first_snapshot)),
        authority,
        policy(),
    )
    second = CharacterLanguageRealizer(
        _ImmediatePort(candidate_payload(candidate(second_snapshot, candidate_id="candidate-2"))),
        _LiveState(current(second_snapshot)),
        authority,
        policy(),
    )
    left, right = await asyncio.gather(
        first.realize(first_snapshot, utterance_id="utterance-1", created_at=NOW),
        second.realize(second_snapshot, utterance_id="utterance-2", created_at=NOW),
    )
    assert {left.utterance_id, right.utterance_id} == {"utterance-1", "utterance-2"}


@pytest.mark.asyncio
async def test_body_motion_planning_equivalent_task_can_start_while_character_role_waits() -> None:
    snapshot = context()
    started = asyncio.Event()
    release = asyncio.Event()
    realizer = CharacterLanguageRealizer(
        _DelayedPort(candidate_payload(candidate(snapshot)), started, release),
        _LiveState(current(snapshot)),
        CharacterLanguageAuthority(),
        policy(),
    )
    character_task = asyncio.create_task(
        realizer.realize(snapshot, utterance_id="utterance-1", created_at=NOW)
    )
    await started.wait()
    body_motion_started = asyncio.Event()

    async def body_motion_planning() -> str:
        body_motion_started.set()
        await asyncio.sleep(0)
        return "body-motion-started"

    assert await asyncio.wait_for(body_motion_planning(), timeout=1) == "body-motion-started"
    assert body_motion_started.is_set()
    release.set()
    await character_task


@pytest.mark.asyncio
async def test_previous_speech_playback_does_not_block_next_character_generation() -> None:
    playback_started = asyncio.Event()
    playback_release = asyncio.Event()

    async def previous_playback() -> None:
        playback_started.set()
        await playback_release.wait()

    playback_task = asyncio.create_task(previous_playback())
    await playback_started.wait()
    snapshot = context()
    realizer = CharacterLanguageRealizer(
        _ImmediatePort(candidate_payload(candidate(snapshot))),
        _LiveState(current(snapshot)),
        CharacterLanguageAuthority(),
        policy(),
    )
    utterance = await asyncio.wait_for(
        realizer.realize(snapshot, utterance_id="utterance-next", created_at=NOW),
        timeout=1,
    )
    assert utterance.utterance_id == "utterance-next"
    assert not playback_task.done()
    playback_release.set()
    await playback_task
