from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import cast
from uuid import uuid4

from app.adapters.character.yaml_loader import (
    CharacterDefinitionLoadError,
    load_character_definition_yaml,
)
from app.adapters.llm.character_language import (
    CHARACTER_LANGUAGE_PROVIDER_FORMAT_NAME,
    character_language_openai_role_config,
)
from app.adapters.llm.openai_responses import (
    OpenAIResponsesAdapter,
    OpenAIResponsesModelPolicy,
    OpenAIResponsesRoleConfig,
)
from app.domain.character import (
    CharacterLanguageProfile,
    RuntimeAvailability,
    RuntimeCharacterFacet,
    project_character_definition,
)
from app.domain.character_language import (
    CharacterLanguageAuthority,
    CharacterLanguageCommitState,
    CharacterLanguageContextSnapshot,
    CharacterLanguagePolicy,
    CharacterLanguageRealizer,
)
from app.domain.contracts import RevisionVector
from app.domain.contracts.common import JsonValue
from app.domain.executive import (
    CommittedExecutiveDecision,
    ExecutiveDecisionCandidate,
    ExecutiveIntent,
    ExecutiveIntentKind,
    ExecutiveInterruptibility,
    ExecutiveOutcome,
    ExecutivePriority,
    SpeechIntentPayload,
)
from app.domain.llm import (
    LLMExecutionPolicy,
    LLMFailurePolicy,
    LLMInterruptibility,
    LLMModelClass,
    LLMPriority,
    LLMReasoningEffort,
    LLMRoleRequest,
    LLMRoleResult,
)
from app.domain.semantic_verification import (
    BLIND_INPUT_SCHEMA,
    BLIND_OUTPUT_SCHEMA,
    BLIND_ROLE_ID,
    RELATION_INPUT_SCHEMA,
    RELATION_OUTPUT_SCHEMA,
    RELATION_ROLE_ID,
    SemanticVerificationAuthority,
    SemanticVerificationContextSnapshot,
    SemanticVerificationEligibilityView,
    SemanticVerificationPolicy,
    SemanticVerifier,
    blind_instructions,
    blind_output_schema,
    relation_instructions,
    relation_output_schema,
)
from app.domain.speech_semantics import (
    DeterministicSpeechDirective,
    SelfDisclosurePolicy,
    SemanticCertainty,
    SemanticPolarity,
    SpeechProposition,
    SpeechPropositionDisposition,
    SpeechSemanticAuthority,
    SpeechSemanticContextSnapshot,
    SpeechSemanticFact,
    SpeechSemanticFactKind,
    SpeechSemanticsPlanner,
    SpeechSemanticsPolicy,
)
from app.usecases.ports.llm import LLMRolePort

LAB_BRANCH = "test/v2-character-language-lab"
DEFAULT_CHARACTER_DEFINITION_PATH = "character_definitions/v2/yura.yaml"


class CharacterLanguageLabMode(str, Enum):
    INTEGRATED = "integrated"
    ISOLATION = "isolation"


class CharacterLanguageLabStatus(str, Enum):
    READY = "READY"
    BLOCKED_UPSTREAM_CHARACTER_DEFINITION = "BLOCKED_UPSTREAM_CHARACTER_DEFINITION"
    INVALID_INPUT = "INVALID_INPUT"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    CHARACTER_COMMIT_REJECTED = "CHARACTER_COMMIT_REJECTED"
    SEMANTIC_VERIFICATION_FAILED = "SEMANTIC_VERIFICATION_FAILED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class CharacterLanguageLabSettings:
    character_definition_path: Path
    default_character_model: str | None
    default_semantic_model: str | None
    git_head: str | None

    @classmethod
    def from_environment(cls) -> CharacterLanguageLabSettings:
        return cls(
            Path(
                os.getenv(
                    "YURA_CHARACTER_DEFINITION_PATH",
                    DEFAULT_CHARACTER_DEFINITION_PATH,
                )
            ),
            os.getenv("YURA_CHARACTER_LANGUAGE_LAB_MODEL"),
            os.getenv("YURA_SEMANTIC_VERIFICATION_LAB_MODEL"),
            os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT"),
        )

    @property
    def provider_configured(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))


