from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.adapters.tts import (
    CandidateArtifactStore,
    InMemoryPreparedAudioResourceStore,
    PreparedAudioArtifact,
    PronunciationOverrideView,
    ProviderSynthesisInput,
    TTSCapabilityView,
    TTSMappingDimension,
    TTSMappingMonotonicity,
    TTSParameterMappingRule,
    TTSPerformanceMappingPolicy,
    TTSProviderAdapter,
    TTSProviderOperationalPolicy,
    TTSProviderResponse,
    TTSSynthesisPriority,
    TTSSynthesisRequest,
    TTSUnitParameterMappingRule,
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
from app.runtime.lifecycle import DependencyRetryPolicy
from tests.domain.semantic_verification.test_semantic_verification import _utterance

NOW = datetime(2026, 8, 24, tzinfo=timezone.utc)


class FakeTTS:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[str, tuple[str, ...], ProviderSynthesisInput]] = []

    async def synthesize(
        self,
        voice_ref: str,
        texts: tuple[str, ...],
        parameters: ProviderSynthesisInput,
    ) -> TTSProviderResponse:
        self.calls.append((voice_ref, texts, parameters))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, TTSProviderResponse)
        return outcome


@dataclass(frozen=True)
class PolicyBundle:
    mapping: TTSPerformanceMappingPolicy
    operational: TTSProviderOperationalPolicy
    retry: DependencyRetryPolicy


def _signed(
    dimension: TTSMappingDimension,
    provider_parameter: str,
    minimum: float = -100.0,
    neutral: float = 0.0,
    maximum: float = 100.0,
) -> TTSParameterMappingRule:
    return TTSParameterMappingRule(
        dimension,
        provider_parameter,
        minimum,
        neutral,
        maximum,
        TTSMappingMonotonicity.INCREASING,
    )


def _unit(
    dimension: TTSMappingDimension,
    provider_parameter: str,
    *,
    source_neutral: float,
    minimum: float,
    neutral: float,
    maximum: float,
) -> TTSUnitParameterMappingRule:
    return TTSUnitParameterMappingRule(
        dimension,
        provider_parameter,
        0.0,
        source_neutral,
        1.0,
        minimum,
        neutral,
        maximum,
        TTSMappingMonotonicity.INCREASING,
    )


def _policy(
    *,
    max_attempts: int = 2,
    retry_backoff_seconds: float = 0.001,
    mapping_revision: int = 1,
    provider_revision: int = 1,
    timeout_seconds: float = 1.0,
) -> PolicyBundle:
    signed_rules = tuple(
        _signed(TTSMappingDimension(axis.value), axis.value)
        for axis in PerformanceAxis
    ) + (_signed(TTSMappingDimension.PITCH_ANCHOR, "pitch_anchor"),)
    unit_rules = (
        _unit(
            TTSMappingDimension.BOUNDARY_STRENGTH,
            "boundary_strength",
            source_neutral=0.5,
            minimum=0.0,
            neutral=0.5,
            maximum=1.0,
        ),
        _unit(
            TTSMappingDimension.PHRASE_PAUSE,
            "phrase_pause",
            source_neutral=0.0,
            minimum=0.0,
            neutral=0.0,
            maximum=1000.0,
        ),
        _unit(
            TTSMappingDimension.DURATION_BIAS,
            "duration_bias",
            source_neutral=0.5,
            minimum=-100.0,
            neutral=0.0,
            maximum=100.0,
        ),
        _unit(
            TTSMappingDimension.EMPHASIS_STRENGTH,
            "emphasis_strength",
            source_neutral=0.5,
            minimum=0.0,
            neutral=0.5,
            maximum=1.0,
        ),
        _unit(
            TTSMappingDimension.HESITATION_STRENGTH,
            "hesitation_strength",
            source_neutral=0.5,
            minimum=0.0,
            neutral=0.5,
            maximum=1.0,
        ),
    )
    mapping = TTSPerformanceMappingPolicy(
        "test.mapping",
        mapping_revision,
        "fake",
        provider_revision,
        signed_rules,
        unit_rules,
    )
    operational = TTSProviderOperationalPolicy(
        "test.tts",
        1,
        "fake",
        provider_revision,
        timeout_seconds,
        1,
        1,
    )
    retry = DependencyRetryPolicy(
        "test.retry",
        1,
        "fake",
        max_attempts > 1,
        max(0, max_attempts - 1),
        max(retry_backoff_seconds, 0.000001),
        2.0,
        max(retry_backoff_seconds, 0.000001) * 4.0,
        1.0,
    )
    return PolicyBundle(mapping, operational, retry)


