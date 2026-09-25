"""実Ownerによる本番構成の初期化・現在性・非破壊cleanupを検証する。"""

import asyncio
import json
from dataclasses import replace
from typing import Any, cast

import httpx2
import pytest
import yaml
from openai import APIConnectionError

import app.composition.executive_configuration as composition
from app.adapters.llm.openai_responses import OpenAIResponsesAdapter, OpenAIResponsesModelPolicy
from app.config.executive import (
    ExecutiveConfigurationError,
    ExecutiveProductionConfig,
    load_executive_config,
)
from app.config.executive import (
    ExecutiveConfigurationFailureCode as Code,
)
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts import CapabilityRequirement
from app.domain.contracts.finalization import FinalizationError
from app.domain.executive import (
    ActivityIntentPayload,
    DirectActivityRequirementSource,
    DirectActivityRequirementsOwner,
    ExecutiveIntent,
    ExecutiveIntentKind,
    ExecutiveOutcome,
    ExecutiveRequirementsOwner,
    RequirementsFailureCode,
    RequirementsRejected,
)
from app.domain.executive.contracts import IntentPayload
from app.domain.executive.deliberator import build_request, descriptor
from app.domain.llm import LLMFailureCode, LLMFailurePolicy, LLMModelClass, LLMReasoningEffort
from tests.adapters.llm.test_openai_responses import FakeClient, make_config
from tests.config.test_executive import SOURCE, data, record_data
from tests.domain.activity_binding.test_binding import fixture, publish
from tests.domain.executive.test_executive import NOW, candidate, live_state, snapshot


def configured_direct() -> ExecutiveProductionConfig:
    raw = data()
    raw["config_revision"] = 2
    record = record_data()
    record["preconditions"] = []
    raw["direct_activity"]["records"] = [record]
    return load_executive_config(yaml.safe_dump(raw))


def test_empty_catalog_and_real_generation_with_safe_provenance() -> None:
    config = load_executive_config(SOURCE)
    bound = composition.create_executive_configuration(config, bounds=BOUNDS, activity_bindings={})
    assert bound.executive_policy.execution is config.execution
    assert bound.executive_policy.bounds is BOUNDS
    assert bound.initial_generation is bound.requirements_owner.current_generation()
    assert bound.initial_generation.policy is config.requirements
    assert bound.initial_generation.serial == 0 != config.config_revision
    assert (
        bound.initial_generation.token == bound.requirements_owner.finalization_participant.token()
    )
    provenance = bound.provenance.to_dict()
    assert provenance["source_config_ref"] == "resources/config/v2/executive.yaml"
    assert provenance["execution_policy_id"] == "yura.executive.execution"
    assert provenance["requirements_policy_id"] == "yura.executive.requirements"
    assert provenance["initial_generation_serial"] == 0
    token = bound.initial_generation.token
    assert dict(bound.provenance.initial_generation_identity) == {
        "owner_identity": token.owner_identity,
        "owner_instance_key": token.owner_instance_key,
        "participant_identity": token.participant_identity,
        "generation": token.generation,
    }
    second = composition.create_executive_configuration(config, bounds=BOUNDS, activity_bindings={})
    assert second.initial_generation.serial == bound.initial_generation.serial
    assert (
        second.provenance.initial_generation_identity
        != bound.provenance.initial_generation_identity
    )
    second.close()
    assert provenance["rule_revisions"] == tuple((r.rule_id, 1) for r in config.requirements.rules)
    assert provenance["bounds_policy_id"] == BOUNDS.policy_id
    serialized = json.dumps(provenance)
    for forbidden in (
        "_participant",
        "_lock",
        "credential",
        "test.llm.execution",
        "/Users/",
        "raw_token",
    ):
        assert forbidden not in serialized
    bound.close()
    with pytest.raises(FinalizationError):
        bound.requirements_owner.current_generation()


