from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from app.domain.speech_performance import PerformanceAxis

from .contracts import (
    PreparedAudioArtifact,
    SpeechTimingKind,
    SpeechTimingTrack,
    SpeechTimingUnit,
    TTSCapabilityView,
    TTSDegradationReason,
    TTSFailureCode,
    TTSSynthesisPriority,
    TTSSynthesisRequest,
    TTSSynthesisResult,
    TTSSynthesisStatus,
)


@dataclass(frozen=True, slots=True)
class ProviderParameterRange:
    """provider固有の実値範囲。正規化値はこの境界を越えない。"""

    minimum: float
    neutral: float
    maximum: float

    def __post_init__(self) -> None:
        if not self.minimum <= self.neutral <= self.maximum:
            raise ValueError("provider parameter range が不正です")

    def project(self, normalized: float) -> float:
        value = max(-1.0, min(1.0, normalized))
        if value < 0.0:
            return self.neutral + value * (self.neutral - self.minimum)
        return self.neutral + value * (self.maximum - self.neutral)


@dataclass(frozen=True, slots=True)
class ProviderPitchAnchor:
    position: float
    relative_pitch: float
    strength: float


@dataclass(frozen=True, slots=True)
class ProviderSegmentParameters:
    utterance_segment_id: str
    boundary_strength: float
    pause_after: float | None
    duration_bias: float
    emphasis_strength: float
    hesitation_strength: float
    local_intent_parameters: tuple[tuple[str, float], ...]
    pitch_anchors: tuple[ProviderPitchAnchor, ...]


@dataclass(frozen=True, slots=True)
class ProviderSynthesisInput:
    global_parameters: tuple[tuple[str, float], ...]
    segments: tuple[ProviderSegmentParameters, ...]


@dataclass(frozen=True, slots=True)
class ProviderTimingUnit:
    unit_id: str
    segment_id: str
    kind: SpeechTimingKind
    symbol: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class TTSProviderResponse:
    raw_audio_ref: str
    audio_format: str
    content_digest: str
    duration_ms: int | None
    timing_units: tuple[ProviderTimingUnit, ...] = ()


class TTSProviderError(Exception):
    """Providerの生エラーを閉じ込めるためのInfrastructure内部例外。"""

    def __init__(self, code: TTSFailureCode, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code.value)


class TTSProviderClient(Protocol):
    async def synthesize(
        self,
        voice_ref: str,
        texts: tuple[str, ...],
        provider_input: ProviderSynthesisInput,
    ) -> TTSProviderResponse: ...


@dataclass(frozen=True, slots=True)
class TTSProviderMappingPolicy:
    provider_config_revision: int
    max_attempts: int
    timeout_seconds: float
    global_ranges: tuple[tuple[PerformanceAxis, ProviderParameterRange], ...]
    boundary_strength_range: ProviderParameterRange
    phrase_pause_range: ProviderParameterRange
    duration_bias_range: ProviderParameterRange
    emphasis_strength_range: ProviderParameterRange
    hesitation_strength_range: ProviderParameterRange
    pitch_anchor_range: ProviderParameterRange
    retry_backoff_seconds: float = 0.0
    max_foreground_synthesis: int = 1
    max_speculative_synthesis: int = 1
    retryable_failure_codes: tuple[TTSFailureCode, ...] = (
        TTSFailureCode.PROVIDER_UNAVAILABLE,
        TTSFailureCode.RATE_LIMITED,
        TTSFailureCode.PROVIDER_SERVER_ERROR,
    )

    def __post_init__(self) -> None:
        if type(self.provider_config_revision) is not int or self.provider_config_revision < 0:
            raise ValueError("provider_config_revision が不正です")
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("max_attempts が不正です")
        if type(self.timeout_seconds) not in (int, float) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds が不正です")
        ranges = tuple(self.global_ranges)
        if len({axis for axis, _ in ranges}) != len(ranges) or any(
            not isinstance(axis, PerformanceAxis) or not isinstance(item, ProviderParameterRange)
            for axis, item in ranges
        ):
            raise ValueError("global_ranges が不正です")
        object.__setattr__(self, "global_ranges", ranges)
        for name in (
            "boundary_strength_range",
            "phrase_pause_range",
            "duration_bias_range",
            "emphasis_strength_range",
            "hesitation_strength_range",
            "pitch_anchor_range",
        ):
            if not isinstance(getattr(self, name), ProviderParameterRange):
                raise ValueError(f"{name} が不正です")
        if type(self.retry_backoff_seconds) not in (int, float) or self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds が不正です")
        if self.max_foreground_synthesis < 1 or self.max_speculative_synthesis < 1:
            raise ValueError("synthesis concurrency が不正です")
        if any(not isinstance(code, TTSFailureCode) for code in self.retryable_failure_codes):
            raise ValueError("retryable_failure_codes が不正です")

    @classmethod
    def revision_1(cls) -> TTSProviderMappingPolicy:
        normalized = ProviderParameterRange(-100.0, 0.0, 100.0)
        unit = ProviderParameterRange(0.0, 0.5, 1.0)
        return cls(
            1,
            2,
            1.0,
            tuple((axis, normalized) for axis in PerformanceAxis),
            unit,
            ProviderParameterRange(0.0, 0.0, 1000.0),
            normalized,
            unit,
            unit,
            normalized,
        )


