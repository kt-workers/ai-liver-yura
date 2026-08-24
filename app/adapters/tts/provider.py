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
    TTSCapabilityView,
    TTSDegradationReason,
    TTSFailureCode,
    TTSSynthesisPriority,
    TTSSynthesisRequest,
    TTSSynthesisResult,
    TTSSynthesisStatus,
)


class TTSProviderError(Exception):
    """Providerの生エラーを閉じ込めるためのInfrastructure内部例外。"""

    def __init__(self, code: TTSFailureCode, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code.value)


class TTSProviderClient(Protocol):
    async def synthesize(
        self, voice_ref: str, texts: tuple[str, ...], parameters: dict[str, float]
    ) -> tuple[str, str, str, int | None]: ...


@dataclass(frozen=True, slots=True)
class TTSProviderMappingPolicy:
    provider_config_revision: int
    max_attempts: int
    timeout_seconds: float
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
        if type(self.retry_backoff_seconds) not in (int, float) or self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds が不正です")
        if self.max_foreground_synthesis < 1 or self.max_speculative_synthesis < 1:
            raise ValueError("synthesis concurrency が不正です")
        if any(not isinstance(code, TTSFailureCode) for code in self.retryable_failure_codes):
            raise ValueError("retryable_failure_codes が不正です")


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
        parameters, degraded = self._map(
            request.capability, request.performance_plan.global_intent.values
        )
        texts = self._pronunciation_texts(request)
        if (
            request.pronunciation_overrides
            and not request.capability.supports_pronunciation_override
        ):
            texts = tuple(segment.text for segment in request.utterance.candidate.segments)
            degraded.append(TTSDegradationReason.UNSUPPORTED_DIMENSION)
        for attempt in range(1, self._policy.max_attempts + 1):
            try:
                audio_ref, audio_format, content_digest, duration_ms = await asyncio.wait_for(
                    self._client.synthesize(
                        request.voice_binding.provider_voice_ref, texts, parameters
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
                    audio_ref,
                    audio_format,
                    content_digest,
                    self._now(),
                    duration_ms,
                )
                return TTSSynthesisResult(
                    request.request_id,
                    TTSSynthesisStatus.SUCCEEDED,
                    attempt,
                    self._now(),
                    artifact,
                    degradation_reasons=tuple(degraded)
                    + (TTSDegradationReason.TIMING_UNAVAILABLE,),
                    applied_dimensions=tuple(parameters),
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
                            request,
                            TTSFailureCode.CANCELLED,
                            attempt,
                            TTSSynthesisStatus.CANCELLED,
                        )
                    continue
                return self._failure(request, error.code, attempt)
            except Exception:
                return self._failure(request, TTSFailureCode.PROVIDER_SERVER_ERROR, attempt)
        raise AssertionError("到達不能なretry状態です")

    def _retry_allowed(self, error: TTSProviderError) -> bool:
        return error.retryable and error.code in self._policy.retryable_failure_codes

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
    def _map(
        capability: TTSCapabilityView, values: tuple[tuple[PerformanceAxis, float], ...]
    ) -> tuple[dict[str, float], list[TTSDegradationReason]]:
        supported = {
            PerformanceAxis.PACE: capability.supports_rate,
            PerformanceAxis.PITCH_CENTER: capability.supports_pitch_center,
            PerformanceAxis.PITCH_RANGE: capability.supports_pitch_range,
            PerformanceAxis.LOUDNESS: capability.supports_loudness,
            PerformanceAxis.BREATHINESS: capability.supports_breathiness,
        }
        parameters: dict[str, float] = {}
        degraded: list[TTSDegradationReason] = []
        for axis, value in values:
            if axis not in supported:
                continue
            if supported[axis]:
                parameters[axis.value] = max(-1.0, min(1.0, value))
            elif value != 0.0:
                degraded.append(TTSDegradationReason.UNSUPPORTED_DIMENSION)
        return parameters, list(dict.fromkeys(degraded))

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
