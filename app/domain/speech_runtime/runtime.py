from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

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


class SpeechRuntime:
    """候補局所の短い状態遷移だけを所有し、Role/Provider awaitを直列化しない。"""

    def __init__(self) -> None:
        self._candidates: dict[str, PreparedSpeechCandidate] = {}
        self._presentations: dict[str, str] = {}
        self._commands: dict[str, SpeechPresentationCommand] = {}
        self._reports: dict[str, tuple[SpeechPresentationReport, ...]] = {}
        self._generations: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def register(self, candidate: PreparedSpeechCandidate) -> None:
        async with self._lock:
            if candidate.candidate_id in self._candidates:
                raise ValueError("candidateは一意です")
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
            self._generations[candidate_id] += 1
            generation = self._generations[candidate_id]
            # 旧世代のartifact/acceptance/performanceはrepairへ継承しない。
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
                updated_at=datetime.now(timezone.utc),
            )
            self._candidates[candidate_id] = updated
            return updated

    async def update_readiness(
        self, candidate_id: str, readiness: SpeechComponentReadiness
    ) -> PreparedSpeechCandidate:
        generation = self.generation(candidate_id)
        updated = await self.commit_generation_result(candidate_id, generation, readiness=readiness)
        if updated is None:  # pragma: no cover - 同一event loop内では発生しない防御。
            raise ValueError("candidate generation が更新されました")
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
            if candidate.lifecycle is not CandidateLifecycle.QUEUED:
                return None
            updated = replace(
                candidate,
                lifecycle=CandidateLifecycle.REVALIDATING,
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
                or (candidate.expires_at is not None and candidate.expires_at <= state.observed_at)
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
