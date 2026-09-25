"""供給publicationとProvider資源の境界を検証する。"""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.adapters.llm.appraisal import appraisal_openai_role_config
from app.adapters.llm.openai_responses import OpenAIResponsesModelPolicy, OpenAIResponsesRoleConfig
from app.adapters.llm.s2_production import create_s2_provider_lease
from app.composition.s2_provider import (
    ModelPoliciesPublication,
    RoleConfigPublication,
    resolve_provider_configuration,
)
from app.config.appraisal import load_appraisal_config
from app.config.executive import load_executive_config
from app.config.minimum_brain import load_minimum_brain_config
from app.config.provider_deployment import ProviderSourceReference, load_provider_deployment
from app.config.s2_contracts import S2ConfigurationError
from app.domain.appraisal.deep import descriptor as appraisal_descriptor
from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.executive.deliberator import ExecutivePolicy
from app.domain.executive.deliberator import descriptor as executive_descriptor
from app.domain.input_meaning.interpreter import descriptor as input_descriptor
from app.domain.llm import LLMFailureCode, LLMRoleDescriptor
from tests.adapters.llm.test_openai_responses import make_request
from tests.config.test_provider_deployment import SOURCE, configured_data


def roles() -> tuple[LLMRoleDescriptor, ...]:
    minimum = load_minimum_brain_config(Path("resources/config/v2/minimum_brain.yaml").read_bytes())
    appraisal = load_appraisal_config(Path("resources/config/v2/appraisal.yaml").read_bytes())
    executive = load_executive_config(Path("resources/config/v2/executive.yaml").read_bytes())
    return (
        input_descriptor(minimum.input_meaning_policy),
        appraisal_descriptor(appraisal.appraisal_policy),
        executive_descriptor(ExecutivePolicy(executive.execution, BOUNDS)),
    )


class Source:
    def __init__(self) -> None:
        self.roles = {role.role_id: role for role in roles()}
        self.bad = ""
        self.calls = 0

    def resolve_model_policies(
        self, role_id: str, ref: ProviderSourceReference
    ) -> ModelPoliciesPublication:
        role = self.roles[role_id]
        policy = role.default_execution_policy
        self.calls += 1
        mapping = OpenAIResponsesModelPolicy(
            "test.deployment.mapping",
            1,
            "test-provider-model",
            {policy.reasoning_effort: "test-effort"},
        )
        if self.bad == "updated" and self.calls > 3:
            mapping = replace(mapping, mapping_revision=2)
        if self.bad == "output-limit":
            mapping = replace(mapping, provider_max_output_tokens=1)
        if self.bad == "ref":
            ref = replace(ref, revision=2)
        return ModelPoliciesPublication(ref, {policy.model_class: mapping})

    def resolve_role_config(
        self, role_id: str, ref: ProviderSourceReference, policies: Any
    ) -> RoleConfigPublication:
        role = self.roles[role_id]
        if role_id == "subjective_appraisal":
            config = appraisal_openai_role_config(policies)
        else:
            config = OpenAIResponsesRoleConfig(
                role_id,
                policies,
                role.input_schema_id,
                role.output_schema_id,
                role_id,
                {"type": "object"},
                role.responsibility,
                role.failure_policy,
            )
        if self.bad == "instructions":
            config = replace(config, instructions="不一致")
        if self.bad == "schema-id":
            config = replace(config, output_schema_id="wrong")
        if self.bad == "format":
            config = replace(config, provider_output_format_name="duplicate")
        return RoleConfigPublication(ref, config)


def test_configured_publication_matches_all_owner_roles() -> None:
    manifest = load_provider_deployment(yaml.safe_dump(configured_data()))
    source = Source()
    configs, bindings = resolve_provider_configuration(manifest, roles(), source)
    assert len(configs) == len(bindings) == 3
    assert source.calls == 6
    assert all(binding.mappings and binding.mapping_ref for binding in bindings)
    assert configs[1] == appraisal_openai_role_config(configs[1].model_policies)


@pytest.mark.parametrize(
    "bad", ["instructions", "schema-id", "format", "ref", "updated", "missing", "output-limit"]
)
def test_invalid_or_changing_publication_fails_closed(bad: str) -> None:
    source = Source()
    source.bad = bad
    manifest = load_provider_deployment(yaml.safe_dump(configured_data()))
    with pytest.raises(S2ConfigurationError, match="PROVIDER_MAPPING_FAILED"):
        resolve_provider_configuration(manifest, roles(), None if bad == "missing" else source)


def test_publication_does_not_share_mutable_schema() -> None:
    source = Source()
    ref = ProviderSourceReference("source", "mapping", 1)
    models = source.resolve_model_policies("input_meaning", ref)
    publication = source.resolve_role_config("input_meaning", ref, models.policies)
    config = publication.config
    assert isinstance(config.output_json_schema, dict)
    config.output_json_schema["type"] = "null"
    assert publication.config.output_json_schema["type"] == "object"


@pytest.mark.asyncio
async def test_unconfigured_uses_real_port_without_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("未構成なのにSDKを生成しました")

    monkeypatch.setattr("openai.AsyncOpenAI", forbidden)
    registered = roles()
    configs, bindings = resolve_provider_configuration(
        load_provider_deployment(SOURCE), registered, None
    )
    lease = await create_s2_provider_lease(registered, configs, bindings, "unconfigured")
    for role in registered:
        request = replace(
            make_request(role.role_id, input_schema_id=role.input_schema_id),
            execution_policy=role.default_execution_policy,
        )
        result = await lease.port.invoke(request)
        assert result.failure is not None
        assert result.failure.code is LLMFailureCode.PROVIDER_UNAVAILABLE
        assert result.attempt_count == 0
    await lease.release()
    await lease.release()


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [False, True])
async def test_credential_manifest_mismatch(
    monkeypatch: pytest.MonkeyPatch, configured: bool
) -> None:
    if configured:
        monkeypatch.setenv("OPENAI_API_KEY", "isolated-test-value")
    else:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(S2ConfigurationError, match="PROVIDER_MAPPING_FAILED"):
        await create_s2_provider_lease(
            roles(), (), (), "unconfigured" if configured else "configured"
        )


@pytest.mark.asyncio
async def test_configured_lease_closes_owned_client_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "isolated-test-value")

    class Client:
        calls = 0
        responses = object()

        async def close(self) -> None:
            self.calls += 1

    client = Client()
    monkeypatch.setattr("openai.AsyncOpenAI", lambda: client)
    configs, bindings = resolve_provider_configuration(
        load_provider_deployment(yaml.safe_dump(configured_data())), roles(), Source()
    )
    lease = await create_s2_provider_lease(roles(), configs, bindings, "configured")
    await lease.release()
    await lease.release()
    assert client.calls == 1
