import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


def test_subsystem_admin_has_no_core_or_gui_imports() -> None:
    files = (ROOT / "subsystems/streaming/admin_api").rglob("*.py")
    forbidden = (
        "app.admin_api",
        "app.bootstrap",
        "app.runtime",
        ".".join(("app", "plugins", "youtube_streaming")),
        ".".join(("app", "adapters", "streaming")),
        "gui",
    )
    violations = [
        (str(path), name)
        for path in files
        for name in imports(path)
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in forbidden)
    ]
    assert violations == []


def test_gui_uses_new_client_outside_documented_compatibility_files() -> None:
    root = ROOT / "gui/yura-streaming-admin"
    compatibility = {"core_api_client.py", "event_stream_client.py", "__init__.py"}
    violations = [
        str(path)
        for path in root.rglob("*.py")
        if path.name not in compatibility
        and ("CoreApiClient" in path.read_text() or "app.admin_api" in path.read_text())
    ]
    assert violations == []
