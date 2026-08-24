from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from app.adapters.tts import (
    CandidateArtifactStore,
    PreparedAudioArtifact,
    PronunciationOverrideView,
    ProviderSynthesisInput,
    TTSCapabilityView,
    TTSProviderAdapter,
    TTSProviderMappingPolicy,
    TTSProviderResponse,
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
from app.adapters.tts.provider import ProviderTimingUnit, TTSProviderError
from app.domain.speech_performance import SpeechPerformancePlanner
from app.domain.speech_performance.contracts import (
    PerformanceAxis,
    PerformanceIntentDelta,
    PerformanceIntentVector,
    PitchAnchor,
)
from app.domain.speech_performance.policy import yura_revision_1_policy
from tests.domain.semantic_verification.test_semantic_verification import _utterance

NOW = datetime(2026, 8, 24, tzinfo=timezone.utc)


class FakeTTS:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, tuple[str, ...], ProviderSynthesisInput]] = []

    async def synthesize(
        self, voice_ref: str, texts: tuple[str, ...], parameters: ProviderSynthesisInput
    ) -> TTSProviderResponse:
        self.calls.append((voice_ref, texts, parameters))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, TTSProviderResponse)
        return outcome


def _response(
    *,
    raw_audio_ref: str = "memory://audio",
    duration_ms: int | None = None,
    timing_units: tuple[ProviderTimingUnit, ...] = (),
) -> TTSProviderResponse:
    return TTSProviderResponse(raw_audio_ref, "wav", "digest", duration_ms, timing_units)


def _policy(
    *, max_attempts: int = 2, retry_backoff_seconds: float = 0.0
) -> TTSProviderMappingPolicy:
    base = TTSProviderMappingPolicy.revision_1()
    return TTSProviderMappingPolicy(
        base.provider_config_revision,
        max_attempts,
        base.timeout_seconds,
        base.global_ranges,
        base.boundary_strength_range,
        base.phrase_pause_range,
        base.duration_bias_range,
        base.emphasis_strength_range,
        base.hesitation_strength_range,
        base.pitch_anchor_range,
        retry_backoff_seconds,
        base.max_foreground_synthesis,
        base.max_speculative_synthesis,
        base.retryable_failure_codes,
    )


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
    client = FakeTTS([_response()])
    result = await TTSProviderAdapter(client, _policy(), now=lambda: NOW).synthesize(request)
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
            _response(),
        ]
    )
    result = await TTSProviderAdapter(client, _policy(), now=lambda: NOW).synthesize(request)
    assert result.status is TTSSynthesisStatus.SUCCEEDED and result.attempts == 2
    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_non_retryable_failure_and_timeout_are_typed() -> None:
    request = _request()
    rejected = await TTSProviderAdapter(
        FakeTTS([TTSProviderError(TTSFailureCode.PROVIDER_REJECTED, False)]),
        _policy(),
        now=lambda: NOW,
    ).synthesize(request)
    assert rejected.failure_code is TTSFailureCode.PROVIDER_REJECTED and rejected.attempts == 1
    timed_out = await TTSProviderAdapter(
        FakeTTS([asyncio.TimeoutError()]), _policy(), now=lambda: NOW
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
        FakeTTS([_response()]),
        _policy(max_attempts=1),
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
    client = FakeTTS([_response()])
    await TTSProviderAdapter(client, _policy(max_attempts=1), now=lambda: NOW).synthesize(request)
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
    client = FakeTTS([_response()])
    result = await TTSProviderAdapter(client, _policy(max_attempts=1), now=lambda: NOW).synthesize(
        request
    )
    assert result.status is TTSSynthesisStatus.SUCCEEDED
    assert TTSDegradationReason.UNSUPPORTED_DIMENSION in result.degradation_reasons
    assert {"pace", "pitch_center", "breathiness"} <= set(result.degraded_dimensions)
    assert client.calls[0][2].global_parameters == ()
    assert request.performance_plan is plan


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("axis", "dimension"),
    (
        (PerformanceAxis.PACE, "pace"),
        (PerformanceAxis.PITCH_CENTER, "pitch_center"),
        (PerformanceAxis.BREATHINESS, "breathiness"),
    ),
)
async def test_each_unsupported_provider_dimension_is_identified(
    axis: PerformanceAxis, dimension: str
) -> None:
    request = _request()
    if axis is PerformanceAxis.PACE:
        capability = replace(request.capability, supports_rate=False)
    elif axis is PerformanceAxis.PITCH_CENTER:
        capability = replace(request.capability, supports_pitch_center=False)
    else:
        capability = replace(request.capability, supports_breathiness=False)
    plan = replace(
        request.performance_plan,
        global_intent=PerformanceIntentVector(
            tuple(
                (current_axis, 0.5 if current_axis is axis else value)
                for current_axis, value in request.performance_plan.global_intent.values
            )
        ),
    )
    result = await TTSProviderAdapter(
        FakeTTS([_response()]), _policy(max_attempts=1), now=lambda: NOW
    ).synthesize(replace(request, capability=capability, performance_plan=plan))
    assert dimension in result.degraded_dimensions
    assert dimension not in result.applied_dimensions


@pytest.mark.asyncio
async def test_provider_mapping_projects_normalized_values_to_configured_ranges() -> None:
    request = _request()
    plan = replace(
        request.performance_plan,
        global_intent=PerformanceIntentVector(
            tuple(
                (axis, 1.0 if axis is PerformanceAxis.PACE else value)
                for axis, value in request.performance_plan.global_intent.values
            )
        ),
    )
    client = FakeTTS([_response()])
    await TTSProviderAdapter(client, _policy(max_attempts=1), now=lambda: NOW).synthesize(
        replace(request, performance_plan=plan)
    )
    assert dict(client.calls[0][2].global_parameters)["pace"] == 100.0


