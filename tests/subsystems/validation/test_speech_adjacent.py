"""実際の発話生成結果の引継ぎ、並行処理、取消時の回収を検証する。"""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.character.contracts import CharacterLanguageProfile, CharacterVoiceStyleProfile
from app.domain.character_language import (
    CharacterLanguageAuthority,
    CharacterLanguageContextSnapshot,
    CharacterLanguageRealizer,
)
from app.domain.llm import LLMInterruptibility, LLMPriority, LLMRoleRequest, LLMRoleResult
from app.domain.semantic_verification import (
    BLIND_ROLE_ID,
    SemanticVerificationAuthority,
    SemanticVerificationContextSnapshot,
    SemanticVerifier,
)
from app.domain.speech_performance import SpeechPerformancePlanner
from app.domain.speech_performance.policy import yura_revision_1_policy
from app.subsystems.validation.contracts import (
    Gate,
    LabMode,
    LabRunSpec,
    RunStatus,
    ValidationFixture,
)
from app.subsystems.validation.runtime import RunContext, ValidationRunner
from app.subsystems.validation.speech_adjacent import (
    SpeechAdjacentBindings,
    SpeechAdjacentCase,
    speech_adjacent_target,
)
from tests.domain.character_language import test_character_language as character
from tests.domain.semantic_verification import test_semantic_verification as semantic
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_runtime import POLICY, PROVENANCE


def case() -> SpeechAdjacentCase:
    snapshot = CharacterLanguageContextSnapshot(
        "character-input",
        semantic._semantic_plan(),
        CharacterLanguageProfile("yura", 1, 1, ()),
        (),
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        semantic.NOW,
        "trace",
    )
    fixture = ValidationFixture(
        "speech",
        "1",
        None,
        {"situation": "楽しさを尋ねられ、今の感覚を控えめに伝える模擬会話"},
    )
    value = SpeechAdjacentCase(
        fixture,
        snapshot,
        CharacterVoiceStyleProfile("yura", 1, 1, ()),
        None,
        semantic.NOW,
    )
    return replace(value, fixture=replace(fixture, typed_inputs=value.typed_inputs()))


def spec() -> LabRunSpec:
    return LabRunSpec(
        "speech-run",
        "speech",
        LabMode.ADJACENT,
        "speech_adjacent",
        "1",
        "speech",
        "1",
        (),
        1,
        semantic.NOW,
    )


class CharacterPort:
    def __init__(self, snapshot: CharacterLanguageContextSnapshot) -> None:
        self.snapshot = snapshot

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        candidate = character.candidate(self.snapshot, text=semantic.TEXT, refs=("prop-required",))
        return replace(
            character.result_for(request, character.candidate_payload(candidate)),
            started_at=semantic.NOW,
            completed_at=semantic.NOW + timedelta(seconds=1),
        )


class Connections:
    def __init__(self, *, blocking: bool = False) -> None:
        self.blocking = blocking
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.snapshots: list[SemanticVerificationContextSnapshot] = []
        self.contexts: list[RunContext] = []

    def realizer(
        self,
        context: RunContext,
        snapshot: CharacterLanguageContextSnapshot,
    ) -> CharacterLanguageRealizer:
        self.contexts.append(context)
        return CharacterLanguageRealizer(
            CharacterPort(snapshot),
            character._LiveState(character.current(snapshot)),
            CharacterLanguageAuthority(),
            character.policy(),
        )

    def verifier(
        self,
        context: RunContext,
        snapshot: SemanticVerificationContextSnapshot,
    ) -> SemanticVerifier:
        self.snapshots.append(snapshot)
        parent = self

        class Port(semantic._SequencePort):
            async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
                if request.role_id == BLIND_ROLE_ID and parent.blocking:
                    parent.started.set()
                    try:
                        await parent.release.wait()
                    except asyncio.CancelledError:
                        parent.cancelled.set()
                        raise
                return await super().invoke(request)

        return SemanticVerifier(
            Port(snapshot),
            semantic._LiveState(snapshot),
            SemanticVerificationAuthority(),
            semantic.verification_policy(),
        )

    def runner(self, item: SpeechAdjacentCase) -> ValidationRunner:
        bindings = SpeechAdjacentBindings(
            self.realizer,
            self.verifier,
            SpeechPerformancePlanner(yura_revision_1_policy()),
        )
        target = speech_adjacent_target((item,), bindings, PROVENANCE, "1", ())
        return ValidationRunner((target,), POLICY)


