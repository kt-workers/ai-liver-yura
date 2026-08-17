from __future__ import annotations

import os
import secrets
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

from app.adapters.llm.openai_responses import (
    OpenAIResponsesAdapter,
    OpenAIResponsesModelPolicy,
    OpenAIResponsesRoleConfig,
)
from app.domain.character import CharacterLanguageProfile
from app.domain.character_language import (
    CharacterLanguageAuthority,
    CharacterLanguageCommitState,
    CharacterLanguageContextSnapshot,
    CharacterUtterance,
    CharacterUtteranceCandidate,
    CharacterUtteranceSegment,
    LinguisticBoundary,
    LinguisticEmphasis,
    LinguisticHesitation,
)
from app.domain.contracts import ExecutionStatus, RevisionVector
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
    SemanticVerificationError,
    SemanticVerificationPolicy,
    SemanticVerifier,
    blind_instructions,
    blind_output_schema,
    relation_instructions,
    relation_output_schema,
)
from app.domain.speech_semantics import (
    SelfDisclosurePolicy,
    SemanticCertainty,
    SemanticClaimKind,
    SemanticPolarity,
    SpeechProposition,
    SpeechPropositionDisposition,
    SpeechSemanticAuthority,
    SpeechSemanticCandidate,
    SpeechSemanticContextSnapshot,
    SpeechSemanticFact,
    SpeechSemanticFactKind,
    SpeechTruthConstraint,
    SpeechTruthRule,
)
from app.usecases.ports.llm import LLMRolePort


class PropositionInput(BaseModel):
    proposition_id: str
    subject_ref: str
    predicate: str
    value: dict[str, object]
    disposition: str = "required"
    polarity: str = "affirm"
    certainty: str = "certain"
    degree: float | None = None
    claim_kind: str = "general"
    execution_status: str | None = None
    fact_kind: str = "general"


class SegmentInput(BaseModel):
    segment_id: str
    text: str
    realization_refs: list[str] | None = None


class SemanticVerificationLabRequest(BaseModel):
    name: str = "manual"
    expected_acceptance: str | None = None
    propositions: list[PropositionInput] = Field(min_length=1)
    segments: list[SegmentInput] = Field(min_length=1)
    question_budget: int = Field(default=0, ge=0)
    new_direction_budget: int = Field(default=0, ge=0)
    question_budget_used: int = Field(default=0, ge=0)
    new_direction_budget_used: int = Field(default=0, ge=0)
    self_disclosure: str = "fact_grounded"
    blind_model_class: str = "balanced"
    blind_reasoning_effort: str = "medium"
    relation_model_class: str = "balanced"
    relation_reasoning_effort: str = "medium"
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_output_tokens: int = Field(default=2400, ge=128, le=12000)
    active: bool = True
    superseded: bool = False
    cancelled: bool = False
    stale_revision: bool = False


