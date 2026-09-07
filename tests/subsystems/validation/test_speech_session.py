"""実生成の型付き候補を同じ所有者の共有待ち行列から提示する。"""

from dataclasses import replace

import pytest

from app.domain.speech_runtime.contracts import CandidateLifecycle, SpeechPresentationMode
from app.subsystems.validation.contracts import RunStatus, TargetObservation
from app.subsystems.validation.runtime import LabTarget, RunContext
from app.subsystems.validation.speech_presentation import execute_presentation
from app.subsystems.validation.speech_session import SpeechPreparationSession
from tests.domain.speech_semantics import test_speech_semantics as semantics
from tests.subsystems.validation.test_generated_presentation import Live
from tests.subsystems.validation.test_runtime import POLICY
from tests.subsystems.validation.test_speech_generation import setup
from tests.subsystems.validation.test_speech_generation_chain import Verification
from tests.subsystems.validation.test_speech_preparation import settings
from tests.subsystems.validation.test_speech_queue import Connections


@pytest.mark.asyncio
async def test_actual_generation_and_acceptance_reach_same_runtime_queue_and_presentation() -> None:
    preparation = replace(settings(), presentation_modes=(SpeechPresentationMode.TEXT_ONLY,))
    context = RunContext(replace(POLICY, max_tasks=64, max_intervals=128))
    session = SpeechPreparationSession(context, preparation.policy, semantics.NOW)
    output = Connections()
    candidates = []
    try:
        for index in range(2):
            targets: list[LabTarget] = []
            item, _, _, _ = setup(
                verifier=Verification(accepted=True).build,
                preparation=preparation,
                preparation_session=lambda _: session,
                scenario_id=f"generated-{index}",
                target_sink=targets,
            )
            result = await targets[0].run(context, item.fixture)
            assert result.status is RunStatus.COMPLETED
        for candidate_id in await session.runtime.active_candidate_ids():
            candidate = await session.runtime.candidate(candidate_id)
            assert candidate.lifecycle is CandidateLifecycle.PREPARED
            assert candidate.utterance_id and candidate.semantic_acceptance_id
            candidates.append(candidate)
            admission = await session.queue.enqueue_current(
                candidate_id,
                session.runtime.generation(candidate_id),
            )
            assert admission.admitted
        assert len(candidates) == 2 and len(session.queue) == 2
        while (queued := await session.queue.pop_for_revalidation()) is not None:
            candidate = queued
            state = replace(await Live().current_state(candidate), observed_at=candidate.updated_at)
            ready = await session.runtime.revalidate_current(
                candidate.candidate_id,
                session.runtime.generation(candidate.candidate_id),
                state,
            )
            assert ready is not None
            await execute_presentation(
                context,
                session.runtime,
                ready,
                state,
                output.present,
                f"{candidate.candidate_id}:presentation",
            )
        assert {x.candidate_id for x in output.commands} == {x.candidate_id for x in candidates}
        assert {x.utterance_id for x in output.commands} == {x.utterance_id for x in candidates}
        for candidate in candidates:
            assert (
                await session.runtime.candidate(candidate.candidate_id)
            ).lifecycle is CandidateLifecycle.COMPLETED
        assert len(session.queue) == 0
    finally:
        await context.close()
    assert session.closed and session.tasks.pending_task_count == 0


@pytest.mark.asyncio
async def test_session_rejects_other_context_policy_and_closed_reuse() -> None:
    context = RunContext(POLICY)
    other = RunContext(POLICY)
    policy = settings().policy
    session = SpeechPreparationSession(context, policy, semantics.NOW)
    try:
        with pytest.raises(ValueError, match="一致"):
            session.observe(other, policy, semantics.NOW)
        with pytest.raises(ValueError, match="一致"):
            session.observe(context, replace(policy, speculative_tts_limit=0), semantics.NOW)
        await session.close()
        with pytest.raises(ValueError, match="一致"):
            session.observe(context, policy, semantics.NOW)
    finally:
        await context.close()
        await other.close()


