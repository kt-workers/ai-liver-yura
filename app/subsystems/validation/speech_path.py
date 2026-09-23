"""本体発話経路の入力根拠・音声・受理済み提示を同じ検証結果へ残す。"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import wave
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import datetime
from time import monotonic_ns
from typing import Any
from weakref import WeakKeyDictionary

from app.adapters.tts import PreparedAudioResourceStore, TTSProviderAdapter
from app.adapters.tts.provider import ProviderSynthesisInput, TTSProviderClient, TTSProviderResponse
from app.composition.cognition import CoreCognitionDelivery
from app.composition.execution_observation import SPEECH_OBSERVATION_SOURCE
from app.composition.speech_feedback import CoreSpeechFeedback, SpeechFactDeliveryDisposition
from app.domain.brain_integration import BrainIntegrationWork, BrainWorkStatus
from app.domain.character_language import CharacterLanguageContextSnapshot, CharacterUtterance
from app.domain.contracts.common import JsonValue
from app.domain.executive import CommittedExecutiveDecision, ExecutiveIntentKind
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from app.domain.semantic_verification import SemanticVerificationContextSnapshot
from app.domain.semantic_verification.verifier import SemanticVerificationRun
from app.domain.speech_performance import SpeechPerformanceContextSnapshot, SpeechPerformancePlan
from app.domain.speech_runtime.contracts import (
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SpeechPresentationCommitState,
    SpeechPresentationMode,
    SpeechPresentationReportStatus,
)
from app.domain.speech_runtime.tasks import CandidateTaskKey
from app.domain.speech_semantics import SpeechSemanticContextSnapshot, SpeechSemanticPlan
from app.usecases.ports.llm import LLMRolePort

from .body import _project
from .cognition import _result_projection, _status
from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
    positive,
)
from .generated_audio import GeneratedAudioSettings
from .llm_port import ObservedLLMRolePort
from .runtime import LabTarget, RunContext
from .speech_presentation import _ObservedTasks
from .tts import _project as project_tts


class SpeechPathEvidence:
    """既存Ownerの公開値だけを有限に保持し、生のLLM応答を記録しない。"""

    def __init__(self, context: RunContext) -> None:
        self.context = context
        self.records: list[JsonValue] = []
        self.audio: dict[str, JsonValue] = {}
        self._audio_bytes = 0
        self._cleanups: list[Callable[[], Awaitable[None]]] = []

    def add_cleanup(self, close: Callable[[], Awaitable[None]]) -> None:
        if len(self._cleanups) >= self.context.policy.max_tasks:
            raise ValueError("発話検証の資源数が上限に達しました")
        self._cleanups.append(close)

    async def close(self) -> None:
        failed = False
        while self._cleanups:
            try:
                await self._cleanups.pop()()
            except Exception:
                failed = True
        if failed:
            raise RuntimeError("発話検証の資源回収に失敗しました")

    def append(self, stage: str, value: JsonValue) -> None:
        if len(self.records) >= self.context.policy.max_intervals:
            raise ValueError("発話経路の証拠件数が上限に達しました")
        self.records.append(
            _project({"stage": stage, "observed_ns": monotonic_ns(), "value": value})
        )

    def __call__(self, stage: str, value: object) -> None:
        if isinstance(
            value,
            (
                SpeechSemanticContextSnapshot,
                SpeechSemanticPlan,
                CharacterLanguageContextSnapshot,
                CharacterUtterance,
            ),
        ):
            projected = _project(value.to_dict())
        elif isinstance(value, SemanticVerificationRun):
            projected = _project(
                {
                    "blind_observation": value.blind_observation,
                    "relation_observation": value.relation_observation,
                    "semantic_observation": value.semantic_observation,
                    "acceptance": value.acceptance,
                }
            )
        elif isinstance(
            value,
            (
                SpeechPerformanceContextSnapshot,
                SpeechPerformancePlan,
                SemanticVerificationContextSnapshot,
                PreparedSpeechCandidate,
                SpeechPresentationCommitState,
            ),
        ):
            projected = _project(value)
        else:
            raise ValueError("発話経路の公開証拠型ではありません")
        self.append(stage, projected)

    def retain_wave(self, audio_ref: str, content: bytes) -> None:
        """trusted資源読取が取得した同じ音声を、参照解放後も評価できる形で保持する。"""
        if (
            not content
            or len(content) + self._audio_bytes > self.context.policy.max_export_bytes // 2
        ):
            raise ValueError("音声証拠は空か書出し容量を超えています")
        with wave.open(io.BytesIO(content), "rb") as source:
            if source.getnframes() < 1 or source.getframerate() < 1:
                raise ValueError("音声証拠に再生可能なframeがありません")
            metadata = {
                "sample_rate": source.getframerate(),
                "channels": source.getnchannels(),
                "frames": source.getnframes(),
                "sample_width": source.getsampwidth(),
            }
            raw = source.readframes(source.getnframes())
            if len(raw) != metadata["frames"] * metadata["channels"] * metadata["sample_width"]:
                raise ValueError("音声証拠のframeが欠損しています")
        artifact = _project(
            {
                "audio_ref": audio_ref,
                "media_type": "audio/wav",
                "metadata": metadata,
                "sha256": hashlib.sha256(content).hexdigest(),
                "data_base64": base64.b64encode(content).decode("ascii"),
            }
        )
        if audio_ref in self.audio and self.audio[audio_ref] != artifact:
            raise ValueError("同じ音声参照の内容が変更されています")
        if len(self.audio) >= self.context.policy.max_intervals and audio_ref not in self.audio:
            raise ValueError("音声証拠の件数上限に達しました")
        if audio_ref not in self.audio:
            self._audio_bytes += len(content)
        self.audio[audio_ref] = artifact


class SpeechPathAudioOutput:
    """本体output接続で実際のTTS Adapterを使い、合成と音声の同じ由来を保持する。"""

    def __init__(
        self,
        evidence: SpeechPathEvidence,
        settings: GeneratedAudioSettings,
        client: TTSProviderClient,
        resources: PreparedAudioResourceStore,
        clock: Callable[[], datetime],
        read_audio: Callable[[str], Awaitable[bytes]],
    ) -> None:
        self.evidence, self.settings = evidence, settings
        evidence.append("tts_configuration", settings.typed_inputs())
        self.client, self.resources, self.clock, self.read_audio = (
            client,
            resources,
            clock,
            read_audio,
        )

        class ObservedClient:
            async def synthesize(
                self, voice_ref: str, texts: tuple[str, ...], provider_input: ProviderSynthesisInput
            ) -> TTSProviderResponse:
                return await evidence.context.invoke_port(
                    "tts.provider", lambda: client.synthesize(voice_ref, texts, provider_input)
                )

        self._adapter = TTSProviderAdapter(
            ObservedClient(),
            settings.mapping,
            settings.operational,
            settings.retry,
            now=clock,
            resource_store=resources,
        )
        evidence.add_cleanup(self._adapter.shutdown)

    async def __call__(
        self, utterance: CharacterUtterance, performance: SpeechPerformancePlan
    ) -> tuple[SpeechPresentationMode, str | None]:
        candidate = utterance.candidate
        key = candidate.source_decision_id + ":" + candidate.source_intent_id
        request = self.settings.request(key, utterance, performance, self.clock())
        self.evidence.append("tts_request", project_tts(request))
        result = await self.evidence.context.invoke_product(
            "tts.synthesis", lambda: self._adapter.synthesize(request)
        )
        self.evidence.append("tts_result", project_tts(result))
        if result.artifact is None:
            raise ValueError("本体発話の音声合成が成功していません")
        reference = result.artifact.audio_ref
        content = await self.evidence.context.invoke_port(
            "speech_path.audio_evidence", lambda: self.read_audio(reference)
        )
        self.evidence.retain_wave(reference, content)
        return SpeechPresentationMode.AUDIO_WITH_TEXT, reference


class SpeechPathLLMPort:
    """raw応答を複製せず、実際のRole要求と結果の方針・Mapping来歴を記録する。"""

    def __init__(self, evidence: SpeechPathEvidence, port: LLMRolePort) -> None:
        self.evidence = evidence
        self.port = ObservedLLMRolePort(
            evidence.context,
            port,
            {
                role: "speech_path.llm"
                for role in (
                    "speech_semantics",
                    "character_language",
                    "semantic_verification_blind_inventory",
                    "semantic_verification_plan_relation",
                )
            },
        )

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self.evidence.append(
            "llm_request",
            _project(
                {
                    "request_id": request.request_id,
                    "role_id": request.role_id,
                    "trace_id": request.trace_id,
                    "policy": request.execution_policy,
                }
            ),
        )
        result = await self.port.invoke(request)
        self.evidence.append(
            "llm_result",
            _project(
                {
                    "request_id": result.request_id,
                    "role_id": result.role_id,
                    "trace_id": result.trace_id,
                    "status": result.status,
                    "model_class": result.model_class,
                    "execution_provenance": result.execution_provenance,
                    "attempt_count": result.attempt_count,
                    "token_usage": result.token_usage,
                    "started_at": result.started_at,
                    "completed_at": result.completed_at,
                    "failure_code": None if result.failure is None else result.failure.code,
                }
            ),
        )
        return result


@dataclass(frozen=True)
class SpeechPathLabCase:
    fixture: ValidationFixture
    work: BrainIntegrationWork
    decision: CommittedExecutiveDecision
    require_audio: bool = True

    def __post_init__(self) -> None:
        if type(self.require_audio) is not bool:
            raise ValueError("音声必須条件はboolで指定してください")

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "envelope": self.work.envelope,
                "decision": self.decision.to_dict(),
                "require_audio": self.require_audio,
            }
        )


class SpeechPathTasks(_ObservedTasks):
    """本番のcandidate task登録を保ち、有限な提示処理を結果消費まで保持する。"""

    def __init__(self, maximum: int) -> None:
        super().__init__()
        positive(maximum)
        self.maximum = maximum

    def start(
        self, key: CandidateTaskKey, work: Coroutine[Any, Any, object]
    ) -> asyncio.Task[object]:
        try:
            if len(self.started) >= self.maximum:
                raise ValueError("提示処理の検証上限に達しました")
            return super().start(key, work)
        except BaseException:
            work.close()
            raise


@dataclass
class SpeechPathSession:
    """trusted構成元が所有する本体接続と、その起動・終了処理を明示する。"""

    cognition: CoreCognitionDelivery
    presentation_tasks: SpeechPathTasks
    start: Callable[[], Awaitable[None]]
    close: Callable[[], Awaitable[None]]


@dataclass
class _IterationSession:
    current: SpeechPathSession | None = None
    evidence: SpeechPathEvidence | None = None

    async def close(self) -> None:
        try:
            if self.current is not None:
                await self.current.close()
                self.current = None
        finally:
            if self.evidence is not None:
                await self.evidence.close()
                self.evidence = None


def speech_path_target(
    cases: tuple[SpeechPathLabCase, ...],
    session_factory: Callable[[RunContext, SpeechPathEvidence], Awaitable[SpeechPathSession]],
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
    *,
    provenance_source: Callable[[], ProductionTargetProvenance],
) -> LabTarget:
    """Brain-Dの確定判断配送とprocess提示を使い、人間評価は共通基盤へ残す。"""
    registered = {case.fixture.scenario_id: case for case in cases}
    if (
        len(registered) != len(cases)
        or not callable(session_factory)
        or not callable(provenance_source)
    ):
        raise ValueError("発話経路の登録条件が不正です")
    ownership: WeakKeyDictionary[RunContext, _IterationSession] = WeakKeyDictionary()

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        actual = provenance_source()
        if not isinstance(actual, ProductionTargetProvenance):
            raise ValueError("現在の製品来歴の公開型が不正です")
        if actual != provenance:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        expected = {
            case.decision.decision_id + ":" + intent.intent_id + ":presentation"
            for intent in case.decision.candidate.intents
            if intent.kind is ExecutiveIntentKind.SPEECH
        }
        if not expected:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        owner = ownership.get(context)
        if owner is None:
            owner = _IterationSession()
            ownership[context] = owner
            context.add_cleanup("speech_path.close", owner.close)
        if owner.current is not None:
            raise ValueError("前iterationの発話sessionが未終了です")
        evidence = SpeechPathEvidence(context)
        owner.evidence = evidence
        session = await session_factory(context, evidence)
        if not isinstance(session, SpeechPathSession):
            raise ValueError("正規の発話sessionが必要です")
        owner.current = session
        speech = session.cognition.speech
        if (
            speech is None
            or speech.pipeline.evidence_sink is not evidence
            or session.presentation_tasks.maximum > context.policy.max_tasks
        ):
            await owner.close()
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        await context.invoke_product("speech_path.start", session.start)

        async def submit() -> None:
            speech.accept_decision(case.work, case.decision)

        await context.invoke_product("speech_path.submit_decision", submit)
        brain = session.cognition.brain
        observed: set[str] = set()
        feedbacks: dict[str, CoreSpeechFeedback] = {}
        outputs: list[JsonValue] = []
        status = RunStatus.COMPLETED
        for _ in range(context.policy.max_intervals):
            outcome = await context.invoke_product("speech_path.outcome", brain.next_outcome)
            trace = brain.trace(case.work.envelope.trace_id)
            if (
                outcome.trace_id != trace.trace_id
                or outcome.work_id in observed
                or outcome.work_id not in {i.work_id for i in trace.intervals}
            ):
                raise ValueError("発話経路の公開outcomeとtraceが一致しません")
            observed.add(outcome.work_id)
            result = outcome.result
            if isinstance(result, CoreSpeechFeedback):
                if result.presentation_id not in expected:
                    raise ValueError("確定判断に由来しない提示結果です")
                feedbacks[result.presentation_id] = result
                projected = _project({"presentation_id": result.presentation_id})

                async def settle() -> None:
                    await asyncio.gather(
                        *session.presentation_tasks.started, return_exceptions=True
                    )

                await context.invoke_product("speech_path.presentation", settle)
            else:
                projected = _result_projection(result)
            outputs.append(
                _project(
                    {
                        "work_id": outcome.work_id,
                        "module": outcome.module,
                        "lane": outcome.lane,
                        "status": outcome.status,
                        "completed_at": outcome.completed_at,
                        "result": projected,
                    }
                )
            )
            current_status = _status(outcome.status, result)
            if status is RunStatus.COMPLETED and current_status is not RunStatus.COMPLETED:
                status = current_status
            trace = brain.trace(case.work.envelope.trace_id)
            if observed == {i.work_id for i in trace.intervals}:
                break
        presentations: list[JsonValue] = []
        complete = set(feedbacks) == expected
        for presentation_id, feedback in feedbacks.items():
            command, candidate, reports = await feedback.runtime.presentation_snapshot(
                presentation_id
            )
            record = feedback.authority.observed_snapshot(
                SPEECH_OBSERVATION_SOURCE.source_contract_id, presentation_id
            ).value
            audio_available = candidate.prepared_audio_ref in evidence.audio
            complete = complete and (
                candidate.lifecycle is CandidateLifecycle.COMPLETED
                and any(r.status is SpeechPresentationReportStatus.STARTED for r in reports)
                and any(r.status is SpeechPresentationReportStatus.COMPLETED for r in reports)
                and feedback.disposition is SpeechFactDeliveryDisposition.DELIVERED
                and record is not None
                and (not case.require_audio or audio_available)
            )
            presentations.append(
                _project(
                    {
                        "command": command,
                        "candidate": candidate,
                        "reports": reports,
                        "execution_fact": record,
                        "delivery": feedback.disposition,
                        "audio_available": audio_available,
                    }
                )
            )
        trace = brain.trace(case.work.envelope.trace_id)
        complete = complete and (
            observed == {i.work_id for i in trace.intervals}
            and all(i.status is BrainWorkStatus.COMPLETED for i in trace.intervals)
            and trace.root_trigger_id
            == (case.work.envelope.root_trigger_id or case.work.envelope.trigger_id)
        )
        if speech.pipeline.evidence_failed:
            status = RunStatus.HARNESS_FAILED
        elif status is RunStatus.COMPLETED and not complete:
            status = RunStatus.PRODUCT_FAILED
        await context.invoke_product("speech_path.close", owner.close)
        return TargetObservation(
            status,
            Gate.PASS if complete and status is RunStatus.COMPLETED else Gate.FAIL,
            _project(
                {
                    "evidence": evidence.records,
                    "audio": tuple(evidence.audio.values()),
                    "presentations": presentations,
                    "outcomes": outputs,
                    "trace": trace,
                }
            ),
        )

    return LabTarget(
        "speech_path",
        contract_revision,
        frozenset({LabMode.INTEGRATED}),
        provider_policy_refs,
        provenance,
        run,
        frozenset({"tts.provider", "speech_path.audio_evidence", "speech_path.llm"}),
        frozenset({"speech_path.llm"}),
    )