def _adapter(
    client: Any,
    bundle: PolicyBundle | None = None,
    *,
    now: Any = None,
    sleep: Any = None,
    resource_store: Any = None,
) -> TTSProviderAdapter:
    policies = bundle or _policy()
    return TTSProviderAdapter(
        client,
        policies.mapping,
        policies.operational,
        policies.retry,
        now=now,
        sleep=sleep,
        resource_store=resource_store,
    )


def _response(
    *,
    raw_audio_ref: str = "memory://audio",
    duration_ms: int | None = None,
    timing_units: tuple[ProviderTimingUnit, ...] = (),
) -> TTSProviderResponse:
    return TTSProviderResponse(raw_audio_ref, "wav", "digest", duration_ms, timing_units)


def _request(
    *,
    bundle: PolicyBundle | None = None,
    capability: TTSCapabilityView | None = None,
    text: str = "表示文は変えない",
    overrides: tuple[PronunciationOverrideView, ...] = (),
    priority: TTSSynthesisPriority = TTSSynthesisPriority.FOREGROUND,
    deadline_at: datetime | None = None,
) -> TTSSynthesisRequest:
    policies = bundle or _policy()
    utterance = _utterance(text=text)
    plan = SpeechPerformancePlanner(yura_revision_1_policy()).plan(
        "performance-plan",
        utterance,
        None,
        None,
        NOW,
    )
    binding = TTSVoiceBinding("binding", "yura", "fake", "voice-1", 1, "ja-JP", True)
    capability = capability or TTSCapabilityView(
        "fake",
        policies.operational.provider_revision,
        1,
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    )
    return TTSSynthesisRequest(
        "request",
        "candidate",
        utterance,
        plan,
        binding,
        capability,
        overrides,
        policies.operational.policy_revision,
        1,
        policies.mapping.mapping_id,
        policies.mapping.mapping_revision,
        policies.retry.policy_id,
        policies.retry.policy_revision,
        priority,
        NOW,
        "trace",
        deadline_at,
    )


@pytest.mark.asyncio
async def test_success_preserves_text_and_never_fabricates_timing() -> None:
    policies = _policy(max_attempts=1)
    request = _request(bundle=policies)
    client = FakeTTS([_response()])
    result = await _adapter(client, policies, now=lambda: NOW).synthesize(request)
    assert result.status is TTSSynthesisStatus.SUCCEEDED
    assert result.artifact is not None and result.timing_track is None
    assert TTSDegradationReason.TIMING_UNAVAILABLE in result.degradation_reasons
    assert request.utterance.candidate.segments[0].text == "表示文は変えない"
    assert result.artifact.mapping_id == policies.mapping.mapping_id
    assert result.artifact.mapping_revision == policies.mapping.mapping_revision
    assert result.artifact.retry_policy_id == policies.retry.policy_id
    assert result.artifact.retry_policy_revision == policies.retry.policy_revision


@pytest.mark.asyncio
async def test_retryable_failure_uses_shared_dependency_retry_policy() -> None:
    policies = _policy(max_attempts=2)
    request = _request(bundle=policies)
    client = FakeTTS(
        [TTSProviderError(TTSFailureCode.PROVIDER_UNAVAILABLE, True), _response()]
    )
    slept: list[float] = []

    async def sleep(delay: float) -> None:
        slept.append(delay)

    result = await _adapter(client, policies, now=lambda: NOW, sleep=sleep).synthesize(request)
    assert result.status is TTSSynthesisStatus.SUCCEEDED
    assert result.attempts == 2
    assert len(client.calls) == 2
    assert slept == [policies.retry.delay_for(1)]


