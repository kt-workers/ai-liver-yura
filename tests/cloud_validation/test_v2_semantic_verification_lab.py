from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from app.domain.contracts.common import JsonValue
from app.domain.llm import (
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)
from app.domain.semantic_verification import (
    BLIND_OUTPUT_SCHEMA,
    BLIND_ROLE_ID,
    RELATION_OUTPUT_SCHEMA,
    RELATION_ROLE_ID,
)
from app.usecases.ports.llm import LLMRolePort
from cloud_validation.v2_semantic_verification_lab import (
    LabSettings,
    SemanticVerificationLabRequest,
    SemanticVerificationLabService,
    build_validation_fixture,
)

NOW = datetime(2026, 8, 17, 14, 0, tzinfo=timezone.utc)


class FakePort(LLMRolePort):
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        self.calls.append(request.role_id)
        payload = cast(dict[str, object], request.input.to_dict()["value"])
        started = request.created_at + timedelta(milliseconds=1)
        completed = request.created_at + timedelta(milliseconds=2)
        if request.role_id == BLIND_ROLE_ID:
            segments = cast(list[dict[str, str]], payload["segments"])
            segment = segments[0]
            output = {
                "candidate_id": "blind-candidate",
                "request_id": request.request_id,
                "utterance_id": payload["utterance_id"],
                "units": [
                    {
                        "unit_id": "unit-1",
                        "kind": "material_semantic_content",
                        "interaction_acts": [],
                        "evidence_refs": [
                            {
                                "segment_id": segment["segment_id"],
                                "quote": segment["text"],
                                "occurrence_index": 0,
                            }
                        ],
                    }
                ],
            }
            schema_id = BLIND_OUTPUT_SCHEMA
        elif request.role_id == RELATION_ROLE_ID:
            plan = cast(dict[str, object], payload["semantic_plan"])
            plan_candidate = cast(dict[str, object], plan["candidate"])
            proposition_values = cast(
                list[dict[str, object]], plan_candidate["propositions"]
            )
            blind = cast(dict[str, object], payload["blind_observation"])
            utterance = cast(dict[str, object], payload["utterance"])
            segments = cast(list[dict[str, str]], utterance["segments"])
            segment = segments[0]
            propositions = [
                {
                    "proposition_id": item["proposition_id"],
                    "relation": "entailed",
                    "polarity_relation": "preserved",
                    "certainty_relation": "preserved",
                    "degree_relation": (
                        "not_applicable" if item.get("degree") is None else "preserved"
                    ),
                    "execution_relation": (
                        "not_applicable"
                        if item.get("claim_kind") != "execution_status"
                        else "preserved"
                    ),
                    "evidence_refs": [
                        {
                            "segment_id": segment["segment_id"],
                            "quote": segment["text"],
                            "occurrence_index": 0,
                        }
                    ],
                    "supporting_blind_unit_ids": ["unit-1"],
                }
                for item in proposition_values
            ]
            output = {
                "candidate_id": "relation-candidate",
                "request_id": request.request_id,
                "semantic_plan_id": plan["plan_id"],
                "utterance_id": utterance["utterance_id"],
                "blind_observation_id": blind["observation_id"],
                "proposition_observations": propositions,
                "blind_unit_accounting": [
                    {
                        "blind_unit_id": "unit-1",
                        "relation": "supported_by_plan",
                        "proposition_ids": [
                            cast(str, item["proposition_id"])
                            for item in proposition_values
                        ],
                        "evidence_refs": [
                            {
                                "segment_id": segment["segment_id"],
                                "quote": segment["text"],
                                "occurrence_index": 0,
                            }
                        ],
                    }
                ],
                "budget_observation": {
                    "directed_question_count": 0,
                    "new_direction_count": 0,
                },
                "self_disclosure_relation": "not_applicable",
            }
            schema_id = RELATION_OUTPUT_SCHEMA
        else:
            raise AssertionError(f"unexpected role: {request.role_id}")
        return LLMRoleResult(
            request.request_id,
            request.role_id,
            LLMRoleStatus.SUCCEEDED,
            request.revisions,
            completed,
            request.trace_id,
            request.execution_policy.model_class,
            1,
            LLMTokenUsage(10, 12),
            StructuredPayload(schema_id, cast(JsonValue, output)),
            started_at=started,
        )


def request(*, stale_revision: bool = False) -> SemanticVerificationLabRequest:
    return SemanticVerificationLabRequest.model_validate(
        {
            "name": "fake-exact",
            "expected_acceptance": "accepted",
            "propositions": [
                {
                    "proposition_id": "p1",
                    "subject_ref": "weather",
                    "predicate": "rain_status",
                    "value": {"raining": True},
                }
            ],
            "segments": [
                {
                    "segment_id": "s1",
                    "text": "今日は雨が降っているよ。",
                    "realization_refs": ["p1"],
                }
            ],
            "stale_revision": stale_revision,
        }
    )


def test_fixture_uses_production_speech_and_character_authorities() -> None:
    fixture = build_validation_fixture(request(), now=NOW)

    assert fixture.semantic_plan.plan_id == "lab-semantic-plan"
    assert fixture.utterance.utterance_id == "lab-utterance"
    assert fixture.utterance.candidate.semantic_plan_id == fixture.semantic_plan.plan_id
    assert fixture.snapshot.semantic_plan is fixture.semantic_plan
    assert fixture.snapshot.utterance is fixture.utterance


@pytest.mark.asyncio
async def test_service_executes_production_two_stage_verifier() -> None:
    port = FakePort()
    service = SemanticVerificationLabService(LabSettings("", "", "", "", ""), port)

    result = await service.verify(request())

    assert result["ok"] is True
    assert result["actual_acceptance"] == "accepted"
    assert result["matches_expectation"] is True
    assert port.calls == [BLIND_ROLE_ID, RELATION_ROLE_ID]


@pytest.mark.asyncio
async def test_stale_pair_fails_before_any_provider_call() -> None:
    port = FakePort()
    service = SemanticVerificationLabService(LabSettings("", "", "", "", ""), port)

    result = await service.verify(request(stale_revision=True))

    assert result["ok"] is False
    error = cast(dict[str, object], result["error"])
    assert error["code"] == "stale"
    assert port.calls == []


def test_communicative_material_content_is_committed_without_word_matcher() -> None:
    value = request().model_dump()
    value["propositions"] = [
        {
            "proposition_id": "p1",
            "subject_ref": "current-interaction",
            "predicate": "communicative-act",
            "value": {"kind": "gratitude", "target_ref": "user"},
            "fact_kind": "discourse",
        }
    ]
    value["segments"] = [
        {
            "segment_id": "s1",
            "text": "助かった、ありがと！",
            "realization_refs": ["p1"],
        }
    ]

    fixture = build_validation_fixture(
        SemanticVerificationLabRequest.model_validate(value),
        now=NOW,
    )

    proposition = fixture.semantic_plan.candidate.propositions[0]
    assert proposition.predicate == "communicative-act"
    assert proposition.evidence_fact_refs == ("fact-p1",)