@dataclass(frozen=True, slots=True)
class CharacterLanguageLabRequest:
    mode: CharacterLanguageLabMode
    scenario_id: str
    repetitions: int
    character_model: str
    character_model_class: LLMModelClass
    character_reasoning_effort: LLMReasoningEffort
    semantic_model: str
    semantic_model_class: LLMModelClass
    semantic_reasoning_effort: LLMReasoningEffort
    run_semantic_verification: bool = True
    timeout_seconds: float = 30
    max_output_tokens: int = 1200

    def __post_init__(self) -> None:
        if not isinstance(self.mode, CharacterLanguageLabMode):
            raise ValueError("modeが不正です")
        if not self.scenario_id.strip():
            raise ValueError("scenario_idは空にできません")
        if type(self.repetitions) is not int or not 1 <= self.repetitions <= 10:
            raise ValueError("repetitionsは1〜10でなければなりません")
        for name in ("character_model", "semantic_model"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name}は空にできません")
        if not isinstance(self.character_model_class, LLMModelClass):
            raise ValueError("character_model_classが不正です")
        if not isinstance(self.character_reasoning_effort, LLMReasoningEffort):
            raise ValueError("character_reasoning_effortが不正です")
        if not isinstance(self.semantic_model_class, LLMModelClass):
            raise ValueError("semantic_model_classが不正です")
        if not isinstance(self.semantic_reasoning_effort, LLMReasoningEffort):
            raise ValueError("semantic_reasoning_effortが不正です")
        if self.character_model_class is LLMModelClass.MULTIMODAL:
            raise ValueError("Character LanguageでMULTIMODALは使用できません")
        if self.semantic_model_class is LLMModelClass.MULTIMODAL:
            raise ValueError("Semantic VerificationでMULTIMODALは使用できません")
        if type(self.run_semantic_verification) is not bool:
            raise ValueError("run_semantic_verificationはboolでなければなりません")
        if type(self.timeout_seconds) not in (int, float) or self.timeout_seconds <= 0:
            raise ValueError("timeout_secondsは正数でなければなりません")
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 1:
            raise ValueError("max_output_tokensは正の整数でなければなりません")


@dataclass(frozen=True, slots=True)
class _Scenario:
    scenario_id: str
    label: str
    fact_kind: SpeechSemanticFactKind
    subject_ref: str
    predicate: str
    value: JsonValue
    polarity: SemanticPolarity = SemanticPolarity.AFFIRM
    certainty: SemanticCertainty = SemanticCertainty.CERTAIN
    degree: float | None = None
    self_disclosure: SelfDisclosurePolicy = SelfDisclosurePolicy.FORBIDDEN
    question_budget: int = 0
    new_direction_budget: int = 0


_SCENARIOS = {
    item.scenario_id: item
    for item in (
        _Scenario(
            "neutral_fact",
            "Neutral fact / direct answer",
            SpeechSemanticFactKind.GENERAL,
            "topic-weather",
            "answer",
            cast(JsonValue, {"content": "今日は少し涼しい"}),
        ),
        _Scenario(
            "unknown_uncertainty",
            "Unknown / uncertainty",
            SpeechSemanticFactKind.GENERAL,
            "topic-schedule",
            "availability",
            cast(JsonValue, {"content": "まだ分からない"}),
            SemanticPolarity.UNKNOWN,
            SemanticCertainty.UNKNOWN,
        ),
        _Scenario(
            "negation",
            "Negation",
            SpeechSemanticFactKind.GENERAL,
            "topic-action",
            "performed",
            cast(JsonValue, {"action": "download"}),
            SemanticPolarity.NEGATE,
        ),
        _Scenario(
            "gratitude",
            "Gratitude communicative act",
            SpeechSemanticFactKind.DISCOURSE,
            "current-interaction",
            "communicative_act",
            cast(JsonValue, {"kind": "gratitude", "target_ref": "user"}),
        ),
        _Scenario(
            "apology",
            "Apology communicative act",
            SpeechSemanticFactKind.DISCOURSE,
            "current-interaction",
            "communicative_act",
            cast(JsonValue, {"kind": "apology", "target_ref": "user"}),
        ),
        _Scenario(
            "degree",
            "Degree preservation",
            SpeechSemanticFactKind.GENERAL,
            "topic-interest",
            "interest_level",
            cast(JsonValue, {"target_ref": "topic-1"}),
            degree=0.4,
        ),
        _Scenario(
            "self_disclosure_grounded",
            "Grounded self-disclosure",
            SpeechSemanticFactKind.SELF,
            "yura",
            "preference",
            cast(JsonValue, {"topic": "静かな時間", "stance": "likes"}),
            self_disclosure=SelfDisclosurePolicy.FACT_GROUNDED,
        ),
    )
}


