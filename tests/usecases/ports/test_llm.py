import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.contracts import RevisionVector
from app.domain.llm import (
    LLMExecutionPolicy,
    LLMFailureCode,
    LLMInterruptibility,
    LLMModelClass,
    LLMPriority,
    LLMReasoningEffort,
    LLMRoleFailure,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMStalePolicy,
    LLMTokenUsage,
    StructuredPayload,
)
from app.usecases.ports import LLMRolePort

NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def make_request(request_id: str, role_id: str) -> LLMRoleRequest:
    return LLMRoleRequest(
        request_id,
        role_id,
        StructuredPayload(f"{role_id}.input.v1", {"value": request_id}),
        (),
        RevisionVector(1),
        (),
        LLMPriority.NORMAL,
        LLMInterruptibility.INTERRUPTIBLE,
        LLMStalePolicy.REJECT,
        LLMExecutionPolicy(
            LLMModelClass.FAST, LLMReasoningEffort.LOW, 5, 1, 100
        ),
        NOW,
        f"trace-{request_id}",
    )


@dataclass
class FakeSharedProvider(LLMRolePort):
    gates: dict[str, asyncio.Event] = field(default_factory=dict)
    failures: dict[str, LLMFailureCode] = field(default_factory=dict)
    started: list[str] = field(default_factory=list)

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self.started.append(request.role_id)
        gate = self.gates.get(request.role_id)
        if gate is not None:
            await gate.wait()
        code = self.failures.get(request.role_id)
        if code is not None:
            return LLMRoleResult(
                request.request_id,
                request.role_id,
                LLMRoleStatus.FAILED,
                request.revisions,
                NOW,
                request.trace_id,
                request.execution_policy.model_class,
                1,
                LLMTokenUsage(1, 0),
                failure=LLMRoleFailure(code, "fake failure"),
                started_at=NOW,
            )
        return LLMRoleResult(
            request.request_id,
            request.role_id,
            LLMRoleStatus.SUCCEEDED,
            request.revisions,
            NOW,
            request.trace_id,
            request.execution_policy.model_class,
            1,
            LLMTokenUsage(1, 1),
            StructuredPayload(f"{request.role_id}.output.v1", {"ok": True}),
            started_at=NOW,
        )


def test_shared_provider_keeps_logical_role_results_independent() -> None:
    async def scenario() -> None:
        provider = FakeSharedProvider(
            failures={"reflection": LLMFailureCode.PROVIDER_ERROR}
        )
        meaning, reflection = await asyncio.gather(
            provider.invoke(make_request("1", "input-meaning")),
            provider.invoke(make_request("2", "reflection")),
        )
        assert meaning.status is LLMRoleStatus.SUCCEEDED
        assert reflection.status is LLMRoleStatus.FAILED
        assert meaning.role_id == "input-meaning"
        assert reflection.role_id == "reflection"

    asyncio.run(scenario())


def test_slow_role_does_not_block_independent_invocation() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()
        provider = FakeSharedProvider(gates={"reflection": gate})
        slow = asyncio.create_task(provider.invoke(make_request("1", "reflection")))
        await asyncio.sleep(0)
        fast = await provider.invoke(make_request("2", "input-meaning"))

        assert not slow.done()
        assert fast.status is LLMRoleStatus.SUCCEEDED
        assert provider.started == ["reflection", "input-meaning"]
        gate.set()
        assert (await slow).status is LLMRoleStatus.SUCCEEDED

    asyncio.run(scenario())
