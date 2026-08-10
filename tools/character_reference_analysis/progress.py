from __future__ import annotations

from collections.abc import Awaitable, Callable

ProgressCallback = Callable[[str, int], Awaitable[None]]


async def report_progress(
    callback: ProgressCallback | None,
    stage: str,
    percent: int,
) -> None:
    if callback is None:
        return
    normalized = max(0, min(100, int(percent)))
    await callback(stage, normalized)