@pytest.mark.asyncio
async def test_cancelling_one_generated_candidate_keeps_other_shared_preparation_alive() -> None:
    import asyncio

    from app.subsystems.validation.generated_audio import GeneratedAudioBindings
    from tests.subsystems.validation.test_audio_presentation import Output
    from tests.subsystems.validation.test_speculative_audio import ControlledTTS
    from tests.subsystems.validation.test_speculative_audio import settings as speculative_settings

    preparation = replace(
        speculative_settings(),
        queue_for_revalidation=False,
        validate_for_presentation=False,
        present_after_validation=False,
    )
    context = RunContext(replace(POLICY, max_tasks=64, max_intervals=128))
    session = SpeechPreparationSession(context, preparation.policy, semantics.NOW)
    client, sink = ControlledTTS(blocked=True), Output()
    verifiers = [Verification(blocking=True, accepted=True) for _ in range(2)]
    work: list[asyncio.Future[TargetObservation]] = []
    try:
        for index, verifier in enumerate(verifiers):
            targets: list[LabTarget] = []
            item, _, _, _ = setup(
                verifier=verifier.build,
                preparation=preparation,
                audio=GeneratedAudioBindings(client, sink.bind),
                preparation_session=lambda _: session,
                scenario_id=f"parallel-{index}",
                target_sink=targets,
            )
            work.append(asyncio.ensure_future(targets[0].run(context, item.fixture)))
        await asyncio.wait_for(asyncio.gather(*(v.started.wait() for v in verifiers)), 1)
        await asyncio.wait_for(client.started.wait(), 1)
        assert session.owner.active_speculative_tts_count == 1
        work[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await work[0]
        assert not work[1].done() and session.admission.active_count == 1
        verifiers[1].release.set()
        client.release.set()
        assert (await work[1]).status is RunStatus.COMPLETED
        assert session.admission.active_count == 0
        assert session.owner.active_speculative_tts_count == 0
    finally:
        for task in work:
            if not task.done():
                task.cancel()
        await asyncio.gather(*work, return_exceptions=True)
        await context.close()
    assert session.tasks.pending_task_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_next_generation_and_queue_admission_continue_during_current_presentation(
    cancel: bool,
) -> None:
    import asyncio

    from app.domain.speech_runtime.contracts import PreparedSpeechCandidate

    preparation = replace(settings(), presentation_modes=(SpeechPresentationMode.TEXT_ONLY,))
    context = RunContext(replace(POLICY, max_tasks=64, max_intervals=128))
    session = SpeechPreparationSession(context, preparation.policy, semantics.NOW)
    output = Connections(block=True)
    presenting: asyncio.Task[TargetObservation] | None = None

    async def generate(index: int) -> PreparedSpeechCandidate:
        before = set(await session.runtime.active_candidate_ids())
        targets: list[LabTarget] = []
        item, _, _, _ = setup(
            verifier=Verification(accepted=True).build,
            preparation=preparation,
            preparation_session=lambda _: session,
            scenario_id=f"overlap-{index}",
            target_sink=targets,
        )
        observed = await targets[0].run(context, item.fixture)
        assert observed.status is RunStatus.COMPLETED
        added = set(await session.runtime.active_candidate_ids()) - before
        assert len(added) == 1
        return await session.runtime.candidate(added.pop())

    async def take_and_present() -> TargetObservation:
        current = await session.queue.pop_for_revalidation()
        assert current is not None
        state = replace(await Live().current_state(current), observed_at=current.updated_at)
        ready = await session.runtime.revalidate_current(
            current.candidate_id,
            session.runtime.generation(current.candidate_id),
            state,
        )
        assert ready is not None
        return await execute_presentation(
            context,
            session.runtime,
            ready,
            state,
            output.present,
            f"{current.candidate_id}:presentation",
        )

    try:
        first = await generate(0)
        assert (
            await session.queue.enqueue_current(
                first.candidate_id, session.runtime.generation(first.candidate_id)
            )
        ).admitted
        presenting = asyncio.create_task(take_and_present())
        await asyncio.wait_for(output.started.wait(), 1)
        interval_count = len(context.intervals)
        second = await generate(1)
        second_generation = tuple(context.intervals[interval_count:])
        assert second.lifecycle is CandidateLifecycle.PREPARED
        assert (
            await session.queue.enqueue_current(
                second.candidate_id, session.runtime.generation(second.candidate_id)
            )
        ).admitted
        assert not presenting.done() and len(session.queue) == 1
        assert (
            await session.runtime.candidate(first.candidate_id)
        ).lifecycle is CandidateLifecycle.PRESENTING
        assert (
            await session.runtime.candidate(second.candidate_id)
        ).lifecycle is CandidateLifecycle.QUEUED
        if cancel:
            presenting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await presenting
            assert len(output.commands) == 1 and output.closed.is_set()
        else:
            output.release.set()
            assert (await presenting).status is RunStatus.COMPLETED
            assert (await take_and_present()).status is RunStatus.COMPLETED
            assert [x.candidate_id for x in output.commands] == [
                first.candidate_id,
                second.candidate_id,
            ]
        first_presentation = next(
            x for x in context.intervals if x.stage == "speech.presentation_reports"
        )
        generated_stages = {x.stage for x in second_generation}
        assert {
            "speech_semantics.plan",
            "speech.character",
            "speech.verifier_entry",
            "speech.preparation_commit",
        } <= generated_stages
        assert all(
            first_presentation.started_ns
            <= x.started_ns
            < x.completed_ns
            <= first_presentation.completed_ns
            for x in second_generation
        )
    finally:
        if presenting is not None:
            presenting.cancel()
            await asyncio.gather(presenting, return_exceptions=True)
        await context.close()
    assert len(session.queue) == session.tasks.pending_task_count == 0
