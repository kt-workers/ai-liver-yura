from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from time import monotonic_ns

from .contracts import (
    AudioReadinessState,
    CandidateLifecycle,
    PreparedSpeechCandidate,
    SemanticVerificationRequirement,
    SpeechComponentReadiness,
    SpeechPresentationCommand,
    SpeechPresentationCommitState,
    SpeechPresentationMode,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
    SpeechReadinessState,
    VerifierReadinessState,
)
from .policy import SpeechRuntimeOperationalPolicy, V2_SPEECH_RUNTIME_OPERATIONAL_POLICY

MonotonicMsSource = Callable[[], int]


def _system_monotonic_ms() -> int:
    return monotonic_ns() // 1_000_000


class SpeechRuntime:
    """候補局所の短い状態遷移だけを所有し、Role/Provider awaitを直列化しない。"""

    def __init__(
        self,
        policy: SpeechRuntimeOperationalPolicy = V2_SPEECH_RUNTIME_OPERATIONAL_POLICY,
        monotonic_ms: MonotonicMsSource = _system_monotonic_ms,
    ) -> None:
        if not isinstance(policy, SpeechRuntimeOperationalPolicy):
            raise ValueError("Speech Runtime operational policy が不正です")
        if not callable(monotonic_ms):
            raise ValueError("monotonic_ms source が不正です")
        self._policy = policy
        self._monotonic_ms = monotonic_ms
        self._candidates: dict[str, PreparedSpeechCandidate] = {}
        self._presentations: dict[str, str] = {}
        self._commands: dict[str, SpeechPresentationCommand] = {}
        self._reports: dict[str, tuple[SpeechPresentationReport, ...]] = {}
        self._generations: dict[str, int] = {}
        self._lock = asyncio.Lock()

    @property
    def operational_policy(self) -> SpeechRuntimeOperationalPolicy:
        return self._policy

    async def update_operational_policy(self, policy: SpeechRuntimeOperationalPolicy) -> None:
        """新generationをcurrentにする。既存candidateへ新しい数値は付け替えない。"""
        if not isinstance(policy, SpeechRuntimeOperationalPolicy):
            raise ValueError("Speech Runtime operational policy が不正です")
        async with self._lock:
            self._policy = policy

    def _now_mono_ms(self) -> int:
        value = self._monotonic_ms()
        if type(value) is not int or value < 0:
            raise ValueError("monotonic clock は0以上の整数msを返す必要があります")
        return value

    def _policy_matches(self, candidate: PreparedSpeechCandidate) -> bool:
        return (
            candidate.runtime_policy_id == self._policy.policy_id
            and candidate.runtime_policy_revision == self._policy.policy_revision
        )

    async def operational_failure(self, candidate_id: str) -> str | None:
        """raw payloadを含めずcandidateのD10 operational failureだけを返す。"""
        async with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                raise ValueError("candidateが存在しません")
            if not self._policy_matches(candidate):
                return "runtime_policy_stale"
            now = self._now_mono_ms()
            if candidate.is_expired_mono(now):
                return "prepared_candidate_expired"
            if candidate.revalidation_is_too_old(now):
                return "revalidation_too_old"
            return None

    async def register(self, candidate: PreparedSpeechCandidate) -> None:
        async with self._lock:
            if candidate.candidate_id in self._candidates:
                raise ValueError("candidateは一意です")
            now = self._now_mono_ms()
            if candidate.has_operational_snapshot:
                if not self._policy_matches(candidate):
                    raise ValueError("candidate runtime policy generation がcurrentではありません")
            else:
                candidate = replace(
                    candidate,
                    runtime_policy_id=self._policy.policy_id,
                    runtime_policy_revision=self._policy.policy_revision,
                    created_mono_ms=now,
                    prepared_mono_ms=now,
                    prepared_ttl_ms=self._policy.prepared_candidate_ttl_ms,
                    revalidation_max_age_ms=self._policy.revalidation_max_age_ms,
                )
            self._candidates[candidate.candidate_id] = candidate
            self._generations[candidate.candidate_id] = 1

    def generation(self, candidate_id: str) -> int:
        return self._generations[candidate_id]

    async def candidate(self, candidate_id: str) -> PreparedSpeechCandidate:
        """現在の不変candidateを返す。呼出側は返値を更新してはならない。"""
        async with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                raise ValueError("candidateが存在しません")
            return candidate

    async def is_current_generation(self, candidate_id: str, generation: int) -> bool:
        async with self._lock:
            return self._generations.get(candidate_id) == generation

    async def supersede_generation(
        self, candidate_id: str, expected_generation: int
    ) -> int | None:
        """repair/rebind前に古いperformance/audio結果をcandidate局所で無効化する。"""
        async with self._lock:
            if self._generations.get(candidate_id) != expected_generation:
                return None
            candidate = self._active(candidate_id)
            if not self._policy_matches(candidate):
                return None
            self._generations[candidate_id] += 1
            generation = self._generations[candidate_id]
            self._candidates[candidate_id] = replace(
                candidate,
                utterance_id=None,
                performance_plan_id=None,
                semantic_acceptance_id=None,
                prepared_audio_ref=None,
                readiness=SpeechComponentReadiness(
                    semantics=candidate.readiness.semantics,
                    character=SpeechReadinessState.PENDING,
                    verifier=VerifierReadinessState.PENDING,
                    performance=SpeechReadinessState.PENDING,
                    audio=AudioReadinessState.NOT_REQUESTED,
                ),
                lifecycle=CandidateLifecycle.PREPARING,
                repair_count=candidate.repair_count + 1,
                revalidation_started_mono_ms=None,
                updated_at=datetime.now(timezone.utc),
            )
            return generation

    async def rebind_performance_for_expression(
        self, candidate_id: str, expected_generation: int, expression_revision: int
    ) -> int | None:
        """意味・Characterを保ったままdynamic expressionだけを最新化する。"""
        if type(expression_revision) is not int or expression_revision < 1:
            raise ValueError("expression_revision が不正です")
        async with self._lock:
            if self._generations.get(candidate_id) != expected_generation:
                return None
            candidate = self._active(candidate_id)
            if not self._policy_matches(candidate):
                return None
            if candidate.utterance_id is None or candidate.semantic_acceptance_id is None:
                raise ValueError("valid Character/semantic acceptance が必要です")
            if candidate.prepared_audio_ref is not None:
                raise ValueError("prepared audioのperformance rebindにはdiscardが必要です")
            self._generations[candidate_id] += 1
            generation = self._generations[candidate_id]
            self._candidates[candidate_id] = replace(
                candidate,
                performance_plan_id=None,
                prepared_audio_ref=None,
                expression_revision=expression_revision,
                performance_generation=candidate.performance_generation + 1,
                readiness=SpeechComponentReadiness(
                    semantics=candidate.readiness.semantics,
                    character=SpeechReadinessState.READY,
                    verifier=VerifierReadinessState.ACCEPTED,
                    performance=SpeechReadinessState.PENDING,
                    audio=AudioReadinessState.NOT_REQUESTED,
                ),
                lifecycle=CandidateLifecycle.PREPARING,
                revalidation_started_mono_ms=None,
                updated_at=datetime.now(timezone.utc),
            )
            return generation

    async def update_readiness_for_generation(
        self, candidate_id: str, generation: int, readiness: SpeechComponentReadiness
    ) -> PreparedSpeechCandidate | None:
        return await self.commit_generation_result(candidate_id, generation, readiness=readiness)

    async def commit_generation_result(
        self,
        candidate_id: str,
        generation: int,
        *,
        readiness: SpeechComponentReadiness,
        utterance_id: str | None = None,
        performance_plan_id: str | None = None,
        semantic_acceptance_id: str | None = None,
        prepared_audio_ref: str | None = None,
        clear_prepared_audio: bool = False,
    ) -> PreparedSpeechCandidate | None:
        """全Role完了が共有する世代fence付きcommit境界。"""
        async with self._lock:
            if self._generations.get(candidate_id) != generation:
                return None
            candidate = self._active(candidate_id)
            if not self._policy_matches(candidate):
                return None
            verifier_ok = (
                candidate.semantic_requirement
                is SemanticVerificationRequirement.NOT_REQUIRED_BY_CLOSED_POLICY
                or readiness.verifier is VerifierReadinessState.ACCEPTED
            )
            lifecycle = candidate.lifecycle
            if readiness.verifier is VerifierReadinessState.REJECTED:
                lifecycle = CandidateLifecycle.REJECTED
            elif any(
                value in (SpeechReadinessState.FAILED, SpeechReadinessState.STALE)
                for value in (readiness.semantics, readiness.character, readiness.performance)
            ) or readiness.verifier in {
                VerifierReadinessState.FAILED,
                VerifierReadinessState.STALE,
            }:
                lifecycle = CandidateLifecycle.FAILED
            elif (
                readiness.character is SpeechReadinessState.READY
                and readiness.performance is SpeechReadinessState.READY
                and verifier_ok
            ):
                lifecycle = CandidateLifecycle.PREPARED
            prepared_mono_ms = candidate.prepared_mono_ms
            if lifecycle is CandidateLifecycle.PREPARED and candidate.lifecycle is not CandidateLifecycle.PREPARED:
                prepared_mono_ms = self._now_mono_ms()
            updated = replace(
                candidate,
                utterance_id=utterance_id if utterance_id is not None else candidate.utterance_id,
                performance_plan_id=(
                    performance_plan_id
                    if performance_plan_id is not None
                    else candidate.performance_plan_id
                ),
                semantic_acceptance_id=(
                    semantic_acceptance_id
                    if semantic_acceptance_id is not None
                    else candidate.semantic_acceptance_id
                ),
                prepared_audio_ref=(
                    None
                    if clear_prepared_audio
                    else prepared_audio_ref
                    if prepared_audio_ref is not None
                    else candidate.prepared_audio_ref
                ),
                readiness=readiness,
                lifecycle=lifecycle,
                prepared_mono_ms=prepared_mono_ms,
                updated_at=datetime.now(timezone.utc),
            )
            self._candidates[candidate_id] = updated
            return updated

    async def update_readiness(
        self, candidate_id: str, readiness: SpeechComponentReadiness
    ) -> PreparedSpeechCandidate:
        generation = self.generation(candidate_id)
        updated = await self.commit_generation_result(candidate_id, generation, readiness=readiness)
        if updated is None:
            raise ValueError("candidate generation又はruntime policyが更新されました")
        return updated

    async def cancel(
        self,
        candidate_id: str,
        lifecycle: CandidateLifecycle = CandidateLifecycle.CANCELLED,
        *,
        expected_generation: int | None = None,
    ) -> PreparedSpeechCandidate | None:
        if lifecycle not in {
            CandidateLifecycle.CANCELLED,
            CandidateLifecycle.SUPERSEDED,
            CandidateLifecycle.STALE,
            CandidateLifecycle.FAILED,
        }:
            raise ValueError("terminal lifecycle が不正です")
        async with self._lock:
            if (
                expected_generation is not None
                and self._generations.get(candidate_id) != expected_generation
            ):
                return None
            candidate = self._active(candidate_id)
            if candidate.prepared_audio_ref is not None:
                raise ValueError("prepared audioのterminal遷移にはdiscardが必要です")
            updated = replace(candidate, lifecycle=lifecycle, updated_at=datetime.now(timezone.utc))
            self._candidates[candidate_id] = updated
            return updated

    async def queue_for_generation(
        self, candidate_id: str, generation: int
    ) -> PreparedSpeechCandidate | None:
        async with self._lock:
            if self._generations.get(candidate_id) != generation:
                return None
            candidate = self._active(candidate_id)
            if not self._policy_matches(candidate) or candidate.is_expired_mono(self._now_mono_ms()):
                return None
            if candidate.lifecycle is not CandidateLifecycle.PREPARED:
                raise ValueError("PREPARED candidateだけをqueueへ入れられます")
            updated = replace(
                candidate,
                lifecycle=CandidateLifecycle.QUEUED,
                updated_at=datetime.now(timezone.utc),
            )
            self._candidates[candidate_id] = updated
            return updated

    async def begin_revalidation(
        self, candidate_id: str, expected_generation: int
    ) -> PreparedSpeechCandidate | None:
        async with self._lock:
            if self._generations.get(candidate_id) != expected_generation:
                return None
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                raise ValueError("candidateが存在しません")
            if not self._policy_matches(candidate) or candidate.is_expired_mono(self._now_mono_ms()):
                return None
            if candidate.lifecycle is not CandidateLifecycle.QUEUED:
                return None
            updated = replace(
                candidate,
                lifecycle=CandidateLifecycle.REVALIDATING,
                revalidation_started_mono_ms=self._now_mono_ms(),
                updated_at=datetime.now(timezone.utc),
            )
            self._candidates[candidate_id] = updated
            return updated

    async def complete_revalidation(
        self,
        candidate_id: str,
        expected_generation: int,
        passed: bool,
        failure: CandidateLifecycle | None = None,
    ) -> PreparedSpeechCandidate | None:
        async with self._lock:
            if self._generations.get(candidate_id) != expected_generation:
                return None
            candidate = self._active(candidate_id)
            if candidate.lifecycle is not CandidateLifecycle.REVALIDATING:
                raise ValueError("revalidation中のcandidateが必要です")
            if not self._policy_matches(candidate):
                passed = False
                failure = CandidateLifecycle.STALE
            now_mono_ms = self._now_mono_ms()
            if candidate.is_expired_mono(now_mono_ms) or candidate.revalidation_is_too_old(
                now_mono_ms
            ):
                passed = False
                failure = CandidateLifecycle.STALE
            if passed:
                lifecycle = CandidateLifecycle.READY_TO_PRESENT
            else:
                if failure not in {
                    CandidateLifecycle.STALE,
                    CandidateLifecycle.CANCELLED,
                    CandidateLifecycle.SUPERSEDED,
                    CandidateLifecycle.FAILED,
                }:
                    raise ValueError("revalidation failure lifecycle が不正です")
                if candidate.prepared_audio_ref is not None:
                    raise ValueError("prepared audioのrevalidation failureにはdiscardが必要です")
                lifecycle = failure
            updated = replace(
                candidate,
                lifecycle=lifecycle,
                updated_at=datetime.now(timezone.utc),
            )
            self._candidates[candidate_id] = updated
            return updated

    async def commit(
        self, candidate_id: str, state: SpeechPresentationCommitState, presentation_id: str
    ) -> SpeechPresentationCommand:
        async with self._lock:
            candidate = self._active(candidate_id)
            now_mono_ms = self._now_mono_ms()
            if (
                not self._policy_matches(candidate)
                or candidate.is_expired_mono(now_mono_ms)
                or candidate.revalidation_is_too_old(now_mono_ms)
            ):
                raise ValueError("Speech Runtime operational revalidationに失敗しました")
            if (
                candidate.lifecycle is not CandidateLifecycle.READY_TO_PRESENT
                or presentation_id in self._presentations
            ):
                raise ValueError("Presentation commitが不正です")
            if (
                candidate.source_context_revision != state.source_context_revision
                or candidate.goal_revision != state.goal_revision
                or candidate.attention_revision != state.attention_revision
                or (candidate.turn_id is not None and candidate.turn_id != state.turn_id)
                or (
                    candidate.focus_revision is not None
                    and candidate.focus_revision != state.focus_revision
                )
                or (
                    state.semantic_acceptance_id is not None
                    and candidate.semantic_acceptance_id != state.semantic_acceptance_id
                )
                or (
                    state.performance_plan_id is not None
                    and candidate.performance_plan_id != state.performance_plan_id
                )
                or (
                    state.prepared_audio_ref is not None
                    and candidate.prepared_audio_ref != state.prepared_audio_ref
                )
                or (candidate.response_obligation_id != state.response_obligation_id)
                or (
                    candidate.character_definition_revision is not None
                    and candidate.character_definition_revision
                    != state.character_definition_revision
                )
                or not state.character_compatible
                or not state.expiry_valid
                or not state.capability.output_available
            ):
                raise ValueError("live revalidationに失敗しました")
            if candidate.semantic_requirement is SemanticVerificationRequirement.REQUIRED and (
                candidate.semantic_acceptance_id is None
                or state.semantic_acceptance_id is None
                or candidate.semantic_acceptance_id != state.semantic_acceptance_id
            ):
                raise ValueError("SemanticAcceptanceが必要です")
            if candidate.performance_plan_id is None or (
                state.performance_plan_id is None
                or candidate.performance_plan_id != state.performance_plan_id
            ):
                raise ValueError("current PerformancePlanが必要です")
            if (
                candidate.expression_revision is not None
                and candidate.expression_revision != state.expression_revision
            ):
                raise ValueError("expression driftにはperformance rebindが必要です")
            if (
                not set(candidate.required_preconditions) <= set(state.satisfied_preconditions)
                or candidate.utterance_id is None
            ):
                raise ValueError("Presentation preconditionが不正です")
            if (
                candidate.prepared_audio_ref
                and state.capability.audio_available
                and SpeechPresentationMode.AUDIO_WITH_TEXT in candidate.presentation_modes
            ):
                if (
                    state.prepared_audio_ref is None
                    or state.prepared_audio_ref != candidate.prepared_audio_ref
                ):
                    raise ValueError("current prepared audioが必要です")
                modes = (SpeechPresentationMode.AUDIO_WITH_TEXT,)
            elif (
                state.capability.text_available
                and SpeechPresentationMode.TEXT_ONLY in candidate.presentation_modes
            ):
                modes = (SpeechPresentationMode.TEXT_ONLY,)
            else:
                raise ValueError("Presentation modeが利用不能です")
            self._presentations[presentation_id] = candidate_id
            command = SpeechPresentationCommand(
                presentation_id,
                candidate_id,
                candidate.utterance_id,
                candidate.prepared_audio_ref,
                modes,
                state.observed_at,
            )
            self._commands[presentation_id] = command
            self._candidates[candidate_id] = replace(
                candidate, lifecycle=CandidateLifecycle.PRESENTING, updated_at=state.observed_at
            )
            return command

    async def accept_report(self, report: SpeechPresentationReport) -> PreparedSpeechCandidate:
        async with self._lock:
            candidate = self._active(report.candidate_id)
            if self._presentations.get(report.presentation_id) != report.candidate_id:
                raise ValueError("Presentation reportのidentityが不正です")
            command = self._commands[report.presentation_id]
            if report.output_modes != command.modes or report.audio_ref != command.audio_ref:
                raise ValueError("Presentation reportのasset identityが不正です")
            previous = self._reports.get(report.presentation_id, ())
            if not previous:
                if report.status not in {
                    SpeechPresentationReportStatus.STARTED,
                    SpeechPresentationReportStatus.FAILED_BEFORE_START,
                }:
                    raise ValueError("terminal reportの前にSTARTEDが必要です")
            elif (
                len(previous) != 1
                or previous[0].status is not SpeechPresentationReportStatus.STARTED
                or report.status
                not in {
                    SpeechPresentationReportStatus.COMPLETED,
                    SpeechPresentationReportStatus.FAILED_AFTER_START,
                    SpeechPresentationReportStatus.INTERRUPTED,
                }
            ):
                raise ValueError("Presentation reportの順序が不正です")
            if candidate.lifecycle is not CandidateLifecycle.PRESENTING:
                raise ValueError("Presentation reportのlifecycleが不正です")
            lifecycle = {
                SpeechPresentationReportStatus.COMPLETED: CandidateLifecycle.COMPLETED,
                SpeechPresentationReportStatus.INTERRUPTED: CandidateLifecycle.INTERRUPTED,
                SpeechPresentationReportStatus.FAILED_BEFORE_START: CandidateLifecycle.FAILED,
                SpeechPresentationReportStatus.FAILED_AFTER_START: CandidateLifecycle.FAILED,
                SpeechPresentationReportStatus.STARTED: CandidateLifecycle.PRESENTING,
            }[report.status]
            updated = replace(
                candidate,
                lifecycle=lifecycle,
                updated_at=report.completed_at or report.started_at or datetime.now(timezone.utc),
            )
            self._candidates[candidate.candidate_id] = updated
            self._reports[report.presentation_id] = (*previous, report)
            return updated

    async def presentation_reports(
        self, presentation_id: str
    ) -> tuple[SpeechPresentationReport, ...]:
        async with self._lock:
            return self._reports.get(presentation_id, ())

    async def fail_presentation_stream(self, candidate_id: str) -> PreparedSpeechCandidate:
        """STARTED後にterminal reportを失ったAdapter streamをfail-closedで閉じる。"""
        async with self._lock:
            candidate = self._active(candidate_id)
            if candidate.lifecycle is not CandidateLifecycle.PRESENTING:
                raise ValueError("presentation stream failureのlifecycleが不正です")
            updated = replace(
                candidate,
                lifecycle=CandidateLifecycle.FAILED,
                updated_at=datetime.now(timezone.utc),
            )
            self._candidates[candidate_id] = updated
            return updated

    async def shutdown(self) -> tuple[str, ...]:
        """外部I/Oを待たず、active candidateをterminalへ閉じる。"""
        async with self._lock:
            closed: list[str] = []
            terminal = {
                CandidateLifecycle.CANCELLED,
                CandidateLifecycle.SUPERSEDED,
                CandidateLifecycle.STALE,
                CandidateLifecycle.REJECTED,
                CandidateLifecycle.FAILED,
                CandidateLifecycle.COMPLETED,
                CandidateLifecycle.INTERRUPTED,
            }
            for candidate_id, candidate in tuple(self._candidates.items()):
                if candidate.lifecycle not in terminal:
                    if candidate.prepared_audio_ref is not None:
                        raise ValueError("prepared audioのshutdownにはdiscardが必要です")
                    self._candidates[candidate_id] = replace(
                        candidate,
                        lifecycle=CandidateLifecycle.CANCELLED,
                        updated_at=datetime.now(timezone.utc),
                    )
                    closed.append(candidate_id)
            return tuple(closed)

    async def active_candidate_ids(self) -> tuple[str, ...]:
        """shutdown等がdiscardを先行させるためのcandidate局所snapshotを返す。"""
        async with self._lock:
            terminal = {
                CandidateLifecycle.CANCELLED,
                CandidateLifecycle.SUPERSEDED,
                CandidateLifecycle.STALE,
                CandidateLifecycle.REJECTED,
                CandidateLifecycle.FAILED,
                CandidateLifecycle.COMPLETED,
                CandidateLifecycle.INTERRUPTED,
            }
            return tuple(
                candidate_id
                for candidate_id, candidate in self._candidates.items()
                if candidate.lifecycle not in terminal
            )

    def _active(self, candidate_id: str) -> PreparedSpeechCandidate:
        candidate = self._candidates.get(candidate_id)
        if candidate is None:
            raise ValueError("candidateが存在しません")
        if candidate.lifecycle in {
            CandidateLifecycle.CANCELLED,
            CandidateLifecycle.SUPERSEDED,
            CandidateLifecycle.STALE,
            CandidateLifecycle.REJECTED,
            CandidateLifecycle.FAILED,
            CandidateLifecycle.COMPLETED,
            CandidateLifecycle.INTERRUPTED,
        }:
            raise ValueError("terminal candidateは再活性化できません")
        return candidate
