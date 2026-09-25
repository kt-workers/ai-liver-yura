"""実Owner経路で並行準備と未採用音声の所有権を確認する。"""

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from app.composition.speech_preparation import (
    PendingSpeechAudioOwner,
    SpeechPreparationCleanupError,
)
from app.domain.speech_runtime.contracts import SpeechPresentationMode, TTSPreparationMode
from app.domain.speech_runtime.discard import PreparedAudioDiscarder
from app.runtime.kernel import CancellationToken
from tests.helpers.speech_path import build_speech_path


async def setup() -> Any:
    value = await build_speech_path()
    pipeline = value.pipeline
    value.discards = []
    value.presented = []
    value.started = asyncio.Event()
    value.prepared = asyncio.Event()
    value.verify_started = asyncio.Event()
    value.release_verifier = asyncio.Event()
    value.cancelled_verifier = asyncio.Event()
    value.producer_cleaned = asyncio.Event()
    value.token = CancellationToken()
    value.fail_discard = False

    class Resources:
        async def discard(self, request: Any) -> None:
            value.discards.append(request)
            if value.fail_discard:
                raise RuntimeError("非公開Provider情報")

    resources = Resources()
    pipeline.discard_port = resources
    pipeline._audio = PendingSpeechAudioOwner(resources)
    pipeline.discarder = PreparedAudioDiscarder(pipeline.runtime, resources)
    pipeline.output_modes = (SpeechPresentationMode.AUDIO_WITH_TEXT,)
    pipeline.tts_mode = TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE
    original_verifier = pipeline.verifier

    class Verifier:
        async def verify(self, *args: Any, **kwargs: Any) -> Any:
            value.verify_started.set()
            try:
                await value.release_verifier.wait()
                return await original_verifier.verify(*args, **kwargs)
            except asyncio.CancelledError:
                value.cancelled_verifier.set()
                raise

    pipeline.verifier = Verifier()

    async def output(utterance: Any, performance: Any) -> Any:
        value.started.set()
        value.prepared.set()
        return SpeechPresentationMode.AUDIO_WITH_TEXT, "audio:" + performance.performance_plan_id

    original_state = pipeline.readers.presentation

    async def state(candidate: Any) -> Any:
        current = await original_state(candidate)
        return replace(
            current,
            prepared_audio_ref=candidate.prepared_audio_ref,
            capability=replace(current.capability, audio_available=True),
        )

    class Presentation:
        async def commit_and_present(self, **kwargs: Any) -> Any:
            command = await pipeline.runtime.commit(
                kwargs["candidate_id"], kwargs["state"], kwargs["presentation_id"]
            )
            value.presented.append(command)
            return command

    pipeline.executor = Presentation()
    pipeline.readers = replace(pipeline.readers, output=output, presentation=state)
    value.key = value.decision.decision_id + ":" + value.decision.candidate.intents[0].intent_id

    def start() -> asyncio.Task[Any]:
        return asyncio.create_task(
            pipeline.execute(
                value.work,
                value.decision,
                value.decision.candidate.intents[0].intent_id,
                value.token,
            )
        )

    value.run = start
    return value


async def cleanup(value: Any) -> None:
    # 提示I/Oを置換した検証でも、採用済み資源はRuntime経路で返す。
    from app.domain.speech_runtime.discard import PreparedAudioDiscardReason

    await value.pipeline.close()
    for key in await value.pipeline.runtime.active_candidate_ids():
        await value.pipeline.discarder.discard_current(
            key,
            value.pipeline.runtime.generation(key),
            PreparedAudioDiscardReason.CANDIDATE_CANCELLED,
        )
        await value.pipeline.runtime.cancel(key)
    await value.close()


@pytest.mark.asyncio
async def test_safe_preparation_overlaps_verifier_and_only_acceptance_presents() -> None:
    v = await setup()
    task = v.run()
    try:
        await asyncio.wait_for(v.prepared.wait(), 2)
        assert v.verify_started.is_set()
        assert not v.presented
        assert v.pipeline._audio.pending_count == 1
        candidate = await v.pipeline.runtime.candidate(v.key)
        assert candidate.prepared_audio_ref is None
        assert candidate.readiness.verifier.value == "pending"
        v.release_verifier.set()
        await asyncio.wait_for(task, 2)
        assert len(v.presented) == 1
        assert v.pipeline._audio.pending_count == 0
        assert not v.discards
    finally:
        await cleanup(v)
    assert len(v.discards) == 1
    assert v.pipeline.pending_preparation_tasks == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("timing", ["before", "returned", "race"])
