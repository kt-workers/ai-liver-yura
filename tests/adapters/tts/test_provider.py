from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.adapters.tts import (
    CandidateArtifactStore,
    PreparedAudioArtifact,
    PronunciationOverrideView,
    TTSCapabilityView,
    TTSProviderAdapter,
    TTSProviderMappingPolicy,
    TTSSynthesisPriority,
    TTSSynthesisRequest,
    TTSVoiceBinding,
    synthesis_cache_identity,
)
from app.adapters.tts.contracts import (
    SpeechTimingKind,
    SpeechTimingTrack,
    SpeechTimingUnit,
    TTSDegradationReason,
    TTSFailureCode,
    TTSSynthesisStatus,
)
from app.adapters.tts.provider import TTSProviderError
from app.domain.speech_performance import SpeechPerformancePlanner
from app.domain.speech_performance.contracts import PerformanceAxis, PerformanceIntentVector
from app.domain.speech_performance.policy import yura_revision_1_policy
from tests.domain.semantic_verification.test_semantic_verification import _utterance

NOW = datetime(2026, 8, 24, tzinfo=timezone.utc)


class FakeTTS:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, tuple[str, ...], dict[str, float]]] = []

    async def synthesize(
        self, voice_ref: str, texts: tuple[str, ...], parameters: dict[str, float]
    ) -> tuple[str, str, str, int | None]:
        self.calls.append((voice_ref, texts, parameters))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, tuple)
        return outcome


def _request(
    *,
    capability: TTSCapabilityView | None = None,
    text: str = "表示文は変えない",
    overrides: tuple[PronunciationOverrideView, ...] = (),
    priority: TTSSynthesisPriority = TTSSynthesisPriority.FOREGROUND,
) -> TTSSynthesisRequest:
    utterance = _utterance(text=text)
    plan = SpeechPerformancePlanner(yura_revision_1_policy()).plan(
        "performance-plan", utterance, None, None, NOW
    )
    binding = TTSVoiceBinding("binding", "yura", "fake", "voice-1", 1, "ja-JP", True)
    capability = capability or TTSCapabilityView(
        "fake", 1, 1, True, False, False, False, False, False, False, False, False, False, False
    )
    return TTSSynthesisRequest(
        "request",
        "candidate",
        utterance,
        plan,
        binding,
        capability,
        overrides,
        1,
        1,
        priority,
        NOW,
        "trace",
    )


@pytest.mark.asyncio
async def test_success_preserves_text_and_never_fabricates_timing() -> None:
    request = _request()
    client = FakeTTS([("memory://audio", "wav", "digest", None)])
    result = await TTSProviderAdapter(
        client, TTSProviderMappingPolicy(1, 2, 1), now=lambda: NOW
    ).synthesize(request)
    assert result.status is TTSSynthesisStatus.SUCCEEDED
    assert result.artifact is not None and result.timing_track is None
    assert TTSDegradationReason.TIMING_UNAVAILABLE in result.degradation_reasons
    assert request.utterance.candidate.segments[0].text == "表示文は変えない"


@pytest.mark.asyncio
async def test_retryable_failure_is_bounded_and_raw_error_is_not_exposed() -> None:
    request = _request()
    client = FakeTTS(
        [
            TTSProviderError(TTSFailureCode.PROVIDER_UNAVAILABLE, True),
            ("memory://audio", "wav", "digest", None),
        ]
    )
    result = await TTSProviderAdapter(
        client, TTSProviderMappingPolicy(1, 2, 1), now=lambda: NOW
    ).synthesize(request)
    assert result.status is TTSSynthesisStatus.SUCCEEDED and result.attempts == 2
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_non_retryable_failure_and_timeout_are_typed() -> None:
    request = _request()
    rejected = await TTSProviderAdapter(
        FakeTTS([TTSProviderError(TTSFailureCode.PROVIDER_REJECTED, False)]),
        TTSProviderMappingPolicy(1, 2, 1),
        now=lambda: NOW,
    ).synthesize(request)
    assert rejected.failure_code is TTSFailureCode.PROVIDER_REJECTED and rejected.attempts == 1
    timed_out = await TTSProviderAdapter(
        FakeTTS([asyncio.TimeoutError()]), TTSProviderMappingPolicy(1, 2, 1), now=lambda: NOW
    ).synthesize(request)
    assert timed_out.failure_code is TTSFailureCode.REQUEST_TIMEOUT


