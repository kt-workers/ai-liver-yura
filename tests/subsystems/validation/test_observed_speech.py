"""既存の発話入口へ配線した接続注入と安全な診断の直接検証。"""

from dataclasses import replace

import pytest

from app.adapters.llm.character_language import character_language_openai_role_config
from app.adapters.llm.openai_responses import OpenAIResponsesAdapter
from app.domain.character_language import CharacterLanguageContextSnapshot, build_request
from app.domain.llm import (
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
)
from app.domain.semantic_verification import BLIND_ROLE_ID, SemanticVerificationContextSnapshot
from app.domain.speech_performance import SpeechPerformancePlanner
from app.domain.speech_performance.policy import yura_revision_1_policy
from app.subsystems.validation.contracts import (
    DelayInjection,
    FailureInjection,
    InjectedFailure,
    RunStatus,
)
from app.subsystems.validation.llm_port import LabLLMPortFactory, ObservedLLMRolePort
from app.subsystems.validation.runtime import RunContext, ValidationRunner
from app.subsystems.validation.speech_adjacent import make_speech_bindings, speech_adjacent_target
from app.usecases.ports.llm import LLMRolePort
from tests.adapters.llm.test_openai_responses import FakeClient, status_error
from tests.domain.character_language import test_character_language as character
from tests.domain.semantic_verification import test_semantic_verification as semantic
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_runtime import POLICY, PROVENANCE
from tests.subsystems.validation.test_speech_adjacent import CharacterPort, case, spec


class Connections:
    def __init__(self) -> None:
        self.character: CharacterLanguageContextSnapshot | None = None
        self.verification: SemanticVerificationContextSnapshot | None = None
        self.requests: list[LLMRoleRequest] = []

    def character_live(self, snapshot: CharacterLanguageContextSnapshot) -> character._LiveState:
        self.character = snapshot
        return character._LiveState(character.current(snapshot))

    def verification_live(
        self, snapshot: SemanticVerificationContextSnapshot
    ) -> semantic._LiveState:
        self.verification = snapshot
        return semantic._LiveState(snapshot)

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self.requests.append(request)
        if request.role_id == "character_language":
            assert self.character is not None
            return await CharacterPort(self.character).invoke(request)
        assert self.verification is not None
        return await semantic._SequencePort(self.verification).invoke(request)

    def runner(self, port: LLMRolePort | LabLLMPortFactory | None = None) -> ValidationRunner:
        bindings = make_speech_bindings(
            port=port or self,
            character_live=self.character_live,
            verification_live=self.verification_live,
            character_policy=character.policy(),
            verification_policy=semantic.verification_policy(),
            performance=SpeechPerformancePlanner(yura_revision_1_policy()),
        )
        target = speech_adjacent_target((case(),), bindings, PROVENANCE, "1", ())
        return ValidationRunner((target,), replace(POLICY, max_intervals=64))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(InjectedFailure))
@pytest.mark.parametrize(
    "stage,previous_roles",
    [
        ("speech.character.llm", []),
        ("speech.blind.llm", ["character_language"]),
        ("speech.relation.llm", ["character_language", BLIND_ROLE_ID]),
    ],
)
async def test_failure_is_injected_at_selected_boundary_and_product_stops(
    kind: InjectedFailure, stage: str, previous_roles: list[str]
) -> None:
    connections = Connections()
    runner = connections.runner()
    run_spec = replace(spec(), failure_injections=(FailureInjection(stage, kind, 1),))
    result = await runner.run(run_spec, case().fixture)
    assert result.status is RunStatus.PRODUCT_FAILED
    assert [request.role_id for request in connections.requests] == previous_roles
    assert result.stage_results == ()
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_injected_verifier_delay_overlaps_real_performance_and_is_bounded_to_first_call() -> (
    None
):
    connections = Connections()
    result = await connections.runner().run(
        replace(
            spec(),
            repeat_count=2,
            delay_injections=(DelayInjection("speech.blind.llm", 0.02, 1),),
        ),
        case().fixture,
    )
    assert result.status is RunStatus.COMPLETED
    first = {interval.stage: interval for interval in result.timeline if interval.iteration == 0}
    assert first["speech.blind.llm"].overlaps(first["speech.performance_entry"])
    assert (
        first["speech.blind.llm"].completed_ns - first["speech.blind.llm"].started_ns >= 20_000_000
    )
    assert len(connections.requests) == 6


@pytest.mark.asyncio
async def test_actual_adapter_diagnostic_survives_character_owner_exception_per_run() -> None:
    clients: list[FakeClient] = []
    contexts: list[RunContext] = []
    closed: list[FakeClient] = []
    config = character_language_openai_role_config(
        {LLMModelClass.BALANCED: "test-model"},
        reasoning_by_effort={LLMReasoningEffort.MEDIUM: "medium"},
    )

    def create(context: RunContext) -> OpenAIResponsesAdapter:
        contexts.append(context)
        client = FakeClient(status_error(401, "公開禁止の試験用本文"))
        clients.append(client)

        async def close() -> None:
            closed.append(client)

        context.add_cleanup("test-client", close)
        return OpenAIResponsesAdapter(
            client, (config,), diagnostic_sink=context.diagnostics, now=lambda: semantic.NOW
        )

    runner = Connections().runner(LabLLMPortFactory(create))
    first = await runner.run(spec(), case().fixture)
    second = await runner.run(replace(spec(), run_id="second"), case().fixture)
    assert first.status is second.status is RunStatus.PRODUCT_FAILED
    assert len(clients) == 2 and all(len(client.calls) == 1 for client in clients)
    assert contexts[0] is not contexts[1]
    assert closed == clients
    assert len(first.provider_diagnostics) == len(second.provider_diagnostics) == 1
    assert value_at(first.provider_diagnostics[0], "http_status") == 401
    assert "公開禁止" not in first.export_json(POLICY.max_export_bytes)


@pytest.mark.asyncio
async def test_unmodified_role_result_is_returned_by_identity() -> None:
    snapshot = case().character_context
    request = build_request(snapshot, created_at=semantic.NOW, policy=character.policy())
    result = await CharacterPort(snapshot).invoke(request)

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return result

    context = RunContext(POLICY)
    observed = ObservedLLMRolePort(context, Port(), {request.role_id: "character.llm"})
    assert await observed.invoke(request) is result
    await context.close()


@pytest.mark.asyncio
async def test_failure_activation_count_does_not_change_later_calls() -> None:
    snapshot = case().character_context
    request = build_request(snapshot, created_at=semantic.NOW, policy=character.policy())
    result = await CharacterPort(snapshot).invoke(request)
    calls: list[str] = []

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            calls.append(request.request_id)
            return result

    context = RunContext(
        POLICY, failures=(FailureInjection("character.llm", InjectedFailure.TIMEOUT, 1),)
    )
    observed = ObservedLLMRolePort(context, Port(), {request.role_id: "character.llm"})
    assert (await observed.invoke(request)).status is LLMRoleStatus.TIMED_OUT
    assert not calls
    assert await observed.invoke(request) is result
    assert calls == [request.request_id]
    await context.close()
