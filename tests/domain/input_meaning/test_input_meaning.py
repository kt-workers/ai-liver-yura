import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts import CapabilityAvailability, RevisionVector
from app.domain.contracts.common import JsonValue
from app.domain.input_gateway import (
    InputAdmissionLedger,
    InputModality,
    InputNormalizer,
    InputObservation,
    InputPermission,
    InputSessionRegistry,
    InputSourceState,
    NormalizedInputEvent,
)
from app.domain.input_meaning import (
    OUTPUT_SCHEMA,
    ExpectedResponse,
    InputMeaningInterpreter,
    InputMeaningLiveContextPort,
    InputMeaningPolicy,
    MeaningResolution,
    PrimaryIntent,
    ReferenceContext,
    ReferenceContextEntry,
    ReferenceContextKind,
    build_request,
    commit_result,
)
from app.domain.llm import (
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)
from tests.helpers.llm import make_execution_policy

NOW = datetime(2026, 8, 19, tzinfo=timezone.utc)


def policy() -> InputMeaningPolicy:
    return InputMeaningPolicy(
        make_execution_policy(LLMModelClass.BALANCED, LLMReasoningEffort.MEDIUM, 10, 1, 800), 0.7
    )


def event(
    text: str = "それをもう一度説明して",
    modality: InputModality = InputModality.TEXT,
) -> NormalizedInputEvent:
    observation = InputObservation(
        "obs-1",
        InputSourceState("chat", "user", CapabilityAvailability.AVAILABLE, InputPermission.GRANTED),
        modality,
        "utterance",
        NOW,
        "trace-1",
        RevisionVector(4),
        {"text": text},
    )
    admission = InputNormalizer(
        InputAdmissionLedger(),
        InputSessionRegistry(),
        bounds_policy=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    ).normalize(observation)
    assert admission.event is not None
    return admission.event


def context(revision: int = 4) -> ReferenceContext:
    return ReferenceContext(
        revision,
        (
            ReferenceContextEntry(
                "speech-1", ReferenceContextKind.RECENT_SPEECH, "presentation:42", 3
            ),
        ),
    )


def output(
    *,
    confidence: float = 0.9,
    unresolved: tuple[str, ...] = (),
    reference: str | None = "presentation:42",
    negated: bool = False,
    hypothetical: bool = False,
) -> dict[str, Any]:
    return {
        "speech_act": "request",
        "primary_intent": "request_information",
        "expected_response": "answer",
        "target_ref": "presentation:42",
        "entities": [],
        "references": [{"mention_id": "それ", "resolved_ref": reference}],
        "information": ["説明の再提示"],
        "negated": negated,
        "hypothetical": hypothetical,
        "temporal_relation": "relative",
        "confidence": confidence,
        "unresolved_fields": list(unresolved),
    }


def result(request: LLMRoleRequest, value: object | None = None) -> LLMRoleResult:
    return LLMRoleResult(
        request.request_id,
        request.role_id,
        LLMRoleStatus.SUCCEEDED,
        request.revisions,
        NOW + timedelta(seconds=1),
        request.trace_id,
        LLMModelClass.BALANCED,
        1,
        LLMTokenUsage(20, 10),
        StructuredPayload(OUTPUT_SCHEMA, cast(JsonValue, output() if value is None else value)),
        started_at=NOW,
    )


