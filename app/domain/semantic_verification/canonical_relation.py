from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from typing import cast

from app.domain.contracts.common import JsonValue
from app.domain.llm import LLMRoleRequest, LLMRoleResult, StructuredPayload
from app.usecases.ports.llm import LLMRolePort

from .authority import SemanticVerificationAuthority
from .canonical_speech_act import augment_relation_instructions
from .contracts import (
    BlindUnitAccountingRelation,
    SemanticVerificationContextSnapshot,
    SemanticVerificationError,
    SemanticVerificationFailureCode,
)
from .schemas import relation_instructions as _legacy_relation_instructions
from .schemas import relation_output_schema as _legacy_relation_output_schema
from .verifier import (
    RELATION_ROLE_ID,
    SemanticVerificationLiveStatePort,
    SemanticVerificationPolicy,
    SemanticVerificationRun,
)
from .verifier import SemanticVerifier as _LegacySemanticVerifier

_SUPPORT_FIELD = "supporting_blind_unit_ids"
_EVIDENCE_FIELD = "evidence_refs"
_DERIVED_PROPOSITION_FIELDS = frozenset({_SUPPORT_FIELD, _EVIDENCE_FIELD})


def relation_output_schema() -> dict[str, object]:
    """Role B Provider schemaからRuntime導出可能なgrounding fieldを除く。"""

    schema = deepcopy(_legacy_relation_output_schema())
    properties = cast(dict[str, object], schema["properties"])
    observations = cast(dict[str, object], properties["proposition_observations"])
    observation = cast(dict[str, object], observations["items"])
    required = cast(list[str], observation["required"])
    observation["required"] = [
        item for item in required if item not in _DERIVED_PROPOSITION_FIELDS
    ]
    observation_properties = cast(dict[str, object], observation["properties"])
    for field in _DERIVED_PROPOSITION_FIELDS:
        observation_properties.pop(field, None)
    return schema


def relation_instructions() -> str:
    """Role Bへsupport edge・evidence・speech-actのcanonical境界を明示する。"""

    legacy = _legacy_relation_instructions()
    old = """ENTAILED relationはactual segmentのexact quote evidenceと、
その意味を担うblind unit IDを示してください。
SUPPORTED_BY_PLAN accountingは、対応proposition側も同じblind unitをsupportとして
ENTAILEDしている場合だけ使用してください。"""
    new = """Plan propositionとblind unitのsupport対応はblind_unit_accountingだけを正本として出力してください。
proposition_observations側へsupport IDやevidence_refsを重複出力してはいけません。
proposition grounding evidenceは、先行確定済みBlindUtteranceObservationのsupport対象unitから
Runtimeが決定論的に導出します。Role Bが別quoteを再生成してはいけません。
SUPPORTED_BY_PLANはsemantic groundingを意味し、発話許可を意味しません。
actual unitがどのPlan propositionと意味的に対応するかを表します。
対応するPlan propositionのrelationがENTAILEDまたはCONTRADICTEDの場合に使用してください。
CONTRADICTEDでも同じPlan propositionについて反対・不整合な内容を述べているなら、
そのblind unitをSUPPORTED_BY_PLANへaccountし、UNSUPPORTED_EXTRAへ落としてはいけません。
MISSINGまたはAMBIGUOUS propositionへSUPPORTED_BY_PLAN edgeを付けてはいけません。
Plan propositionがFORBIDDENでもactual utteranceがその禁止命題を実現した場合は、
そのpropositionをENTAILEDとし、対応blind unitをSUPPORTED_BY_PLANへaccountしてください。
FORBIDDENだからという理由だけでUNSUPPORTED_EXTRAへ分類してはいけません。
UNSUPPORTED_EXTRAは対応するPlan proposition自体がないmaterial contentに使用してください。"""
    if old not in legacy:
        raise RuntimeError("legacy relation instructionのsupport contractを更新できません")
    return augment_relation_instructions(legacy.replace(old, new))


def _blind_evidence_by_unit(relation_input: object) -> dict[str, list[object]]:
    if not isinstance(relation_input, Mapping):
        return {}
    blind_value = relation_input.get("blind_observation")
    if not isinstance(blind_value, Mapping):
        return {}
    units_value = blind_value.get("units")
    if not isinstance(units_value, (list, tuple)):
        return {}

    evidence_by_unit: dict[str, list[object]] = {}
    for raw_unit in units_value:
        if not isinstance(raw_unit, Mapping):
            continue
        unit_id = raw_unit.get("unit_id")
        evidence_refs = raw_unit.get("evidence_refs")
        if not isinstance(unit_id, str) or not isinstance(evidence_refs, (list, tuple)):
            continue
        evidence_by_unit[unit_id] = [deepcopy(item) for item in evidence_refs]
    return evidence_by_unit


def _canonicalize_relation_value(
    value: object,
    relation_input: object | None = None,
) -> object:
    """accountingとfixed blind evidenceからproposition groundingを決定論的に導出する。"""

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

    evidence_by_unit = _blind_evidence_by_unit(relation_input)
    normalized_observations: list[object] = []
    for raw_observation in observations_value:
        if not isinstance(raw_observation, Mapping):
            normalized_observations.append(raw_observation)
            continue
        observation = dict(cast(Mapping[str, object], raw_observation))
        proposition_id = observation.get("proposition_id")
        support_ids = (
            list(support_by_proposition.get(proposition_id, ()))
            if isinstance(proposition_id, str)
            else []
        )
        evidence_refs: list[object] = []
        for unit_id in support_ids:
            for evidence_ref in evidence_by_unit.get(unit_id, ()):  # pragma: no branch
                if evidence_ref not in evidence_refs:
                    evidence_refs.append(deepcopy(evidence_ref))
        observation[_SUPPORT_FIELD] = support_ids
        observation[_EVIDENCE_FIELD] = evidence_refs
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
        normalized = _canonicalize_relation_value(
            result.output.value,
            request.input.value,
        )
        return replace(
            result,
            output=StructuredPayload(
                result.output.schema_id,
                cast(JsonValue, normalized),
            ),
        )


class SemanticVerifier(_LegacySemanticVerifier):
    """Role B groundingを単一正本化して既存Authorityへ渡すproduction Verifier。"""

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

    async def verify(
        self,
        snapshot: SemanticVerificationContextSnapshot,
        *,
        blind_observation_id: str,
        relation_observation_id: str,
        semantic_observation_id: str,
        acceptance_id: str,
        created_at: datetime,
    ) -> SemanticVerificationRun:
        try:
            return await super().verify(
                snapshot,
                blind_observation_id=blind_observation_id,
                relation_observation_id=relation_observation_id,
                semantic_observation_id=semantic_observation_id,
                acceptance_id=acceptance_id,
                created_at=created_at,
            )
        except SemanticVerificationError:
            raise
        except ValueError as error:
            raise SemanticVerificationError(
                SemanticVerificationFailureCode.SCHEMA_INVALID,
                f"Semantic Verification candidate contract invalid: {error}",
            ) from error


__all__ = [
    "SemanticVerifier",
    "relation_instructions",
    "relation_output_schema",
]