@pytest.mark.asyncio
async def test_generated_utterance_reaches_both_production_owners_and_repeats_are_distinct() -> (
    None
):
    item, connections = case(), Connections()
    runner = connections.runner(item)
    result = await runner.run(replace(spec(), repeat_count=2), item.fixture)
    assert result.status is RunStatus.COMPLETED
    assert result.machine_gate is Gate.NOT_RUN
    assert len(connections.snapshots) == 2
    assert len({s.utterance.utterance_id for s in connections.snapshots}) == 2
    for stage, snapshot in zip(result.stage_results, connections.snapshots, strict=True):
        output = stage.typed_outputs
        assert value_at(output, "utterance", "utterance_id") == snapshot.utterance.utterance_id
        assert (
            value_at(output, "performance_plan", "utterance_id") == snapshot.utterance.utterance_id
        )
        assert value_at(output, "verification", "acceptance", "state") == "accepted"
        assert value_at(output, "utterance", "candidate", "segments", 0, "text") == semantic.TEXT
    encoded = result.export_json(POLICY.max_export_bytes)
    assert '"UNRATED"' in encoded
    assert "blind_result" not in encoded and "relation_result" not in encoded
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_performance_runs_while_verifier_waits_and_intervals_are_measured() -> None:
    item, connections = case(), Connections(blocking=True)
    runner = connections.runner(item)
    task = asyncio.create_task(runner.run(spec(), item.fixture))
    await asyncio.wait_for(connections.started.wait(), 0.5)
    context = connections.contexts[0]
    # 検証の待機開始前から予約された表現計画は、この時点までに完了している。
    assert any(i.stage == "speech.performance" for i in context.intervals)
    connections.release.set()
    result = await task
    assert result.status is RunStatus.COMPLETED
    intervals = {i.stage: i for i in result.timeline}
    assert intervals["speech.verification"].overlaps(intervals["speech.performance"])


@pytest.mark.asyncio
async def test_cancel_reaches_waiting_product_and_returns_no_live_children() -> None:
    item, connections = case(), Connections(blocking=True)
    runner = connections.runner(item)
    task = asyncio.create_task(runner.run(spec(), item.fixture))
    await asyncio.wait_for(connections.started.wait(), 0.5)
    await runner.cancel(spec().run_id)
    result = await task
    assert result.status is RunStatus.CANCELLED
    assert connections.cancelled.is_set()
    assert runner.pending_count == 0
    assert not any(
        t.get_name().startswith("validation:speech.") and not t.done() for t in asyncio.all_tasks()
    )


@pytest.mark.asyncio
async def test_input_mismatch_is_rejected_before_generation() -> None:
    item, connections = case(), Connections()
    inconsistent = replace(
        item, fixture=replace(item.fixture, typed_inputs={"other": "入力不一致"})
    )
    result = await connections.runner(inconsistent).run(spec(), inconsistent.fixture)
    assert result.status is RunStatus.BLOCKED_UPSTREAM
    assert not connections.contexts


@pytest.mark.asyncio
async def test_failed_performance_collects_waiting_verifier_without_exposing_exception() -> None:
    item, connections = case(), Connections(blocking=True)
    invalid = replace(item, voice_style=CharacterVoiceStyleProfile("other", 1, 1, ()))
    invalid = replace(
        invalid, fixture=replace(invalid.fixture, typed_inputs=invalid.typed_inputs())
    )
    runner = connections.runner(invalid)
    result = await runner.run(spec(), invalid.fixture)
    assert result.status is RunStatus.PRODUCT_FAILED
    assert connections.started.is_set() and connections.cancelled.is_set()
    assert runner.pending_count == 0
    assert result.stage_results == ()
    assert "provenance" not in str(result.blockers)


@pytest.mark.asyncio
async def test_binding_failure_remains_a_harness_failure() -> None:
    item, connections = case(), Connections()

    def broken(
        context: RunContext, snapshot: CharacterLanguageContextSnapshot
    ) -> CharacterLanguageRealizer:
        raise ValueError("試験用の非公開設定情報")

    bindings = SpeechAdjacentBindings(
        broken,
        connections.verifier,
        SpeechPerformancePlanner(yura_revision_1_policy()),
    )
    target = speech_adjacent_target((item,), bindings, PROVENANCE, "1", ())
    result = await ValidationRunner((target,), POLICY).run(spec(), item.fixture)
    assert result.status is RunStatus.HARNESS_FAILED
    assert "非公開設定" not in result.export_json(POLICY.max_export_bytes)
