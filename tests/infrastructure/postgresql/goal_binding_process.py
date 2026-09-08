"""別プロセスから隔離DBの目標を、本体の復元入口で取得する試験補助。"""

import asyncio
import json
import os
import sys
from pathlib import Path

from app.bootstrap import build_persistent_core
from app.composition.goal_persistence import CoreGoalPersistenceBinding
from app.domain.executive import GoalTransitionOperation
from app.domain.memory import MemoryWriteRequest
from app.infrastructure.persistence import DurabilityStatus
from app.infrastructure.persistence.postgresql_connection import PostgresEndpoint
from tests.domain.goals.test_goal_commitment_store import decision, goal_transition
from tests.domain.memory import test_memory_store_retrieval as memory
from tests.infrastructure.postgresql.test_runtime import runtime
from tests.runtime.test_lifecycle import retry_policy


async def main() -> None:
    endpoint = PostgresEndpoint(
        sys.argv[1],
        int(sys.argv[2]),
        sys.argv[3],
        sys.argv[4],
        "isolated-test-no-auth",
        "disable",
    )
    persistence = runtime(endpoint)
    if len(sys.argv) == 6:
        app = await build_persistent_core(
            Path(sys.argv[5]),
            persistence=persistence,
            retry_policy=retry_policy("db", retry_enabled=False),
            runtime_epoch="child-before-exit",
            max_pending_memory=2,
        )
        await app.start()
        assert isinstance(app.goals, CoreGoalPersistenceBinding)
        assert app.memory is not None
        committed = app.goals.apply(
            decision("create", 0, goals=(goal_transition(GoalTransitionOperation.CREATE, 0),))
        )
        assert (await committed.durability).status is DurabilityStatus.DURABLE
        written = await app.memory.submit_write(MemoryWriteRequest(memory.candidate())).wait()
        assert written.failure_code is None and written.value is not None
        print(json.dumps(committed.committed.snapshot.to_dict(), ensure_ascii=False), flush=True)
        # 保存確認後に終了処理を省略し、別プロセスの復元を検証する。
        os._exit(0)
    try:
        assert await persistence.start() is None
        binding = await CoreGoalPersistenceBinding.restore(persistence, runtime_epoch="child")
        assert binding.restore_failure is None
        print(json.dumps(binding.snapshot().to_dict(), ensure_ascii=False))
    finally:
        await persistence.close()


if __name__ == "__main__":
    asyncio.run(main())
