from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PROJECT_ROOT / "app"
BASELINE_PATH = PROJECT_ROOT / "tests" / "dependency_boundary_baseline.json"


@dataclass(frozen=True, order=True)
class Violation:
    rule: str
    source: str
    imported: str
    line: int

    def key(self) -> str:
        return f"{self.rule}|{self.source}|{self.imported}|{self.line}"


def _module_name(path: Path) -> str:
    relative = path.relative_to(PROJECT_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_import_from(source_module: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = source_module.split(".")[:-1]
    keep = max(0, len(package) - node.level + 1)
    prefix = package[:keep]
    if node.module:
        prefix.extend(node.module.split("."))
    return ".".join(prefix)


def _imports(path: Path) -> list[tuple[str, int]]:
    source_module = _module_name(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_import_from(source_module, node)
            if module:
                found.append((module, node.lineno))
    return found


def _adapter_name(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) >= 3 and parts[:2] == ["app", "adapters"]:
        return parts[2]
    return None


def _detect_violations() -> set[str]:
    violations: set[Violation] = set()
    external_runtime_prefixes = (
        "PyQt6",
        "google",
        "httpx",
        "openai",
        "psycopg",
        "requests",
        "yaml",
    )

    for path in sorted(APP_ROOT.rglob("*.py")):
        source = _module_name(path)
        source_adapter = _adapter_name(source)
        for imported, line in _imports(path):
            if source.startswith("app.domain") and imported.startswith(
                ("app.runtime", "app.adapters", "app.plugins", "app.bootstrap")
            ):
                violations.add(Violation("domain_inward_only", source, imported, line))

            if source.startswith("app.ports") and imported.startswith("app.adapters"):
                violations.add(Violation("ports_no_adapters", source, imported, line))

            if source.startswith("app.usecases") and imported.startswith("app.bootstrap"):
                violations.add(Violation("usecases_no_bootstrap", source, imported, line))

            if source.startswith("app.runtime") and imported.startswith(
                external_runtime_prefixes
            ):
                violations.add(Violation("runtime_no_external_sdk", source, imported, line))

            imported_adapter = _adapter_name(imported)
            if (
                source_adapter is not None
                and imported_adapter is not None
                and source_adapter != imported_adapter
            ):
                violations.add(
                    Violation("adapters_no_cross_dependency", source, imported, line)
                )

            if source.startswith("app.plugins") and imported.startswith("app."):
                imported_parts = imported.split(".")
                if any(part.startswith("_") for part in imported_parts[1:]):
                    violations.add(
                        Violation("plugins_no_core_private_modules", source, imported, line)
                    )

    return {violation.key() for violation in violations}


def _load_baseline() -> set[str]:
    raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    assert all(isinstance(item, str) for item in raw)
    return set(raw)


def test_dependency_boundaries_have_no_new_violations() -> None:
    current = _detect_violations()
    baseline = _load_baseline()

    new_violations = sorted(current - baseline)
    stale_baseline = sorted(baseline - current)

    assert not new_violations, (
        "新しい依存方向違反があります。依存を修正してください。"
        "既存違反として意図的に許容する場合のみbaselineへ追加します。\n"
        + "\n".join(new_violations)
    )
    assert not stale_baseline, (
        "解消済みのbaseline項目があります。baselineから削除してください。\n"
        + "\n".join(stale_baseline)
    )