async def test_output_cancellation_ownership(timing: str) -> None:
    v = await setup()

    async def output(utterance: Any, performance: Any) -> Any:
        v.started.set()
        if timing in ("before", "race"):
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if timing == "before":
                    v.producer_cleaned.set()
                    raise
                # 完了と取消の競合で、正常結果が既に成立したproducerを模擬する。
                return SpeechPresentationMode.AUDIO_WITH_TEXT, "old-audio"
        return SpeechPresentationMode.AUDIO_WITH_TEXT, "old-audio"

    v.pipeline.readers = replace(v.pipeline.readers, output=output)
    task = v.run()
    await asyncio.wait_for(v.started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(v.discards) == (0 if timing == "before" else 1)
    assert not v.presented
    if v.discards:
        assert v.discards[0].audio_ref == "old-audio"
        assert v.discards[0].candidate_id == v.key
    assert v.pipeline._audio.pending_count == 0
    await cleanup(v)
    await v.pipeline.close()
    assert v.pipeline.pending_preparation_tasks == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["supersede", "stale", "commit_none", "verifier", "tts"])
async def test_failed_adoption_discards_original_audio(failure: str) -> None:
    v = await setup()
    if failure == "tts":

        async def broken_output(u: Any, p: Any) -> Any:
            v.prepared.set()
            raise ValueError("TTSの型付き失敗")

        v.pipeline.readers = replace(v.pipeline.readers, output=broken_output)
    if failure == "verifier":

        class FailedVerifier:
            async def verify(self, *args: Any, **kwargs: Any) -> Any:
                await v.release_verifier.wait()
                raise ValueError("Verifierの型付き失敗")

        v.pipeline.verifier = FailedVerifier()
    task = v.run()
    await asyncio.wait_for(v.prepared.wait(), 2)
    old = v.pipeline._audio.result(v.key, 1)
    if failure == "supersede":
        assert await v.pipeline.runtime.supersede_generation(v.key, 1) == 2
    elif failure == "stale":
        await v.pipeline.runtime.update_operational_policy(
            replace(v.pipeline.runtime.operational_policy, policy_revision=2)
        )
    elif failure == "commit_none":

        async def refuse(*args: Any, **kwargs: Any) -> None:
            return None

        v.pipeline.runtime.commit_generation_result = refuse
    v.release_verifier.set()
    with pytest.raises(ValueError):
        await task
    assert not v.presented
    if failure == "tts":
        assert not v.discards
    else:
        assert old is not None
        assert len(v.discards) == 1
        r = v.discards[0]
        assert (r.candidate_id, r.utterance_id, r.performance_plan_id, r.audio_ref) == (
            old.candidate_id,
            old.utterance_id,
            old.performance_plan_id,
            old.audio_ref,
        )
    if failure in ("supersede", "stale", "verifier"):
        assert (
            v.discards[0].reason.value
            == {
                "supersede": "candidate_superseded",
                "stale": "candidate_stale",
                "verifier": "verifier_failed",
            }[failure]
        )
    if failure == "supersede":
        assert (await v.pipeline.runtime.candidate(v.key)).lifecycle.value == "preparing"
    await cleanup(v)
    assert v.pipeline.pending_preparation_tasks == 0


@pytest.mark.asyncio
async def test_discard_failure_preserves_failure_and_cleans_tasks() -> None:
    v = await setup()
    v.fail_discard = True
    task = v.run()
    await asyncio.wait_for(v.prepared.wait(), 2)
    task.cancel()
    with pytest.raises(SpeechPreparationCleanupError) as error:
        await task
    assert error.value.terminal_reason == "candidate_cancelled"
    assert "非公開" not in str(error.value)
    assert not v.presented
    assert v.pipeline._audio.pending_count == 1
    assert v.pipeline.pending_preparation_tasks == 0
    for _ in range(2):
        with pytest.raises(SpeechPreparationCleanupError):
            await v.pipeline.close()
    assert len(v.discards) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["verifier", "output"])
