from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from app.domain.contracts.common import utc_instant
from app.domain.speech_performance import PerformanceAxis
from app.runtime.lifecycle import DependencyRetryPolicy

from .contracts import (
    PreparedAudioArtifact,
    SpeechTimingKind,
    SpeechTimingTrack,
    SpeechTimingUnit,
    TTSDegradationReason,
    TTSFailureCode,
    TTSSynthesisPriority,
    TTSSynthesisRequest,
    TTSSynthesisResult,
    TTSSynthesisStatus,
)
from .policy import (
    TTSMappingDimension,
    TTSParameterMappingRule,
    TTSPerformanceMappingPolicy,
    TTSProviderOperationalPolicy,
    TTSUnitParameterMappingRule,
    validate_tts_policy_bundle,
)
from .provider import (
    InMemoryPreparedAudioResourceStore,
    PreparedAudioResourceStore,
    ProviderPitchAnchor,
    ProviderSegmentParameters,
    ProviderSynthesisInput,
    ProviderTimingUnit,
    TTSProviderClient,
    TTSProviderError,
    TTSProviderResponse,
)

_PERFORMANCE_DIMENSIONS: dict[PerformanceAxis, TTSMappingDimension] = {
    PerformanceAxis.PACE: TTSMappingDimension.PACE,
    PerformanceAxis.ENERGY: TTSMappingDimension.ENERGY,
    PerformanceAxis.PITCH_CENTER: TTSMappingDimension.PITCH_CENTER,
    PerformanceAxis.PITCH_RANGE: TTSMappingDimension.PITCH_RANGE,
    PerformanceAxis.LOUDNESS: TTSMappingDimension.LOUDNESS,
    PerformanceAxis.SOFTNESS: TTSMappingDimension.SOFTNESS,
    PerformanceAxis.BREATHINESS: TTSMappingDimension.BREATHINESS,
    PerformanceAxis.TENSION: TTSMappingDimension.TENSION,
    PerformanceAxis.EXPRESSIVENESS: TTSMappingDimension.EXPRESSIVENESS,
}


