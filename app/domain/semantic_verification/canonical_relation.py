from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from typing import cast

from app.domain.contracts.common import JsonValue
from app.domain.llm import LLMRoleRequest, LLMRoleResult, StructuredPayload
from app.usecases.ports.llm import LLMRolePort

from .authority import SemanticVerificationAuthority
from .contracts import BlindUnitAccountingRelation
from .schemas import relation_instructions as _legacy_relation_instructions
from .schemas import relation_output_schema as _legacy_relation_output_schema
from .verifier import (
    RELATION_ROLE_ID,
    SemanticVerificationLiveStatePort,
    SemanticVerificationPolicy,
)
from .verifier import SemanticVerifier as _LegacySemanticVerifier

_SUPPORT_FIELD = "supporting_blind_unit_ids"


def relation_output_schema() -> dict[str, object]:
    """Role B Provider schemaから重複support edgeを除いたproduction schema。"""

    schema = deepcopy(_legacy_relation_output_schema())
    properties = cast(dict[str, object], schema["properties"])
    observations = cast(dict[str, object], properties["proposition_observations"])
    observation = cast(dict[str, object], observations["items"])
    required = cast(list[str], observation["required"])
    observation["required"] = [item for item in required if item != _SUPPORT_FIELD]
    observation_properties = cast(dict[str, object], observation["properties"])
    observation_properties.pop(_SUPPORT_FIELD, None)
    return schema


def relation_instructions() -> str:
    """Role Bへsupport edgeの単一正本を明示するproduction instruction。"""

    legacy = _legacy_relation_instructions()
    old = """ENTAILED relationはactual segmentのexact quote evidenceと、
その意味を担うblind unit IDを示してください。
SUPPORTED_BY_PLAN accountingは、対応proposition側も同じblind unitをsupportとして
ENTAILEDしている場合だけ使用してください。"""
    new = """ENTAILED relationにはactual segmentのexact quote evidenceを示してください。
Plan propositionとblind unitのsupport対応はblind_unit_accountingだけを正本として出力してください。
proposition_observations側へ同じsupport IDを重複出力してはいけません。
SUPPORTED_BY_PLAN accountingは、対応するPlan propositionがENTAILEDの場合だけ使用してください。"""
    if old not in legacy:
        raise RuntimeError("legacy relation instructionのsupport contractを更新できません")
    return legacy.replace(old, new)


def _canonicalize_relation_value(value: object) -> object:
    """accountingを唯一のsupport edgeとして逆向きsupportを決定論的に導出する。"""

    if not isinstance(value, Mapping):
        return value
    candidate = dict(cast(Mapping[str, object], value))
    accounting_value = candidate.get("blind_unit_accounting")
    observations_value = candidate.get("proposition_observations")
    if not isinstance(accounting_value, (list, tuple)) or not isinstance(
        observations_value, (list, tuple)
    ):
        return value

    support_by_proposition: dict[str, list[str]] = {}
    for raw_accounting in accounting_value:
        if not isinstance(raw_accounting, Mapping):
            continue
        accounting = cast(Mapping[str, object], raw_accounting)
        if accounting.get("relation") != BlindUnitAccountingRelation.SUPPORTED_BY_PLAN.value:
            continue
        blind_unit_id = accounting.get("blind_unit_id")
        proposition_ids = accounting.get("proposition_ids")
        if not isinstance(blind_unit_id, str) or not isinstance(
            proposition_ids, (list, tuple)
        ):
            continue
        for proposition_id in proposition_ids:
            if isinstance(proposition_id, str):
                support_by_proposition.setdefault(proposition_id, []).append(
                    blind_unit_id
                )

    normalized_observations: list[object] = []
    for raw_observation in observations_value:
        if not isinstance(raw_observation, Mapping):
            normalized_observations.append(raw_observation)
            continue
        observation = dict(cast(Mapping[str, object], raw_observation))
        proposition_id = observation.get("proposition_id")
        observation[_SUPPORT_FIELD] = (
            list(support_by_proposition.get(proposition_id, ()))
            if isinstance(proposition_id, str)
            else []
        )
        normalized_observations.append(observation)
    candidate["proposition_observations"] = normalized_observations
    return candidate


class _CanonicalRelationOutputPort:
    def __init__(self, inner: LLMRolePort) -> None:
        self._inner = inner

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        result = await self._inner.invoke(request)
        if request.role_id != RELATION_ROLE_ID or result.output is None:
            return result
        normalized = _canonicalize_relation_value(result.output.value)
        return replace(
            result,
            output=StructuredPayload(
                result.output.schema_id,
                cast(JsonValue, normalized),
            ),
        )


class SemanticVerifier(_LegacySemanticVerifier):
    """Role B support edgeを単一正本化して既存Authorityへ渡すproduction Verifier。"""

    def __init__(
        self,
        port: LLMRolePort,
        live_state: SemanticVerificationLiveStatePort,
        authority: SemanticVerificationAuthority,
        policy: SemanticVerificationPolicy,
    ) -> None:
        super().__init__(
            _CanonicalRelationOutputPort(port),
            live_state,
            authority,
            policy,
        )


__all__ = [
    "SemanticVerifier",
    "relation_instructions",
    "relation_output_schema",
]