@pytest.mark.asyncio
async def test_unsupported_dimension_is_degraded_without_changing_plan() -> None:
    request = _request()
    plan = replace(
        request.performance_plan,
        global_intent=PerformanceIntentVector(
            tuple(
                (axis, 0.5 if axis is PerformanceAxis.PITCH_CENTER else value)
                for axis, value in request.performance_plan.global_intent.values
            )
        ),
    )
    request = replace(request, performance_plan=plan)
    original = request.performance_plan.global_intent
    result = await TTSProviderAdapter(
        FakeTTS([("memory://audio", "wav", "digest", None)]),
        TTSProviderMappingPolicy(1, 1, 1),
        now=lambda: NOW,
    ).synthesize(request)
    assert request.performance_plan.global_intent == original
    assert TTSDegradationReason.UNSUPPORTED_DIMENSION in result.degradation_reasons


def test_cache_identity_includes_performance_and_configuration() -> None:
    request = _request()
    assert synthesis_cache_identity(request) != synthesis_cache_identity(
        replace(request, provider_config_revision=2)
    )
    assert synthesis_cache_identity(request) != synthesis_cache_identity(
        replace(
            request, performance_plan=replace(request.performance_plan, performance_plan_id="other")
        )
    )


def test_timing_track_rejects_non_monotonic_provider_timing() -> None:
    units = (
        SpeechTimingUnit("unit-1", "segment-1", SpeechTimingKind.PHONEME, "a", 0, 10),
        SpeechTimingUnit("unit-2", "segment-1", SpeechTimingKind.PHONEME, "i", 10, 20),
    )
    assert SpeechTimingTrack("track", "artifact", units, NOW).units == units
    with pytest.raises(ValueError, match="単調"):
        SpeechTimingTrack(
            "track",
            "artifact",
            (
                SpeechTimingUnit("unit-1", "segment-1", SpeechTimingKind.PHONEME, "a", 0, 10),
                SpeechTimingUnit("unit-2", "segment-1", SpeechTimingKind.MORA, "あ", 5, 20),
            ),
            NOW,
        )


def test_request_rejects_mismatched_or_unavailable_binding() -> None:
    request = _request()
    with pytest.raises(ValueError, match="Character"):
        replace(request, voice_binding=replace(request.voice_binding, character_id="other"))
    with pytest.raises(ValueError, match="利用不能"):
        replace(request, voice_binding=replace(request.voice_binding, enabled=False))


def test_request_rejects_mismatched_performance_plan_and_unknown_override() -> None:
    request = _request()
    with pytest.raises(ValueError, match="utterance"):
        replace(request, performance_plan=replace(request.performance_plan, utterance_id="other"))
    with pytest.raises(ValueError, match="存在しません"):
        _request(
            overrides=(
                PronunciationOverrideView("override", "未知語", "みちご", "ja-JP", "config", 1),
            )
        )
    with pytest.raises(ValueError, match="変更"):
        PronunciationOverrideView("override", "表示", "表示", "ja-JP", "config", 1)


@pytest.mark.asyncio
async def test_pronunciation_changes_provider_reading_only_and_revision_changes_cache() -> None:
    override = PronunciationOverrideView("override", "表示文", "ひょうじぶん", "ja-JP", "config", 1)
    request = _request(
        capability=TTSCapabilityView(
            "fake", 1, 1, True, False, False, False, False, False, True, False, False, False, False
        ),
        overrides=(override,),
    )
    client = FakeTTS([("memory://audio", "wav", "digest", None)])
    await TTSProviderAdapter(client, TTSProviderMappingPolicy(1, 1, 1), now=lambda: NOW).synthesize(
        request
    )
    assert client.calls[0][1] == ("ひょうじぶんは変えない",)
    assert request.utterance.candidate.segments[0].text == "表示文は変えない"
    assert synthesis_cache_identity(request) != synthesis_cache_identity(
        replace(request, pronunciation_overrides=(replace(override, revision=2),))
    )
    assert synthesis_cache_identity(request) != synthesis_cache_identity(
        replace(request, pronunciation_config_revision=2)
    )


@pytest.mark.asyncio
async def test_unsupported_rate_pitch_and_breathiness_are_omitted_but_audio_succeeds() -> None:
    capability = TTSCapabilityView(
        "fake", 1, 1, False, False, False, False, False, False, False, False, False, False, False
    )
    request = _request(capability=capability)
    plan = replace(
        request.performance_plan,
        global_intent=PerformanceIntentVector(
            tuple(
                (
                    axis,
                    0.5
                    if axis
                    in {
                        PerformanceAxis.PACE,
                        PerformanceAxis.PITCH_CENTER,
                        PerformanceAxis.BREATHINESS,
                    }
                    else value,
                )
                for axis, value in request.performance_plan.global_intent.values
            )
        ),
    )
    request = replace(request, performance_plan=plan)
    client = FakeTTS([("memory://audio", "wav", "digest", None)])
    result = await TTSProviderAdapter(
        client, TTSProviderMappingPolicy(1, 1, 1), now=lambda: NOW
    ).synthesize(request)
    assert result.status is TTSSynthesisStatus.SUCCEEDED
    assert TTSDegradationReason.UNSUPPORTED_DIMENSION in result.degradation_reasons
    assert client.calls[0][2] == {}
    assert request.performance_plan is plan


