"""配信の本番観測履歴とコメント集約を、明示した入力列と間隔で観測する。"""

import asyncio
from dataclasses import asdict, dataclass
from math import isfinite
from time import monotonic

from app.subsystems.streaming.contracts import StreamingCommentEvent, StreamingExternalObservation
from app.subsystems.streaming.runtime import StreamingSubsystemRuntime

from .contracts import positive
from .runtime import RunContext


@dataclass(frozen=True)
class StreamingMonitorFrame:
    comments: tuple[StreamingCommentEvent, ...] = ()
    observations: tuple[StreamingExternalObservation, ...] = ()

    def __post_init__(self) -> None:
        comments, observations = tuple(self.comments), tuple(self.observations)
        if any(not isinstance(item, StreamingCommentEvent) for item in comments):
            raise ValueError("配信コメントには本番の型付き入力が必要です")
        if any(not isinstance(item, StreamingExternalObservation) for item in observations):
            raise ValueError("配信観測には本番の型付き入力が必要です")
        object.__setattr__(self, "comments", comments)
        object.__setattr__(self, "observations", observations)


@dataclass(frozen=True)
class StreamingMonitorSettings:
    frames: tuple[StreamingMonitorFrame, ...]
    sample_interval_s: float
    comment_limit: int

    def __post_init__(self) -> None:
        frames = tuple(self.frames)
        if not frames or any(not isinstance(item, StreamingMonitorFrame) for item in frames):
            raise ValueError("配信監視には1件以上の型付き入力区間が必要です")
        positive(self.comment_limit)
        if (
            type(self.sample_interval_s) not in (int, float)
            or not isfinite(self.sample_interval_s)
            or self.sample_interval_s <= 0
        ):
            raise ValueError("観測間隔は有限の正数で指定してください")
        object.__setattr__(self, "frames", frames)


async def observe_streaming(
    context: RunContext, owner: StreamingSubsystemRuntime, settings: StreamingMonitorSettings
) -> dict[str, object]:
    if len(settings.frames) > context.policy.max_intervals:
        raise ValueError("配信監視の入力区間数が記録上限を超えています")
    rows: list[dict[str, object]] = []
    started = monotonic()
    for index, frame in enumerate(settings.frames):
        accepted: list[bool] = []

        async def ingest(item: StreamingMonitorFrame = frame, flags: list[bool] = accepted) -> None:
            for observation in item.observations:
                flags.append(owner.accept_observation(observation))
            for comment in item.comments:
                await owner.ingest_comment(comment)

        await context.invoke_product("streaming.monitor_ingress", ingest)
        await asyncio.sleep(settings.sample_interval_s)

        async def sample(
            current_index: int = index,
            item: StreamingMonitorFrame = frame,
            flags: list[bool] = accepted,
        ) -> dict[str, object]:
            return {
                "index": current_index,
                "elapsed_s": monotonic() - started,
                "accepted_observations": flags,
                "submitted_comments": len(item.comments),
                "signals": [asdict(item) for item in owner.drain_comment_signals()],
                "dropped_comments": owner.dropped_comment_count,
                "pending_streaming_tasks": owner.pending_task_count,
            }

        rows.append(await context.invoke_product("streaming.monitor_sample", sample))
    keys = dict.fromkeys(
        (item.source_kind, item.source_ref)
        for frame in settings.frames
        for item in frame.observations
    )
    return {
        "samples": rows,
        "histories": [
            {
                "source_kind": kind,
                "source_ref": ref,
                "observations": [asdict(item) for item in owner.observation_history(kind, ref)],
            }
            for kind, ref in keys
        ],
        "dropped_comments": owner.dropped_comment_count,
        "pending_at_window_end": owner.pending_task_count,
    }
