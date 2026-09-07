"""既存の振り返り実行入口と候補採用判断を単独で検証する。"""

from dataclasses import dataclass, replace

from app.domain.contracts.common import JsonValue, require_identifier, require_revision
from app.domain.memory import (
    InMemoryMemoryRepository,
    MemoryRelationKind,
    MemoryRetrievalQuery,
    MemoryRetrievalRankingPolicy,
    MemoryStoreAuthority,
    MemoryWriteRequest,
    MemoryWriteResult,
    RankedMemoryEvidenceView,
)
from app.domain.memory_reflection import (
    MemoryCandidateProposal,
    ReflectionAcceptancePolicy,
    ReflectionCandidateAuthority,
    ReflectionCandidateStatus,
    ReflectionContextSnapshot,
    ReflectionCoordinator,
    ReflectionOperationalPolicy,
    ReflectionProposalPort,
    ReflectionSupportObservation,
    ReflectionSupportPort,
)
from app.domain.memory_reflection.runtime import LiveReflectionContextReader

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .memory import _project
from .runtime import LabTarget, RunContext


@dataclass(frozen=True)
class ReflectionMemoryWriteBinding:
    """候補から推測せず、検証入力が明示した記憶書込み条件を保持する。"""

    proposal_id: str
    target_memory_id: str
    expected_revision: int
    relation_kind: MemoryRelationKind

    def __post_init__(self) -> None:
        require_identifier(self.proposal_id, "proposal_id")
        require_identifier(self.target_memory_id, "target_memory_id")
        require_revision(self.expected_revision, "expected_revision")
        if not isinstance(self.relation_kind, MemoryRelationKind):
            raise ValueError("記憶関係の公開型が必要です")

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "proposal_id": self.proposal_id,
                "target_memory_id": self.target_memory_id,
                "expected_revision": self.expected_revision,
                "relation_kind": self.relation_kind,
            }
        )


@dataclass(frozen=True)
class ReflectionMemorySettings:
    ranking_policy: MemoryRetrievalRankingPolicy
    queries: tuple[MemoryRetrievalQuery, ...]
    initial_writes: tuple[MemoryWriteRequest, ...] = ()
    write_bindings: tuple[ReflectionMemoryWriteBinding, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "queries", tuple(self.queries))
        if not self.queries or any(not isinstance(x, MemoryRetrievalQuery) for x in self.queries):
            raise ValueError("記憶への接続検証には公開型の検索条件が必要です")
        object.__setattr__(self, "initial_writes", tuple(self.initial_writes))
        object.__setattr__(self, "write_bindings", tuple(self.write_bindings))
        if any(not isinstance(x, MemoryWriteRequest) for x in self.initial_writes):
            raise ValueError("初期記憶は公開型の書込み要求で指定してください")
        if any(not isinstance(x, ReflectionMemoryWriteBinding) for x in self.write_bindings):
            raise ValueError("振り返りの記憶書込み条件が不正です")
        ids = [x.proposal_id for x in self.write_bindings]
        if len(ids) != len(set(ids)):
            raise ValueError("同じ提案への記憶書込み条件は重複できません")

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "ranking_policy": self.ranking_policy,
                "queries": self.queries,
                "initial_writes": self.initial_writes,
                "write_bindings": tuple(x.typed_inputs() for x in self.write_bindings),
            }
        )


@dataclass(frozen=True)
class ReflectionLabCase:
    fixture: ValidationFixture
    snapshot: ReflectionContextSnapshot
    memory: ReflectionMemorySettings | None = None

    def typed_inputs(
        self, acceptance: ReflectionAcceptancePolicy, operational: ReflectionOperationalPolicy
    ) -> JsonValue:
        return _project(
            {
                "context": self.snapshot,
                "acceptance": acceptance,
                "operational": operational,
                "memory": self.memory.typed_inputs() if self.memory is not None else None,
            }
        )