async def test_shutdown_reclaims_parallel_preparation(stage: str) -> None:
    v = await setup()
    if stage == "output":

        async def output(u: Any, p: Any) -> Any:
            v.prepared.set()
            try:
                await asyncio.Event().wait()
            finally:
                v.producer_cleaned.set()

        v.pipeline.readers = replace(v.pipeline.readers, output=output)
    task = v.run()
    await asyncio.wait_for(v.prepared.wait(), 2)
    await v.pipeline.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    await v.pipeline.close()
    assert v.pipeline.pending_preparation_tasks == 0
    assert v.pipeline.admission.active_count == 0
    assert not v.presented
    await cleanup(v)


@pytest.mark.asyncio
@pytest.mark.parametrize("repair_accepts", [True, False])
async def test_repair_discards_old_audio_before_new_generation(repair_accepts: bool) -> None:
    from types import SimpleNamespace

    from app.domain.contracts.common import thaw_json
    from app.domain.llm import StructuredPayload
    from app.domain.semantic_verification import SemanticAcceptanceState, SemanticRejectionCategory

    v = await setup()
    invoke = v.port.invoke
    generated: list[str] = []
    verification_count = 0

    async def character_provider(request: Any) -> Any:
        result = await invoke(request)
        if "character" in request.role_id:
            assert result.output is not None
            payload = thaw_json(result.output.value)
            assert isinstance(payload, dict)
            payload["candidate_id"] = request.request_id + ":candidate"
            result = replace(result, output=StructuredPayload(result.output.schema_id, payload))
        return result

    v.port.invoke = character_provider

    def observe(stage: str, value: Any) -> None:
        if stage == "character_context":
            v.contexts["character"] = value
            if generated:
                assert len(v.discards) == 1
                assert value.prior_realizations == ()
        if stage == "utterance":
            v.prepared.clear()
            generated.append(value.utterance_id)

    v.pipeline.evidence_sink = observe

    class RejectionSequence:
        async def verify(self, context: Any, **kwargs: Any) -> Any:
            nonlocal verification_count
            verification_count += 1
            # この検証では採否境界だけを固定し、repairとCharacterは実Ownerを使う。
            await v.prepared.wait()
            await asyncio.sleep(0)
            accepted = repair_accepts and verification_count > 1
            return SimpleNamespace(
                acceptance=SimpleNamespace(
                    state=SemanticAcceptanceState.ACCEPTED
                    if accepted
                    else SemanticAcceptanceState.REJECTED,
                    acceptance_id=kwargs["acceptance_id"],
                    rejection_categories=()
                    if accepted
                    else (SemanticRejectionCategory.CERTAINTY_CHANGED,),
                )
            )

    v.pipeline.verifier = RejectionSequence()
    task = v.run()
    try:
        if repair_accepts:
            await asyncio.wait_for(task, 2)
            assert len(v.presented) == 1
        else:
            with pytest.raises(ValueError, match="受理"):
                await asyncio.wait_for(task, 2)
            assert not v.presented
        assert len(generated) == verification_count == 2
        assert generated[0] != generated[1]
        assert len(v.discards) == (1 if repair_accepts else 2)
        assert v.discards[0].utterance_id == generated[0]
        assert v.discards[0].reason.value == "semantic_rejected"
        assert v.pipeline._audio.pending_count == 0
    finally:
        await cleanup(v)
    assert v.pipeline.pending_preparation_tasks == 0


@pytest.mark.asyncio
async def test_explicit_deferred_policy_does_not_speculate() -> None:
    v = await setup()
    v.pipeline.tts_mode = TTSPreparationMode.AFTER_SEMANTIC_ACCEPTANCE
    task = v.run()
    await asyncio.wait_for(v.verify_started.wait(), 2)
    assert not v.started.is_set()
    v.release_verifier.set()
    await asyncio.wait_for(task, 2)
    assert v.started.is_set()
    assert len(v.presented) == 1
    await cleanup(v)


@pytest.mark.asyncio
@pytest.mark.parametrize("when", ["return", "accepted"])
async def test_token_cancellation_at_transfer_boundary(when: str) -> None:
    from app.runtime.kernel.contracts import CancellationRecord
    from tests.helpers.speech_path import now

    v = await setup()

    def cancel() -> None:
        v.token.cancel(CancellationRecord(v.key, "取消検証", now()))

    if when == "return":

        async def output(u: Any, p: Any) -> Any:
            cancel()
            return SpeechPresentationMode.AUDIO_WITH_TEXT, "unaccepted-audio"

        v.pipeline.readers = replace(v.pipeline.readers, output=output)
    else:
        original = v.pipeline.runtime.commit_generation_result

        async def commit(*args: Any, **kwargs: Any) -> Any:
            value = await original(*args, **kwargs)
            cancel()
            return value

        v.pipeline.runtime.commit_generation_result = commit
    v.release_verifier.set()
    task = v.run()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(v.discards) == 1
    assert not v.presented
    assert v.pipeline._audio.pending_count == 0
    await cleanup(v)
    assert len(v.discards) == 1


