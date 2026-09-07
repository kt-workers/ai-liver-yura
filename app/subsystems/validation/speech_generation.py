"""発話意味の生成結果を人物表現の製品入口へそのまま引き渡す。"""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime

from app.domain.character.contracts import CharacterLanguageProfile, CharacterVoiceStyleProfile
from app.domain.character_language import (
    CharacterLanguageConstraintView,
    CharacterLanguageContextSnapshot,
    CharacterLanguageRealizer,
)
from app.domain.contracts.common import JsonValue
from app.domain.llm import LLMInterruptibility, LLMPriority
from app.domain.speech_performance import SpeechExpressionContext
from app.domain.speech_semantics import (
    SpeechSemanticAuthority,
    SpeechSemanticBoundsPolicyPort,
    SpeechSemanticContextSnapshot,
    SpeechSemanticsLiveStatePort,
    SpeechSemanticsPlanner,
    SpeechSemanticsPolicy,
)
from app.usecases.ports.llm import LLMRolePort

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
    aware,
)
from .llm_port import LabLLMPortFactory, ObservedLLMRolePort, resolve_port
from .runtime import LabTarget, RunContext
from .speech_adjacent import (
    SpeechAdjacentBindings,
    SpeechAdjacentCase,
    _project,
    evaluate_generated_speech,
)
from .speech_preparation import SpeechPreparationSettings


@dataclass(frozen=True)
class SpeechGenerationCase:
    fixture: ValidationFixture
    semantic_context: SpeechSemanticContextSnapshot
    character_profile: CharacterLanguageProfile
    constraints: tuple[CharacterLanguageConstraintView, ...]
    priority: LLMPriority
    interruptibility: LLMInterruptibility
    created_at: datetime
    voice_style: CharacterVoiceStyleProfile | None = None
    expression: SpeechExpressionContext | None = None
    preparation: SpeechPreparationSettings | None = None

    def __post_init__(self) -> None:
        aware(self.created_at)
        object.__setattr__(self, "constraints", tuple(self.constraints))

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "semantic_context": self.semantic_context.to_dict(),
                "character_profile": asdict(self.character_profile),
                "constraints": [item.to_dict() for item in self.constraints],
                "priority": self.priority,
                "interruptibility": self.interruptibility,
                "created_at": self.created_at,
                "voice_style": asdict(self.voice_style) if self.voice_style is not None else None,
                "expression": asdict(self.expression) if self.expression is not None else None,
                "preparation": self.preparation.typed_inputs()
                if self.preparation is not None
                else None,
            }
        )


def speech_generation_target(
    cases: tuple[SpeechGenerationCase, ...],
    port: LLMRolePort | LabLLMPortFactory,
    live_state: SpeechSemanticsLiveStatePort,
    policy: SpeechSemanticsPolicy,
    realizer: Callable[[RunContext, CharacterLanguageContextSnapshot], CharacterLanguageRealizer]
    | SpeechAdjacentBindings,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
    *,
    bounds_state: SpeechSemanticBoundsPolicyPort | None = None,
    character_llm_stages: frozenset[str] = frozenset(),
) -> LabTarget:
    if any(case.preparation is not None for case in cases) and not isinstance(
        realizer, SpeechAdjacentBindings
    ):
        raise ValueError("候補準備には意味検証と表現計画への接続が必要です")
    if any(
        case.preparation is not None and case.preparation.queue_for_revalidation for case in cases
    ) and (not isinstance(realizer, SpeechAdjacentBindings) or realizer.revalidation is None):
        raise ValueError("再照合の最新状態取得への接続が必要です")
    if any(
        case.preparation is not None and case.preparation.present_after_validation for case in cases
    ) and (
        not isinstance(realizer, SpeechAdjacentBindings)
        or (realizer.presentation is None and realizer.audio is None)
    ):
        raise ValueError("提示への継続には提示先の接続が必要です")
    if any(
        case.preparation is not None and case.preparation.audio is not None for case in cases
    ) and (not isinstance(realizer, SpeechAdjacentBindings) or realizer.audio is None):
        raise ValueError("音声合成への接続が必要です")
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("発話生成の隣接検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        prefix = f"{context.run_id}:{fixture.scenario_id}:{context.iteration}"
        planner = SpeechSemanticsPlanner(
            ObservedLLMRolePort(
                context, resolve_port(port, context), {"speech_semantics": "speech_semantics.llm"}
            ),
            live_state,
            SpeechSemanticAuthority(),
            policy,
            bounds_state,
        )
        plan = await context.invoke_product(
            "speech_semantics.plan",
            lambda: planner.plan(
                case.semantic_context,
                request_id=f"{prefix}:semantics",
                trace_id=prefix,
                candidate_id=f"{prefix}:candidate",
                plan_id=f"{prefix}:plan",
                created_at=case.created_at,
            ),
        )
        captured_at = max(case.created_at, plan.committed_at)
        snapshot = CharacterLanguageContextSnapshot(
            f"{prefix}:character",
            plan,
            case.character_profile,
            case.constraints,
            case.priority,
            case.interruptibility,
            captured_at,
            prefix,
        )
        build_realizer = (
            realizer.realizer if isinstance(realizer, SpeechAdjacentBindings) else realizer
        )
        owner = build_realizer(context, snapshot)
        utterance = await context.invoke_product(
            "speech.character",
            lambda: owner.realize(
                snapshot, utterance_id=f"{prefix}:utterance", created_at=captured_at
            ),
        )
        continuation: JsonValue = None
        status = RunStatus.COMPLETED
        if isinstance(realizer, SpeechAdjacentBindings):
            evaluated = await evaluate_generated_speech(
                context,
                SpeechAdjacentCase(
                    fixture,
                    snapshot,
                    case.voice_style,
                    case.expression,
                    captured_at,
                    case.preparation,
                ),
                realizer,
                utterance,
            )
            continuation = evaluated.typed_outputs
            status = evaluated.status
        return TargetObservation(
            status,
            Gate.NOT_RUN,
            _project(
                {
                    "semantic_plan": plan.to_dict(),
                    "character_input": snapshot.to_dict(),
                    "utterance": utterance.to_dict(),
                    "evaluation": continuation,
                }
            ),
        )

    stages = character_llm_stages | {"speech_semantics.llm"}
    if isinstance(realizer, SpeechAdjacentBindings):
        stages |= realizer.llm_stages
    return LabTarget(
        "speech_generation_chain"
        if isinstance(realizer, SpeechAdjacentBindings)
        else "speech_generation",
        contract_revision,
        frozenset({LabMode.ADJACENT}),
        provider_policy_refs,
        provenance,
        run,
        stages
        | (
            {"tts.provider"}
            if isinstance(realizer, SpeechAdjacentBindings) and realizer.audio is not None
            else set()
        )
        | (
            {"speech.revalidation_state"}
            if isinstance(realizer, SpeechAdjacentBindings) and realizer.revalidation is not None
            else set()
        ),
        stages,
    )
