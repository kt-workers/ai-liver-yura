import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.contracts import CapabilityAvailability, RevisionVector
from app.domain.input_gateway import (
    InputAdmissionLedger,
    InputModality,
    InputNormalizer,
    InputObservation,
    InputPermission,
    InputSessionRegistry,
    InputSourceState,
)
from app.domain.input_meaning import (
    OUTPUT_SCHEMA,
    ExpectedResponse,
    InputMeaningInterpreter,
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
    LLMExecutionPolicy,
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)

NOW = datetime(2026, 8, 19, tzinfo=timezone.utc)


def policy() -> InputMeaningPolicy:
    return InputMeaningPolicy(
        LLMExecutionPolicy(LLMModelClass.BALANCED, LLMReasoningEffort.MEDIUM, 10, 1, 800), 0.7
    )


def event(text: str = "それをもう一度説明して", modality: InputModality = InputModality.TEXT):
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
    admission = InputNormalizer(InputAdmissionLedger(), InputSessionRegistry()).normalize(
        observation
    )
    assert admission.event is not None
    return admission.event


def context() -> ReferenceContext:
    return ReferenceContext(
        4,
        (
            ReferenceContextEntry(
                "speech-1", ReferenceContextKind.RECENT_SPEECH, "presentation:42", 3
            ),
        ),
    )


def output(
    *,
    confidence: float = 0.9,
    unresolved=(),
    reference="presentation:42",
    negated=False,
    hypothetical=False,
):
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


def result(request, value=None):
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
        StructuredPayload(OUTPUT_SCHEMA, output() if value is None else value),
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
    assert (
        text_request.input.to_dict()["value"]["reference_context"]["entries"][0]["reference_id"]
        == "speech-1"
    )


@pytest.mark.parametrize("surface", ["それをもう一度説明して", "先ほどの内容を再度教えて"])
def test_paraphrase_provider_candidates_commit_to_same_typed_meaning(surface: str) -> None:
    request = build_request(
        event(surface), context(), request_id="r1", trace_id="t1", created_at=NOW, policy=policy()
    )
    meaning = commit_result(
        request, result(request), current_source_context_revision=4, policy=policy()
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
        commit_result(request, result(request), current_source_context_revision=5, policy=policy())
    invalid = output()
    invalid["appraisal"] = "happy"
    with pytest.raises(ValueError, match="fields do not match schema"):
        commit_result(
            request, result(request, invalid), current_source_context_revision=4, policy=policy()
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
        async def invoke(self, request):
            await asyncio.sleep(0.02)
            return result(request)

    async def scenario() -> None:
        task = asyncio.create_task(
            InputMeaningInterpreter(SlowPort(), policy()).interpret(
                event(),
                context(),
                request_id="r1",
                trace_id="t1",
                created_at=NOW,
                current_source_context_revision=4,
            )
        )
        await asyncio.sleep(0)
        observed.append("unrelated")
        await task

    asyncio.run(scenario())
    assert observed == ["unrelated"]
