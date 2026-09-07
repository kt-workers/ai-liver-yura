from dataclasses import replace

import pytest

from app.adapters.tts.contracts import TTSSynthesisStatus
from tests.adapters.tts.test_provider import FakeTTS, _adapter, _policy, _request, _response


@pytest.mark.asyncio
async def test_provider_config_revision_is_independent_from_operational_policy_revision() -> None:
    policies = _policy(max_attempts=1)
    request = replace(
        _request(bundle=policies),
        provider_config_revision=99,
    )
    result = await _adapter(
        FakeTTS([_response()]),
        policies,
        now=lambda: request.created_at,
    ).synthesize(request)

    assert result.status is TTSSynthesisStatus.SUCCEEDED
    assert result.artifact is not None
    assert result.artifact.provider_config_revision == 99
    assert policies.operational.policy_revision != request.provider_config_revision
