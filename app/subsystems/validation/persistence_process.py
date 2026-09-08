"""専用pipeで指定された隔離DBを本番入口から復元する子プロセス。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from app.domain.contracts.common import freeze_json, thaw_json
from app.domain.memory import MemoryKind, MemoryRetrievalQuery
from app.domain.memory.contracts import MemoryFreshnessState
from app.domain.memory.ranking import (
    MemoryFreshnessScoreRule,
    MemoryRankingMissingBehavior,
    MemoryRankingPolarity,
    MemoryRankingSignal,
    MemoryRankingSignalRule,
    MemoryRetrievalRankingPolicy,
    MemoryStableTieBreaker,
)
from app.infrastructure.persistence import SnapshotPersistenceRetryPolicy
from app.infrastructure.persistence.postgresql_connection import (
    PostgresConnectionPolicy,
    PostgresEndpoint,
)
from app.runtime.lifecycle import DependencyRetryPolicy

from .memory import _project
from .persistence import PersistenceLabSettings, _boot, _state, _stop
from .provenance import capture_production_provenance


async def restore(packet: dict[str, Any]) -> dict[str, object]:
    raw = packet["settings"]
    ranking = dict(raw["ranking_policy"])
    ranking["signal_rules"] = tuple(
        MemoryRankingSignalRule(
            MemoryRankingSignal(x["signal"]),
            x["weight"],
            MemoryRankingPolarity(x["polarity"]),
            MemoryRankingMissingBehavior(x["missing_behavior"]),
        )
        for x in ranking["signal_rules"]
    )
    ranking["freshness_scores"] = tuple(
        MemoryFreshnessScoreRule(MemoryFreshnessState(x["freshness"]), x["score"])
        for x in ranking["freshness_scores"]
    )
    ranking["stable_tie_breaker"] = MemoryStableTieBreaker(ranking["stable_tie_breaker"])
    settings = PersistenceLabSettings(
        Path.cwd(),
        Path(packet["config_path"]),
        PostgresEndpoint(**packet["endpoint"]),
        PostgresConnectionPolicy(**raw["connection_policy"]),
        MemoryRetrievalRankingPolicy(**ranking),
        SnapshotPersistenceRetryPolicy(**raw["snapshot_retry_policy"]),
        DependencyRetryPolicy(**raw["retry_policy"]),
        raw["max_pending"],
        raw["max_pending_memory"],
    )
    if settings.public_settings() != freeze_json(raw):
        raise ValueError("親と子の設定リビジョンが一致しません")
    query = dict(packet["query"])
    for name in ("created_at", "observed_from", "observed_until"):
        if query[name] is not None:
            query[name] = datetime.fromisoformat(query[name])
    query["memory_kinds"] = tuple(MemoryKind(value) for value in query["memory_kinds"])
    query["subject_refs"] = tuple(query["subject_refs"])
    typed_query = MemoryRetrievalQuery(**query)
    expected = packet["provenance"]
    provenance = capture_production_provenance(
        settings.repository,
        (
            "app/bootstrap.py",
            "app/composition/goal_persistence.py",
            "app/composition/memory_persistence.py",
            "app/infrastructure/persistence",
        ),
        tuple(expected["module_contract_ids"]),
        tuple(expected["role_schema_ids"]),
    )
    if provenance.git_head != expected["git_head"] or provenance.branch != expected["branch"]:
        raise ValueError("親と子の製品ソースが一致しません")
    app, storage = await _boot(settings, settings.admin_endpoint, packet["run_id"] + "-child")
    try:
        if app.memory is None:
            raise ValueError("本番の記憶接続がありません")
        retrieved = await app.memory.submit_retrieval(typed_query).wait()
        result: dict[str, object] = {
            "run_id": packet["run_id"],
            "iteration": packet["iteration"],
            "git_head": provenance.git_head,
            "branch": provenance.branch,
            "pid": os.getpid(),
            "restored": thaw_json(_state(app, storage)),
            "memory_failure": None
            if retrieved.failure_code is None
            else retrieved.failure_code.value,
            "memory_result": None
            if retrieved.value is None
            else thaw_json(_project(retrieved.value)),
        }
    finally:
        stopped = await _stop(app, storage)
    result["stopped"] = thaw_json(stopped)
    restored = result["restored"]
    assert isinstance(restored, dict) and isinstance(stopped, Mapping)
    result["product_failed"] = (
        restored["restore_failure"] is not None
        or result["memory_failure"] is not None
        or bool(stopped["shutdown_failures"])
    )
    return result


def main() -> None:
    try:
        data = sys.stdin.buffer.read(1_048_577)
        if len(data) > 1_048_576:
            raise ValueError("子プロセスへの入力が上限を超えています")
        result = asyncio.run(restore(json.loads(data)))
        sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False))
        sys.stdout.flush()
    except Exception:
        # 提供元例外・接続先・認証情報を標準出力やstderrへ返さない。
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