class _NoopPort:
    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        raise RuntimeError(f"deterministic pathでProviderを呼んではいけません: {request.role_id}")


class _StaticSpeechLiveState:
    async def current_revisions(
        self, snapshot: SpeechSemanticContextSnapshot
    ) -> RevisionVector:
        return snapshot.revisions


class _StaticCharacterLiveState:
    async def current_state(
        self, snapshot: CharacterLanguageContextSnapshot
    ) -> CharacterLanguageCommitState:
        return CharacterLanguageCommitState(
            snapshot.revisions,
            snapshot.semantic_plan,
            True,
            snapshot.character_profile,
            snapshot.constraints,
        )


class _StaticSemanticLiveState:
    async def current_state(
        self, snapshot: SemanticVerificationContextSnapshot
    ) -> SemanticVerificationEligibilityView:
        return SemanticVerificationEligibilityView(
            snapshot.semantic_plan.plan_id,
            snapshot.utterance.utterance_id,
            snapshot.revisions,
            True,
            False,
            False,
        )


class _RecordingPort:
    def __init__(self, delegate: LLMRolePort) -> None:
        self._delegate = delegate
        self.results: list[LLMRoleResult] = []
        self.latency_ms: list[tuple[str, float]] = []

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        started = perf_counter()
        result = await self._delegate.invoke(request)
        self.results.append(result)
        self.latency_ms.append((request.role_id, round((perf_counter() - started) * 1000, 3)))
        return result

    def metrics(self) -> list[dict[str, object]]:
        values: list[dict[str, object]] = []
        for index, result in enumerate(self.results):
            role_id, latency = self.latency_ms[index]
            values.append(
                {
                    "role_id": role_id,
                    "status": result.status.value,
                    "model_class": result.model_class.value,
                    "attempt_count": result.attempt_count,
                    "token_usage": result.token_usage.to_dict(),
                    "provider_latency_ms": latency,
                    "started_at": None
                    if result.started_at is None
                    else result.started_at.isoformat(),
                    "completed_at": result.completed_at.isoformat(),
                }
            )
        return values


def _profile_dict(profile: CharacterLanguageProfile) -> dict[str, object]:
    return {
        "character_id": profile.character_id,
        "schema_version": profile.schema_version,
        "definition_revision": profile.definition_revision,
        "facets": [
            {
                "facet_id": item.facet_id,
                "availability": item.availability.value,
                "value": item.value,
                "basis_refs": list(item.basis_refs),
            }
            for item in profile.facets
        ],
    }


