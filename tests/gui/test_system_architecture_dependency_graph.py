from pathlib import Path
import sys

MODULE_DIR = (
    Path(__file__).resolve().parents[2]
    / "gui"
    / "yura-system-architecture-visualizer"
)
sys.path.insert(0, str(MODULE_DIR))

from dependency_graph import build_graph  # noqa: E402


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_graph_aggregates_internal_imports_and_ignores_external(tmp_path: Path) -> None:
    write(tmp_path, "app/core/__init__.py", "")
    write(tmp_path, "app/core/model.py", "VALUE = 1\n")
    write(tmp_path, "app/runtime/runner.py", "import os\nimport app.core.model\nfrom app.core import model\n")
    graph = build_graph(tmp_path, analysis_roots=("app",))
    assert {node["id"] for node in graph["nodes"]} == {"app.core", "app.runtime"}
    assert graph["edges"] == [{"id":"app.runtime->app.core","source":"app.runtime","target":"app.core","kind":"python_import","weight":2}]


def test_build_graph_resolves_relative_import(tmp_path: Path) -> None:
    write(tmp_path, "app/domain/__init__.py", "")
    write(tmp_path, "app/domain/entities.py", "class Entity: ...\n")
    write(tmp_path, "app/services/__init__.py", "")
    write(tmp_path, "app/services/use_case.py", "from ..domain import entities\n")
    graph = build_graph(tmp_path, analysis_roots=("app",))
    assert any(edge["source"] == "app.services" and edge["target"] == "app.domain" for edge in graph["edges"])


def test_build_graph_splits_plugins_into_logical_modules(tmp_path: Path) -> None:
    write(tmp_path, "app/core/api.py", "class Api: ...\n")
    write(tmp_path, "app/plugins/voice/adapter.py", "from app.core import api\n")
    write(tmp_path, "app/plugins/avatar/adapter.py", "from app.core import api\n")
    graph = build_graph(tmp_path, analysis_roots=("app",))
    node_ids = {node["id"] for node in graph["nodes"]}
    assert "app.plugins.voice" in node_ids
    assert "app.plugins.avatar" in node_ids
    assert "app.plugins" not in node_ids


def test_build_graph_ignores_self_edges(tmp_path: Path) -> None:
    write(tmp_path, "app/runtime/a.py", "from app.runtime import b\n")
    write(tmp_path, "app/runtime/b.py", "VALUE = 1\n")
    graph = build_graph(tmp_path, analysis_roots=("app",))
    assert graph["edges"] == []


def test_build_graph_keeps_working_when_file_has_syntax_error(tmp_path: Path) -> None:
    write(tmp_path, "app/core/good.py", "VALUE = 1\n")
    write(tmp_path, "app/runtime/broken.py", "def broken(:\n")
    graph = build_graph(tmp_path, analysis_roots=("app",))
    assert len(graph["diagnostics"]) == 1
    assert graph["diagnostics"][0]["path"] == "app/runtime/broken.py"