@pytest.mark.asyncio
async def test_invalid_mode_does_not_drop_received_audio() -> None:
    v = await setup()

    async def output(u: Any, p: Any) -> Any:
        return SpeechPresentationMode.TEXT_ONLY, "invalid-mode-audio"

    v.pipeline.readers = replace(v.pipeline.readers, output=output)
    v.release_verifier.set()
    with pytest.raises(ValueError, match="mode"):
        await v.run()
    assert [d.audio_ref for d in v.discards] == ["invalid-mode-audio"]
    assert not v.presented
    await cleanup(v)


@pytest.mark.asyncio
async def test_repeated_parent_cancel_joins_resource_cleanup() -> None:
    v = await setup()
    discard_started, release_discard = asyncio.Event(), asyncio.Event()

    class Resources:
        async def discard(self, request: Any) -> None:
            v.discards.append(request)
            discard_started.set()
            await release_discard.wait()

    resources = Resources()
    v.pipeline._audio = PendingSpeechAudioOwner(resources)
    task = v.run()
    await asyncio.wait_for(v.prepared.wait(), 2)
    task.cancel()
    await asyncio.wait_for(discard_started.wait(), 2)
    task.cancel()
    assert not task.done()
    release_discard.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(v.discards) == 1
    assert v.pipeline.pending_preparation_tasks == 0
    await cleanup(v)


@pytest.mark.asyncio
async def test_other_trace_progresses_on_same_pipeline_while_verifier_waits() -> None:
    from types import SimpleNamespace

    from app.domain.semantic_verification import SemanticAcceptanceState
    from tests.domain.speech_semantics.test_speech_semantics import result_for
    from tests.helpers.speech_path import now
    from tests.system_integration.test_speech_semantics_policy import speech_candidate

    v = await setup()
    captured: dict[str, Any] = {}
    original_invoke = v.port.invoke

    def observe(stage: str, value: Any) -> None:
        captured[stage] = value
        if stage == "character_context":
            v.contexts["character"] = value

    async def invoke(request: Any) -> Any:
        if request.role_id.startswith(("speech.semantics", "speech_semantics")):
            ctx = captured["semantic_context"]
            value = replace(
                speech_candidate(ctx, 0, 0),
                created_at=now(),
                candidate_id=request.request_id + ":candidate",
                self_disclosure=ctx.self_disclosure_policy,
            ).to_dict()
            value.pop("created_at", None)
            return replace(
                result_for(request, value), started_at=request.created_at, completed_at=now()
            )
        return await original_invoke(request)

    class Verifier:
        async def verify(self, context: Any, **kwargs: Any) -> Any:
            if context.trace_id != "other-trace":
                await v.release_verifier.wait()
            return SimpleNamespace(
                acceptance=SimpleNamespace(
                    state=SemanticAcceptanceState.ACCEPTED,
                    acceptance_id=kwargs["acceptance_id"],
                )
            )

    v.pipeline.evidence_sink = observe
    v.pipeline.verifier = Verifier()
    v.port.invoke = invoke
    first = v.run()
    await asyncio.wait_for(v.prepared.wait(), 2)
    intent = replace(v.decision.candidate.intents[0], intent_id="other-intent")
    decision = replace(
        v.decision,
        decision_id="other-decision",
        candidate=replace(v.decision.candidate, intents=(intent,)),
        speech_reference_resolutions=tuple(
            replace(r, intent_id=intent.intent_id) for r in v.decision.speech_reference_resolutions
        ),
    )
    work = replace(v.work, envelope=replace(v.work.envelope, trace_id="other-trace"))
    try:
        await asyncio.wait_for(
            v.pipeline.execute(work, decision, intent.intent_id, CancellationToken()), 2
        )
        assert len(v.presented) == 1
        assert not first.done()
    finally:
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        await cleanup(v)
    assert v.pipeline.pending_preparation_tasks == 0