def reflection_target(
    cases: tuple[ReflectionLabCase, ...],
    proposal_port: ReflectionProposalPort,
    support_port: ReflectionSupportPort,
    acceptance_policy: ReflectionAcceptancePolicy,
    operational_policy: ReflectionOperationalPolicy,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
    *,
    live_context: LiveReflectionContextReader | None = None,
) -> LabTarget:
    memory_mode = any(case.memory is not None for case in cases)
    if memory_mode and any(case.memory is None for case in cases):
        raise ValueError("記憶へ接続する検証と単独検証は同じ対象へ混在できません")
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("振り返りの検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if (
            case is None
            or case.fixture != fixture
            or case.typed_inputs(acceptance_policy, operational_policy) != fixture.typed_inputs
        ):
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)

        class Proposal:
            async def propose(
                self, snapshot: ReflectionContextSnapshot
            ) -> tuple[MemoryCandidateProposal, ...]:
                return await context.invoke_port(
                    "reflection.proposal", lambda: proposal_port.propose(snapshot)
                )

        class Support:
            async def observe(
                self, snapshot: ReflectionContextSnapshot, proposal: MemoryCandidateProposal
            ) -> ReflectionSupportObservation:
                return await context.invoke_port(
                    "reflection.support", lambda: support_port.observe(snapshot, proposal)
                )

        owner = ReflectionCoordinator(
            Proposal(),
            Support(),
            ReflectionCandidateAuthority(acceptance_policy),
            operational_policy=operational_policy,
            max_pending_tasks=context.policy.max_tasks,
            live_context=live_context,
        )
        context.add_cleanup("reflection.coordinator", owner.shutdown)
        snapshot = replace(
            case.snapshot,
            reflection_id=f"{context.run_id}:{fixture.scenario_id}:{context.iteration}",
        )
        result = await context.invoke_product("reflection.run", lambda: owner.submit(snapshot))
        failures = {
            ReflectionCandidateStatus.REFLECTION_PROVIDER_UNAVAILABLE,
            ReflectionCandidateStatus.SUPPORT_PROVIDER_UNAVAILABLE,
        }
        status = (
            RunStatus.PROVIDER_FAILED
            if any(item.status in failures for item in result.results)
            else RunStatus.COMPLETED
        )
        memory_result: JsonValue = None
        if case.memory is not None:
            if (
                len(case.memory.queries) + len(result.results) + len(case.memory.initial_writes)
                > context.policy.max_intervals
            ):
                raise ValueError("振り返りから記憶への操作数が検証上限を超えました")
            bindings = {x.proposal_id: x for x in case.memory.write_bindings}
            if set(bindings) - {item.proposal_id for item in result.results}:
                raise ValueError("記憶書込み条件に対応する振り返り結果がありません")
            repository = InMemoryMemoryRepository()
            store = MemoryStoreAuthority(repository, ranking_policy=case.memory.ranking_policy)
            initial_results: list[JsonValue] = []
            for initial in case.memory.initial_writes:

                async def initialize(item: MemoryWriteRequest = initial) -> MemoryWriteResult:
                    return store.write(item)

                initial_results.append(
                    _project(
                        {
                            "request": initial,
                            "result": await context.invoke_product(
                                "reflection.memory_initialize", initialize
                            ),
                        }
                    )
                )
            writes: list[JsonValue] = []
            retrieved: list[JsonValue] = []
            for accepted in result.results:
                if accepted.candidate is None:
                    continue
                binding = bindings.get(accepted.proposal_id)
                request = (
                    MemoryWriteRequest(accepted.candidate)
                    if binding is None
                    else MemoryWriteRequest(
                        accepted.candidate,
                        binding.expected_revision,
                        binding.target_memory_id,
                        binding.relation_kind,
                    )
                )

                async def write(request: MemoryWriteRequest = request) -> MemoryWriteResult:
                    return store.write(request)

                written = await context.invoke_product("reflection.memory_write", write)
                writes.append(
                    _project(
                        {"proposal_id": accepted.proposal_id, "request": request, "result": written}
                    )
                )
            for query in case.memory.queries:

                async def retrieve(query: MemoryRetrievalQuery = query) -> RankedMemoryEvidenceView:
                    return store.retrieve(query)

                retrieved.append(
                    _project(await context.invoke_product("reflection.memory_retrieve", retrieve))
                )
            memory_result = _project(
                {
                    "initial_writes": initial_results,
                    "writes": writes,
                    "repository": repository.snapshot(),
                    "retrieval": retrieved,
                }
            )
        return TargetObservation(
            status,
            Gate.NOT_RUN,
            _project(
                {
                    "reflection_result": result,
                    "pending_reflection_tasks": owner.pending_task_count,
                    "memory": memory_result,
                }
            ),
        )

    return LabTarget(
        "reflection_memory" if memory_mode else "reflection",
        contract_revision,
        frozenset({LabMode.ADJACENT if memory_mode else LabMode.ISOLATION}),
        (),
        provenance,
        run,
        frozenset({"reflection.proposal", "reflection.support"}),
    )