@pytest.mark.parametrize(
    "change",
    ["missing", "extra", "identity", "revision", "activity_type", "target_ref", "empty_records"],
)
def test_exact_binding_mismatch(change: str) -> None:
    owner, _, _ = fixture()
    pub = publish(owner)
    config = configured_direct()
    bindings = {"binding-1": owner}
    if change == "missing":
        bindings = {}
    elif change == "extra":
        bindings["extra"] = owner
    elif change == "identity":
        config = replace(
            config, direct_records=(replace(config.direct_records[0], binding_ref="wrong"),)
        )
        bindings = {"wrong": owner}
    elif change == "empty_records":
        config = load_executive_config(SOURCE)
    else:
        changes = {
            "revision": {"binding_revision": 2},
            "activity_type": {"activity_type": "other"},
            "target_ref": {"target_ref": None},
        }
        config = replace(
            config,
            direct_records=(replace(config.direct_records[0], **cast(Any, changes[change])),),
        )
    with pytest.raises(ExecutiveConfigurationError) as caught:
        composition.create_executive_configuration(
            config, bounds=BOUNDS, activity_bindings=bindings
        )
    assert caught.value.code is Code.BINDING_MISMATCH
    assert owner.capture() == pub


def test_direct_capture_derivation_candidate_mismatch_and_policy_currentness() -> None:
    owner, _, _ = fixture()
    pub = publish(owner)
    bound = composition.create_executive_configuration(
        configured_direct(), bounds=BOUNDS, activity_bindings={"binding-1": owner}
    )
    initial = replace(
        snapshot(),
        requirements_generation=None,
        activity_bindings=(pub,),
        capabilities=(pub.descriptor,),
    )
    captured = bound.requirements_owner.capture(initial)
    assert captured.requirements_generation is not None
    assert captured.requirements_generation is not bound.initial_generation
    assert captured.requirements_generation.base_generation is bound.initial_generation
    assert bound.requirements_owner.current_generation() is bound.initial_generation
    sources = captured.requirements_generation.sources
    assert len(sources) == 1 and isinstance(sources[0].value, DirectActivityRequirementSource)
    assert sources[0].value.record == bound.config.direct_records[0]
    proposed = replace(
        candidate(),
        outcome=ExecutiveOutcome.ACT,
        intents=(
            ExecutiveIntent(
                "direct",
                ExecutiveIntentKind.ACTIVITY,
                "正規sourceの照合",
                ActivityIntentPayload("activity", "target", (), "binding-1"),
                required_capabilities=(CapabilityRequirement("activity", "run"),),
            ),
        ),
    )
    result = bound.requirements_owner.derive(captured, proposed)
    assert result.failure is None and len(result.values) == 1
    changed = replace(proposed, intents=(replace(proposed.intents[0], required_capabilities=()),))
    # derive自体は正本を返す。既存の確定前照合が候補の省略を拒否する。
    current_state = bound.requirements_owner.prepare(captured, proposed, live_state())
    with pytest.raises(RequirementsRejected) as mismatch:
        bound.requirements_owner.validate_captured(captured, changed, current_state)
    assert mismatch.value.failure.code is RequirementsFailureCode.CANDIDATE_MISMATCH
    new_policy = replace(
        bound.config.requirements,
        revision=2,
        rules=tuple(replace(r, policy_revision=2) for r in bound.config.requirements.rules),
    )
    current = bound.requirements_owner.publish(new_policy)
    assert current.serial == 1
    stale = bound.requirements_owner.derive(captured, proposed)
    assert stale.failure is not None and not stale.values
    bound.close()
    assert owner.capture() == pub


def test_missing_direct_source_is_not_empty_success() -> None:
    owner, _, _ = fixture()
    pub = publish(owner)
    bound = composition.create_executive_configuration(
        load_executive_config(SOURCE), bounds=BOUNDS, activity_bindings={}
    )
    with pytest.raises(RequirementsRejected) as caught:
        bound.requirements_owner.capture(
            replace(snapshot(), requirements_generation=None, activity_bindings=(pub,))
        )
    assert caught.value.failure.code is RequirementsFailureCode.SOURCE_UNAVAILABLE
    bound.close()


