"""別プロセスから隔離DBの目標を、本体の復元入口で取得する試験補助。"""

import asyncio
import json
import sys

from app.composition.goal_persistence import CoreGoalPersistenceBinding
from app.infrastructure.persistence.postgresql_connection import PostgresEndpoint
from tests.infrastructure.postgresql.test_runtime import runtime


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
    try:
        assert await persistence.start() is None
        binding = await CoreGoalPersistenceBinding.restore(persistence, runtime_epoch="child")
        assert binding.restore_failure is None
        print(json.dumps(binding.snapshot().to_dict(), ensure_ascii=False))
    finally:
        await persistence.close()


if __name__ == "__main__":
    asyncio.run(main())
