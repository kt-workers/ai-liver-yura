"""構成から分離した資源台帳の回収順序と失敗を検証する。"""

from __future__ import annotations

import asyncio

import pytest

from app.usecases.resource_cleanup import OwnedResourceLedger, OwnedResourcesCloseError


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["none", "error", "cancel", "both"])
async def test_reverse_order_reclaims_all_actions_even_after_failure(failure: str) -> None:
    ledger = OwnedResourceLedger()
    events: list[int] = []
    for index in range(4):

        async def close(index: int = index) -> None:
            events.append(index)
            if index == 2 and failure in ("error", "both"):
                raise ValueError("非公開の試験詳細")
            if index == 1 and failure in ("cancel", "both"):
                raise asyncio.CancelledError

        ledger.actions.append(close)
    if failure == "none":
        await ledger.close()
    elif failure == "error":
        with pytest.raises(OwnedResourcesCloseError) as caught:
            await ledger.close()
        assert "非公開の試験詳細" not in str(caught.value)
    else:
        with pytest.raises(asyncio.CancelledError):
            await ledger.close()
    assert events == [3, 2, 1, 0]
    assert not ledger.actions
    await ledger.close()
    assert events == [3, 2, 1, 0]


@pytest.mark.asyncio
async def test_sync_and_async_resources_share_the_same_reverse_order() -> None:
    ledger = OwnedResourceLedger()
    events: list[str] = []
    ledger.add_sync(lambda: events.append("first"))

    async def close() -> None:
        events.append("second")

    ledger.actions.append(close)
    ledger.add_sync(lambda: events.append("third"))
    await ledger.close()
    assert events == ["third", "second", "first"]
