from __future__ import annotations

import importlib.util
from pathlib import Path

from app.runtime import runtime_factory

ROOT = Path(__file__).parents[1]


def _module_exists(*parts: str) -> bool:
    try:
        return importlib.util.find_spec(".".join(parts)) is not None
    except ModuleNotFoundError:
        return False


def test_legacy_streaming_packages_are_physically_absent() -> None:
    paths = (
        ("app", "plugins", "youtube_streaming"),
        ("app", "adapters", "streaming"),
        ("app", "adapters", "youtube"),
        ("app", "adapters", "obs"),
    )
    assert [parts for parts in paths if (ROOT.joinpath(*parts)).exists()] == []
    assert [parts for parts in paths if _module_exists(*parts)] == []


def test_legacy_streaming_ports_and_bootstrap_modules_are_absent() -> None:
    modules = (
        ("app", "ports", "streaming_control"),
        ("app", "ports", "streaming_preparation"),
        ("app", "ports", "youtube_live_chat"),
        ("app", "ports", "comment_ranking"),
        ("app", "bootstrap", "streaming"),
        ("app", "bootstrap", "streaming_runtime"),
        ("app", "config", "streaming_compat"),
    )
    assert [parts for parts in modules if _module_exists(*parts)] == []


def test_runtime_factory_has_no_streaming_compatibility_exports() -> None:
    names = (
        "Stream" + "PreparationRuntime",
        "compose_" + "streaming",
        "create_stream_" + "preparation_runtime",
    )
    assert [name for name in names if hasattr(runtime_factory, name)] == []