@pytest.mark.asyncio
async def test_non_retryable_failure_and_timeout_are_typed() -> None:
    policies = _policy(max_attempts=1)
    request = _request(bundle=policies)
    rejected = await _adapter(
        FakeTTS([TTSProviderError(TTSFailureCode.PROVIDER_REJECTED, False)]),
        policies,
        now=lambda: NOW,
    ).synthesize(request)
    assert rejected.failure_code is TTSFailureCode.PROVIDER_REJECTED
    assert rejected.attempts == 1
    timed_out = await _adapter(
        FakeTTS([asyncio.TimeoutError()]),
        policies,
        now=lambda: NOW,
    ).synthesize(request)
    assert timed_out.failure_code is TTSFailureCode.REQUEST_TIMEOUT
    assert timed_out.status is TTSSynthesisStatus.TIMED_OUT


@pytest.mark.asyncio
async def test_retry_sleep_rechecks_deadline_before_next_provider_call() -> None:
    current = [NOW]
    policies = _policy(max_attempts=2, retry_backoff_seconds=1.0)
    request = _request(bundle=policies, deadline_at=NOW + timedelta(seconds=0.5))
    client = FakeTTS(
        [TTSProviderError(TTSFailureCode.PROVIDER_UNAVAILABLE, True), _response()]
    )

    async def sleep(delay: float) -> None:
        current[0] += timedelta(seconds=delay)

    result = await _adapter(
        client,
        policies,
        now=lambda: current[0],
        sleep=sleep,
    ).synthesize(request)
    assert result.failure_code is TTSFailureCode.REQUEST_TIMEOUT
    assert result.attempts == 1
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_unsupported_dimension_is_degraded_without_changing_plan() -> None:
    policies = _policy(max_attempts=1)
    request = _request(bundle=policies)
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
    result = await _adapter(FakeTTS([_response()]), policies, now=lambda: NOW).synthesize(request)
    assert request.performance_plan.global_intent == original
    assert TTSDegradationReason.UNSUPPORTED_DIMENSION in result.degradation_reasons
    assert "pitch_center" in result.degraded_dimensions


