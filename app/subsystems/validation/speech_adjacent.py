"""確定済み発話意味から既存の生成・検証・表現計画を接続する隣接検証。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import Enum
from typing import cast

from app.domain.character.contracts import CharacterVoiceStyleProfile
from app.domain.character_language import (
    CharacterLanguageAuthority,
    CharacterLanguageBoundsPolicyPort,
    CharacterLanguageConstraintView,
    CharacterLanguageContextSnapshot,
    CharacterLanguageLiveStatePort,
    CharacterLanguagePolicy,
    CharacterLanguageRealizer,
    CharacterUtterance,
    prior_realization_from_utterance,
)
from app.domain.character_language.realizer import ROLE_ID as CHARACTER_ROLE_ID
from app.domain.contracts.common import JsonValue, freeze_json
from app.domain.semantic_verification import (
    BLIND_ROLE_ID,
    RELATION_ROLE_ID,
    SemanticAcceptance,
    SemanticAcceptanceState,
    SemanticVerificationAuthority,
    SemanticVerificationBoundsPolicyPort,
    SemanticVerificationContextSnapshot,
    SemanticVerificationLiveStatePort,
    SemanticVerificationPolicy,
    SemanticVerifier,
)
from app.domain.semantic_verification.verifier import SemanticVerificationRun
from app.domain.speech_performance import (
    SpeechExpressionContext,
    SpeechPerformancePlan,
    SpeechPerformancePlanner,
)
from app.domain.speech_runtime.contracts import TTSPreparationMode
from app.domain.speech_runtime.presentation import PresentationAdapter
from app.usecases.ports.llm import LLMRolePort

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .generated_audio import GeneratedAudioBindings
from .llm_port import LabLLMPortFactory, ObservedLLMRolePort, resolve_port
from .runtime import LabTarget, RunContext
from .speech_preparation import (
    SpeechPreparationSettings,
    SpeechRevalidationStatePort,
    prepare_generated_speech,
)
from .speech_session import SpeechPreparationSession


def _json_default(value: object) -> object:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError("公開する発話契約に未対応の値があります")


def _project(value: object) -> JsonValue:
    return freeze_json(cast(JsonValue, json.loads(json.dumps(value, default=_json_default))))


@dataclass(frozen=True)
class SpeechPriorExample:
    utterance: CharacterUtterance
    acceptance: SemanticAcceptance
    constraints: tuple[CharacterLanguageConstraintView, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.utterance, CharacterUtterance) or not isinstance(
            self.acceptance, SemanticAcceptance
        ):
            raise ValueError("過去の表現には確定済み発話と意味検証の採用結果が必要です")
        if (
            self.acceptance.utterance_id != self.utterance.utterance_id
            or self.acceptance.semantic_plan_id != self.utterance.candidate.semantic_plan_id
        ):
            raise ValueError("過去の発話と採用結果の識別子が一致しません")
        constraints = tuple(self.constraints)
        if any(not isinstance(item, CharacterLanguageConstraintView) for item in constraints):
            raise ValueError("過去の表現の制約が不正です")
        object.__setattr__(self, "constraints", constraints)

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "utterance": self.utterance.to_dict(),
                "acceptance": asdict(self.acceptance),
                "constraints": [asdict(item) for item in self.constraints],
            }
        )


@dataclass(frozen=True)
class SpeechAdjacentCase:
    fixture: ValidationFixture
    character_context: CharacterLanguageContextSnapshot
    voice_style: CharacterVoiceStyleProfile | None
    expression: SpeechExpressionContext | None
    created_at: datetime
    preparation: SpeechPreparationSettings | None = None
    prior_examples: tuple[SpeechPriorExample, ...] = ()

    def __post_init__(self) -> None:
        examples = tuple(self.prior_examples)
        if any(not isinstance(item, SpeechPriorExample) for item in examples):
            raise ValueError("過去の表現の検証入力が不正です")
        if examples and self.character_context.prior_realizations:
            raise ValueError("過去の表現の入力元は一つにしてください")
        object.__setattr__(self, "prior_examples", examples)

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "character_context": self.character_context.to_dict(),
                "voice_style": asdict(self.voice_style) if self.voice_style is not None else None,
                "expression": asdict(self.expression) if self.expression is not None else None,
                "created_at": self.created_at,
                "prior_examples": [item.typed_inputs() for item in self.prior_examples],
                "preparation": self.preparation.typed_inputs()
                if self.preparation is not None
                else None,
            }
        )


@dataclass(frozen=True)
class SpeechAdjacentBindings:
    """信頼済み起動コードが製品インスタンスを構築する。入力から関数を解決しない。"""

    realizer: Callable[[RunContext, CharacterLanguageContextSnapshot], CharacterLanguageRealizer]
    verifier: Callable[[RunContext, SemanticVerificationContextSnapshot], SemanticVerifier]
    performance: SpeechPerformancePlanner
    llm_stages: frozenset[str] = frozenset()
    revalidation: SpeechRevalidationStatePort | None = None
    presentation: PresentationAdapter | None = None
    audio: GeneratedAudioBindings | None = None
    preparation_session: Callable[[RunContext], SpeechPreparationSession] | None = None


def make_speech_bindings(
    *,
    port: LLMRolePort | LabLLMPortFactory,
    character_live: Callable[[CharacterLanguageContextSnapshot], CharacterLanguageLiveStatePort],
    verification_live: Callable[
        [SemanticVerificationContextSnapshot], SemanticVerificationLiveStatePort
    ],
    character_policy: CharacterLanguagePolicy,
    verification_policy: SemanticVerificationPolicy,
    performance: SpeechPerformancePlanner,
    character_bounds: CharacterLanguageBoundsPolicyPort | None = None,
    verification_bounds: SemanticVerificationBoundsPolicyPort | None = None,
) -> SpeechAdjacentBindings:
    """既存の判断主体を構築し、LLM接続境界に観測と注入を配置する。"""
    character_stages = {CHARACTER_ROLE_ID: "speech.character.llm"}
    verification_stages = {
        BLIND_ROLE_ID: "speech.blind.llm",
        RELATION_ROLE_ID: "speech.relation.llm",
    }

    def realizer(
        context: RunContext, snapshot: CharacterLanguageContextSnapshot
    ) -> CharacterLanguageRealizer:
        return CharacterLanguageRealizer(
            ObservedLLMRolePort(context, resolve_port(port, context), character_stages),
            character_live(snapshot),
            CharacterLanguageAuthority(),
            character_policy,
            character_bounds,
        )

    def verifier(
        context: RunContext, snapshot: SemanticVerificationContextSnapshot
    ) -> SemanticVerifier:
        return SemanticVerifier(
            ObservedLLMRolePort(context, resolve_port(port, context), verification_stages),
            verification_live(snapshot),
            SemanticVerificationAuthority(),
            verification_policy,
            verification_bounds,
        )

    return SpeechAdjacentBindings(
        realizer,
        verifier,
        performance,
        frozenset((*character_stages.values(), *verification_stages.values())),
    )


def speech_adjacent_target(
    cases: tuple[SpeechAdjacentCase, ...],
    bindings: SpeechAdjacentBindings,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    provider_policy_refs: tuple[str, ...],
) -> LabTarget:
    if (
        any(
            case.preparation is not None and case.preparation.queue_for_revalidation
            for case in cases
        )
        and bindings.revalidation is None
    ):
        raise ValueError("再照合の最新状態取得への接続が必要です")
    if (
        any(
            case.preparation is not None and case.preparation.present_after_validation
            for case in cases
        )
        and bindings.presentation is None
        and bindings.audio is None
    ):
        raise ValueError("提示への継続には提示先の接続が必要です")
    if (
        any(case.preparation is not None and case.preparation.audio is not None for case in cases)
        and bindings.audio is None
    ):
        raise ValueError("音声合成への接続が必要です")
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("発話の隣接検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        if case.character_context.prior_realizations:
            raise ValueError("過去の表現は採用結果を伴うprior_examplesから渡してください")
        prefix = f"{context.run_id}:{fixture.scenario_id}:{context.iteration}"
        snapshot = replace(case.character_context, request_id=f"{prefix}:character")
        if case.prior_examples:
            accepted = tuple(
                item
                for item in case.prior_examples
                if item.acceptance.state is SemanticAcceptanceState.ACCEPTED
            )
            if any(item.acceptance.committed_at > snapshot.captured_at for item in accepted):
                raise ValueError("取得時点より後の採用結果を過去の表現として使えません")
            snapshot = replace(
                snapshot,
                prior_realizations=tuple(
                    prior_realization_from_utterance(item.utterance, item.constraints)
                    for item in accepted
                ),
            )
        realizer = bindings.realizer(context, snapshot)
        utterance = await context.invoke_product(
            "speech.character",
            lambda: realizer.realize(
                snapshot, utterance_id=f"{prefix}:utterance", created_at=case.created_at
            ),
        )
        return await evaluate_generated_speech(
            context,
            replace(case, character_context=snapshot, prior_examples=()),
            bindings,
            utterance,
        )

    return LabTarget(
        "speech_adjacent",
        contract_revision,
        frozenset({LabMode.ADJACENT}),
        provider_policy_refs,
        provenance,
        run,
        bindings.llm_stages
        | ({"speech.revalidation_state"} if bindings.revalidation is not None else set())
        | ({"tts.provider"} if bindings.audio is not None else set()),
        bindings.llm_stages,
    )


async def evaluate_generated_speech(
    context: RunContext,
    case: SpeechAdjacentCase,
    bindings: SpeechAdjacentBindings,
    utterance: CharacterUtterance,
) -> TargetObservation:
    """既に生成した発話を再生成せず、意味検証と表現計画へ渡す。"""
    prefix = f"{context.run_id}:{case.fixture.scenario_id}:{context.iteration}"
    snapshot = case.character_context
    captured_at = max(case.created_at, utterance.committed_at)
    verification = SemanticVerificationContextSnapshot(
        f"{prefix}:verification",
        f"{prefix}:blind",
        f"{prefix}:relation",
        snapshot.semantic_plan,
        utterance,
        snapshot.llm_priority,
        snapshot.interruptibility,
        captured_at,
        snapshot.trace_id,
    )
    verifier = bindings.verifier(context, verification)

    async def verify() -> SemanticVerificationRun:
        result = await context.invoke_product(
            "speech.verifier_entry",
            lambda: verifier.verify(
                verification,
                blind_observation_id=f"{prefix}:blind-observation",
                relation_observation_id=f"{prefix}:relation-observation",
                semantic_observation_id=f"{prefix}:semantic-observation",
                acceptance_id=f"{prefix}:acceptance",
                created_at=captured_at,
            ),
        )
        return result

    async def plan() -> SpeechPerformancePlan:
        async def invoke() -> SpeechPerformancePlan:
            return bindings.performance.plan(
                f"{prefix}:performance",
                utterance,
                case.voice_style,
                case.expression,
                captured_at,
            )

        result = await context.invoke_product("speech.performance_entry", invoke)
        return result

    verification_task = context.spawn("speech.verification", verify)
    performance_task = context.spawn("speech.performance", plan)
    speculative = (
        case.preparation is not None
        and case.preparation.audio is not None
        and case.preparation.tts_mode is TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE
    )
    if speculative:
        performance = cast(SpeechPerformancePlan, await performance_task)
    else:
        _, performance_value = await asyncio.gather(verification_task, performance_task)
        performance = cast(SpeechPerformancePlan, performance_value)

    async def accepted_result() -> SemanticAcceptance:
        return cast(SemanticVerificationRun, await verification_task).acceptance

    prepared = None
    status = RunStatus.COMPLETED
    if case.preparation is not None:
        prepared_result = await prepare_generated_speech(
            context,
            case.preparation,
            snapshot,
            utterance,
            performance,
            cast(Awaitable[SemanticAcceptance], context.spawn("speech.acceptance", accepted_result))
            if speculative
            else await accepted_result(),
            bindings.revalidation,
            bindings.presentation,
            bindings.audio,
            case.fixture,
            bindings.preparation_session(context)
            if bindings.preparation_session is not None
            else None,
        )
        prepared = prepared_result.typed_outputs
        status = prepared_result.status
    observed = cast(SemanticVerificationRun, await verification_task)
    return TargetObservation(
        status,
        Gate.NOT_RUN,
        _project(
            {
                "utterance": utterance.to_dict(),
                "prior_utterance_ids": tuple(
                    item.source_utterance_id for item in snapshot.prior_realizations
                ),
                "verification": {
                    "blind_observation": asdict(observed.blind_observation),
                    "relation_observation": asdict(observed.relation_observation),
                    "semantic_observation": asdict(observed.semantic_observation),
                    "acceptance": asdict(observed.acceptance),
                },
                "performance_plan": asdict(performance),
                "prepared_candidate": prepared,
            }
        ),
    )
