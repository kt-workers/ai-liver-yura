from __future__ import annotations

from app.domain.body_realtime.contracts import (
    ChannelOverlay,
    RealtimeChannel,
    RealtimeOverlayBundle,
)

from .contracts import BodyFrameChannelValue


def select_overlay_channels(
    bundle: RealtimeOverlayBundle | None,
    current_revision: int,
) -> tuple[
    tuple[BodyFrameChannelValue, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    """現行#340のchannel-only overlayを決定論的に競合解決する。"""

    if bundle is None:
        return (), (), ()
    overlays = tuple(bundle.channel_overlays)
    if bundle.based_on_body_state_revision != current_revision:
        return (), (), tuple(sorted(item.overlay_id for item in overlays))

    by_channel: dict[RealtimeChannel, list[ChannelOverlay]] = {}
    for overlay in overlays:
        by_channel.setdefault(overlay.channel, []).append(overlay)

    values: list[BodyFrameChannelValue] = []
    applied: list[str] = []
    degraded: list[str] = []
    for channel in sorted(by_channel, key=lambda item: item.value):
        candidates = sorted(
            by_channel[channel],
            key=lambda item: (-item.priority, item.overlay_id),
        )
        winner = candidates[0]
        if winner.strength > 0:
            values.append(BodyFrameChannelValue(winner.channel, winner.value))
            applied.append(winner.overlay_id)
        else:
            degraded.append(winner.overlay_id)
        degraded.extend(item.overlay_id for item in candidates[1:])
    return tuple(values), tuple(sorted(applied)), tuple(sorted(degraded))