@dataclass(slots=True)
class CandidateArtifactStore:
    """#348へ渡す前だけに使う、候補単位の再利用・破棄境界。"""

    _artifacts: dict[str, PreparedAudioArtifact] = field(default_factory=dict)
    _discarded_candidates: set[str] = field(default_factory=set)

    def retain(self, artifact: PreparedAudioArtifact) -> None:
        if artifact.candidate_id not in self._discarded_candidates:
            self._artifacts[artifact.candidate_id] = artifact

    def discard(self, candidate_id: str) -> TTSDegradationReason:
        self._discarded_candidates.add(candidate_id)
        self._artifacts.pop(candidate_id, None)
        return TTSDegradationReason.ARTIFACT_DISCARDED

    def current_artifact(self, candidate_id: str) -> PreparedAudioArtifact | None:
        if candidate_id in self._discarded_candidates:
            return None
        return self._artifacts.get(candidate_id)


class TTSProviderAdapter:
    """Provider呼出だけを所有し、再生・Presentation・Body副作用を持たない。"""

    def __init__(
        self,
        client: TTSProviderClient,
        policy: TTSProviderMappingPolicy,
        *,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._client = client
        self._policy = policy
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or asyncio.sleep
        self._foreground_slots = asyncio.Semaphore(policy.max_foreground_synthesis)
        self._speculative_slots = asyncio.Semaphore(policy.max_speculative_synthesis)
        self._pending: set[asyncio.Task[object]] = set()

    @property
    def pending_task_count(self) -> int:
        return len(self._pending)

    async def shutdown(self) -> None:
        pending = tuple(self._pending)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def synthesize(self, request: TTSSynthesisRequest) -> TTSSynthesisResult:
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
        if request.provider_config_revision != self._policy.provider_config_revision:
            return self._failure(request, TTSFailureCode.INVALID_REQUEST, 0)
        provider_input, degraded = self._map(request)
        texts = self._pronunciation_texts(request)
        if (
            request.pronunciation_overrides
            and not request.capability.supports_pronunciation_override
        ):
            texts = tuple(segment.text for segment in request.utterance.candidate.segments)
            degraded.append("pronunciation_override")
        for attempt in range(1, self._policy.max_attempts + 1):
            try:
                response = await asyncio.wait_for(
                    self._client.synthesize(
                        request.voice_binding.provider_voice_ref, texts, provider_input
                    ),
                    timeout=float(self._policy.timeout_seconds),
                )
                artifact = PreparedAudioArtifact(
                    f"artifact-{request.request_id}",
                    request.request_id,
                    request.candidate_id,
                    request.utterance.utterance_id,
                    request.performance_plan.performance_plan_id,
                    request.voice_binding.binding_id,
                    request.voice_binding.binding_revision,
                    request.capability.provider_revision,
                    request.provider_config_revision,
                    request.pronunciation_config_revision,
                    self._safe_artifact_ref(response),
                    response.audio_format,
                    response.content_digest,
                    self._now(),
                    response.duration_ms,
                )
                timing = self._normalize_timing(request.capability, artifact, response)
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
            except asyncio.CancelledError:
                return self._failure(
                    request, TTSFailureCode.CANCELLED, attempt, TTSSynthesisStatus.CANCELLED
                )
            except asyncio.TimeoutError:
                return self._failure(
                    request, TTSFailureCode.REQUEST_TIMEOUT, attempt, TTSSynthesisStatus.TIMED_OUT
                )
            except TTSProviderError as error:
                if self._retry_allowed(error) and attempt < self._policy.max_attempts:
                    try:
                        await self._sleep(float(self._policy.retry_backoff_seconds))
                    except asyncio.CancelledError:
                        return self._failure(
                            request, TTSFailureCode.CANCELLED, attempt, TTSSynthesisStatus.CANCELLED
                        )
                    continue
                return self._failure(request, error.code, attempt)
            except ValueError:
                return self._failure(
                    request, TTSFailureCode.AUDIO_DECODE_OR_STORAGE_FAILED, attempt
                )
            except Exception:
                return self._failure(request, TTSFailureCode.PROVIDER_SERVER_ERROR, attempt)
        raise AssertionError("到達不能なretry状態です")

    def _map(self, request: TTSSynthesisRequest) -> tuple[ProviderSynthesisInput, list[str]]:
        ranges = dict(self._policy.global_ranges)
        support = {
            PerformanceAxis.PACE: request.capability.supports_rate,
            PerformanceAxis.PITCH_CENTER: request.capability.supports_pitch_center,
            PerformanceAxis.PITCH_RANGE: request.capability.supports_pitch_range,
            PerformanceAxis.LOUDNESS: request.capability.supports_loudness,
            PerformanceAxis.BREATHINESS: request.capability.supports_breathiness,
        }
        degraded: list[str] = []
        global_parameters = self._project_intent(
            request.performance_plan.global_intent.values, ranges, support, degraded
        )
        segments: list[ProviderSegmentParameters] = []
        for segment in request.performance_plan.segments:
            local = self._project_intent(
                segment.local_intent_delta.values, ranges, support, degraded
            )
            pause_after: float | None = None
            if request.capability.supports_phrase_pause:
                pause_after = self._policy.phrase_pause_range.project(segment.pause_after_intent)
            elif segment.pause_after_intent != 0.0:
                degraded.append("phrase_pause")
            anchors = tuple(
                ProviderPitchAnchor(
                    anchor.position,
                    self._policy.pitch_anchor_range.project(anchor.relative_pitch),
                    anchor.strength,
                )
                for anchor in segment.pitch_anchors
            )
            segments.append(
                ProviderSegmentParameters(
                    segment.utterance_segment_id,
                    self._policy.boundary_strength_range.project(
                        segment.boundary_strength * 2.0 - 1.0
                    ),
                    pause_after,
                    self._policy.duration_bias_range.project(segment.duration_bias * 2.0 - 1.0),
                    self._policy.emphasis_strength_range.project(
                        segment.emphasis_strength * 2.0 - 1.0
                    ),
                    self._policy.hesitation_strength_range.project(
                        segment.hesitation_strength * 2.0 - 1.0
                    ),
                    tuple(local.items()),
                    anchors,
                )
            )
        return ProviderSynthesisInput(tuple(global_parameters.items()), tuple(segments)), degraded

    @staticmethod
    def _project_intent(
        values: tuple[tuple[PerformanceAxis, float], ...],
        ranges: dict[PerformanceAxis, ProviderParameterRange],
        support: dict[PerformanceAxis, bool],
        degraded: list[str],
    ) -> dict[str, float]:
        parameters: dict[str, float] = {}
        for axis, value in values:
            if axis not in support:
                if value != 0.0:
                    degraded.append(axis.value)
                continue
            if support[axis] and axis in ranges:
                parameters[axis.value] = ranges[axis].project(value)
            elif value != 0.0:
                degraded.append(axis.value)
        return parameters

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
    def _safe_artifact_ref(response: TTSProviderResponse) -> str:
        material = (
            f"{response.raw_audio_ref}\x1f{response.audio_format}\x1f{response.content_digest}"
        )
        return f"artifact://prepared/{hashlib.sha256(material.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _normalize_timing(
        capability: TTSCapabilityView,
        artifact: PreparedAudioArtifact,
        response: TTSProviderResponse,
    ) -> SpeechTimingTrack | None:
        if not response.timing_units:
            return None
        supported = {
            SpeechTimingKind.PHONEME: capability.supports_phoneme_timing,
            SpeechTimingKind.MORA: capability.supports_mora_timing,
            SpeechTimingKind.VISEME: capability.supports_viseme_timing,
            SpeechTimingKind.WORD_BOUNDARY: True,
        }
        if any(not supported[unit.kind] for unit in response.timing_units):
            raise ValueError("provider timing capabilityが一致しません")
        units = tuple(
            SpeechTimingUnit(
                unit.unit_id, unit.segment_id, unit.kind, unit.symbol, unit.start_ms, unit.end_ms
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

    def _retry_allowed(self, error: TTSProviderError) -> bool:
        return error.retryable and error.code in self._policy.retryable_failure_codes

    def _failure(
        self,
        request: TTSSynthesisRequest,
        code: TTSFailureCode,
        attempts: int,
        status: TTSSynthesisStatus = TTSSynthesisStatus.FAILED,
    ) -> TTSSynthesisResult:
        return TTSSynthesisResult(
            request.request_id, status, attempts, self._now(), failure_code=code
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
            str(request.pronunciation_config_revision),
            *(f"{item.override_id}:{item.revision}" for item in request.pronunciation_overrides),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