@pytest.mark.parametrize("stage", ["direct_publish", "requirements_publish", "provenance"])
def test_partial_failure_reclaims_only_created_owners(
    stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, _, _ = fixture()
    pub = publish(owner)
    created_direct: list[DirectActivityRequirementsOwner] = []
    created_requirements: list[ExecutiveRequirementsOwner] = []
    original_direct = DirectActivityRequirementsOwner.publish
    original_requirements = ExecutiveRequirementsOwner.publish

    def publish_direct(self: DirectActivityRequirementsOwner, record: Any) -> Any:
        created_direct.append(self)
        if stage == "direct_publish":
            raise RuntimeError("/private/secret-input")
        return original_direct(self, record)

    def publish_requirements(
        self: ExecutiveRequirementsOwner, policy: Any, sources: Any = ()
    ) -> Any:
        created_requirements.append(self)
        if stage == "requirements_publish":
            raise RuntimeError("/private/secret-input")
        return original_requirements(self, policy, sources)

    def provenance_failure(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("/private/secret-input")

    monkeypatch.setattr(DirectActivityRequirementsOwner, "publish", publish_direct)
    monkeypatch.setattr(ExecutiveRequirementsOwner, "publish", publish_requirements)
    if stage == "provenance":
        monkeypatch.setattr(composition, "ExecutiveConfigurationProvenance", provenance_failure)
    with pytest.raises(ExecutiveConfigurationError) as caught:
        composition.create_executive_configuration(
            configured_direct(), bounds=BOUNDS, activity_bindings={"binding-1": owner}
        )
    assert caught.value.code is Code.INITIALIZATION_FAILED
    assert "/private/" not in str(caught.value)
    assert caught.value.__suppress_context__
    assert len(created_direct) == 1
    for direct in created_direct:
        with pytest.raises(FinalizationError):
            direct.capture()
    for requirements in created_requirements:
        with pytest.raises(FinalizationError):
            requirements.current_generation()
    assert owner.capture() == pub


def test_primary_capability_is_validated_by_direct_owner() -> None:
    owner, _, _ = fixture()
    pub = publish(owner)
    config = configured_direct()
    config = replace(config, direct_records=(replace(config.direct_records[0], capabilities=()),))
    with pytest.raises(ExecutiveConfigurationError) as caught:
        composition.create_executive_configuration(
            config, bounds=BOUNDS, activity_bindings={"binding-1": owner}
        )
    assert caught.value.code is Code.INITIALIZATION_FAILED
    assert owner.capture() == pub


def test_production_request_descriptor_and_adapter_fail_closed() -> None:
    async def run() -> None:
        config = load_executive_config(SOURCE)
        bound = composition.create_executive_configuration(
            config, bounds=BOUNDS, activity_bindings={}
        )
        desc = descriptor(bound.executive_policy)
        request = build_request(
            snapshot(),
            request_id="production-request",
            trace_id="production-trace",
            created_at=NOW,
            policy=bound.executive_policy,
        )
        assert desc.default_execution_policy is request.execution_policy is config.execution
        delays: list[float] = []

        async def sleep(delay: float) -> None:
            delays.append(delay)

        model = OpenAIResponsesModelPolicy(
            "test-deployment-mapping",
            1,
            "test-provider-model",
            {LLMReasoningEffort.MEDIUM: "test-medium"},
        )
        role = make_config(
            role_id=desc.role_id,
            input_schema_id=desc.input_schema_id,
            output_schema_id=desc.output_schema_id,
            provider_output_format_name="test_candidate",
            model_policies={LLMModelClass.BALANCED: model},
            failure_policy=LLMFailurePolicy.FAIL_CLOSED,
        )
        client = FakeClient(
            APIConnectionError(request=httpx2.Request("POST", "https://example.invalid"))
        )
        result = await OpenAIResponsesAdapter(client, (role,), now=lambda: NOW, sleep=sleep).invoke(
            request
        )
        assert result.failure is not None
        assert len(client.calls) == 1 and delays == []
        unsupported = replace(role, model_policies={LLMModelClass.FAST: model})
        unused = FakeClient()
        result = await OpenAIResponsesAdapter(unused, (unsupported,), now=lambda: NOW).invoke(
            request
        )
        assert result.failure is not None and result.failure.code is LLMFailureCode.POLICY_VIOLATION
        assert unused.calls == []
        bound.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "kind", [ExecutiveIntentKind.SPEECH, ExecutiveIntentKind.BODY, ExecutiveIntentKind.ATTENTION]
)
def test_production_explicit_empty_is_not_unregistered_fallback(kind: ExecutiveIntentKind) -> None:
    from app.domain.executive import AttentionIntentPayload, BodyIntentPayload, SpeechIntentPayload

    bound = composition.create_executive_configuration(
        load_executive_config(SOURCE), bounds=BOUNDS, activity_bindings={}
    )
    payloads: dict[ExecutiveIntentKind, IntentPayload] = {
        ExecutiveIntentKind.SPEECH: SpeechIntentPayload("answer-user"),
        ExecutiveIntentKind.BODY: BodyIntentPayload("answer-user"),
        ExecutiveIntentKind.ATTENTION: AttentionIntentPayload("answer-user", "focus"),
    }
    proposed = replace(
        candidate(),
        outcome=ExecutiveOutcome.CONTINUE_ACTIVITY,
        intents=(ExecutiveIntent("explicit-empty", kind, "明示空要件", payloads[kind]),),
    )
    captured = bound.requirements_owner.capture(replace(snapshot(), requirements_generation=None))
    result = bound.requirements_owner.derive(captured, proposed)
    assert result.failure is None
    assert result.values[0].requirements.capabilities == ()
    assert result.values[0].requirements.preconditions == ()
    assert result.values[0].provenance.rule_id == "executive.requirements.production." + kind.value
    # 実Ownerで規則を除外した場合は、構成の明示空と異なる非成功になる。
    stripped = replace(
        bound.config.requirements,
        revision=2,
        rules=tuple(
            replace(rule, policy_revision=2)
            for rule in bound.config.requirements.rules
            if rule.intent_kind is not kind
        ),
    )
    bound.requirements_owner.publish(stripped)
    fresh = bound.requirements_owner.capture(replace(snapshot(), requirements_generation=None))
    failure = bound.requirements_owner.derive(fresh, proposed)
    assert (
        failure.failure is not None
        and failure.failure.code is RequirementsFailureCode.RULE_UNREGISTERED
    )
    assert not failure.values
    bound.close()


@pytest.mark.parametrize(
    "kind", [ExecutiveIntentKind.PLAN_EXECUTION, ExecutiveIntentKind.PLAN_PROGRESS]
)
def test_production_plan_requires_real_source_even_with_empty_rule(
    kind: ExecutiveIntentKind,
) -> None:
    from app.domain.executive import PlanExecutionIntentPayload, PlanProgressIntentPayload
    from app.domain.plan_execution.progress_contracts import PlanStepCompletionClaim

    bound = composition.create_executive_configuration(
        load_executive_config(SOURCE), bounds=BOUNDS, activity_bindings={}
    )
    payload = (
        PlanExecutionIntentPayload("missing-scope")
        if kind is ExecutiveIntentKind.PLAN_EXECUTION
        else PlanProgressIntentPayload(
            "missing-context", (PlanStepCompletionClaim("step", (), ("fact",)),)
        )
    )
    proposed = replace(
        candidate(),
        outcome=ExecutiveOutcome.CONTINUE_ACTIVITY,
        intents=(ExecutiveIntent("plan", kind, "正規計画文脈が必要", payload),),
    )
    captured = bound.requirements_owner.capture(replace(snapshot(), requirements_generation=None))
    result = bound.requirements_owner.derive(captured, proposed)
    assert result.failure is not None
    expected = (
        RequirementsFailureCode.SCOPE_UNAVAILABLE
        if kind is ExecutiveIntentKind.PLAN_EXECUTION
        else RequirementsFailureCode.CONTEXT_UNAVAILABLE
    )
    assert result.failure.code is expected and not result.values
    bound.close()


def test_factory_uses_no_test_configuration_authority() -> None:
    import ast
    from pathlib import Path

    for path in ("app/config/executive.py", "app/composition/executive_configuration.py"):
        tree = ast.parse(Path(path).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("tests")
            elif isinstance(node, ast.Import):
                assert all(not alias.name.startswith("tests") for alias in node.names)