@pytest.mark.asyncio
async def test_segment_performance_maps_to_versioned_provider_input_and_uses_phrase_pause() -> None:
    capability = replace(
        _request().capability,
        supports_phrase_pause=True,
        supports_pitch_center=True,
        supports_pitch_range=True,
        supports_loudness=True,
        supports_breathiness=True,
    )
    request = _request(capability=capability)
    original = request.performance_plan.segments[0]
    segment = replace(
        original,
        boundary_strength=0.5,
        pause_after_intent=0.6,
        duration_bias=0.7,
        emphasis_strength=0.8,
        hesitation_strength=0.9,
        local_intent_delta=PerformanceIntentDelta(((PerformanceAxis.PACE, 0.4),)),
        pitch_anchors=(PitchAnchor(0.5, 0.3, 0.8),),
    )
    client = FakeTTS([_response()])
    await TTSProviderAdapter(client, _policy(max_attempts=1), now=lambda: NOW).synthesize(
        replace(request, performance_plan=replace(request.performance_plan, segments=(segment,)))
    )
    mapped = client.calls[0][2].segments[0]
    assert mapped.utterance_segment_id == segment.utterance_segment_id
    assert mapped.pause_after == 600.0
    assert mapped.boundary_strength == 0.5
    assert mapped.duration_bias == pytest.approx(40.0)
    assert mapped.emphasis_strength == 0.8
    assert mapped.hesitation_strength == 0.9
    assert mapped.local_intent_parameters == (("pace", 40.0),)
    assert mapped.pitch_anchors[0].relative_pitch == 30.0


@pytest.mark.asyncio
async def test_provider_timing_is_normalized_only_when_trustworthy_units_are_returned() -> None:
    capability = replace(
        _request().capability,
        supports_phoneme_timing=True,
        supports_mora_timing=True,
        supports_viseme_timing=True,
    )
    timing = (
        ProviderTimingUnit("phoneme", "segment-1", SpeechTimingKind.PHONEME, "a", 0, 10),
        ProviderTimingUnit("mora", "segment-1", SpeechTimingKind.MORA, "あ", 10, 20),
        ProviderTimingUnit("viseme", "segment-1", SpeechTimingKind.VISEME, "A", 20, 30),
        ProviderTimingUnit("word", "segment-1", SpeechTimingKind.WORD_BOUNDARY, "語", 30, 40),
    )
    result = await TTSProviderAdapter(
        FakeTTS([_response(duration_ms=40, timing_units=timing)]),
        _policy(max_attempts=1),
        now=lambda: NOW,
    ).synthesize(_request(capability=capability))
    assert result.timing_track is not None
    assert tuple(unit.kind for unit in result.timing_track.units) == tuple(
        unit.kind for unit in timing
    )
    assert TTSDegradationReason.TIMING_UNAVAILABLE not in result.degradation_reasons


@pytest.mark.asyncio
async def test_secret_bearing_provider_audio_ref_is_normalized_before_public_artifact() -> None:
    result = await TTSProviderAdapter(
        FakeTTS([_response(raw_audio_ref="https://example.invalid/audio?token=VERY_SECRET")]),
        _policy(max_attempts=1),
        now=lambda: NOW,
    ).synthesize(_request())
    assert result.artifact is not None
    assert result.artifact.audio_ref.startswith("artifact://prepared/")
    assert "VERY_SECRET" not in result.artifact.audio_ref
    assert "VERY_SECRET" not in repr(result)


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
            _policy(max_attempts=1),
            now=lambda: NOW,
        ).synthesize(request)
        assert result.failure_code is code and result.artifact is None

    class LeakingProvider:
        async def synthesize(
            self, voice_ref: str, texts: tuple[str, ...], parameters: ProviderSynthesisInput
        ) -> TTSProviderResponse:
            raise RuntimeError("Authorization: Bearer secret-token https://secret.example/raw-body")

    result = await TTSProviderAdapter(
        LeakingProvider(), _policy(max_attempts=1), now=lambda: NOW
    ).synthesize(request)
    assert result.failure_code is TTSFailureCode.PROVIDER_SERVER_ERROR
    assert "secret-token" not in repr(result)


@pytest.mark.asyncio
async def test_cancellation_during_call_and_retry_wait_is_typed_and_bounded() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingProvider:
        async def synthesize(
            self, voice_ref: str, texts: tuple[str, ...], parameters: ProviderSynthesisInput
        ) -> TTSProviderResponse:
            entered.set()
            await release.wait()
            return _response()

    adapter = TTSProviderAdapter(BlockingProvider(), _policy(), now=lambda: NOW)
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
        _policy(retry_backoff_seconds=1),
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
            self, voice_ref: str, texts: tuple[str, ...], parameters: ProviderSynthesisInput
        ) -> TTSProviderResponse:
            if voice_ref == "speculative":
                speculative_entered.set()
                await speculative_release.wait()
            else:
                foreground_entered.set()
            return _response()

    adapter = TTSProviderAdapter(PriorityProvider(), _policy(max_attempts=1), now=lambda: NOW)
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
            self, voice_ref: str, texts: tuple[str, ...], parameters: ProviderSynthesisInput
        ) -> TTSProviderResponse:
            if voice_ref == "candidate-a":
                candidate_a_entered.set()
                await candidate_a_release.wait()
            return _response()

    adapter = TTSProviderAdapter(IndependentProvider(), _policy(max_attempts=1), now=lambda: NOW)
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
        FakeTTS([_response()]),
        _policy(max_attempts=1),
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
