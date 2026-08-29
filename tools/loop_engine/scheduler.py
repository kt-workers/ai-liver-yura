"""実行可能性、Work選択、重複割当の純粋な判定規則。"""

from __future__ import annotations

import hashlib
import json

from .models import LineageClassification, LineageSnapshot, ObservationEpoch, WorkSnapshot

_PRIORITY = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def select_work(epoch: ObservationEpoch) -> WorkSnapshot | None:
    current = next(
        (item for item in epoch.works if item.issue_number == epoch.mission.current_work_id), None
    )
    if current is not None and current.dependency_ready and current.actionable:
        return current
    candidates = [item for item in epoch.works if item.dependency_ready and item.actionable]
    if not candidates:
        return None
    return min(candidates, key=lambda item: (_priority(item), _status(item), item.issue_number))


def canonical_lineage(epoch: ObservationEpoch, issue_number: int) -> LineageSnapshot | None:
    return next(
        (
            item
            for item in epoch.lineages
            if item.work_issue == issue_number
            and item.classification is LineageClassification.CANONICAL
        ),
        None,
    )


def schedule_key(epoch: ObservationEpoch, work: WorkSnapshot, transition: str) -> str:
    lineage = canonical_lineage(epoch, work.issue_number)
    state = {
        "canonical_designs": sorted(
            (item.identity.stable_id, item.live_blob_sha) for item in epoch.canonical_designs
        ),
        "issue": work.issue_number,
        "dependency_completion_identities": sorted(work.dependency_completion_identities),
        "lineage": (
            lineage.classification.value if lineage else None,
            lineage.base_sha if lineage else None,
            lineage.head_sha if lineage else None,
            lineage.ci_head_sha if lineage else None,
            lineage.review_head_sha if lineage else None,
        ),
        "mission": (
            epoch.mission.identity.stable_id,
            epoch.mission.identity.source_revision,
            epoch.mission.checkpoint_identity,
        ),
        "priority": work.priority,
        "project_number": epoch.project_number,
        "project_status": work.project_status,
        "source_revision": work.identity.source_revision,
        "work_checkpoint_identity": work.checkpoint_identity,
        "transition": transition,
    }
    serialized = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def is_duplicate(epoch: ObservationEpoch, key: str) -> bool:
    return key in epoch.checkpoint_schedule_keys


def _priority(work: WorkSnapshot) -> int:
    return _PRIORITY.get(work.priority or "", 4)


def _status(work: WorkSnapshot) -> int:
    return 0 if work.project_status == "In progress" else 1
