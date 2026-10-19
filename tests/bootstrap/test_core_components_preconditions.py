"""統合本体の必須構成を副作用より先に拒否する。"""

from typing import Any, cast

import pytest

from app.bootstrap.core_components import compose_core_components


def test_missing_cognition_is_rejected_before_owner_construction() -> None:
    placeholder = cast(Any, object())
    with pytest.raises(ValueError, match="認知・主観評価・注意・判断"):
        compose_core_components(placeholder, placeholder, placeholder, placeholder)