class TTSProviderAdapter:
    """Provider呼出だけを所有し、再生・Presentation・Body副作用を持たない。"""

    def __init__(
        self,
        client: TTSProviderClient,
        mapping_policy: TTSPerformanceMappingPolicy,
        operational_policy: TTSProviderOperationalPolicy,
        retry_policy: DependencyRetryPolicy,
        *,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        resource_store: PreparedAudioResourceStore | None = None,
    ) -> None:
        validate_tts_policy_bundle(mapping_policy, operational_policy, retry_policy)
        self._client = client
        self._mapping_policy = mapping_policy
        self._operational_policy = operational_policy
        self._retry_policy = retry_policy
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or asyncio.sleep
        self._resource_store = resource_store or InMemoryPreparedAudioResourceStore()
        self._foreground_slots = asyncio.Semaphore(operational_policy.max_foreground_synthesis)
        self._speculative_slots = asyncio.Semaphore(operational_policy.max_speculative_synthesis)
        self._pending: set[asyncio.Task[object]] = set()
        self._shutdown = False

    @property
    def pending_task_count(self) -> int:
        return len(self._pending)

    @property
    def mapping_policy(self) -> TTSPerformanceMappingPolicy:
        return self._mapping_policy

    @property
    def retry_policy(self) -> DependencyRetryPolicy:
        return self._retry_policy

    async def shutdown(self) -> None:
        self._shutdown = True
        pending = tuple(self._pending)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def synthesize(self, request: TTSSynthesisRequest) -> TTSSynthesisResult:
        if self._shutdown:
            return self._failure(
                request,
                TTSFailureCode.CANCELLED,
                0,
                TTSSynthesisStatus.CANCELLED,
            )
        task = asyncio.current_task()
        if task is not None:
            self._pending.add(task)
        slots = (
            self._foreground_slots
            if request.priority is TTSSynthesisPriority.FOREGROUND
            else self._speculative_slots
        )
        try:
            async with slots:
                return await self._synthesize(request)
        finally:
            if task is not None:
                self._pending.discard(task)

    async def _synthesize(self, request: TTSSynthesisRequest) -> TTSSynthesisResult:
        if not self._policy_matches(request):
            return self._failure(request, TTSFailureCode.INVALID_REQUEST, 0)
        if self._deadline_expired(request):
            return self._failure(
                request,
                TTSFailureCode.REQUEST_TIMEOUT,
                0,
                TTSSynthesisStatus.TIMED_OUT,
            )
        try:
            provider_input, degraded = self._map(request)
        except (TypeError, ValueError):
            return self._failure(request, TTSFailureCode.INVALID_REQUEST, 0)
        texts = self._pronunciation_texts(request)
        if (
            request.pronunciation_overrides
            and not request.capability.supports_pronunciation_override
        ):
            texts = tuple(segment.text for segment in request.utterance.candidate.segments)
            degraded.append("pronunciation_override")

        attempt = 0
        while True:
            if self._shutdown or self._deadline_expired(request):
                status = (
                    TTSSynthesisStatus.CANCELLED
                    if self._shutdown
                    else TTSSynthesisStatus.TIMED_OUT
                )
                code = (
                    TTSFailureCode.CANCELLED
                    if self._shutdown
                    else TTSFailureCode.REQUEST_TIMEOUT
                )
                return self._failure(request, code, attempt, status)
            attempt += 1
            try:
                response = await asyncio.wait_for(
                    self._client.synthesize(
                        request.voice_binding.provider_voice_ref,
                        texts,
                        provider_input,
                    ),
                    timeout=self._operational_policy.timeout_seconds,
                )
                if self._shutdown or self._deadline_expired(request):
                    status = (
                        TTSSynthesisStatus.CANCELLED
                        if self._shutdown
                        else TTSSynthesisStatus.TIMED_OUT
                    )
                    code = (
                        TTSFailureCode.CANCELLED
                        if self._shutdown
                        else TTSFailureCode.REQUEST_TIMEOUT
                    )
                    return self._failure(request, code, attempt, status)
                return self._success(request, response, provider_input, degraded, attempt)
            except asyncio.CancelledError:
                return self._failure(
                    request,
                    TTSFailureCode.CANCELLED,
                    attempt,
                    TTSSynthesisStatus.CANCELLED,
                )
            except asyncio.TimeoutError:
                failure = TTSProviderError(TTSFailureCode.REQUEST_TIMEOUT, True)
            except TTSProviderError as error:
                failure = error
            except ValueError:
                return self._failure(
                    request,
                    TTSFailureCode.AUDIO_DECODE_OR_STORAGE_FAILED,
                    attempt,
                )
            except Exception:
                failure = TTSProviderError(TTSFailureCode.PROVIDER_SERVER_ERROR, False)

            retry_number = attempt
            if not self._retry_allowed(failure, retry_number):
                status = (
                    TTSSynthesisStatus.TIMED_OUT
                    if failure.code is TTSFailureCode.REQUEST_TIMEOUT
                    else TTSSynthesisStatus.FAILED
                )
                return self._failure(request, failure.code, attempt, status)
            try:
                await self._sleep(self._retry_policy.delay_for(retry_number))
            except asyncio.CancelledError:
                return self._failure(
                    request,
                    TTSFailureCode.CANCELLED,
                    attempt,
                    TTSSynthesisStatus.CANCELLED,
                )
            if self._shutdown:
                return self._failure(
                    request,
                    TTSFailureCode.CANCELLED,
                    attempt,
                    TTSSynthesisStatus.CANCELLED,
                )
            if self._deadline_expired(request):
                return self._failure(
                    request,
                    TTSFailureCode.REQUEST_TIMEOUT,
                    attempt,
                    TTSSynthesisStatus.TIMED_OUT,
                )

    def _success(
        self,
        request: TTSSynthesisRequest,
        response: TTSProviderResponse,
        provider_input: ProviderSynthesisInput,
        degraded: list[str],
        attempt: int,
    ) -> TTSSynthesisResult:
        artifact_id = f"artifact-{request.request_id}"
        safe_ref = self._resource_store.store(
            artifact_id,
            request.request_id,
            response.raw_audio_ref,
        )
        artifact = PreparedAudioArtifact(
            artifact_id,
            request.request_id,
            request.candidate_id,
            request.utterance.utterance_id,
            request.performance_plan.performance_plan_id,
            request.voice_binding.binding_id,
            request.voice_binding.binding_revision,
            request.capability.provider_revision,
            request.provider_config_revision,
            request.pronunciation_config_revision,
            request.mapping_id,
            request.mapping_revision,
            request.retry_policy_id,
            request.retry_policy_revision,
            safe_ref,
            response.audio_format,
            response.content_digest,
            self._now(),
            response.duration_ms,
        )
        try:
            timing = self._normalize_timing(request, artifact, response)
        except (KeyError, TypeError, ValueError):
            timing = None
        reasons: tuple[TTSDegradationReason, ...] = ()
        if degraded:
            reasons += (TTSDegradationReason.UNSUPPORTED_DIMENSION,)
        if timing is None:
            reasons += (TTSDegradationReason.TIMING_UNAVAILABLE,)
        return TTSSynthesisResult(
            request.request_id,
            TTSSynthesisStatus.SUCCEEDED,
            attempt,
            self._now(),
            artifact,
            timing_track=timing,
            degradation_reasons=reasons,
            applied_dimensions=self._applied_dimensions(provider_input),
            degraded_dimensions=tuple(dict.fromkeys(degraded)),
        )

    def _map(self, request: TTSSynthesisRequest) -> tuple[ProviderSynthesisInput, list[str]]:
        support = {
            PerformanceAxis.PACE: request.capability.supports_rate,
            PerformanceAxis.PITCH_CENTER: request.capability.supports_pitch_center,
            PerformanceAxis.PITCH_RANGE: request.capability.supports_pitch_range,
            PerformanceAxis.LOUDNESS: request.capability.supports_loudness,
            PerformanceAxis.BREATHINESS: request.capability.supports_breathiness,
        }
        degraded: list[str] = []
        global_parameters = self._project_intent(
            request.performance_plan.global_intent.values,
            support,
            degraded,
        )
        segments: list[ProviderSegmentParameters] = []
        for segment in request.performance_plan.segments:
            local = self._project_intent(segment.local_intent_delta.values, support, degraded)
            pause_after: float | None = None
            pause_rule = self._mapping_policy.unit_rule_for(TTSMappingDimension.PHRASE_PAUSE)
            if request.capability.supports_phrase_pause and pause_rule is not None:
                pause_after = pause_rule.project(segment.pause_after_intent)
            elif segment.pause_after_intent != 0.0:
                degraded.append(TTSMappingDimension.PHRASE_PAUSE.value)
            anchors = tuple(
                ProviderPitchAnchor(
                    anchor.position,
                    self._required_signed(TTSMappingDimension.PITCH_ANCHOR).project(
                        anchor.relative_pitch
                    ),
                    anchor.strength,
                )
                for anchor in segment.pitch_anchors
            )
            segments.append(
                ProviderSegmentParameters(
                    segment.utterance_segment_id,
                    self._required_unit(TTSMappingDimension.BOUNDARY_STRENGTH).project(
                        segment.boundary_strength
                    ),
                    pause_after,
                    self._required_unit(TTSMappingDimension.DURATION_BIAS).project(
                        segment.duration_bias
                    ),
                    self._required_unit(TTSMappingDimension.EMPHASIS_STRENGTH).project(
                        segment.emphasis_strength
                    ),
                    self._required_unit(TTSMappingDimension.HESITATION_STRENGTH).project(
                        segment.hesitation_strength
                    ),
                    tuple(local.items()),
                    anchors,
                )
            )
        return ProviderSynthesisInput(tuple(global_parameters.items()), tuple(segments)), degraded

    def _project_intent(
        self,
        values: tuple[tuple[PerformanceAxis, float], ...],
        support: dict[PerformanceAxis, bool],
        degraded: list[str],
    ) -> dict[str, float]:
        parameters: dict[str, float] = {}
        for axis, value in values:
            dimension = _PERFORMANCE_DIMENSIONS[axis]
            rule = self._mapping_policy.signed_rule_for(dimension)
            if support.get(axis, False) and rule is not None:
                parameters[rule.provider_parameter] = rule.project(value)
            elif value != 0.0:
                degraded.append(dimension.value)
        return parameters

    def _required_signed(
        self,
        dimension: TTSMappingDimension,
    ) -> TTSParameterMappingRule:
        rule = self._mapping_policy.signed_rule_for(dimension)
        if rule is None:
            raise ValueError(f"required signed mapping ruleがありません: {dimension.value}")
        return rule

    def _required_unit(
        self,
        dimension: TTSMappingDimension,
    ) -> TTSUnitParameterMappingRule:
        rule = self._mapping_policy.unit_rule_for(dimension)
        if rule is None:
            raise ValueError(f"required unit mapping ruleがありません: {dimension.value}")
        return rule

    @staticmethod
    def _applied_dimensions(provider_input: ProviderSynthesisInput) -> tuple[str, ...]:
        dimensions = [name for name, _ in provider_input.global_parameters]
        for segment in provider_input.segments:
            dimensions.extend(
                ("boundary_strength", "duration_bias", "emphasis_strength", "hesitation_strength")
            )
            if segment.pause_after is not None:
                dimensions.append("phrase_pause")
            dimensions.extend(name for name, _ in segment.local_intent_parameters)
            if segment.pitch_anchors:
                dimensions.append("pitch_anchors")
        return tuple(dict.fromkeys(dimensions))

    @staticmethod
    def _pronunciation_texts(request: TTSSynthesisRequest) -> tuple[str, ...]:
        replacements = {item.surface: item.reading for item in request.pronunciation_overrides}
        surfaces = sorted(replacements, key=len, reverse=True)
        texts: list[str] = []
        for segment in request.utterance.candidate.segments:
            reading = segment.text
            for surface in surfaces:
                reading = reading.replace(surface, replacements[surface])
            texts.append(reading)
        return tuple(texts)

    @staticmethod
    def _normalize_timing(
        request: TTSSynthesisRequest,
        artifact: PreparedAudioArtifact,
        response: TTSProviderResponse,
    ) -> SpeechTimingTrack | None:
        if not response.timing_units or not response.timing_trustworthy:
            return None
        supported = {
            SpeechTimingKind.PHONEME: request.capability.supports_phoneme_timing,
            SpeechTimingKind.MORA: request.capability.supports_mora_timing,
            SpeechTimingKind.VISEME: request.capability.supports_viseme_timing,
            SpeechTimingKind.WORD_BOUNDARY: True,
        }
        expected_segments = {segment.segment_id for segment in request.utterance.candidate.segments}
        if any(
            not isinstance(unit, ProviderTimingUnit)
            or unit.segment_id not in expected_segments
            or not supported[unit.kind]
            for unit in response.timing_units
        ):
            raise ValueError("provider timing capabilityが一致しません")
        units = tuple(
            SpeechTimingUnit(
                unit.unit_id,
                unit.segment_id,
                unit.kind,
                unit.symbol,
                unit.start_ms,
                unit.end_ms,
            )
            for unit in response.timing_units
        )
        return SpeechTimingTrack(
            f"timing-{artifact.audio_artifact_id}",
            artifact.audio_artifact_id,
            units,
            artifact.created_at,
            artifact.duration_ms,
        )

    def _retry_allowed(self, error: TTSProviderError, retry_number: int) -> bool:
        return (
            error.retryable
            and self._retry_policy.retry_enabled
            and retry_number <= self._retry_policy.max_retry_attempts
        )

    def _policy_matches(self, request: TTSSynthesisRequest) -> bool:
        return (
            request.mapping_id == self._mapping_policy.mapping_id
            and request.mapping_revision == self._mapping_policy.mapping_revision
            and request.retry_policy_id == self._retry_policy.policy_id
            and request.retry_policy_revision == self._retry_policy.policy_revision
            and request.voice_binding.provider_id == self._operational_policy.provider_id
            and request.capability.provider_id == self._operational_policy.provider_id
            and request.capability.provider_revision == self._operational_policy.provider_revision
            and self._mapping_policy.provider_revision == self._operational_policy.provider_revision
        )

    def _deadline_expired(self, request: TTSSynthesisRequest) -> bool:
        return request.deadline_at is not None and utc_instant(self._now()) >= utc_instant(
            request.deadline_at
        )

    def _failure(
        self,
        request: TTSSynthesisRequest,
        code: TTSFailureCode,
        attempts: int,
        status: TTSSynthesisStatus = TTSSynthesisStatus.FAILED,
    ) -> TTSSynthesisResult:
        return TTSSynthesisResult(
            request.request_id,
            status,
            attempts,
            self._now(),
            failure_code=code,
        )


def synthesis_cache_identity(request: TTSSynthesisRequest) -> str:
    material = "\x1f".join(
        (
            *(segment.text for segment in request.utterance.candidate.segments),
            request.performance_plan.performance_plan_id,
            request.voice_binding.binding_id,
            str(request.voice_binding.binding_revision),
            str(request.capability.provider_revision),
            str(request.provider_config_revision),
            request.mapping_id,
            str(request.mapping_revision),
            str(request.pronunciation_config_revision),
            *(f"{item.override_id}:{item.revision}" for item in request.pronunciation_overrides),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