def _isolation_profile() -> CharacterLanguageProfile:
    return CharacterLanguageProfile(
        "yura",
        1,
        0,
        (
            RuntimeCharacterFacet(
                "diagnostic_distance",
                RuntimeAvailability.CONFIRMED,
                "親しみはあるが馴れ馴れしすぎない",
            ),
            RuntimeCharacterFacet(
                "diagnostic_softness",
                RuntimeAvailability.CONFIRMED,
                "やわらかく自然体",
            ),
            RuntimeCharacterFacet(
                "diagnostic_directness",
                RuntimeAvailability.CONFIRMED,
                "必要なことは回りくどくせず伝える",
            ),
            RuntimeCharacterFacet(
                "diagnostic_rhythm",
                RuntimeAvailability.CONFIRMED,
                "会話らしい短いまとまりと自然な間",
            ),
            RuntimeCharacterFacet(
                "diagnostic_restraint",
                RuntimeAvailability.CONFIRMED,
                "不要な冗談・照れ・質問・自己開示を足さない",
            ),
        ),
    )


def _decision(now: datetime, revisions: RevisionVector, scenario: _Scenario) -> CommittedExecutiveDecision:
    if revisions.goal_revision is None or revisions.attention_revision is None:
        raise ValueError("Lab scenarioにはgoal/attention revisionが必要です")
    intent = ExecutiveIntent(
        "intent-speech",
        ExecutiveIntentKind.SPEECH,
        "controlled Character Language quality validation",
        SpeechIntentPayload("fact-main"),
        (),
        (),
        (),
        (),
    )
    candidate = ExecutiveDecisionCandidate(
        "decision-candidate",
        "trigger-lab",
        ("event-lab",),
        revisions.source_context_revision,
        revisions.goal_revision,
        revisions.attention_revision,
        ExecutiveOutcome.RESPOND,
        ExecutivePriority.FOREGROUND,
        ExecutiveInterruptibility.INTERRUPTIBLE,
        (intent,),
        (),
        (),
        (),
        ("fact-main",),
        now,
    )
    return CommittedExecutiveDecision("decision-lab", candidate, (), now)


def _semantic_context(now: datetime, scenario: _Scenario) -> SpeechSemanticContextSnapshot:
    revisions = RevisionVector(1, 1, 1)
    fact = SpeechSemanticFact(
        "fact-main",
        scenario.fact_kind,
        scenario.subject_ref,
        scenario.predicate,
        scenario.value,
        polarity=scenario.polarity,
        certainty=scenario.certainty,
        degree=scenario.degree,
    )
    proposition = SpeechProposition(
        "p1",
        scenario.subject_ref,
        scenario.predicate,
        scenario.value,
        SpeechPropositionDisposition.REQUIRED,
        scenario.polarity,
        scenario.certainty,
        ("fact-main",),
        scenario.degree,
    )
    directive = DeterministicSpeechDirective(
        (proposition,),
        scenario.self_disclosure,
        scenario.question_budget,
        scenario.new_direction_budget,
        (),
    )
    return SpeechSemanticContextSnapshot(
        _decision(now, revisions, scenario),
        "intent-speech",
        (fact,),
        (),
        (),
        scenario.self_disclosure,
        scenario.question_budget,
        scenario.new_direction_budget,
        now,
        directive,
    )


async def _committed_plan(scenario: _Scenario) -> object:
    now = datetime.now(timezone.utc)
    snapshot = _semantic_context(now, scenario)
    policy = SpeechSemanticsPolicy(
        LLMExecutionPolicy(
            LLMModelClass.BALANCED,
            LLMReasoningEffort.MEDIUM,
            5,
            1,
            800,
        )
    )
    planner = SpeechSemanticsPlanner(
        cast(LLMRolePort, _NoopPort()),
        _StaticSpeechLiveState(),
        SpeechSemanticAuthority(),
        policy,
    )
    return await planner.plan(
        snapshot,
        request_id=f"speech-request-{uuid4().hex}",
        trace_id=f"speech-trace-{uuid4().hex}",
        candidate_id=f"speech-candidate-{uuid4().hex}",
        plan_id=f"speech-plan-{uuid4().hex}",
        created_at=datetime.now(timezone.utc),
    )


