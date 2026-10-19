"""統合本体の標準起動で、必須Memoryの未登録を成功扱いしない。"""

from typing import Any

import pytest

from app.bootstrap import cli_composition as cli
from app.config.core_contracts import CoreConfigurationError, CoreFailureCode


@pytest.mark.asyncio
async def test_product_cli_rejects_missing_memory_before_core_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """外部PortやBrainの構築前に、正本必須Ownerの不足を拒否する。"""
    called = False

    async def unexpected_core(**_kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("未登録Memoryのまま本体構成を開始してはいけない")

    monkeypatch.setattr(cli, "build_core", unexpected_core)
    with pytest.raises(CoreConfigurationError) as caught:
        await cli.build_core_application()
    assert caught.value.code is CoreFailureCode.INVALID_SYSTEM_CONFIG
    assert not called