def test_text_and_stt_use_same_role_schema_and_reference_context() -> None:
    text_request = build_request(
        event(), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    speech_request = build_request(
        event(modality=InputModality.SPEECH),
        context(),
        request_id="r2",
        trace_id="t2",
        created_at=NOW,
        policy=policy(),
    )
    assert text_request.role_id == speech_request.role_id == "input_meaning"
    assert text_request.input.schema_id == speech_request.input.schema_id
    request_value = cast(dict[str, Any], text_request.input.to_dict()["value"])
    assert request_value["reference_context"]["entries"][0]["reference_id"] == "speech-1"


@pytest.mark.parametrize("surface", ["それをもう一度説明して", "先ほどの内容を再度教えて"])
def test_paraphrase_provider_candidates_commit_to_same_typed_meaning(surface: str) -> None:
    request = build_request(
        event(surface), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    meaning = commit_result(
        request,
        result(request),
        reference_context=context(),
        current_source_context_revision=4,
        policy=policy(),
    )
    assert meaning.primary_intent is PrimaryIntent.REQUEST_INFORMATION
    assert meaning.expected_response is ExpectedResponse.ANSWER
    assert meaning.references[0].resolved_ref == "presentation:42"
    assert "text" not in meaning.to_dict()
    json.dumps(meaning.to_dict(), allow_nan=False)


def test_low_confidence_and_unresolved_reference_fail_closed_to_clarification() -> None:
    request = build_request(
        event(), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    meaning = commit_result(
        request,
        result(request, output(confidence=0.2, reference=None)),
        reference_context=context(),
        current_source_context_revision=4,
        policy=policy(),
    )
    assert meaning.resolution is MeaningResolution.CLARIFICATION_REQUIRED
    assert set(meaning.unresolved_fields) == {"confidence", "references"}


@pytest.mark.parametrize(
    "intent",
    ["request_action", "start_activity", "stop_activity"],
)
def test_action_intents_without_target_require_clarification(intent: str) -> None:
    request = build_request(
        event(), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    value = output()
    value["primary_intent"] = intent
    value["target_ref"] = None
    meaning = commit_result(
        request,
        result(request, value),
        reference_context=context(),
        current_source_context_revision=4,
        policy=policy(),
    )
    assert meaning.resolution is MeaningResolution.CLARIFICATION_REQUIRED
    assert "target_ref" in meaning.unresolved_fields


def test_negation_and_hypothetical_are_typed_without_surface_matching() -> None:
    request = build_request(
        event("仮に始めるとしても今は始めない"),
        context(),
        request_id="r1",
        trace_id="t1",
        created_at=NOW,
        policy=policy(),
    )
    meaning = commit_result(
        request,
        result(request, output(negated=True, hypothetical=True)),
        reference_context=context(),
        current_source_context_revision=4,
        policy=policy(),
    )
    assert meaning.negated is True and meaning.hypothetical is True


def test_non_language_stale_and_extra_output_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="only text or speech"):
        build_request(
            event(modality=InputModality.VISION),
            context(),
            request_id="r",
            trace_id="t",
            created_at=NOW,
            policy=policy(),
        )
    request = build_request(
        event(), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    with pytest.raises(ValueError, match="stale"):
        commit_result(
            request,
            result(request),
            reference_context=context(),
            current_source_context_revision=5,
            policy=policy(),
        )
    invalid = output()
    invalid["appraisal"] = "happy"
    with pytest.raises(ValueError, match="fields do not match schema"):
        commit_result(
            request,
            result(request, invalid),
            reference_context=context(),
            current_source_context_revision=4,
            policy=policy(),
        )


def test_reference_outside_bounded_context_is_rejected() -> None:
    request = build_request(
        event(), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    with pytest.raises(ValueError, match="outside bounded"):
        commit_result(
            request,
            result(request, output(reference="made-up:999")),
            reference_context=context(),
            current_source_context_revision=4,
            policy=policy(),
        )


def test_wrapper_modality_cannot_relabel_vision_envelope_as_text() -> None:
    vision = event(modality=InputModality.VISION)
    disguised = replace(vision, modality=InputModality.TEXT)
    with pytest.raises(ValueError, match="event_type does not match"):
        build_request(
            disguised,
            context(),
            request_id="r1",
            trace_id="t1",
            created_at=NOW,
            policy=policy(),
        )


def test_reference_context_is_bounded_unique_and_not_from_future() -> None:
    entry = ReferenceContextEntry("r", ReferenceContextKind.CURRENT_TOPIC, "topic:1", 4)
    with pytest.raises(ValueError, match="max_entries"):
        ReferenceContext(4, (entry,), max_entries=0)
    with pytest.raises(ValueError, match="unique"):
        ReferenceContext(4, (entry, entry))
    with pytest.raises(ValueError, match="newer"):
        ReferenceContext(3, (entry,))


def test_slow_meaning_port_does_not_block_unrelated_task() -> None:
    observed: list[str] = []

    class SlowPort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            await asyncio.sleep(0.02)
            return result(request)

    class LiveContext:
        async def current_source_context_revision(self) -> int:
            return 4

    async def scenario() -> None:
        task = asyncio.create_task(
            InputMeaningInterpreter(SlowPort(), LiveContext(), policy()).interpret(
                event(),
                context(),
                request_id="r1",
                trace_id="t1",
                created_at=NOW,
            )
        )
        await asyncio.sleep(0)
        observed.append("unrelated")
        await task

    asyncio.run(scenario())
    assert observed == ["unrelated"]


def test_interpret_rejects_result_when_live_context_advances_during_provider_wait() -> None:
    class AdvancingPort:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            self.started.set()
            await self.release.wait()
            return result(request)

    class LiveContext:
        revision = 4

        async def current_source_context_revision(self) -> int:
            return self.revision

    async def scenario() -> None:
        provider = AdvancingPort()
        live_context = LiveContext()
        task = asyncio.create_task(
            InputMeaningInterpreter(provider, live_context, policy()).interpret(
                event(), context(), request_id="r1", trace_id="t1", created_at=NOW
            )
        )
        await provider.started.wait()
        live_context.revision = 5
        provider.release.set()
        with pytest.raises(ValueError, match="stale"):
            await task

    asyncio.run(scenario())


def test_interpret_preserves_request_revision_after_post_await_live_read() -> None:
    class ImmediatePort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return result(request)

    class LiveContext:
        async def current_source_context_revision(self) -> int:
            return 4

    meaning = asyncio.run(
        InputMeaningInterpreter(ImmediatePort(), LiveContext(), policy()).interpret(
            event(), context(), request_id="r1", trace_id="t1", created_at=NOW
        )
    )
    assert meaning.source_context_revision == 4


def test_interpret_fails_closed_when_live_context_read_fails() -> None:
    class ImmediatePort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return result(request)

    class FailingLiveContext:
        async def current_source_context_revision(self) -> int:
            raise RuntimeError("live context unavailable")

    with pytest.raises(RuntimeError, match="live context unavailable"):
        asyncio.run(
            InputMeaningInterpreter(ImmediatePort(), FailingLiveContext(), policy()).interpret(
                event(), context(), request_id="r1", trace_id="t1", created_at=NOW
            )
        )


def test_live_context_port_is_read_only_protocol() -> None:
    class LiveContext:
        async def current_source_context_revision(self) -> int:
            return 4

    port: InputMeaningLiveContextPort = LiveContext()
    assert asyncio.run(port.current_source_context_revision()) == 4


def test_old_result_cannot_be_reused_with_new_reference_context() -> None:
    request = build_request(
        event(), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    with pytest.raises(ValueError, match="reference context does not match request snapshot"):
        commit_result(
            request,
            result(request),
            reference_context=context(5),
            current_source_context_revision=4,
            policy=policy(),
        )