def _semantic_role_configs(
    model: str,
    model_class: LLMModelClass,
    effort: LLMReasoningEffort,
) -> tuple[OpenAIResponsesRoleConfig, OpenAIResponsesRoleConfig]:
    policy = {
        model_class: OpenAIResponsesModelPolicy(
            model,
            {effort: effort.value},
        )
    }
    return (
        OpenAIResponsesRoleConfig(
            BLIND_ROLE_ID,
            policy,
            BLIND_INPUT_SCHEMA,
            BLIND_OUTPUT_SCHEMA,
            "semantic_blind_v1",
            blind_output_schema(),
            blind_instructions(),
            LLMFailurePolicy.FAIL_CLOSED,
        ),
        OpenAIResponsesRoleConfig(
            RELATION_ROLE_ID,
            policy,
            RELATION_INPUT_SCHEMA,
            RELATION_OUTPUT_SCHEMA,
            "semantic_relation_v1",
            relation_output_schema(),
            relation_instructions(),
            LLMFailurePolicy.FAIL_CLOSED,
        ),
    )


def _execution_policy(
    model_class: LLMModelClass,
    effort: LLMReasoningEffort,
    request: CharacterLanguageLabRequest,
) -> LLMExecutionPolicy:
    return LLMExecutionPolicy(
        model_class,
        effort,
        request.timeout_seconds,
        1,
        request.max_output_tokens,
    )


def _character_source(
    settings: CharacterLanguageLabSettings,
    mode: CharacterLanguageLabMode,
) -> tuple[CharacterLanguageProfile | None, dict[str, object]]:
    if mode is CharacterLanguageLabMode.ISOLATION:
        profile = _isolation_profile()
        return profile, {
            "kind": "isolation_fixture",
            "path": None,
            "content_sha256": None,
            "profile": _profile_dict(profile),
        }

    path = settings.character_definition_path
    if not path.is_file():
        return None, {
            "kind": "production",
            "path": str(path),
            "status": CharacterLanguageLabStatus.BLOCKED_UPSTREAM_CHARACTER_DEFINITION.value,
            "reason": "production Character Definition YAMLが存在しません",
        }
    source = path.read_bytes()
    try:
        document = load_character_definition_yaml(source)
    except CharacterDefinitionLoadError as error:
        return None, {
            "kind": "production",
            "path": str(path),
            "status": CharacterLanguageLabStatus.BLOCKED_UPSTREAM_CHARACTER_DEFINITION.value,
            "reason": f"Character Definition load failed: {error.code.value}",
        }
    profile = project_character_definition(document).language
    confirmed = tuple(
        item for item in profile.facets if item.availability is RuntimeAvailability.CONFIRMED
    )
    if not confirmed:
        return None, {
            "kind": "production",
            "path": str(path),
            "status": CharacterLanguageLabStatus.BLOCKED_UPSTREAM_CHARACTER_DEFINITION.value,
            "reason": "confirmed Character Language facetがありません",
        }
    return profile, {
        "kind": "production",
        "path": str(path),
        "content_sha256": hashlib.sha256(source).hexdigest(),
        "authority": {
            "bible_path": document.authority.bible_path,
            "owner_issue": document.authority.owner_issue,
        },
        "profile": _profile_dict(profile),
    }


