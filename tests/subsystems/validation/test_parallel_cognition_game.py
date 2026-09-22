"""実行判断と人物表現の実際の待機中にゲームを進め、終了と古い結果の拒否を確認する。"""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.character_language import (
    CharacterLanguageAuthority,
    CharacterLanguageContextSnapshot,
    CharacterLanguageRealizer,
)
from app.domain.character_language.realizer import ROLE_ID as CHARACTER_ROLE_ID
from app.domain.contracts import RevisionVector
from app.domain.executive import (
    ExecutiveCommitState,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
)
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from app.domain.speech_semantics import SpeechSemanticContextSnapshot
from app.subsystems.validation.contracts import (
    Gate,
    LabMode,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from app.subsystems.validation.executive import ExecutiveLabCase, executive_target
from app.subsystems.validation.game_monitor import GameMonitorFrame, game_monitor_target
from app.subsystems.validation.llm_port import ObservedLLMRolePort
from app.subsystems.validation.parallel import ParallelCase, ParallelInput, parallel_target
from app.subsystems.validation.runtime import RunContext, ValidationRunner
from app.subsystems.validation.speech_generation import speech_generation_target
from tests.domain.character_language import test_character_language as character
from tests.domain.executive import test_executive as executive
from tests.domain.speech_semantics import test_speech_semantics as semantics
from tests.helpers.executive_requirements import SPEECH_OWNER
from tests.subsystems.game_skill import test_runtime as game_product
from tests.subsystems.validation.json_values import array_at, integer_at, value_at
from tests.subsystems.validation.test_game_monitor import case as monitor_case
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec
from tests.subsystems.validation.test_speech_generation import setup


@pytest.mark.asyncio
@pytest.mark.parametrize("ending,duration", [("normal", 20), ("cancel", 0), ("stale", 0)])
async def test_game_progresses_while_both_cognitive_owners_await(
    ending: str, duration: int
) -> None:
    executive_started, character_started, release, game_done = (asyncio.Event() for _ in range(4))
    executive_stopped, character_stopped = asyncio.Event(), asyncio.Event()
    stale = False

    class ExecutivePort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            executive_started.set()
            try:
                await release.wait()
                return executive.success(request)
            finally:
                executive_stopped.set()

    class ExecutiveLive:
        async def current_for_commit(
            self, snapshot: ExecutiveContextSnapshot, candidate: ExecutiveDecisionCandidate
        ) -> ExecutiveCommitState:
            return executive.live_state(internal_state_revision=3 if stale else 2)

    evaluation = ExecutiveLabCase(FIXTURE, executive.snapshot(), executive.NOW)
    evaluation = replace(
        evaluation,
        fixture=replace(FIXTURE, typed_inputs=evaluation.typed_inputs(executive.policy())),
    )
    deliberation = executive_target(
        (evaluation,),
        ExecutivePort(),
        ExecutiveLive(),
        executive.policy(),
        PROVENANCE,
        "1",
        (),
        requirements_owner=SPEECH_OWNER,
    )
    speech, unused, _, _ = setup()
    await unused.close()

    class SemanticsPort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return semantics.result_for(request, semantics.candidate_json())

    class SemanticsLive:
        async def current_revisions(
            self, snapshot: SpeechSemanticContextSnapshot
        ) -> RevisionVector:
            return snapshot.revisions

    def realizer(
        context: RunContext, snapshot: CharacterLanguageContextSnapshot
    ) -> CharacterLanguageRealizer:
        class CharacterPort:
            async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
                character_started.set()
                try:
                    await release.wait()
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
                finally:
                    character_stopped.set()

        return CharacterLanguageRealizer(
            ObservedLLMRolePort(
                context, CharacterPort(), {CHARACTER_ROLE_ID: "speech.character.llm"}
            ),
            character._LiveState(character.current(snapshot)),
            CharacterLanguageAuthority(),
            character.policy(),
        )

    language = speech_generation_target(
        (speech,),
        SemanticsPort(),
        SemanticsLive(),
        semantics.policy(),
        realizer,
        PROVENANCE,
        "1",
        (),
        character_llm_stages=frozenset({"speech.character.llm"}),
    )
    frames = duration or 2
    monitored = monitor_case(
        (GameMonitorFrame(),) * frames,
        sample_interval_s=1 if duration else 0.03,
        loop_interval_s=0.05 if duration else 0.005,
    )
    game = game_monitor_target(
        (monitored,), game_product.Controller(), game_product.Policy(), PROVENANCE, "1"
    )

    async def observed_game(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        await executive_started.wait()
        await character_started.wait()
        result = await game.run(context, fixture)
        game_done.set()
        return result

    case = ParallelCase(
        FIXTURE,
        (
            ParallelInput(
                replace(spec(), run_id="executive", target_module="executive"), evaluation.fixture
            ),
            ParallelInput(
                replace(
                    spec(),
                    run_id="language",
                    target_module="speech_generation",
                    mode=LabMode.ADJACENT,
                ),
                speech.fixture,
            ),
            ParallelInput(
                replace(spec(), run_id="game", target_module="game_monitor"), monitored.fixture
            ),
        ),
    )
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    runner = ValidationRunner(
        (
            parallel_target(
                (case,), (deliberation, language, replace(game, run=observed_game)), PROVENANCE, "1"
            ),
        ),
        replace(
            POLICY,
            max_tasks=12,
            max_intervals=192,
            max_export_bytes=1_000_000,
            timeout_seconds=duration + 5,
        ),
    )
    request = replace(spec(), target_module="parallel", mode=LabMode.SYSTEM_SLICE)
    task = asyncio.create_task(runner.run(request, case.fixture))
    try:
        await asyncio.wait_for(game_done.wait(), duration + 2)
        assert not executive_stopped.is_set() and not character_stopped.is_set()
        assert not task.done()
        if ending == "cancel":
            await runner.cancel(request.run_id)
        else:
            stale = ending == "stale"
            release.set()
        result = await task
    finally:
        await runner.close()
        await asyncio.gather(task, return_exceptions=True)
    assert executive_stopped.is_set() and character_stopped.is_set()
    assert runner.pending_count == 0
    assert (
        result.status
        is {
            "normal": RunStatus.COMPLETED,
            "cancel": RunStatus.CANCELLED,
            "stale": RunStatus.PRODUCT_FAILED,
        }[ending]
    )
    assert result.machine_gate is Gate.NOT_RUN
    if ending == "cancel":
        return
    children = array_at(result.stage_results[0].typed_outputs, "results")
    assert value_at(children[1], "status") == value_at(children[2], "status") == "COMPLETED"
    assert value_at(children[0], "status") == ("PRODUCT_FAILED" if stale else "COMPLETED")
    samples = array_at(children[2], "stage_results", 0, "typed_outputs", "samples")
    assert len(samples) == frames
    assert all(
        integer_at(x, "after", "game_state_revision")
        > integer_at(x, "before", "game_state_revision")
        for x in samples
    )
    assert integer_at(children[2], "stage_results", 0, "typed_outputs", "pending_game_tasks") == 0
    intervals = [
        x
        for x in array_at(children[2], "timeline")
        if value_at(x, "stage") == "game.monitor_sample"
    ]
    assert len(intervals) == frames
    assert (
        integer_at(intervals[-1], "completed_ns") - integer_at(intervals[0], "started_ns")
        >= duration * 1_000_000_000
    )
    for child, stage in ((children[0], "executive.llm"), (children[1], "speech.character.llm")):
        wait = next(x for x in array_at(child, "timeline") if value_at(x, "stage") == stage)
        assert all(
            integer_at(wait, "started_ns")
            <= integer_at(x, "started_ns")
            <= integer_at(x, "completed_ns")
            <= integer_at(wait, "completed_ns")
            for x in intervals
        )
