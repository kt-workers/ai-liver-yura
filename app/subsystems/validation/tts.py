"""発話と表現計画から本番の音声合成接続を呼び、公開結果を記録する。"""

import json
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import timedelta
from time import monotonic
from typing import cast

from app.adapters.tts import (
    PreparedAudioResourceStore,
    TTSPerformanceMappingPolicy,
    TTSProviderAdapter,
    TTSProviderOperationalPolicy,
    TTSSynthesisRequest,
    TTSSynthesisResult,
)
from app.adapters.tts.contracts import TTSFailureCode, TTSSynthesisStatus
from app.adapters.tts.provider import ProviderSynthesisInput, TTSProviderClient, TTSProviderResponse
from app.domain.contracts.common import JsonValue, freeze_json
from app.runtime.lifecycle import DependencyRetryPolicy

from .body import _encode as encode_domain
from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .runtime import LabTarget, RunContext


def _encode(value: object) -> object:
    if (
        is_dataclass(value)
        and not isinstance(value, type)
        and type(value).__module__
        in {
            "app.adapters.tts.contracts",
            "app.adapters.tts.policy",
            "app.runtime.lifecycle",
        }
    ):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    return encode_domain(value)


def _project(value: object) -> JsonValue:
    return freeze_json(
        cast(JsonValue, json.loads(json.dumps(value, default=_encode, allow_nan=False)))
    )


@dataclass(frozen=True)
class TTSSynthesisCase:
    fixture: ValidationFixture
    request: TTSSynthesisRequest
    mapping: TTSPerformanceMappingPolicy
    operational: TTSProviderOperationalPolicy
    retry: DependencyRetryPolicy

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "request": self.request,
                "mapping": self.mapping,
                "operational": self.operational,
                "retry": self.retry,
            }
        )


def tts_synthesis_target(
    cases: tuple[TTSSynthesisCase, ...],
    client: TTSProviderClient,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("音声合成の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)

        request, result = await synthesize_audio(context, case, client)
        status = synthesis_run_status(result)
        return TargetObservation(
            status, Gate.NOT_RUN, _project({"request": request, "result": result})
        )

    return LabTarget(
        "tts_synthesis",
        contract_revision,
        frozenset({LabMode.ISOLATION}),
        (),
        provenance,
        run,
        frozenset({"tts.provider"}),
    )


async def synthesize_audio(
    context: RunContext,
    case: TTSSynthesisCase,
    client: TTSProviderClient,
    resource_store: PreparedAudioResourceStore | None = None,
    *,
    preserve_identity: bool = False,
) -> tuple[TTSSynthesisRequest, TTSSynthesisResult]:
    """資源参照表を結合先と共有し、本番の合成結果を型付きで返す。"""

    class ObservedClient:
        async def synthesize(
            self, voice_ref: str, texts: tuple[str, ...], provider_input: ProviderSynthesisInput
        ) -> TTSProviderResponse:
            return await context.invoke_port(
                "tts.provider", lambda: client.synthesize(voice_ref, texts, provider_input)
            )

    started = monotonic()
    owner = TTSProviderAdapter(
        ObservedClient(),
        case.mapping,
        case.operational,
        case.retry,
        now=lambda: case.request.created_at + timedelta(seconds=monotonic() - started),
        resource_store=resource_store,
    )
    context.add_cleanup("tts.adapter", owner.shutdown)
    prefix = f"{context.run_id}:{case.fixture.scenario_id}:{context.iteration}"
    request = (
        case.request
        if preserve_identity
        else replace(case.request, request_id=f"{prefix}:tts", candidate_id=f"{prefix}:candidate")
    )
    result = await context.invoke_product("tts.synthesis", lambda: owner.synthesize(request))
    return request, result


def synthesis_run_status(result: TTSSynthesisResult) -> RunStatus:
    status = {
        TTSSynthesisStatus.SUCCEEDED: RunStatus.COMPLETED,
        TTSSynthesisStatus.FAILED: RunStatus.PROVIDER_FAILED,
        TTSSynthesisStatus.TIMED_OUT: RunStatus.TIMED_OUT,
        TTSSynthesisStatus.CANCELLED: RunStatus.CANCELLED,
    }[result.status]
    if result.failure_code in {TTSFailureCode.INVALID_REQUEST, TTSFailureCode.INVALID_BINDING}:
        status = RunStatus.PRODUCT_FAILED
    return status