def test_provider_mapping_clamps_normalized_values_at_adapter_boundary() -> None:
    capability = TTSCapabilityView(
        "fake", 1, 1, True, True, False, False, True, False, False, False, False, False, False
    )
    parameters, _ = TTSProviderAdapter._map(
        capability,
        (
            (PerformanceAxis.PACE, 4.0),
            (PerformanceAxis.PITCH_CENTER, -4.0),
            (PerformanceAxis.BREATHINESS, 2.0),
        ),
    )
    assert parameters == {"pace": 1.0, "pitch_center": -1.0, "breathiness": 1.0}


def test_timing_supports_monotonic_phoneme_mora_and_viseme_and_rejects_duration_overrun() -> None:
    units = (
        SpeechTimingUnit("unit-1", "segment-1", SpeechTimingKind.PHONEME, "a", 0, 10),
        SpeechTimingUnit("unit-2", "segment-1", SpeechTimingKind.MORA, "あ", 10, 20),
        SpeechTimingUnit("unit-3", "segment-1", SpeechTimingKind.VISEME, "A", 20, 30),
    )
    assert SpeechTimingTrack("track", "artifact", units, NOW, 30).units == units
    with pytest.raises(ValueError, match="duration"):
        SpeechTimingTrack("track", "artifact", units, NOW, 29)


@pytest.mark.asyncio
async def test_all_failure_categories_are_typed_and_raw_provider_secrets_do_not_leak() -> None:
    request = _request()
    for code in (
        TTSFailureCode.PROVIDER_UNAVAILABLE,
        TTSFailureCode.RATE_LIMITED,
        TTSFailureCode.PROVIDER_SERVER_ERROR,
        TTSFailureCode.PROVIDER_REJECTED,
        TTSFailureCode.AUDIO_DECODE_OR_STORAGE_FAILED,
    ):
        result = await TTSProviderAdapter(
            FakeTTS([TTSProviderError(code, False)]),
            TTSProviderMappingPolicy(1, 1, 1),
            now=lambda: NOW,
        ).synthesize(request)
        assert result.failure_code is code and result.artifact is None

    class LeakingProvider:
        async def synthesize(
            self, voice_ref: str, texts: tuple[str, ...], parameters: dict[str, float]
        ) -> tuple[str, str, str, int | None]:
            raise RuntimeError("Authorization: Bearer secret-token https://secret.example/raw-body")

    result = await TTSProviderAdapter(
        LeakingProvider(), TTSProviderMappingPolicy(1, 1, 1), now=lambda: NOW
    ).synthesize(request)
    assert result.failure_code is TTSFailureCode.PROVIDER_SERVER_ERROR
    assert "secret-token" not in repr(result)


@pytest.mark.asyncio
async def test_cancellation_during_call_and_retry_wait_is_typed_and_bounded() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingProvider:
        async def synthesize(
            self, voice_ref: str, texts: tuple[str, ...], parameters: dict[str, float]
        ) -> tuple[str, str, str, int | None]:
            entered.set()
            await release.wait()
            return "memory://audio", "wav", "digest", None

    adapter = TTSProviderAdapter(
        BlockingProvider(), TTSProviderMappingPolicy(1, 2, 1), now=lambda: NOW
    )
    task = asyncio.create_task(adapter.synthesize(_request()))
    await entered.wait()
    task.cancel()
    assert (await task).failure_code is TTSFailureCode.CANCELLED
    assert adapter.pending_task_count == 0


@pytest.mark.asyncio
async def test_cancellation_during_retry_wait_and_shutdown_settles_all_tasks() -> None:
    retry_entered = asyncio.Event()
    retry_release = asyncio.Event()

    async def waiting_sleep(seconds: float) -> None:
        retry_entered.set()
        await retry_release.wait()

    adapter = TTSProviderAdapter(
        FakeTTS([TTSProviderError(TTSFailureCode.RATE_LIMITED, True)]),
        TTSProviderMappingPolicy(1, 2, 1, retry_backoff_seconds=1),
        now=lambda: NOW,
        sleep=waiting_sleep,
    )
    task = asyncio.create_task(adapter.synthesize(_request()))
    await retry_entered.wait()
    await adapter.shutdown()
    assert (await task).failure_code is TTSFailureCode.CANCELLED
    assert adapter.pending_task_count == 0


def test_candidate_scoped_artifact_discard_blocks_verifier_rejected_or_superseded_reuse() -> None:
    artifact = PreparedAudioArtifact(
        "artifact",
        "request",
        "candidate-a",
        "utterance",
        "plan",
        "binding",
        1,
        1,
        1,
        1,
        "memory://audio",
        "wav",
        "digest",
        NOW,
    )
    store = CandidateArtifactStore()
    store.retain(artifact)
    assert store.current_artifact("candidate-a") == artifact
    assert store.discard("candidate-a") is TTSDegradationReason.ARTIFACT_DISCARDED
    assert store.current_artifact("candidate-a") is None
    store.retain(artifact)
    assert store.current_artifact("candidate-a") is None