def test_cache_identity_includes_performance_configuration_and_mapping_revision() -> None:
    request = _request()
    assert synthesis_cache_identity(request) != synthesis_cache_identity(
        replace(request, provider_config_revision=2)
    )
    assert synthesis_cache_identity(request) != synthesis_cache_identity(
        replace(request, mapping_revision=2)
    )
    assert synthesis_cache_identity(request) != synthesis_cache_identity(
        replace(
            request,
            performance_plan=replace(request.performance_plan, performance_plan_id="other"),
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


def test_request_rejects_mismatched_or_unavailable_binding_and_deadline() -> None:
    request = _request()
    with pytest.raises(ValueError, match="Character"):
        replace(request, voice_binding=replace(request.voice_binding, character_id="other"))
    with pytest.raises(ValueError, match="利用不能"):
        replace(request, voice_binding=replace(request.voice_binding, enabled=False))
    with pytest.raises(ValueError, match="deadline"):
        replace(request, deadline_at=NOW)


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
    policies = _policy(max_attempts=1)
    override = PronunciationOverrideView("override", "表示文", "ひょうじぶん", "ja-JP", "config", 1)
    request = _request(
        bundle=policies,
        capability=TTSCapabilityView(
            "fake", 1, 1, True, False, False, False, False, False, True, False, False, False, False
        ),
        overrides=(override,),
    )
    client = FakeTTS([_response()])
    await _adapter(client, policies, now=lambda: NOW).synthesize(request)
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
    policies = _policy(max_attempts=1)
    capability = TTSCapabilityView(
        "fake", 1, 1, False, False, False, False, False, False, False, False, False, False, False
    )
    request = _request(bundle=policies, capability=capability)
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
    result = await _adapter(client, policies, now=lambda: NOW).synthesize(request)
    assert result.status is TTSSynthesisStatus.SUCCEEDED
    assert {"pace", "pitch_center", "breathiness"} <= set(result.degraded_dimensions)
    assert client.calls[0][2].global_parameters == ()
    assert request.performance_plan is plan


@pytest.mark.asyncio
async def test_provider_mapping_projects_normalized_values_to_configured_ranges() -> None:
    policies = _policy(max_attempts=1)
    request = _request(bundle=policies)
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
    await _adapter(client, policies, now=lambda: NOW).synthesize(
        replace(request, performance_plan=plan)
    )
    assert dict(client.calls[0][2].global_parameters)["pace"] == 100.0


@pytest.mark.asyncio
async def test_segment_performance_uses_explicit_unit_rules_and_phrase_pause() -> None:
    policies = _policy(max_attempts=1)
    capability = replace(
        _request(bundle=policies).capability,
        supports_phrase_pause=True,
        supports_pitch_center=True,
        supports_pitch_range=True,
        supports_loudness=True,
        supports_breathiness=True,
    )
    request = _request(bundle=policies, capability=capability)
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
    await _adapter(client, policies, now=lambda: NOW).synthesize(
        replace(request, performance_plan=replace(request.performance_plan, segments=(segment,)))
    )
    mapped = client.calls[0][2].segments[0]
    assert mapped.pause_after == 600.0
    assert mapped.boundary_strength == 0.5
    assert mapped.duration_bias == pytest.approx(40.0)
    assert mapped.emphasis_strength == pytest.approx(0.8)
    assert mapped.hesitation_strength == pytest.approx(0.9)
    assert mapped.local_intent_parameters == (("pace", 40.0),)
    assert mapped.pitch_anchors[0].relative_pitch == 30.0


@pytest.mark.asyncio
async def test_provider_timing_is_normalized_only_when_trustworthy_units_are_returned() -> None:
    policies = _policy(max_attempts=1)
    capability = replace(
        _request(bundle=policies).capability,
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
    result = await _adapter(
        FakeTTS([_response(duration_ms=40, timing_units=timing)]),
        policies,
        now=lambda: NOW,
    ).synthesize(_request(bundle=policies, capability=capability))
    assert result.timing_track is not None
    assert tuple(unit.kind for unit in result.timing_track.units) == tuple(
        unit.kind for unit in timing
    )
    assert TTSDegradationReason.TIMING_UNAVAILABLE not in result.degradation_reasons


@pytest.mark.asyncio
async def test_secret_bearing_provider_audio_ref_is_normalized_before_public_artifact() -> None:
    policies = _policy(max_attempts=1)
    store = InMemoryPreparedAudioResourceStore()
    result = await _adapter(
        FakeTTS([_response(raw_audio_ref="https://example.invalid/audio?token=VERY_SECRET")]),
        policies,
        now=lambda: NOW,
        resource_store=store,
    ).synthesize(_request(bundle=policies))
    assert result.artifact is not None
    assert result.artifact.audio_ref.startswith("artifact://prepared/")
    assert "VERY_SECRET" not in result.artifact.audio_ref
    assert "VERY_SECRET" not in repr(result)
    assert (
        store.resolve(result.artifact.audio_ref)
        == "https://example.invalid/audio?token=VERY_SECRET"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "timing_units",
    (
        (
            ProviderTimingUnit("first", "segment-1", SpeechTimingKind.PHONEME, "a", 0, 20),
            ProviderTimingUnit("second", "segment-1", SpeechTimingKind.PHONEME, "i", 10, 30),
        ),
        (ProviderTimingUnit("overrun", "segment-1", SpeechTimingKind.PHONEME, "a", 0, 41),),
        (ProviderTimingUnit("unknown", "unknown-segment", SpeechTimingKind.PHONEME, "a", 0, 10),),
    ),
)
async def test_invalid_provider_timing_degrades_without_discarding_valid_audio(
    timing_units: tuple[ProviderTimingUnit, ...],
) -> None:
    policies = _policy(max_attempts=1)
    capability = replace(_request(bundle=policies).capability, supports_phoneme_timing=True)
    result = await _adapter(
        FakeTTS([_response(duration_ms=40, timing_units=timing_units)]),
        policies,
        now=lambda: NOW,
    ).synthesize(_request(bundle=policies, capability=capability))
    assert result.status is TTSSynthesisStatus.SUCCEEDED
    assert result.artifact is not None
    assert result.timing_track is None
    assert TTSDegradationReason.TIMING_UNAVAILABLE in result.degradation_reasons


@pytest.mark.asyncio
async def test_untrusted_provider_timing_is_not_published_but_audio_succeeds() -> None:
    policies = _policy(max_attempts=1)
    capability = replace(_request(bundle=policies).capability, supports_phoneme_timing=True)
    response = TTSProviderResponse(
        "memory://audio",
        "wav",
        "digest",
        10,
        (ProviderTimingUnit("unit", "segment-1", SpeechTimingKind.PHONEME, "a", 0, 10),),
        False,
    )
    result = await _adapter(FakeTTS([response]), policies, now=lambda: NOW).synthesize(
        _request(bundle=policies, capability=capability)
    )
    assert result.status is TTSSynthesisStatus.SUCCEEDED
    assert result.timing_track is None


@pytest.mark.asyncio
async def test_policy_generation_mismatch_fails_before_provider_invocation() -> None:
    policies = _policy(max_attempts=1)
    for request in (
        replace(_request(bundle=policies), mapping_revision=2),
        replace(_request(bundle=policies), retry_policy_revision=2),
        replace(_request(bundle=policies), provider_config_revision=2),
    ):
        client = FakeTTS([_response()])
        result = await _adapter(client, policies, now=lambda: NOW).synthesize(request)
        assert result.failure_code is TTSFailureCode.INVALID_REQUEST
        assert client.calls == []


def test_timing_supports_monotonic_units_and_rejects_duration_overrun() -> None:
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
    policies = _policy(max_attempts=1)
    request = _request(bundle=policies)
    for code in (
        TTSFailureCode.PROVIDER_UNAVAILABLE,
        TTSFailureCode.RATE_LIMITED,
        TTSFailureCode.PROVIDER_SERVER_ERROR,
        TTSFailureCode.PROVIDER_REJECTED,
        TTSFailureCode.AUDIO_DECODE_OR_STORAGE_FAILED,
    ):
        result = await _adapter(
            FakeTTS([TTSProviderError(code, False)]),
            policies,
            now=lambda: NOW,
        ).synthesize(request)
        assert result.failure_code is code and result.artifact is None

    class LeakingProvider:
        async def synthesize(
            self,
            voice_ref: str,
            texts: tuple[str, ...],
            parameters: ProviderSynthesisInput,
        ) -> TTSProviderResponse:
            raise RuntimeError("Authorization: Bearer secret-token https://secret.example/raw-body")

    result = await _adapter(LeakingProvider(), policies, now=lambda: NOW).synthesize(request)
    assert result.failure_code is TTSFailureCode.PROVIDER_SERVER_ERROR
    assert "secret-token" not in repr(result)


@pytest.mark.asyncio
async def test_cancellation_during_call_is_typed_and_pending_task_is_released() -> None:
    policies = _policy()
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockingProvider:
        async def synthesize(
            self,
            voice_ref: str,
            texts: tuple[str, ...],
            parameters: ProviderSynthesisInput,
        ) -> TTSProviderResponse:
            entered.set()
            await release.wait()
            return _response()

    adapter = _adapter(BlockingProvider(), policies, now=lambda: NOW)
    task = asyncio.create_task(adapter.synthesize(_request(bundle=policies)))
    await entered.wait()
    task.cancel()
    assert (await task).failure_code is TTSFailureCode.CANCELLED
    assert adapter.pending_task_count == 0


@pytest.mark.asyncio
async def test_shutdown_interrupts_retry_wait_and_settles_all_tasks() -> None:
    policies = _policy(max_attempts=2, retry_backoff_seconds=1.0)
    retry_entered = asyncio.Event()
    retry_release = asyncio.Event()

    async def waiting_sleep(seconds: float) -> None:
        retry_entered.set()
        await retry_release.wait()

    adapter = _adapter(
        FakeTTS([TTSProviderError(TTSFailureCode.RATE_LIMITED, True)]),
        policies,
        now=lambda: NOW,
        sleep=waiting_sleep,
    )
    task = asyncio.create_task(adapter.synthesize(_request(bundle=policies)))
    await retry_entered.wait()
    await adapter.shutdown()
    assert (await task).failure_code is TTSFailureCode.CANCELLED
    assert adapter.pending_task_count == 0


def test_candidate_scoped_artifact_discard_blocks_rejected_or_superseded_reuse() -> None:
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
        "mapping",
        1,
        "retry",
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
    policies = _policy(max_attempts=1)
    speculative_entered = asyncio.Event()
    speculative_release = asyncio.Event()
    foreground_entered = asyncio.Event()

    class PriorityProvider:
        async def synthesize(
            self,
            voice_ref: str,
            texts: tuple[str, ...],
            parameters: ProviderSynthesisInput,
        ) -> TTSProviderResponse:
            if voice_ref == "speculative":
                speculative_entered.set()
                await speculative_release.wait()
            else:
                foreground_entered.set()
            return _response()

    adapter = _adapter(PriorityProvider(), policies, now=lambda: NOW)
    speculative_request = _request(
        bundle=policies,
        priority=TTSSynthesisPriority.SPECULATIVE,
    )
    speculative = asyncio.create_task(
        adapter.synthesize(
            replace(
                speculative_request,
                voice_binding=replace(
                    speculative_request.voice_binding,
                    provider_voice_ref="speculative",
                ),
            )
        )
    )
    await speculative_entered.wait()
    heartbeat = asyncio.Event()

    async def tick() -> None:
        heartbeat.set()

    foreground = asyncio.create_task(adapter.synthesize(_request(bundle=policies)))
    await tick()
    await foreground_entered.wait()
    assert heartbeat.is_set()
    speculative_release.set()
    assert (await foreground).status is TTSSynthesisStatus.SUCCEEDED
    assert (await speculative).status is TTSSynthesisStatus.SUCCEEDED
    assert adapter.pending_task_count == 0


@pytest.mark.asyncio
async def test_cancelling_candidate_a_does_not_cancel_unrelated_candidate_b() -> None:
    policies = _policy(max_attempts=1)
    candidate_a_entered = asyncio.Event()
    candidate_a_release = asyncio.Event()

    class IndependentProvider:
        async def synthesize(
            self,
            voice_ref: str,
            texts: tuple[str, ...],
            parameters: ProviderSynthesisInput,
        ) -> TTSProviderResponse:
            if voice_ref == "candidate-a":
                candidate_a_entered.set()
                await candidate_a_release.wait()
            return _response()

    adapter = _adapter(IndependentProvider(), policies, now=lambda: NOW)
    candidate_a = _request(bundle=policies, priority=TTSSynthesisPriority.SPECULATIVE)
    candidate_a = replace(
        candidate_a,
        candidate_id="candidate-a",
        voice_binding=replace(candidate_a.voice_binding, provider_voice_ref="candidate-a"),
    )
    running_a = asyncio.create_task(adapter.synthesize(candidate_a))
    await candidate_a_entered.wait()
    result_b = await adapter.synthesize(_request(bundle=policies))
    running_a.cancel()
    assert (await running_a).failure_code is TTSFailureCode.CANCELLED
    assert result_b.status is TTSSynthesisStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_prepared_audio_is_not_playback_or_actual_speech_fact() -> None:
    policies = _policy(max_attempts=1)
    result = await _adapter(FakeTTS([_response()]), policies, now=lambda: NOW).synthesize(
        _request(bundle=policies, priority=TTSSynthesisPriority.SPECULATIVE)
    )
    assert result.status is TTSSynthesisStatus.SUCCEEDED
    assert not hasattr(result, "playback_started")
    assert not hasattr(result, "actual_speech_fact")


def test_architecture_keeps_presentation_body_and_provider_values_out_of_domain() -> None:
    domain = Path("app/domain/speech_performance/contracts.py").read_text()
    adapter = Path("app/adapters/tts/d10_provider.py").read_text()
    assert "provider_voice_ref" not in domain
    assert "app.domain.presentation" not in adapter
    assert "app.domain.body" not in adapter
    assert "ActualSpeechFact" not in adapter
