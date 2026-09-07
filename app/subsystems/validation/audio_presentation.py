"""合成した音声の公開参照を、同じ資源参照表とともに提示入口へ渡す。"""

from collections.abc import Callable
from dataclasses import dataclass, replace

from app.adapters.tts import InMemoryPreparedAudioResourceStore, PreparedAudioResourceStore
from app.adapters.tts.provider import TTSProviderClient
from app.domain.contracts.common import JsonValue
from app.domain.speech_runtime.contracts import AudioReadinessState
from app.domain.speech_runtime.discard import PreparedAudioDiscardRequest
from app.domain.speech_runtime.presentation import PresentationAdapter

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .runtime import LabTarget, RunContext
from .speech_presentation import SpeechPresentationCase, present_speech
from .tts import TTSSynthesisCase, _project, synthesis_run_status, synthesize_audio


class LabAudioResources:
    """反復内の参照表を所有し、破棄と終了で公開参照を無効にする。"""

    def __init__(self) -> None:
        self._store = InMemoryPreparedAudioResourceStore()
        self._revoked: set[str] = set()

    def store(self, artifact_id: str, request_id: str, raw_resource_ref: str) -> str:
        return self._store.store(artifact_id, request_id, raw_resource_ref)

    def resolve(self, artifact_ref: str) -> str | None:
        return None if artifact_ref in self._revoked else self._store.resolve(artifact_ref)

    async def discard(self, request: PreparedAudioDiscardRequest) -> None:
        self._revoked.add(request.audio_ref)

    async def close(self) -> None:
        self._store = InMemoryPreparedAudioResourceStore()
        self._revoked.clear()


@dataclass(frozen=True)
class AudioPresentationCase:
    fixture: ValidationFixture
    synthesis: TTSSynthesisCase
    presentation: SpeechPresentationCase

    def __post_init__(self) -> None:
        request, candidate = self.synthesis.request, self.presentation.candidate
        utterance = request.utterance.candidate
        if (
            request.candidate_id != candidate.candidate_id
            or request.utterance.utterance_id != candidate.utterance_id
            or request.performance_plan.performance_plan_id != candidate.performance_plan_id
            or utterance.semantic_plan_id != candidate.speech_plan_id
            or utterance.source_decision_id != candidate.source_decision_id
            or utterance.source_event_ids != candidate.source_event_ids
            or utterance.revisions.source_context_revision != candidate.source_context_revision
            or utterance.revisions.goal_revision != candidate.goal_revision
            or utterance.revisions.attention_revision != candidate.attention_revision
            or candidate.prepared_audio_ref is not None
        ):
            raise ValueError("合成要求と提示候補の対応が一致しません")

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "synthesis": self.synthesis.typed_inputs(),
                "presentation": self.presentation.typed_inputs(),
            }
        )


def audio_presentation_target(
    cases: tuple[AudioPresentationCase, ...],
    client: TTSProviderClient,
    adapter: Callable[[PreparedAudioResourceStore], PresentationAdapter],
    provenance: ProductionTargetProvenance,
    contract_revision: str,
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("音声提示の結合検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        resources = LabAudioResources()
        context.add_cleanup("audio.resources", resources.close)
        request, result = await synthesize_audio(
            context, replace(case.synthesis, fixture=fixture), client, resources
        )
        if result.artifact is None:
            return TargetObservation(
                synthesis_run_status(result),
                Gate.NOT_RUN,
                _project({"synthesis": result, "presentation": None}),
            )
        observed_at = max(case.presentation.state.observed_at, result.completed_at)
        candidate = replace(
            case.presentation.candidate,
            candidate_id=request.candidate_id,
            prepared_audio_ref=result.artifact.audio_ref,
            readiness=replace(
                case.presentation.candidate.readiness, audio=AudioReadinessState.READY
            ),
            updated_at=observed_at,
        )
        state = replace(
            case.presentation.state,
            observed_at=observed_at,
            prepared_audio_ref=result.artifact.audio_ref,
        )
        presentation = await present_speech(
            context,
            replace(case.presentation, fixture=fixture, candidate=candidate, state=state),
            adapter(resources),
            resources,
        )
        return TargetObservation(
            presentation.status,
            presentation.machine_gate,
            _project(
                {
                    "synthesis_request": request,
                    "synthesis": result,
                    "presentation": presentation.typed_outputs,
                }
            ),
        )

    return LabTarget(
        "audio_presentation",
        contract_revision,
        frozenset({LabMode.ADJACENT}),
        (),
        provenance,
        run,
        frozenset({"tts.provider"}),
    )