class CharacterLanguageLabService:
    def __init__(
        self,
        settings: CharacterLanguageLabSettings | None = None,
        port: LLMRolePort | None = None,
    ) -> None:
        self._settings = settings or CharacterLanguageLabSettings.from_environment()
        self._injected_port = port

    def readiness(self) -> dict[str, object]:
        profile, source = _character_source(
            self._settings,
            CharacterLanguageLabMode.INTEGRATED,
        )
        return {
            "status": (
                CharacterLanguageLabStatus.READY.value
                if profile is not None
                else CharacterLanguageLabStatus.BLOCKED_UPSTREAM_CHARACTER_DEFINITION.value
            ),
            "integrated_ready": profile is not None,
            "provider_configured": self._settings.provider_configured
            or self._injected_port is not None,
            "character_source": source,
            "branch": LAB_BRANCH,
            "git_head": self._settings.git_head,
            "scenarios": [
                {"id": item.scenario_id, "label": item.label}
                for item in _SCENARIOS.values()
            ],
            "default_character_model": self._settings.default_character_model,
            "default_semantic_model": self._settings.default_semantic_model,
        }

    async def run(self, request: CharacterLanguageLabRequest) -> dict[str, object]:
        scenario = _SCENARIOS.get(request.scenario_id)
        if scenario is None:
            raise ValueError("unknown scenario_id")
        profile, source = _character_source(self._settings, request.mode)
        if profile is None:
            return {
                "ok": False,
                "status": CharacterLanguageLabStatus.BLOCKED_UPSTREAM_CHARACTER_DEFINITION.value,
                "mode": request.mode.value,
                "evidence_class": "not_eligible",
                "character_source": source,
                "runs": [],
            }

        port = self._injected_port
        if port is None:
            if not self._settings.provider_configured:
                raise ValueError("OPENAI_API_KEYが設定されていません")
            character_config = character_language_openai_role_config(
                {request.character_model_class: request.character_model},
                reasoning_by_effort={
                    request.character_reasoning_effort: request.character_reasoning_effort.value
                },
            )
            configs: tuple[OpenAIResponsesRoleConfig, ...] = (character_config,)
            if request.run_semantic_verification:
                configs += _semantic_role_configs(
                    request.semantic_model,
                    request.semantic_model_class,
                    request.semantic_reasoning_effort,
                )
            port = OpenAIResponsesAdapter.from_environment(configs)
        recorder = _RecordingPort(port)

        runs: list[dict[str, object]] = []
        for repetition_index in range(request.repetitions):
            runs.append(
                await self._run_once(
                    request,
                    scenario,
                    profile,
                    source,
                    recorder,
                    repetition_index,
                )
            )
        return {
            "ok": all(bool(item.get("ok")) for item in runs),
            "status": CharacterLanguageLabStatus.COMPLETED.value,
            "mode": request.mode.value,
            "evidence_class": (
                "integrated" if request.mode is CharacterLanguageLabMode.INTEGRATED else "isolation_only"
            ),
            "integrated_evidence_eligible": request.mode is CharacterLanguageLabMode.INTEGRATED,
            "scenario": {"id": scenario.scenario_id, "label": scenario.label},
            "character_source": source,
            "model_policy": {
                "character": {
                    "provider_model": request.character_model,
                    "model_class": request.character_model_class.value,
                    "reasoning_effort": request.character_reasoning_effort.value,
                    "provider_format": CHARACTER_LANGUAGE_PROVIDER_FORMAT_NAME,
                },
                "semantic": {
                    "enabled": request.run_semantic_verification,
                    "provider_model": request.semantic_model,
                    "model_class": request.semantic_model_class.value,
                    "reasoning_effort": request.semantic_reasoning_effort.value,
                },
            },
            "runs": runs,
            "provider_metrics": recorder.metrics(),
            "branch": LAB_BRANCH,
            "git_head": self._settings.git_head,
        }

    async def _run_once(
        self,
        request: CharacterLanguageLabRequest,
        scenario: _Scenario,
        profile: CharacterLanguageProfile,
        source: Mapping[str, object],
        recorder: _RecordingPort,
        repetition_index: int,
    ) -> dict[str, object]:
        run_id = f"character-language-run-{uuid4().hex}"
        plan = cast("SpeechSemanticPlan", await _committed_plan(scenario))
        snapshot = CharacterLanguageContextSnapshot(
            f"character-request-{uuid4().hex}",
            plan,
            profile,
            (),
            LLMPriority.FOREGROUND,
            LLMInterruptibility.INTERRUPTIBLE,
            datetime.now(timezone.utc),
            f"character-trace-{uuid4().hex}",
        )
        character_policy = CharacterLanguagePolicy(
            _execution_policy(
                request.character_model_class,
                request.character_reasoning_effort,
                request,
            )
        )
        realizer = CharacterLanguageRealizer(
            recorder,
            _StaticCharacterLiveState(),
            CharacterLanguageAuthority(),
            character_policy,
        )
        started = perf_counter()
        try:
            utterance = await realizer.realize(
                snapshot,
                utterance_id=f"utterance-{uuid4().hex}",
                created_at=datetime.now(timezone.utc),
            )
        except Exception as error:
            return {
                "ok": False,
                "run_id": run_id,
                "repetition_index": repetition_index,
                "status": CharacterLanguageLabStatus.CHARACTER_COMMIT_REJECTED.value,
                "error": str(error),
                "semantic_plan": plan.to_dict(),
                "character_profile": _profile_dict(profile),
                "character_source_kind": source.get("kind"),
                "character_latency_ms": round((perf_counter() - started) * 1000, 3),
            }
        character_latency = round((perf_counter() - started) * 1000, 3)
        semantic_result: dict[str, object] | None = None
        if request.run_semantic_verification:
            semantic_result = await self._verify_semantics(request, plan, utterance, recorder)
        return {
            "ok": semantic_result is None or bool(semantic_result.get("ok")),
            "run_id": run_id,
            "repetition_index": repetition_index,
            "status": CharacterLanguageLabStatus.COMPLETED.value,
            "semantic_plan": plan.to_dict(),
            "character_profile": _profile_dict(profile),
            "character_utterance": utterance.to_dict(),
            "character_latency_ms": character_latency,
            "semantic_verification": semantic_result,
            "human_evaluation": None,
        }

    async def _verify_semantics(
        self,
        request: CharacterLanguageLabRequest,
        plan: object,
        utterance: object,
        recorder: _RecordingPort,
    ) -> dict[str, object]:
        from app.domain.character_language import CharacterUtterance
        from app.domain.speech_semantics import SpeechSemanticPlan

        semantic_plan = cast(SpeechSemanticPlan, plan)
        actual_utterance = cast(CharacterUtterance, utterance)
        snapshot = SemanticVerificationContextSnapshot(
            f"verification-{uuid4().hex}",
            f"blind-request-{uuid4().hex}",
            f"relation-request-{uuid4().hex}",
            semantic_plan,
            actual_utterance,
            LLMPriority.FOREGROUND,
            LLMInterruptibility.INTERRUPTIBLE,
            datetime.now(timezone.utc),
            f"semantic-trace-{uuid4().hex}",
        )
        policy = SemanticVerificationPolicy(
            _execution_policy(
                request.semantic_model_class,
                request.semantic_reasoning_effort,
                request,
            ),
            _execution_policy(
                request.semantic_model_class,
                request.semantic_reasoning_effort,
                request,
            ),
        )
        verifier = SemanticVerifier(
            recorder,
            _StaticSemanticLiveState(),
            SemanticVerificationAuthority(),
            policy,
        )
        started = perf_counter()
        try:
            run = await verifier.verify(
                snapshot,
                blind_observation_id=f"blind-observation-{uuid4().hex}",
                relation_observation_id=f"relation-observation-{uuid4().hex}",
                semantic_observation_id=f"semantic-observation-{uuid4().hex}",
                acceptance_id=f"acceptance-{uuid4().hex}",
                created_at=datetime.now(timezone.utc),
            )
        except Exception as error:
            return {
                "ok": False,
                "status": CharacterLanguageLabStatus.SEMANTIC_VERIFICATION_FAILED.value,
                "error": str(error),
                "latency_ms": round((perf_counter() - started) * 1000, 3),
            }
        return {
            "ok": True,
            "status": run.acceptance.state.value,
            "rejection_categories": [
                item.value for item in run.acceptance.rejection_categories
            ],
            "blind_observation": run.blind_observation.to_dict(),
            "blind_provider_result": run.blind_result.to_dict(),
            "relation_provider_result": run.relation_result.to_dict(),
            "latency_ms": round((perf_counter() - started) * 1000, 3),
        }


__all__ = [
    "CharacterLanguageLabMode",
    "CharacterLanguageLabRequest",
    "CharacterLanguageLabService",
    "CharacterLanguageLabSettings",
    "CharacterLanguageLabStatus",
]
