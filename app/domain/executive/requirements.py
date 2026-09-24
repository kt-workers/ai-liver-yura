"""実行判断の必須要件と、公開世代の更新・最終確定の同期境界。"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import InitVar, dataclass, field, replace
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import NoReturn, TypeAlias

from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts import CapabilityRequirement
from app.domain.contracts.common import JsonValue, freeze_json, require_identifier, require_revision
from app.domain.contracts.finalization import (
    AuthorityFinalizationParticipant,
    AuthorityGenerationToken,
    authority_mutation,
)
from app.domain.plan_execution.contracts import PlanExecutionScope
from app.domain.plan_execution.progress_contracts import PlanProgressContext

from .contracts import (
    ActivityIntentPayload,
    AuthoritativeIntentRequirements,
    ExecutiveCommitState,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
    ExecutiveIntent,
    ExecutiveIntentKind,
    ExecutivePreconditionRequirement,
    IntentPayload,
    PlanExecutionIntentPayload,
    PlanProgressIntentPayload,
)
from .direct_activity_requirements import (
    DirectActivityRequirementSource,
    DirectActivityRequirementSourceSpec,
    DirectActivityRequirementsOwner,
)


class RequirementsFailureCode(str, Enum):
    POLICY_UNREGISTERED = "policy_unregistered"
    RULE_UNREGISTERED = "rule_unregistered"
    AMBIGUOUS_RULE = "ambiguous_rule"
    UNSUPPORTED_INTENT = "unsupported_intent"
    SOURCE_UNAVAILABLE = "source_unavailable"
    STALE_POLICY = "stale_policy"
    STALE_SOURCE = "stale_source"
    INVALID_PROJECTION = "invalid_projection"
    SCOPE_UNAVAILABLE = "scope_unavailable"
    STALE_SCOPE = "stale_scope"
    CONTEXT_UNAVAILABLE = "context_unavailable"
    STALE_CONTEXT = "stale_context"
    CANDIDATE_MISMATCH = "candidate_mismatch"


@dataclass(frozen=True, slots=True)
class RequirementsFailure:
    code: RequirementsFailureCode


class RequirementsRejected(ValueError):
    """既存の例外境界でも必須要件の失敗分類を保持する。"""

    def __init__(self, code: RequirementsFailureCode) -> None:
        self.failure = RequirementsFailure(code)
        super().__init__(f"必須要件を確定できません（{code.value}）")


def reject(code: RequirementsFailureCode) -> NoReturn:
    raise RequirementsRejected(code)


def typed_json(value: JsonValue) -> object:
    """真偽値と数値を区別し、配列順を保持して比較する。"""
    if isinstance(value, Mapping):
        return ("object", tuple(sorted((k, typed_json(v)) for k, v in value.items())))
    if isinstance(value, tuple):
        return ("array", tuple(typed_json(v) for v in value))
    return (type(value).__name__, value)


class RequirementMode(str, Enum):
    CONSTANT = "constant"
    UPSTREAM = "upstream"
    PLAN_SCOPE = "plan_scope"


class RequirementSelectorField(str, Enum):
    KIND = "kind"
    SEMANTIC_GOAL = "semantic_goal_ref"
    MOTION_GOAL = "motion_goal_ref"
    ACTIVITY_TYPE = "activity_type"
    ATTENTION_MODE = "mode"


_SELECTOR_FIELDS = {
    ExecutiveIntentKind.SPEECH: RequirementSelectorField.SEMANTIC_GOAL,
    ExecutiveIntentKind.BODY: RequirementSelectorField.MOTION_GOAL,
    ExecutiveIntentKind.ACTIVITY: RequirementSelectorField.ACTIVITY_TYPE,
    ExecutiveIntentKind.ATTENTION: RequirementSelectorField.ATTENTION_MODE,
}


@dataclass(frozen=True, slots=True)
class RequirementSelector:
    field: RequirementSelectorField = RequirementSelectorField.KIND
    value: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.field, RequirementSelectorField):
            reject(RequirementsFailureCode.UNSUPPORTED_INTENT)
        if self.field is RequirementSelectorField.KIND:
            if self.value is not None:
                reject(RequirementsFailureCode.UNSUPPORTED_INTENT)
        elif not isinstance(self.value, str) or not self.value.strip():
            reject(RequirementsFailureCode.UNSUPPORTED_INTENT)


@dataclass(frozen=True, slots=True)
class RequirementSourceSpec:
    owner_id: str
    contract_id: str
    reference_field: str

    def __post_init__(self) -> None:
        for name in ("owner_id", "contract_id", "reference_field"):
            require_identifier(getattr(self, name), name)


_SOURCE_FIELDS = {
    ExecutiveIntentKind.SPEECH: ("semantic_goal_ref", "target_ref", "constraint_refs"),
    ExecutiveIntentKind.BODY: ("motion_goal_ref", "target_ref", "constraint_refs"),
    ExecutiveIntentKind.ACTIVITY: ("activity_type", "target_ref", "constraint_refs"),
    ExecutiveIntentKind.ATTENTION: ("target_ref", "constraint_refs"),
    ExecutiveIntentKind.PLAN_PROGRESS: ("context_ref",),
}


def _requirements_key(
    capabilities: tuple[CapabilityRequirement, ...],
    preconditions: tuple[ExecutivePreconditionRequirement, ...],
) -> object:
    if any(not isinstance(x, CapabilityRequirement) for x in capabilities) or any(
        not isinstance(x, ExecutivePreconditionRequirement) for x in preconditions
    ):
        reject(RequirementsFailureCode.INVALID_PROJECTION)
    cap_keys = [(x.capability_type, x.operation) for x in capabilities]
    ids = [x.precondition_id for x in preconditions]
    if len(set(cap_keys)) != len(cap_keys) or len(set(ids)) != len(ids):
        reject(RequirementsFailureCode.INVALID_PROJECTION)
    if any(type(x.allow_degraded) is not bool for x in capabilities):
        reject(RequirementsFailureCode.INVALID_PROJECTION)
    return (
        tuple(sorted((x.capability_type, x.operation, x.allow_degraded) for x in capabilities)),
        tuple(sorted((x.precondition_id, typed_json(x.expected)) for x in preconditions)),
    )


@dataclass(frozen=True, slots=True)
class ExecutiveIntentRequirementRule:
    rule_id: str
    revision: int
    policy_id: str
    policy_revision: int
    intent_kind: ExecutiveIntentKind
    selector: RequirementSelector
    mode: RequirementMode
    capabilities: tuple[CapabilityRequirement, ...] = ()
    preconditions: tuple[ExecutivePreconditionRequirement, ...] = ()
    source: RequirementSourceSpec | DirectActivityRequirementSourceSpec | None = None

    def __post_init__(self) -> None:
        require_identifier(self.rule_id, "rule_id")
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.revision, "revision")
        require_revision(self.policy_revision, "policy_revision")
        if (
            not isinstance(self.intent_kind, ExecutiveIntentKind)
            or not isinstance(self.selector, RequirementSelector)
            or not isinstance(self.mode, RequirementMode)
        ):
            reject(RequirementsFailureCode.UNSUPPORTED_INTENT)
        if self.selector.field is not RequirementSelectorField.KIND and (
            _SELECTOR_FIELDS.get(self.intent_kind) is not self.selector.field
        ):
            reject(RequirementsFailureCode.UNSUPPORTED_INTENT)
        if (self.intent_kind is ExecutiveIntentKind.PLAN_EXECUTION) != (
            self.mode is RequirementMode.PLAN_SCOPE
        ):
            reject(RequirementsFailureCode.UNSUPPORTED_INTENT)
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "preconditions", tuple(self.preconditions))
        if any(not isinstance(x, CapabilityRequirement) for x in self.capabilities) or any(
            not isinstance(x, ExecutivePreconditionRequirement) for x in self.preconditions
        ):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        _requirements_key(self.capabilities, self.preconditions)
        if self.mode is RequirementMode.UPSTREAM:
            if isinstance(self.source, DirectActivityRequirementSourceSpec):
                if self.intent_kind is not ExecutiveIntentKind.ACTIVITY:
                    reject(RequirementsFailureCode.UNSUPPORTED_INTENT)
            elif not isinstance(self.source, RequirementSourceSpec) or (
                self.source.reference_field not in _SOURCE_FIELDS.get(self.intent_kind, ())
            ):
                reject(RequirementsFailureCode.UNSUPPORTED_INTENT)
        elif self.source is not None:
            reject(RequirementsFailureCode.UNSUPPORTED_INTENT)
        if self.mode is not RequirementMode.CONSTANT and (self.capabilities or self.preconditions):
            reject(RequirementsFailureCode.INVALID_PROJECTION)

    def matches(self, intent: ExecutiveIntent) -> bool:
        return self.intent_kind is intent.kind and (
            self.selector.field is RequirementSelectorField.KIND
            or getattr(intent.payload, self.selector.field.value, None) == self.selector.value
        )


@dataclass(frozen=True, slots=True)
class ExecutiveIntentRequirementsPolicy:
    policy_id: str
    revision: int
    rules: tuple[ExecutiveIntentRequirementRule, ...]

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "policy_id")
        require_revision(self.revision, "revision")
        object.__setattr__(self, "rules", tuple(self.rules))
        if any(not isinstance(x, ExecutiveIntentRequirementRule) for x in self.rules):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        if len({x.rule_id for x in self.rules}) != len(self.rules) or any(
            x.policy_id != self.policy_id or x.policy_revision != self.revision for x in self.rules
        ):
            reject(RequirementsFailureCode.INVALID_PROJECTION)


@dataclass(frozen=True, slots=True)
class UpstreamRequirementRecord:
    owner_id: str
    contract_id: str
    record_id: str
    revision: int
    reference: str
    intent_kind: ExecutiveIntentKind
    payload: IntentPayload
    capabilities: tuple[CapabilityRequirement, ...]
    preconditions: tuple[ExecutivePreconditionRequirement, ...]

    def __post_init__(self) -> None:
        for name in ("owner_id", "contract_id", "record_id", "reference"):
            require_identifier(getattr(self, name), name)
        require_revision(self.revision, "revision")
        try:
            ExecutiveIntent("upstream-type-check", self.intent_kind, "上流の型照合", self.payload)
        except ValueError:
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "preconditions", tuple(self.preconditions))
        _requirements_key(self.capabilities, self.preconditions)


SourceValue: TypeAlias = (
    UpstreamRequirementRecord
    | PlanExecutionScope
    | PlanProgressContext
    | DirectActivityRequirementSource
)
_CAPTURE_PROOF = object()


@dataclass(frozen=True, slots=True)
class RequirementSourcePublication:
    """この公開境界が現在値を所有する型付き出典。外部の読取値は直接受理しない。"""

    source_id: str
    revision: int
    value: SourceValue
    tokens: tuple[AuthorityGenerationToken, ...]

    def __post_init__(self) -> None:
        require_identifier(self.source_id, "source_id")
        require_revision(self.revision, "revision")
        object.__setattr__(self, "tokens", tuple(self.tokens))
        if not self.tokens or any(not isinstance(t, AuthorityGenerationToken) for t in self.tokens):
            reject(RequirementsFailureCode.SOURCE_UNAVAILABLE)
        if not isinstance(
            self.value,
            (
                UpstreamRequirementRecord,
                PlanExecutionScope,
                PlanProgressContext,
                DirectActivityRequirementSource,
            ),
        ):
            reject(RequirementsFailureCode.INVALID_PROJECTION)

        if isinstance(self.value, DirectActivityRequirementSource) and (
            self.source_id != self.value.record.record_id
            or self.revision != self.value.record.revision
            or self.tokens != self.value.tokens
        ):
            reject(RequirementsFailureCode.INVALID_PROJECTION)


@dataclass(frozen=True, slots=True)
class RequirementsGeneration:
    owner: ExecutiveRequirementsOwner
    policy: ExecutiveIntentRequirementsPolicy
    sources: tuple[RequirementSourcePublication, ...]
    serial: int
    token: AuthorityGenerationToken
    base_generation: RequirementsGeneration | None = field(default=None, repr=False)
    _issued: RequirementsGeneration | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _proof: InitVar[object | None] = None

    def __post_init__(self, _proof: object | None) -> None:
        if self.base_generation is not None:
            if _proof is not _CAPTURE_PROOF or self.base_generation.base_generation is not None:
                reject(RequirementsFailureCode.INVALID_PROJECTION)
            object.__setattr__(self, "_issued", self)

    def to_dict(self) -> dict[str, object]:
        return {
            "policy": project(self.policy),
            "sources": project(self.sources),
            "serial": self.serial,
        }


@dataclass(frozen=True, slots=True)
class RequirementProvenance:
    policy_id: str
    policy_revision: int
    rule_id: str
    rule_revision: int
    selector: RequirementSelector
    sources: tuple[RequirementSourcePublication, ...]
    route_id: str | None = None


@dataclass(frozen=True, slots=True)
class DerivedIntentRequirements:
    requirements: AuthoritativeIntentRequirements
    provenance: RequirementProvenance

    def to_dict(self) -> dict[str, object]:
        return {"requirements": project(self.requirements), "provenance": project(self.provenance)}


@dataclass(frozen=True, slots=True)
class RequirementsDerivationResult:
    values: tuple[DerivedIntentRequirements, ...] = ()
    failure: RequirementsFailure | None = None


class ExecutiveRequirementsOwner:
    """要件の公開と判断確定で共有する短い同期境界を所有する。"""

    def __init__(
        self,
        bounds: BrainOperationalBoundsPolicy,
        *,
        direct_routes: Mapping[str, Mapping[str, DirectActivityRequirementsOwner]] | None = None,
    ) -> None:
        self._bounds = bounds.executive
        routes = {key: dict(value) for key, value in (direct_routes or {}).items()}
        owners = [owner for route in routes.values() for owner in route.values()]
        if max(len(routes), len(owners)) > self._bounds.max_fact_refs or (
            len({owner.owner_id for owner in owners}) != len(owners)
        ):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        for route_id, route in routes.items():
            require_identifier(route_id, "route_id")
            for binding_id, owner in route.items():
                if (
                    not isinstance(owner, DirectActivityRequirementsOwner)
                    or binding_id != owner.binding.binding_id
                ):
                    reject(RequirementsFailureCode.INVALID_PROJECTION)
        if len({o.binding.binding_id for o in owners}) != len(owners):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        self._direct_routes = MappingProxyType({k: MappingProxyType(v) for k, v in routes.items()})
        self._participant = AuthorityFinalizationParticipant(self, "ExecutiveRequirementsOwner", 80)
        self._lock = self._participant
        self._generation: RequirementsGeneration | None = None
        self._rule_history: dict[str, ExecutiveIntentRequirementRule] = {}

    @property
    def finalization_participant(self) -> AuthorityFinalizationParticipant:
        """要件公開と最終確定に共通する正規の同期境界。"""
        return self._participant

    @authority_mutation
    def publish(
        self,
        policy: ExecutiveIntentRequirementsPolicy,
        sources: tuple[RequirementSourcePublication, ...] = (),
    ) -> RequirementsGeneration:
        """正規の現在出典を一括公開する。別所有者の読取やコールバックは実行しない。"""
        sources = tuple(sources)
        if not isinstance(policy, ExecutiveIntentRequirementsPolicy) or any(
            not isinstance(s, RequirementSourcePublication) for s in sources
        ):
            raise RequirementsRejected(RequirementsFailureCode.INVALID_PROJECTION)
        if len(policy.rules) + len(sources) > self._bounds.max_fact_refs or len(
            {s.source_id for s in sources}
        ) != len(sources):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        if any(isinstance(source.value, DirectActivityRequirementSource) for source in sources):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        for rule in policy.rules:
            if (
                isinstance(rule.source, DirectActivityRequirementSourceSpec)
                and rule.source.route_id not in self._direct_routes
            ):
                reject(RequirementsFailureCode.SOURCE_UNAVAILABLE)
            if len(rule.capabilities) + len(rule.preconditions) > self._bounds.max_refs_per_intent:
                reject(RequirementsFailureCode.INVALID_PROJECTION)
        for value in (*policy.rules, *sources):
            if (
                len(json.dumps(project(value), ensure_ascii=False, allow_nan=False).encode("utf-8"))
                > self._bounds.max_fact_payload_json_bytes
            ):
                reject(RequirementsFailureCode.INVALID_PROJECTION)
        with self._lock:
            previous = self._generation
            if previous is not None:
                if (
                    policy.policy_id != previous.policy.policy_id
                    or policy.revision < previous.policy.revision
                ):
                    reject(RequirementsFailureCode.STALE_POLICY)
                if policy.revision == previous.policy.revision and not _same_public_value(
                    policy, previous.policy
                ):
                    reject(RequirementsFailureCode.STALE_POLICY)
                old_rules = self._rule_history
                if (
                    len(old_rules.keys() | {r.rule_id for r in policy.rules})
                    > self._bounds.max_fact_refs
                ):
                    reject(RequirementsFailureCode.INVALID_PROJECTION)
                for rule in policy.rules:
                    old = old_rules.get(rule.rule_id)
                    if old is not None and (
                        rule.revision < old.revision
                        or (
                            rule.revision == old.revision
                            and not _same_public_value(
                                replace(rule, policy_revision=old.policy_revision), old
                            )
                        )
                    ):
                        reject(RequirementsFailureCode.STALE_POLICY)
                old_sources = {s.source_id: s for s in previous.sources}
                for source in sources:
                    old_source = old_sources.get(source.source_id)
                    if old_source is not None and (
                        source.revision < old_source.revision
                        or (source.revision == old_source.revision and source is not old_source)
                    ):
                        reject(RequirementsFailureCode.STALE_SOURCE)
                if (
                    _same_public_value(policy, previous.policy)
                    and all(a is b for a, b in zip(sources, previous.sources, strict=False))
                    and len(sources) == len(previous.sources)
                ):
                    generation = replace(previous, token=self._participant.token())
                    self._generation = generation
                    return generation
            generation = RequirementsGeneration(
                self,
                policy,
                sources,
                0 if previous is None else previous.serial + 1,
                self._participant.token(),
            )
            self._rule_history.update((r.rule_id, r) for r in policy.rules)
            self._generation = generation
            return generation

    def current_generation(self) -> RequirementsGeneration:
        """現在の論理内容と機械的世代を同じ同期境界で読み取る。"""
        with self._lock:
            if self._generation is None:
                raise RequirementsRejected(RequirementsFailureCode.POLICY_UNREGISTERED)
            token = self._participant.token()
            if self._generation.token != token:
                self._generation = replace(self._generation, token=token)
            return self._generation

    def capture(self, snapshot: ExecutiveContextSnapshot) -> ExecutiveContextSnapshot:
        base = self.current_generation()
        bindings = snapshot.activity_bindings
        if len(bindings) > self._bounds.max_fact_refs or len(
            {b.value.binding_id for b in bindings}
        ) != len(bindings):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        sources = list(base.sources)
        for binding in bindings:
            owners = [
                route[binding.value.binding_id]
                for route in self._direct_routes.values()
                if binding.value.binding_id in route
            ]
            if len(owners) != 1:
                reject(RequirementsFailureCode.SOURCE_UNAVAILABLE)
            source = owners[0].capture()
            assert isinstance(source.value, DirectActivityRequirementSource)
            if source.value.binding_publication != binding:
                reject(RequirementsFailureCode.STALE_SOURCE)
            sources.append(source)
        if len(base.policy.rules) + len(sources) > self._bounds.max_fact_refs or len(
            {s.source_id for s in sources}
        ) != len(sources):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        if not bindings:
            return replace(snapshot, requirements_generation=base)
        generation = RequirementsGeneration(
            self, base.policy, tuple(sources), base.serial, base.token, base, _proof=_CAPTURE_PROOF
        )
        self.check_generation(generation)
        return replace(snapshot, requirements_generation=generation)

    def check_generation(self, generation: RequirementsGeneration) -> None:
        """共有世代と正規request captureの現在性を検査する。"""
        with self._lock:
            self._check(generation)

    def require_binding_owners(self, bindings: tuple[object, ...]) -> None:
        """構成に使うbindingが登録済みの同じ実Ownerか照合する。"""
        configured = {
            id(o.binding) for route in self._direct_routes.values() for o in route.values()
        }
        if any(id(binding) not in configured for binding in bindings):
            reject(RequirementsFailureCode.SOURCE_UNAVAILABLE)

    def refresh_selected(self, values: tuple[DerivedIntentRequirements, ...]) -> None:
        """選択された出典だけを実Ownerから読み直し、旧値と照合する。"""
        for value in values:
            for source in value.provenance.sources:
                if not isinstance(source.value, DirectActivityRequirementSource):
                    continue
                route: Mapping[str, DirectActivityRequirementsOwner] = self._direct_routes.get(
                    value.provenance.route_id or "", {}
                )
                owner = route.get(source.value.record.binding_ref)
                if owner is None:
                    reject(RequirementsFailureCode.SOURCE_UNAVAILABLE)
                live = owner.capture()
                binding = owner.binding.capture()
                if live != source or binding != source.value.binding_publication:
                    reject(RequirementsFailureCode.STALE_SOURCE)

    def _check(self, generation: RequirementsGeneration) -> None:
        current = self._generation
        if current is None:
            reject(RequirementsFailureCode.POLICY_UNREGISTERED)
        elif (
            generation.owner is not self
            or (
                current is not generation
                and (
                    generation.base_generation is not current
                    or generation._issued is not generation
                    or generation.policy is not current.policy
                    or generation.serial != current.serial
                )
            )
            or generation.token != self._participant.token()
        ):
            if not _same_public_value(current.policy, generation.policy):
                reject(RequirementsFailureCode.STALE_POLICY)
            reject(RequirementsFailureCode.STALE_SOURCE)

    @contextmanager
    def final_guard(self, generation: RequirementsGeneration) -> Iterator[None]:
        with self._lock:
            self._check(generation)
            yield

    def derive(
        self, snapshot: ExecutiveContextSnapshot, candidate: ExecutiveDecisionCandidate
    ) -> RequirementsDerivationResult:
        generation = snapshot.requirements_generation
        if generation is None:
            return RequirementsDerivationResult(
                failure=RequirementsFailure(RequirementsFailureCode.POLICY_UNREGISTERED)
            )
        try:
            with self.final_guard(generation):
                values = self._derive(generation, candidate, snapshot)
            self.refresh_selected(values)
            return RequirementsDerivationResult(values)
        except RequirementsRejected as exc:
            return RequirementsDerivationResult(failure=exc.failure)

    def prepare(
        self,
        snapshot: ExecutiveContextSnapshot,
        candidate: ExecutiveDecisionCandidate,
        current: ExecutiveCommitState,
    ) -> ExecutiveCommitState:
        result = self.derive(snapshot, candidate)
        if result.failure is not None:
            raise RequirementsRejected(result.failure.code)
        return replace(
            current,
            requirements=tuple(x.requirements for x in result.values),
            requirement_derivations=result.values,
        )

    def _derive(
        self,
        generation: RequirementsGeneration,
        candidate: ExecutiveDecisionCandidate,
        snapshot: ExecutiveContextSnapshot,
    ) -> tuple[DerivedIntentRequirements, ...]:
        if len(candidate.intents) > self._bounds.max_candidate_intents:
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        values = []
        for intent in candidate.intents:
            rules = [rule for rule in generation.policy.rules if rule.matches(intent)]
            if len(rules) != 1:
                raise RequirementsRejected(
                    RequirementsFailureCode.RULE_UNREGISTERED
                    if not rules
                    else RequirementsFailureCode.AMBIGUOUS_RULE
                )
            rule = rules[0]
            if (
                isinstance(intent.payload, ActivityIntentPayload)
                and intent.payload.binding_ref is not None
                and not isinstance(rule.source, DirectActivityRequirementSourceSpec)
            ):
                reject(RequirementsFailureCode.INVALID_PROJECTION)
            sources: tuple[RequirementSourcePublication, ...] = ()
            capabilities, conditions = rule.capabilities, rule.preconditions
            if isinstance(intent.payload, PlanExecutionIntentPayload):
                found = [
                    s
                    for s in generation.sources
                    if isinstance(s.value, PlanExecutionScope)
                    and s.value.scope_id == intent.payload.scope_ref
                ]
                if len(found) != 1:
                    raise RequirementsRejected(RequirementsFailureCode.SCOPE_UNAVAILABLE)
                scope = found[0].value
                assert isinstance(scope, PlanExecutionScope)
                if not any(
                    typed_json(freeze_json(s.to_dict())) == typed_json(freeze_json(scope.to_dict()))
                    for s in snapshot.plan_scopes
                ):
                    raise RequirementsRejected(RequirementsFailureCode.STALE_SCOPE)
                capabilities, conditions = _project_plan(scope)
                sources = (found[0],)
            elif isinstance(rule.source, DirectActivityRequirementSourceSpec):
                if not isinstance(intent.payload, ActivityIntentPayload):
                    reject(RequirementsFailureCode.INVALID_PROJECTION)
                binding_ref = intent.payload.binding_ref
                route: Mapping[str, DirectActivityRequirementsOwner] = self._direct_routes.get(
                    rule.source.route_id, {}
                )
                owner = route.get(binding_ref or "")
                bindings = [
                    b for b in snapshot.activity_bindings if b.value.binding_id == binding_ref
                ]
                found = [
                    source
                    for source in generation.sources
                    if isinstance(source.value, DirectActivityRequirementSource)
                    and source.value.record.binding_ref == binding_ref
                ]
                if owner is None or len(bindings) != 1 or len(found) != 1:
                    reject(RequirementsFailureCode.SOURCE_UNAVAILABLE)
                direct = found[0].value
                assert isinstance(direct, DirectActivityRequirementSource)
                record = direct.record
                binding = bindings[0]
                if (
                    record.owner_id != owner.owner_id
                    or record.contract_id != rule.source.contract_id
                    or direct.binding_publication != binding
                    or (
                        record.binding_ref,
                        record.binding_revision,
                        record.activity_type,
                        record.target_ref,
                    )
                    != (
                        binding.value.binding_id,
                        binding.value.revision,
                        intent.payload.activity_type,
                        intent.payload.target_ref,
                    )
                    or sum(
                        c.capability_type == binding.value.activity_type
                        and c.operation == binding.value.operation_ref
                        for c in record.capabilities
                    )
                    != 1
                    or direct.tokens[0]._participant is not owner.finalization_participant
                ):
                    reject(RequirementsFailureCode.INVALID_PROJECTION)
                capabilities, conditions = record.capabilities, record.preconditions
                sources = (found[0],)
            elif rule.mode is RequirementMode.UPSTREAM:
                assert isinstance(rule.source, RequirementSourceSpec)
                reference = getattr(intent.payload, rule.source.reference_field, None)
                refs = reference if isinstance(reference, tuple) else (reference,)
                found = [
                    s
                    for s in generation.sources
                    if isinstance(s.value, UpstreamRequirementRecord)
                    and s.value.owner_id == rule.source.owner_id
                    and s.value.contract_id == rule.source.contract_id
                    and s.value.reference in refs
                ]
                if len(found) != 1:
                    raise RequirementsRejected(RequirementsFailureCode.SOURCE_UNAVAILABLE)
                upstream = found[0].value
                assert isinstance(upstream, UpstreamRequirementRecord)
                if upstream.intent_kind is not intent.kind or upstream.payload != intent.payload:
                    reject(RequirementsFailureCode.INVALID_PROJECTION)
                capabilities, conditions = upstream.capabilities, upstream.preconditions
                sources = (found[0],)
            if isinstance(intent.payload, PlanProgressIntentPayload):
                found_context = [
                    s
                    for s in generation.sources
                    if isinstance(s.value, PlanProgressContext)
                    and s.value.context_id == intent.payload.context_ref
                ]
                if len(found_context) != 1:
                    raise RequirementsRejected(RequirementsFailureCode.CONTEXT_UNAVAILABLE)
                context_value = found_context[0].value
                assert isinstance(context_value, PlanProgressContext)
                if not any(
                    typed_json(freeze_json(c.to_dict()))
                    == typed_json(freeze_json(context_value.to_dict()))
                    for c in snapshot.plan_progress_contexts
                ):
                    reject(RequirementsFailureCode.STALE_CONTEXT)
                sources += (found_context[0],)
            if len(capabilities) + len(conditions) > self._bounds.max_refs_per_intent:
                reject(RequirementsFailureCode.INVALID_PROJECTION)
            _requirements_key(capabilities, conditions)
            values.append(
                DerivedIntentRequirements(
                    AuthoritativeIntentRequirements(intent.intent_id, capabilities, conditions),
                    RequirementProvenance(
                        generation.policy.policy_id,
                        generation.policy.revision,
                        rule.rule_id,
                        rule.revision,
                        rule.selector,
                        sources,
                        rule.source.route_id
                        if isinstance(rule.source, DirectActivityRequirementSourceSpec)
                        else None,
                    ),
                )
            )
        return tuple(values)

    def validate_final(
        self,
        snapshot: ExecutiveContextSnapshot,
        candidate: ExecutiveDecisionCandidate,
        current: ExecutiveCommitState,
    ) -> tuple[DerivedIntentRequirements, ...]:
        """呼出し元がfinal_guardを保持する。外部処理を含まない有界の照合。"""
        generation = snapshot.requirements_generation
        assert generation is not None
        self._check(generation)
        return self.validate_captured(snapshot, candidate, current)

    def validate_captured(
        self,
        snapshot: ExecutiveContextSnapshot,
        candidate: ExecutiveDecisionCandidate,
        current: ExecutiveCommitState,
    ) -> tuple[DerivedIntentRequirements, ...]:
        """不変な要求・候補の整合だけを照合し、現在性はFence内で検査する。"""
        generation = snapshot.requirements_generation
        if (
            generation is not None
            and generation.base_generation is not None
            and generation._issued is not generation
        ):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        if generation is None or generation.owner is not self:
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        expected = self._derive(generation, candidate, snapshot)
        if len(current.requirement_derivations) != len(expected):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        if len(current.requirements) != len(expected):
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        live_requirements = {item.intent_id: item for item in current.requirements}
        for value in expected:
            live = live_requirements.get(value.requirements.intent_id)
            if live is None or _requirements_key(
                live.capabilities, live.preconditions
            ) != _requirements_key(
                value.requirements.capabilities, value.requirements.preconditions
            ):
                reject(RequirementsFailureCode.INVALID_PROJECTION)
        for intent, value, supplied in zip(
            candidate.intents, expected, current.requirement_derivations, strict=True
        ):
            if (
                value.provenance != supplied.provenance
                or value.requirements.intent_id != supplied.requirements.intent_id
            ):
                reject(RequirementsFailureCode.INVALID_PROJECTION)
            key = _requirements_key(
                value.requirements.capabilities, value.requirements.preconditions
            )
            if key != _requirements_key(
                supplied.requirements.capabilities, supplied.requirements.preconditions
            ):
                reject(RequirementsFailureCode.INVALID_PROJECTION)
            try:
                equal = key == _requirements_key(intent.required_capabilities, intent.preconditions)
            except RequirementsRejected:
                equal = False
            if not equal:
                reject(RequirementsFailureCode.CANDIDATE_MISMATCH)
        return expected


def _project_plan(
    scope: PlanExecutionScope,
) -> tuple[tuple[CapabilityRequirement, ...], tuple[ExecutivePreconditionRequirement, ...]]:
    capabilities: dict[tuple[str, str], CapabilityRequirement] = {}
    conditions: dict[str, ExecutivePreconditionRequirement] = {}
    meanings: dict[str, object] = {}
    steps = {s.step_id: s for s in scope.plan.candidate.steps}
    if set(steps) != {b.step_id for b in scope.bindings} or len(steps) != len(scope.bindings):
        reject(RequirementsFailureCode.INVALID_PROJECTION)
    for binding in scope.bindings:
        step = steps[binding.step_id]
        if (step.operation_ref, step.target_ref) != (
            binding.operation_ref,
            binding.target_ref,
        ) or set(step.precondition_ids) != {p.precondition_id for p in binding.preconditions}:
            reject(RequirementsFailureCode.INVALID_PROJECTION)
        for cap in step.required_capabilities:
            key = (cap.capability_type, cap.operation)
            if key in capabilities and capabilities[key].allow_degraded != cap.allow_degraded:
                reject(RequirementsFailureCode.INVALID_PROJECTION)
            capabilities[key] = cap
        for condition in binding.preconditions:
            meaning = (condition.subject_ref, condition.predicate, typed_json(condition.expected))
            if (
                condition.precondition_id in meanings
                and meanings[condition.precondition_id] != meaning
            ):
                reject(RequirementsFailureCode.INVALID_PROJECTION)
            meanings[condition.precondition_id] = meaning
            conditions[condition.precondition_id] = ExecutivePreconditionRequirement(
                condition.precondition_id, condition.expected
            )
    return tuple(capabilities.values()), tuple(conditions.values())


def project(value: object) -> object:
    """登録済み不変契約の由来を公開値へ投影し、所有者やLockを含めない。"""
    from dataclasses import fields, is_dataclass

    if isinstance(value, AuthorityGenerationToken):
        return {
            "owner_identity": value.owner_identity,
            "owner_instance_key": value.owner_instance_key,
            "participant_identity": value.participant_identity,
            "generation": value.generation,
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): project(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [project(v) for v in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(
        value,
        (
            PlanExecutionScope,
            PlanProgressContext,
            DirectActivityRequirementSource,
            RequirementsGeneration,
        ),
    ):
        return value.to_dict()
    if is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: project(getattr(value, f.name))
            for f in fields(value)
            if not (
                isinstance(value, RequirementProvenance)
                and f.name == "route_id"
                and value.route_id is None
            )
        }
    raise ValueError("公開できない要件の由来です")


def _same_public_value(left: object, right: object) -> bool:
    """公開契約の比較でもJSONの型を維持する。"""
    return typed_json(freeze_json(project(left))) == typed_json(freeze_json(project(right)))
