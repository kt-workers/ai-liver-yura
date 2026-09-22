"""検証専用の記憶保存先を使い、既存の書込判断と検索を実行する。"""

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import Enum

from app.domain.contracts.common import JsonValue, freeze_json
from app.domain.memory import (
    InMemoryMemoryRepository,
    MemoryRetrievalQuery,
    MemoryRetrievalRankingPolicy,
    MemoryStoreAuthority,
    MemoryWriteRequest,
    MemoryWriteResult,
    RankedMemoryEvidenceView,
)

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .runtime import LabTarget, RunContext


def _project(value: object) -> JsonValue:
    if isinstance(value, Enum):
        return _project(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, bool, int, float)):
        return freeze_json(value)
    if isinstance(value, Mapping):
        return freeze_json({str(key): _project(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_project(item) for item in value)
    if (
        is_dataclass(value)
        and not isinstance(value, type)
        and type(value).__module__.startswith(
            ("app.domain.memory.", "app.domain.memory_reflection.")
        )
    ):
        return freeze_json(
            {field.name: _project(getattr(value, field.name)) for field in fields(value)}
        )
    raise ValueError("記憶の公開契約以外は検証証拠へ投影できません")


@dataclass(frozen=True)
class MemoryLabCase:
    fixture: ValidationFixture
    writes: tuple[MemoryWriteRequest, ...]
    queries: tuple[MemoryRetrievalQuery, ...]

    def __post_init__(self) -> None:
        if not self.queries or any(not isinstance(x, MemoryWriteRequest) for x in self.writes):
            raise ValueError("記憶の書込候補と検索条件が不正です")
        if any(not isinstance(x, MemoryRetrievalQuery) for x in self.queries):
            raise ValueError("記憶の検索条件が不正です")
        object.__setattr__(self, "writes", tuple(self.writes))
        object.__setattr__(self, "queries", tuple(self.queries))

    def typed_inputs(self, policy: MemoryRetrievalRankingPolicy) -> JsonValue:
        return _project(
            {
                "writes": self.writes,
                "queries": self.queries,
                "ranking_policy": policy,
            }
        )


def memory_target(
    cases: tuple[MemoryLabCase, ...],
    ranking_policy: MemoryRetrievalRankingPolicy,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("記憶の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if (
            case is None
            or case.fixture != fixture
            or case.typed_inputs(ranking_policy) != fixture.typed_inputs
        ):
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        # 各反復の保存先を分け、現在運用中の記憶を読んだり変更したりしない。
        repository = InMemoryMemoryRepository()
        owner = MemoryStoreAuthority(repository, ranking_policy=ranking_policy)
        written: list[JsonValue] = []
        retrieved: list[JsonValue] = []
        for request in case.writes:

            async def write(item: MemoryWriteRequest = request) -> MemoryWriteResult:
                return owner.write(item)

            written.append(_project(await context.invoke_product("memory.write", write)))
        for query in case.queries:

            async def retrieve(item: MemoryRetrievalQuery = query) -> RankedMemoryEvidenceView:
                return owner.retrieve(item)

            retrieved.append(_project(await context.invoke_product("memory.retrieve", retrieve)))
        return TargetObservation(
            RunStatus.COMPLETED,
            Gate.NOT_RUN,
            _project(
                {
                    "write_results": written,
                    "retrieval_results": retrieved,
                }
            ),
        )

    return LabTarget(
        "memory",
        contract_revision,
        frozenset({LabMode.ISOLATION}),
        (),
        provenance,
        run,
    )
