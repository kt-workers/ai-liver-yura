"""生成済み計画の内容と由来を保持した引継ぎ、上流失敗時の停止を確認する。"""

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.character.contracts import CharacterLanguageProfile
from app.domain.character_language import (
    CharacterLanguageAuthority,
    CharacterLanguageConstraintKind,
    CharacterLanguageConstraintView,
    CharacterLanguageContextSnapshot,
    CharacterLanguageRealizer,
)
from app.domain.contracts import RevisionVector
from app.domain.llm import LLMInterruptibility, LLMPriority, LLMRoleRequest, LLMRoleResult
from app.domain.semantic_verification import SemanticVerificationContextSnapshot, SemanticVerifier
from app.domain.speech_runtime.presentation import PresentationAdapter
from app.domain.speech_semantics import SpeechSemanticContextSnapshot
from app.subsystems.validation.contracts import (
    FailureInjection,
    Gate,
    InjectedFailure,
    LabMode,
    LabPolicy,
    LabRunSpec,
    RunStatus,
)
from app.subsystems.validation.generated_audio import GeneratedAudioBindings
from app.subsystems.validation.runtime import LabTarget, RunContext, ValidationRunner
from app.subsystems.validation.speech_adjacent import SpeechAdjacentBindings
from app.subsystems.validation.speech_generation import (
    SpeechGenerationCase,
    speech_generation_target,
)
from app.subsystems.validation.speech_preparation import (
    SpeechPreparationSettings,
    SpeechRevalidationStatePort,
)
from app.subsystems.validation.speech_session import SpeechPreparationSession
from tests.domain.character_language import test_character_language as character
from tests.domain.speech_semantics import test_speech_semantics as semantics
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def setup(
    *,
    deterministic: bool = False,
    verifier: Callable[[RunContext, SemanticVerificationContextSnapshot], SemanticVerifier]
    | None = None,
    preparation: SpeechPreparationSettings | None = None,
    revalidation: SpeechRevalidationStatePort | None = None,
    presentation: PresentationAdapter | None = None,
    audio: GeneratedAudioBindings | None = None,
    lab_policy: LabPolicy = POLICY,
    preparation_session: Callable[[RunContext], SpeechPreparationSession] | None = None,
    scenario_id: str | None = None,
    target_sink: list[LabTarget] | None = None,
) -> tuple[
    SpeechGenerationCase,
    ValidationRunner,
    list[CharacterLanguageContextSnapshot],
    list[LLMRoleRequest],
]:
    item = SpeechGenerationCase(
        FIXTURE,
        semantics.context(deterministic=deterministic),
        CharacterLanguageProfile("yura", 1, 1, ()),
        (
            CharacterLanguageConstraintView(
                "relationship-soft",
                CharacterLanguageConstraintKind.RELATIONSHIP,
                "relationship",
                "source-1",
                1,
                "穏やかに伝える",
            ),
            CharacterLanguageConstraintView(
                "discourse-answer",
                CharacterLanguageConstraintKind.DISCOURSE,
                "discourse",
                "source-2",
                1,
                "問いに答える",
            ),
        ),
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        semantics.NOW,
        preparation=preparation,
    )
    item = replace(
        item,
        fixture=replace(
            FIXTURE,
            typed_inputs=item.typed_inputs(),
            scenario_id=scenario_id or FIXTURE.scenario_id,
        ),
    )
    snapshots: list[CharacterLanguageContextSnapshot] = []
    requests: list[LLMRoleRequest] = []

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            requests.append(request)
            return semantics.result_for(request, semantics.candidate_json())

    class Live:
        async def current_revisions(
            self, snapshot: SpeechSemanticContextSnapshot
        ) -> RevisionVector:
            return snapshot.revisions

    def realizer(
        context: RunContext, snapshot: CharacterLanguageContextSnapshot
    ) -> CharacterLanguageRealizer:
        snapshots.append(snapshot)

        class CharacterPort:
            async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
                refs = tuple(
                    p.proposition_id
                    for p in snapshot.candidate.propositions
                    if p.disposition.value != "forbidden"
                )
                candidate = replace(
                    character.candidate(snapshot, refs=refs), created_at=snapshot.captured_at
                )
                return replace(
                    character.result_for(request, character.candidate_payload(candidate)),
                    started_at=snapshot.captured_at,
                    completed_at=snapshot.captured_at + timedelta(seconds=1),
                )

        return CharacterLanguageRealizer(
            CharacterPort(),
            character._LiveState(character.current(snapshot)),
            CharacterLanguageAuthority(),
            character.policy(),
        )

    bindings: (
        Callable[[RunContext, CharacterLanguageContextSnapshot], CharacterLanguageRealizer]
        | SpeechAdjacentBindings
    ) = realizer
    if verifier is not None:
        from app.domain.speech_performance import SpeechPerformancePlanner
        from app.domain.speech_performance.policy import yura_revision_1_policy

        bindings = SpeechAdjacentBindings(
            realizer,
            verifier,
            SpeechPerformancePlanner(yura_revision_1_policy()),
            revalidation=revalidation,
            presentation=presentation,
            audio=audio,
            preparation_session=preparation_session,
        )
    target = speech_generation_target(
        (item,), Port(), Live(), semantics.policy(), bindings, PROVENANCE, "1", ()
    )
    if target_sink is not None:
        target_sink.append(target)
    return item, ValidationRunner((target,), lab_policy), snapshots, requests


def run_spec(
    *, repeat_count: int = 1, failure_injections: tuple[FailureInjection, ...] = ()
) -> LabRunSpec:
    return replace(
        spec(),
        mode=LabMode.ADJACENT,
        target_module="speech_generation",
        repeat_count=repeat_count,
        failure_injections=failure_injections,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("deterministic", [False, True])
async def test_generated_plan_reaches_character_unchanged(deterministic: bool) -> None:
    item, runner, snapshots, requests = setup(deterministic=deterministic)
    result = await runner.run(run_spec(repeat_count=2), item.fixture)
    assert result.status is RunStatus.COMPLETED
    assert result.machine_gate is Gate.NOT_RUN
    assert len(snapshots) == 2
    assert len(requests) == (0 if deterministic else 2)
    assert len({s.semantic_plan.plan_id for s in snapshots}) == 2
    for stage, snapshot in zip(result.stage_results, snapshots, strict=True):
        output = stage.typed_outputs
        assert value_at(output, "semantic_plan") == value_at(
            output, "character_input", "semantic_plan"
        )
        assert (
            value_at(output, "utterance", "candidate", "semantic_plan_id")
            == snapshot.semantic_plan.plan_id
        )
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_semantic_failure_does_not_invoke_character() -> None:
    item, runner, snapshots, _ = setup()
    result = await runner.run(
        run_spec(
            failure_injections=(
                FailureInjection("speech_semantics.llm", InjectedFailure.PROVIDER_UNAVAILABLE, 1),
            )
        ),
        item.fixture,
    )
    assert result.status is RunStatus.PRODUCT_FAILED
    assert snapshots == []


@pytest.mark.asyncio
async def test_mismatched_mode_does_not_run_generation() -> None:
    item, runner, snapshots, requests = setup()
    result = await runner.run(replace(run_spec(), mode=LabMode.INTEGRATED), item.fixture)
    assert result.status is RunStatus.BLOCKED_UPSTREAM
    assert snapshots == [] and requests == []