def test_request_rejects_unknown_and_duplicate_performance_segment_mapping() -> None:
    request = _request()
    original = request.performance_plan.segments[0]
    unknown = replace(original, utterance_segment_id="unknown-segment")
    with pytest.raises(ValueError, match="mapping"):
        replace(request, performance_plan=replace(request.performance_plan, segments=(unknown,)))
    with pytest.raises(ValueError, match="一対一"):
        replace(request.performance_plan, segments=(original, original))


@pytest.mark.asyncio
async def test_speculative_does_not_starve_foreground_or_block_unrelated_coroutine() -> None:
    speculative_entered = asyncio.Event()
    speculative_release = asyncio.Event()
    foreground_entered = asyncio.Event()

    class PriorityProvider:
        async def synthesize(
            self, voice_ref: str, texts: tuple[str, ...], parameters: dict[str, float]
        ) -> tuple[str, str, str, int | None]:
            if voice_ref == "speculative":
                speculative_entered.set()
                await speculative_release.wait()
            else:
                foreground_entered.set()
            return "memory://audio", "wav", "digest", None

    adapter = TTSProviderAdapter(
        PriorityProvider(), TTSProviderMappingPolicy(1, 1, 1), now=lambda: NOW
    )
    speculative = asyncio.create_task(
        adapter.synthesize(
            replace(
                _request(priority=TTSSynthesisPriority.SPECULATIVE),
                voice_binding=replace(_request().voice_binding, provider_voice_ref="speculative"),
            )
        )
    )
    await speculative_entered.wait()
    heartbeat = asyncio.Event()

    async def tick() -> None:
        heartbeat.set()

    foreground = asyncio.create_task(adapter.synthesize(_request()))
    await tick()
    await foreground_entered.wait()
    assert heartbeat.is_set()
    speculative_release.set()
    assert (await foreground).status is TTSSynthesisStatus.SUCCEEDED
    assert (await speculative).status is TTSSynthesisStatus.SUCCEEDED
    assert adapter.pending_task_count == 0


@pytest.mark.asyncio
async def test_cancelling_candidate_a_does_not_cancel_unrelated_candidate_b() -> None:
    candidate_a_entered = asyncio.Event()
    candidate_a_release = asyncio.Event()

    class IndependentProvider:
        async def synthesize(
            self, voice_ref: str, texts: tuple[str, ...], parameters: dict[str, float]
        ) -> tuple[str, str, str, int | None]:
            if voice_ref == "candidate-a":
                candidate_a_entered.set()
                await candidate_a_release.wait()
            return "memory://audio", "wav", "digest", None

    adapter = TTSProviderAdapter(
        IndependentProvider(), TTSProviderMappingPolicy(1, 1, 1), now=lambda: NOW
    )
    candidate_a = _request(priority=TTSSynthesisPriority.SPECULATIVE)
    candidate_a = replace(
        candidate_a,
        candidate_id="candidate-a",
        voice_binding=replace(candidate_a.voice_binding, provider_voice_ref="candidate-a"),
    )
    running_a = asyncio.create_task(adapter.synthesize(candidate_a))
    await candidate_a_entered.wait()
    result_b = await adapter.synthesize(_request())
    running_a.cancel()
    assert (await running_a).failure_code is TTSFailureCode.CANCELLED
    assert result_b.status is TTSSynthesisStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_prepared_audio_is_not_playback_or_actual_speech_fact() -> None:
    result = await TTSProviderAdapter(
        FakeTTS([("memory://audio", "wav", "digest", None)]),
        TTSProviderMappingPolicy(1, 1, 1),
        now=lambda: NOW,
    ).synthesize(_request(priority=TTSSynthesisPriority.SPECULATIVE))
    assert result.status is TTSSynthesisStatus.SUCCEEDED
    assert not hasattr(result, "playback_started")
    assert not hasattr(result, "actual_speech_fact")


def test_architecture_does_not_reverse_provider_values_or_own_presentation_or_actual_speech() -> (
    None
):
    domain_text = ("app/domain/speech_performance/contracts.py").replace("app/", "")
    import pathlib

    domain = pathlib.Path("app/domain/speech_performance/contracts.py").read_text()
    adapter = pathlib.Path("app/adapters/tts/provider.py").read_text()
    assert "provider_voice_ref" not in domain
    assert "app.domain.presentation" not in adapter
    assert "app.domain.body" not in adapter
    assert "ActualSpeechFact" not in adapter
    assert domain_text == "domain/speech_performance/contracts.py"