@dataclass(frozen=True, slots=True)
class LabSettings:
    model: str
    blind_model: str
    relation_model: str
    username: str
    password: str

    @classmethod
    def from_env(cls) -> "LabSettings":
        model = os.getenv("YURA_SEMANTIC_VERIFICATION_LAB_MODEL", "").strip()
        return cls(
            model=model,
            blind_model=os.getenv("YURA_SEMANTIC_VERIFICATION_BLIND_MODEL", model).strip(),
            relation_model=os.getenv(
                "YURA_SEMANTIC_VERIFICATION_RELATION_MODEL", model
            ).strip(),
            username=os.getenv("YURA_LAB_USERNAME", "").strip(),
            password=os.getenv("YURA_LAB_PASSWORD", ""),
        )

    @property
    def auth_configured(self) -> bool:
        return bool(self.username and self.password)

    @property
    def live_configured(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY") and self.blind_model and self.relation_model)


@dataclass(frozen=True, slots=True)
class LabFixture:
    semantic_plan: object
    utterance: CharacterUtterance
    snapshot: SemanticVerificationContextSnapshot


class _StaticLiveState:
    def __init__(
        self,
        snapshot: SemanticVerificationContextSnapshot,
        request: SemanticVerificationLabRequest,
    ) -> None:
        revisions = snapshot.revisions
        if request.stale_revision:
            revisions = RevisionVector(
                revisions.source_context_revision + 1,
                revisions.goal_revision,
                revisions.attention_revision,
            )
        self._view = SemanticVerificationEligibilityView(
            snapshot.semantic_plan.plan_id,
            snapshot.utterance.utterance_id,
            revisions,
            request.active,
            request.superseded,
            request.cancelled,
        )

    async def current_state(
        self, snapshot: SemanticVerificationContextSnapshot
    ) -> SemanticVerificationEligibilityView:
        return self._view


def _offset(base: datetime, milliseconds: int) -> datetime:
    return base + timedelta(milliseconds=milliseconds)


def _enum_value(enum_type: type[Enum], value: str, field_name: str) -> Enum:
    try:
        return enum_type(value)
    except ValueError as error:
        raise ValueError(f"{field_name} が不正です: {value}") from error


def build_validation_fixture(
    request: SemanticVerificationLabRequest,
    *,
    now: datetime | None = None,
) -> LabFixture:
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None or base.utcoffset() is None:
        raise ValueError("now はtimezone-awareでなければなりません")
    revisions = RevisionVector(1, 1, 1)
    facts: list[SpeechSemanticFact] = []
    propositions: list[SpeechProposition] = []
    truth_constraints: list[SpeechTruthConstraint] = []
    forbidden_fact_refs: list[str] = []

    for item in request.propositions:
        disposition = _enum_value(
            SpeechPropositionDisposition, item.disposition, "disposition"
        )
        polarity = _enum_value(SemanticPolarity, item.polarity, "polarity")
        certainty = _enum_value(SemanticCertainty, item.certainty, "certainty")
        claim_kind = _enum_value(SemanticClaimKind, item.claim_kind, "claim_kind")
        fact_kind = _enum_value(SpeechSemanticFactKind, item.fact_kind, "fact_kind")
        execution_status = (
            None
            if item.execution_status is None
            else _enum_value(ExecutionStatus, item.execution_status, "execution_status")
        )
        if claim_kind is SemanticClaimKind.EXECUTION_STATUS:
            fact_kind = SpeechSemanticFactKind.EXECUTION
        fact_id = f"fact-{item.proposition_id}"
        facts.append(
            SpeechSemanticFact(
                fact_id,
                fact_kind,
                item.subject_ref,
                item.predicate,
                item.value,
                claim_kind=claim_kind,
                execution_status=execution_status,
                polarity=polarity,
                certainty=certainty,
                degree=item.degree,
            )
        )
        propositions.append(
            SpeechProposition(
                item.proposition_id,
                item.subject_ref,
                item.predicate,
                item.value,
                disposition,
                polarity,
                certainty,
                (fact_id,),
                degree=item.degree,
                claim_kind=claim_kind,
                execution_status=execution_status,
            )
        )
        if disposition is SpeechPropositionDisposition.FORBIDDEN:
            forbidden_fact_refs.append(fact_id)
        if (
            claim_kind is SemanticClaimKind.EXECUTION_STATUS
            and disposition is not SpeechPropositionDisposition.FORBIDDEN
        ):
            truth_constraints.append(
                SpeechTruthConstraint(
                    f"truth-{item.proposition_id}",
                    fact_id,
                    SpeechTruthRule.REQUIRE_MATCH,
                )
            )

    goal = next(
        (
            fact
            for fact, proposition in zip(facts, propositions)
            if proposition.disposition is not SpeechPropositionDisposition.FORBIDDEN
        ),
        None,
    )
    if goal is None:
        raise ValueError("少なくとも1つnon-FORBIDDEN propositionが必要です")

    intent = ExecutiveIntent(
        "lab-intent",
        ExecutiveIntentKind.SPEECH,
        "Semantic Verification Lab fixture",
        SpeechIntentPayload(goal.fact_id),
        (),
        (),
        (),
        tuple(forbidden_fact_refs),
    )
    decision_candidate = ExecutiveDecisionCandidate(
        "lab-decision-candidate",
        "lab-trigger",
        ("lab-event",),
        revisions.source_context_revision,
        revisions.goal_revision or 0,
        revisions.attention_revision or 0,
        ExecutiveOutcome.RESPOND,
        ExecutivePriority.FOREGROUND,
        ExecutiveInterruptibility.INTERRUPTIBLE,
        (intent,),
        (),
        (),
        (goal.fact_id,),
        base,
    )
    decision = CommittedExecutiveDecision("lab-decision", decision_candidate, (), base)
    truth_refs = tuple(item.constraint_id for item in truth_constraints)
    self_disclosure = _enum_value(
        SelfDisclosurePolicy, request.self_disclosure, "self_disclosure"
    )
    semantic_snapshot = SpeechSemanticContextSnapshot(
        decision,
        intent.intent_id,
        tuple(facts),
        tuple(truth_constraints),
        (),
        self_disclosure,
        request.question_budget,
        request.new_direction_budget,
        _offset(base, 1),
    )
    semantic_candidate = SpeechSemanticCandidate(
        "lab-semantic-candidate",
        decision.decision_id,
        intent.intent_id,
        ("lab-event",),
        revisions,
        tuple(propositions),
        self_disclosure,
        request.question_budget,
        request.new_direction_budget,
        truth_refs,
        (),
        (),
        _offset(base, 2),
    )
    semantic_plan = SpeechSemanticAuthority().commit(
        semantic_candidate,
        semantic_snapshot,
        current_revisions=revisions,
        plan_id="lab-semantic-plan",
        committed_at=_offset(base, 3),
    )

    profile = CharacterLanguageProfile("yura", 1, 1, ())
    character_snapshot = CharacterLanguageContextSnapshot(
        "lab-character-request",
        semantic_plan,
        profile,
        (),
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        _offset(base, 4),
        "lab-character-trace",
    )
    required_refs = tuple(
        item.proposition_id
        for item in propositions
        if item.disposition is SpeechPropositionDisposition.REQUIRED
    )
    segments: list[CharacterUtteranceSegment] = []
    for index, item in enumerate(request.segments):
        refs = (
            tuple(item.realization_refs)
            if item.realization_refs is not None
            else (required_refs if index == 0 else ())
        )
        segments.append(
            CharacterUtteranceSegment(
                item.segment_id,
                item.text,
                refs,
                LinguisticBoundary.SENTENCE,
                LinguisticEmphasis.NEUTRAL,
                LinguisticHesitation.NONE,
            )
        )
    utterance_candidate = CharacterUtteranceCandidate(
        "lab-character-candidate",
        character_snapshot.request_id,
        semantic_plan.plan_id,
        semantic_plan.candidate.decision_id,
        semantic_plan.candidate.intent_id,
        semantic_plan.candidate.source_event_ids,
        semantic_plan.candidate.revisions,
        profile.character_id,
        profile.schema_version,
        profile.definition_revision,
        tuple(segments),
        request.question_budget_used,
        request.new_direction_budget_used,
        _offset(base, 5),
    )
    utterance = CharacterLanguageAuthority().commit(
        utterance_candidate,
        character_snapshot,
        current=CharacterLanguageCommitState(
            revisions,
            semantic_plan,
            True,
            profile,
            (),
        ),
        utterance_id="lab-utterance",
        committed_at=_offset(base, 6),
    )
    verification_snapshot = SemanticVerificationContextSnapshot(
        f"verification-{uuid4().hex}",
        f"blind-{uuid4().hex}",
        f"relation-{uuid4().hex}",
        semantic_plan,
        utterance,
        LLMPriority.FOREGROUND,
        LLMInterruptibility.INTERRUPTIBLE,
        _offset(base, 7),
        f"trace-{uuid4().hex}",
    )
    return LabFixture(semantic_plan, utterance, verification_snapshot)


def _model_policy(model: str) -> dict[LLMModelClass, OpenAIResponsesModelPolicy]:
    efforts = {item: item.value for item in LLMReasoningEffort}
    return {
        model_class: OpenAIResponsesModelPolicy(model, efforts)
        for model_class in (
            LLMModelClass.FAST,
            LLMModelClass.BALANCED,
            LLMModelClass.DEEP_REASONING,
        )
    }


def _role_configs(settings: LabSettings) -> tuple[OpenAIResponsesRoleConfig, ...]:
    if not settings.blind_model or not settings.relation_model:
        raise ValueError("Semantic Verification Labのmodelが未設定です")
    return (
        OpenAIResponsesRoleConfig(
            BLIND_ROLE_ID,
            _model_policy(settings.blind_model),
            BLIND_INPUT_SCHEMA,
            BLIND_OUTPUT_SCHEMA,
            "semantic_blind_v1",
            blind_output_schema(),
            blind_instructions(),
            LLMFailurePolicy.FAIL_CLOSED,
        ),
        OpenAIResponsesRoleConfig(
            RELATION_ROLE_ID,
            _model_policy(settings.relation_model),
            RELATION_INPUT_SCHEMA,
            RELATION_OUTPUT_SCHEMA,
            "semantic_relation_v1",
            relation_output_schema(),
            relation_instructions(),
            LLMFailurePolicy.FAIL_CLOSED,
        ),
    )


def _execution_policy(
    model_class: str,
    reasoning_effort: str,
    request: SemanticVerificationLabRequest,
) -> LLMExecutionPolicy:
    return LLMExecutionPolicy(
        _enum_value(LLMModelClass, model_class, "model_class"),
        _enum_value(LLMReasoningEffort, reasoning_effort, "reasoning_effort"),
        request.timeout_seconds,
        1,
        request.max_output_tokens,
        None,
    )


def _jsonable(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


class SemanticVerificationLabService:
    def __init__(
        self,
        settings: LabSettings,
        port: LLMRolePort | None = None,
    ) -> None:
        self._settings = settings
        self._injected_port = port

    async def verify(
        self, request: SemanticVerificationLabRequest
    ) -> dict[str, object]:
        fixture = build_validation_fixture(request)
        port = self._injected_port
        if port is None:
            if not self._settings.live_configured:
                raise ValueError(
                    "OPENAI_API_KEYとSemantic Verification Lab modelを設定してください"
                )
            port = OpenAIResponsesAdapter.from_environment(_role_configs(self._settings))
        policy = SemanticVerificationPolicy(
            _execution_policy(
                request.blind_model_class,
                request.blind_reasoning_effort,
                request,
            ),
            _execution_policy(
                request.relation_model_class,
                request.relation_reasoning_effort,
                request,
            ),
        )
        verifier = SemanticVerifier(
            port,
            _StaticLiveState(fixture.snapshot, request),
            SemanticVerificationAuthority(),
            policy,
        )
        started = perf_counter()
        created_at = _offset(fixture.snapshot.captured_at, 1)
        try:
            run = await verifier.verify(
                fixture.snapshot,
                blind_observation_id=f"blind-observation-{uuid4().hex}",
                relation_observation_id=f"relation-observation-{uuid4().hex}",
                semantic_observation_id=f"semantic-observation-{uuid4().hex}",
                acceptance_id=f"acceptance-{uuid4().hex}",
                created_at=created_at,
            )
        except SemanticVerificationError as error:
            return {
                "ok": False,
                "case": request.name,
                "expected_acceptance": request.expected_acceptance,
                "error": {"code": error.code.value, "message": str(error)},
                "semantic_plan": fixture.semantic_plan.to_dict(),
                "character_utterance": fixture.utterance.to_dict(),
                "total_latency_ms": round((perf_counter() - started) * 1000, 3),
            }
        total_ms = round((perf_counter() - started) * 1000, 3)
        return {
            "ok": True,
            "case": request.name,
            "expected_acceptance": request.expected_acceptance,
            "actual_acceptance": run.acceptance.state.value,
            "matches_expectation": (
                request.expected_acceptance is None
                or request.expected_acceptance == run.acceptance.state.value
            ),
            "semantic_plan": fixture.semantic_plan.to_dict(),
            "character_utterance": fixture.utterance.to_dict(),
            "blind_result": run.blind_result.to_dict(),
            "relation_result": run.relation_result.to_dict(),
            "blind_observation": run.blind_observation.to_dict(),
            "relation_observation": _jsonable(run.relation_observation),
            "semantic_observation": _jsonable(run.semantic_observation),
            "acceptance": _jsonable(run.acceptance),
            "timing": {
                "blind_latency_ms": _result_latency_ms(run.blind_result),
                "relation_latency_ms": _result_latency_ms(run.relation_result),
                "total_latency_ms": total_ms,
            },
            "tokens": {
                "blind": run.blind_result.token_usage.to_dict(),
                "relation": run.relation_result.token_usage.to_dict(),
                "total": {
                    "input_tokens": (
                        run.blind_result.token_usage.input_tokens
                        + run.relation_result.token_usage.input_tokens
                    ),
                    "output_tokens": (
                        run.blind_result.token_usage.output_tokens
                        + run.relation_result.token_usage.output_tokens
                    ),
                },
            },
        }


def _result_latency_ms(result: object) -> float | None:
    started_at = getattr(result, "started_at", None)
    completed_at = getattr(result, "completed_at", None)
    if not isinstance(started_at, datetime) or not isinstance(completed_at, datetime):
        return None
    return round((completed_at - started_at).total_seconds() * 1000, 3)


def _prop(
    proposition_id: str,
    subject: str,
    predicate: str,
    value: dict[str, object],
    **overrides: object,
) -> dict[str, object]:
    item: dict[str, object] = {
        "proposition_id": proposition_id,
        "subject_ref": subject,
        "predicate": predicate,
        "value": value,
    }
    item.update(overrides)
    return item


_PRESETS: dict[str, dict[str, object]] = {
    "exact_preservation": {
        "name": "exact_preservation",
        "expected_acceptance": "accepted",
        "propositions": [_prop("p1", "weather-today", "rain_status", {"raining": True})],
        "segments": [
            {
                "segment_id": "s1",
                "text": "今日は雨が降っているよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "unseen_paraphrase": {
        "name": "unseen_paraphrase",
        "expected_acceptance": "accepted",
        "propositions": [_prop("p1", "weather-today", "rain_status", {"raining": True})],
        "segments": [
            {
                "segment_id": "s1",
                "text": "今日は空から水滴がずっと落ちてきてるね。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "polarity_reversal": {
        "name": "polarity_reversal",
        "expected_acceptance": "rejected",
        "propositions": [_prop("p1", "meeting", "start_time", {"hour": 15})],
        "segments": [
            {
                "segment_id": "s1",
                "text": "会議は3時には始まらないよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "unknown_committed": {
        "name": "unknown_committed",
        "expected_acceptance": "rejected",
        "propositions": [
            _prop(
                "p1",
                "museum",
                "open_status",
                {"open": "unknown"},
                polarity="unknown",
                certainty="unknown",
            )
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "博物館は今日は開いてるよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "unsupported_extra": {
        "name": "unsupported_extra",
        "expected_acceptance": "rejected",
        "propositions": [_prop("p1", "yura", "preference", {"item": "tea", "likes": True})],
        "segments": [
            {
                "segment_id": "s1",
                "text": "お茶は好きだよ。昨日京都のお店で飲んだんだ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "communicative_gratitude": {
        "name": "communicative_gratitude",
        "expected_acceptance": "accepted",
        "propositions": [
            _prop(
                "p1",
                "current-interaction",
                "communicative-act",
                {"kind": "gratitude", "target_ref": "user"},
                fact_kind="discourse",
            )
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "助かった、ありがと！",
                "realization_refs": ["p1"],
            }
        ],
    },
    "question_budget_exceeded": {
        "name": "question_budget_exceeded",
        "expected_acceptance": "rejected",
        "propositions": [_prop("p1", "weather-today", "rain_status", {"raining": True})],
        "question_budget": 0,
        "question_budget_used": 0,
        "segments": [
            {
                "segment_id": "s1",
                "text": "今日は雨だよ。傘は持ってる？",
                "realization_refs": ["p1"],
            }
        ],
    },
    "certainty_strengthened": {
        "name": "certainty_strengthened",
        "expected_acceptance": "rejected",
        "propositions": [
            _prop(
                "p1",
                "train",
                "delay_status",
                {"delayed": True},
                certainty="likely",
            )
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "電車は確実に遅れてるよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
}

for preset in _PRESETS.values():
    preset.setdefault("question_budget", 0)
    preset.setdefault("new_direction_budget", 0)
    preset.setdefault("question_budget_used", 0)
    preset.setdefault("new_direction_budget_used", 0)
    preset.setdefault("self_disclosure", "fact_grounded")
    preset.setdefault("blind_model_class", "balanced")
    preset.setdefault("blind_reasoning_effort", "medium")
    preset.setdefault("relation_model_class", "balanced")
    preset.setdefault("relation_reasoning_effort", "medium")
    preset.setdefault("timeout_seconds", 60.0)
    preset.setdefault("max_output_tokens", 2400)
    preset.setdefault("active", True)
    preset.setdefault("superseded", False)
    preset.setdefault("cancelled", False)
    preset.setdefault("stale_revision", False)


_security = HTTPBasic(auto_error=False)


def create_app(
    *,
    settings: LabSettings | None = None,
    service: SemanticVerificationLabService | None = None,
) -> FastAPI:
    resolved_settings = settings or LabSettings.from_env()
    resolved_service = service or SemanticVerificationLabService(resolved_settings)
    application = FastAPI(
        title="Yura V2 Semantic Verification Lab",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def require_auth(
        credentials: HTTPBasicCredentials | None = Depends(_security),
    ) -> str:
        if not resolved_settings.auth_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="YURA_LAB_USERNAME / YURA_LAB_PASSWORD が未設定です",
            )
        valid = bool(
            credentials
            and secrets.compare_digest(credentials.username, resolved_settings.username)
            and secrets.compare_digest(credentials.password, resolved_settings.password)
        )
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="認証に失敗しました",
                headers={"WWW-Authenticate": "Basic"},
            )
        return resolved_settings.username

    @application.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "auth_configured": resolved_settings.auth_configured,
            "live_configured": resolved_settings.live_configured,
            "blind_model_configured": bool(resolved_settings.blind_model),
            "relation_model_configured": bool(resolved_settings.relation_model),
            "production_roles": [BLIND_ROLE_ID, RELATION_ROLE_ID],
            "secret_exposed": False,
        }

    @application.get("/api/presets")
    async def presets(_: str = Depends(require_auth)) -> dict[str, object]:
        return _PRESETS

    @application.post("/api/verify")
    async def verify(
        request: SemanticVerificationLabRequest,
        _: str = Depends(require_auth),
    ) -> dict[str, object]:
        try:
            return await resolved_service.verify(request)
        except (TypeError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error

    @application.get("/", response_class=HTMLResponse)
    async def index(_: str = Depends(require_auth)) -> HTMLResponse:
        return HTMLResponse(_INDEX_HTML)

    return application


settings = LabSettings.from_env()
service = SemanticVerificationLabService(settings)
app = create_app(settings=settings, service=service)


_INDEX_HTML = r"""
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Yura V2 Semantic Verification Lab</title>
<style>
:root{color-scheme:dark;font-family:Inter,system-ui,-apple-system,sans-serif}
*{box-sizing:border-box} body{margin:0;background:#071019;color:#eaf6ff;min-height:100vh}
main{width:min(1500px,96vw);margin:auto;padding:24px 0 52px}
header{display:flex;justify-content:space-between;gap:16px;align-items:end;margin-bottom:16px}
h1{margin:0;font-size:clamp(24px,3vw,38px)} .sub{color:#9bc6dc;margin-top:5px}
.badge{border:1px solid #345b70;border-radius:999px;padding:7px 11px;color:#a9d9ef}
.toolbar,.card{border:1px solid #24485c;background:#0a1924;border-radius:14px}
.toolbar{display:grid;grid-template-columns:1fr auto auto auto;gap:9px;padding:12px;margin-bottom:13px}
.grid{display:grid;grid-template-columns:minmax(0,.85fr) minmax(0,1.15fr);gap:13px}
.card{padding:15px}.card h2{margin:0 0 11px;font-size:16px}
select,button,textarea{font:inherit} select,textarea{width:100%;background:#040d14;color:#eaf6ff;border:1px solid #31566a;border-radius:9px;padding:9px}
textarea{min-height:640px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;line-height:1.45;resize:vertical}
button{background:#10364c;color:#eefaff;border:1px solid #49778e;border-radius:9px;padding:9px 13px;cursor:pointer;font-weight:650}
button.primary{background:#145b7d}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:10px}
.kpi{border:1px solid #274b60;background:#06121b;border-radius:10px;padding:9px}.kpi small{color:#82acc2;display:block}.kpi strong{display:block;margin-top:4px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#030a10;border:1px solid #264a5d;border-radius:10px;padding:12px;min-height:180px;font-size:12px}
details{border-top:1px solid #1c3949;padding-top:9px;margin-top:10px} summary{cursor:pointer;color:#bde5f6}
.status{color:#92cce6;min-height:1.4em;margin:8px 0}
@media(max-width:900px){.grid{grid-template-columns:1fr}.toolbar{grid-template-columns:1fr 1fr}.toolbar select{grid-column:1/-1}.summary{grid-template-columns:1fr 1fr}}
</style>
</head>
<body><main>
<header><div><h1>V2 Semantic Verification Lab</h1><div class="sub">production #363 / #357 をwhole-appなしで実LLM検証</div></div><div class="badge">A blind → B relation → Runtime acceptance</div></header>
<div class="toolbar">
<select id="preset"></select>
<button id="load">プリセット読込</button>
<button id="run" class="primary">実LLM実行</button>
<button id="export">Markdown Export</button>
</div>
<div class="grid">
<section class="card"><h2>Typed Fixture Input</h2><textarea id="input"></textarea><div id="status" class="status"></div></section>
<section class="card"><h2>Production Result</h2>
<div class="summary">
<div class="kpi"><small>Acceptance</small><strong id="acceptance">-</strong></div>
<div class="kpi"><small>Expectation</small><strong id="expectation">-</strong></div>
<div class="kpi"><small>Total latency</small><strong id="latency">-</strong></div>
<div class="kpi"><small>Tokens</small><strong id="tokens">-</strong></div>
</div>
<details open><summary>Role A — Blind Inventory</summary><pre id="blind">-</pre></details>
<details open><summary>Role B — Plan Relation / Accounting</summary><pre id="relation">-</pre></details>
<details><summary>Acceptance / Observer facts</summary><pre id="acceptanceJson">-</pre></details>
<details><summary>Full result</summary><pre id="full">-</pre></details>
</section></div>
<script>
let presets={}, lastResult=null;
const pretty=v=>JSON.stringify(v,null,2);
async function init(){presets=await (await fetch('/api/presets')).json(); const s=document.getElementById('preset'); Object.keys(presets).forEach(k=>{const o=document.createElement('option');o.value=k;o.textContent=k;s.appendChild(o)});load()}
function load(){document.getElementById('input').value=pretty(presets[document.getElementById('preset').value]);}
async function run(){
 const st=document.getElementById('status');st.textContent='実行中…';
 try{
  const body=JSON.parse(document.getElementById('input').value);
  const r=await fetch('/api/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await r.json(); if(!r.ok) throw new Error(data.detail||'request failed');
  lastResult=data; render(data); st.textContent=data.ok?'完了':'production verifierがfail-closedで停止';
 }catch(e){st.textContent=String(e)}
}
function render(d){
 document.getElementById('acceptance').textContent=d.actual_acceptance||d.error?.code||'-';
 document.getElementById('expectation').textContent=d.expected_acceptance?(d.matches_expectation===false?'不一致: ':'')+d.expected_acceptance:'-';
 document.getElementById('latency').textContent=d.timing?d.timing.total_latency_ms+' ms':(d.total_latency_ms||'-');
 document.getElementById('tokens').textContent=d.tokens?`${d.tokens.total.input_tokens}/${d.tokens.total.output_tokens}`:'-';
 document.getElementById('blind').textContent=pretty(d.blind_observation||d.blind_result||d.error||null);
 document.getElementById('relation').textContent=pretty(d.relation_observation||d.relation_result||d.error||null);
 document.getElementById('acceptanceJson').textContent=pretty({semantic_observation:d.semantic_observation,acceptance:d.acceptance,error:d.error});
 document.getElementById('full').textContent=pretty(d);
}
function exportMd(){
 if(!lastResult)return;
 const d=lastResult, md=`# Yura V2 Semantic Verification Lab Export\n\n- case: ${d.case}\n- expected: ${d.expected_acceptance??'-'}\n- actual: ${d.actual_acceptance??d.error?.code??'-'}\n- total latency ms: ${d.timing?.total_latency_ms??d.total_latency_ms??'-'}\n\n## Input\n\`\`\`json\n${document.getElementById('input').value}\n\`\`\`\n\n## Result\n\`\`\`json\n${pretty(d)}\n\`\`\`\n`;
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([md],{type:'text/markdown'}));a.download=`semantic-verification-${d.case||'export'}.md`;a.click();URL.revokeObjectURL(a.href);
}
document.getElementById('load').onclick=load;document.getElementById('run').onclick=run;document.getElementById('export').onclick=exportMd;init();
</script>
</main></body></html>
"""
