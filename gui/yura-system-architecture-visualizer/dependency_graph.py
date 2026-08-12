from __future__ import annotations

import ast
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_ANALYSIS_ROOTS = ("app", "gui", "cloud_validation")


def _module_name(relative_path: Path) -> str:
    parts = list(relative_path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _package_name(relative_path: Path) -> str:
    module = _module_name(relative_path)
    if relative_path.name == "__init__.py":
        return module
    return module.rpartition(".")[0]


def _logical_module_id(relative_path: Path) -> str:
    parts = relative_path.parts
    if not parts:
        return "other"

    root = parts[0]
    if root == "app":
        if len(parts) < 2:
            return "app"
        first = parts[1]
        if first in {"plugins", "subsystems"} and len(parts) >= 3:
            return f"app.{first}.{parts[2]}"
        return f"app.{first}"

    if root == "gui":
        return f"gui.{parts[1]}" if len(parts) >= 2 else "gui"

    if root == "cloud_validation":
        return (
            f"cloud_validation.{parts[1]}"
            if len(parts) >= 2 and Path(parts[1]).suffix == ""
            else "cloud_validation"
        )

    return root


def _logical_module_from_import(module_name: str) -> str:
    parts = module_name.split(".")
    if not parts:
        return "other"

    if parts[0] == "app":
        if len(parts) == 1:
            return "app"
        if parts[1] in {"plugins", "subsystems"} and len(parts) >= 3:
            return ".".join(parts[:3])
        return ".".join(parts[:2])

    if parts[0] == "gui":
        return ".".join(parts[:2]) if len(parts) >= 2 else "gui"

    if parts[0] == "cloud_validation":
        return ".".join(parts[:2]) if len(parts) >= 2 else "cloud_validation"

    return parts[0]


def _category(module_id: str) -> str:
    if module_id.startswith("gui.") or module_id == "gui":
        return "gui"
    if module_id.startswith("cloud_validation"):
        return "validation"
    if module_id.startswith("app.plugins."):
        return "plugin"
    if module_id.startswith("app.subsystems."):
        return "subsystem"

    segment = module_id.split(".")[-1]
    mapping = {
        "adapters": "adapter",
        "admin_api": "admin",
        "bootstrap": "bootstrap",
        "config": "config",
        "core": "core",
        "diagnostics": "diagnostics",
        "domain": "domain",
        "infrastructure": "infrastructure",
        "integrations": "integration",
        "ports": "port",
        "prompting": "prompting",
        "runtime": "runtime",
        "services": "service",
    }
    return mapping.get(segment, "other")


def _resolve_relative(package: str, level: int, module: str | None) -> str:
    package_parts = [part for part in package.split(".") if part]
    keep = max(0, len(package_parts) - max(0, level - 1))
    base = package_parts[:keep]
    if module:
        base.extend(module.split("."))
    return ".".join(base)


def _known_internal(module: str, known_modules: set[str], roots: set[str]) -> bool:
    if not module:
        return False
    if module.split(".", 1)[0] not in roots:
        return False
    if module in known_modules:
        return True
    prefix = module + "."
    return any(candidate.startswith(prefix) for candidate in known_modules)


def _import_targets(
    tree: ast.AST,
    *,
    package: str,
    known_modules: set[str],
    roots: set[str],
) -> Iterable[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _known_internal(alias.name, known_modules, roots):
                    yield alias.name
            continue

        if not isinstance(node, ast.ImportFrom):
            continue

        base = node.module or ""
        if node.level:
            base = _resolve_relative(package, node.level, node.module)

        candidates: list[str] = []
        for alias in node.names:
            if alias.name == "*":
                continue
            candidate = f"{base}.{alias.name}" if base else alias.name
            if _known_internal(candidate, known_modules, roots):
                candidates.append(candidate)

        if candidates:
            yield from candidates
        elif _known_internal(base, known_modules, roots):
            yield base


def build_graph(
    repo_root: str | Path,
    *,
    analysis_roots: Iterable[str] = DEFAULT_ANALYSIS_ROOTS,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    roots = tuple(analysis_roots)
    root_names = set(roots)

    files: list[tuple[Path, Path]] = []
    for name in roots:
        base = root / name
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if any(part in {".venv", "venv", "__pycache__"} for part in path.parts):
                continue
            files.append((path, path.relative_to(root)))

    module_by_path = {relative: _module_name(relative) for _, relative in files}
    known_modules = {module for module in module_by_path.values() if module}

    logical_files: dict[str, list[str]] = defaultdict(list)
    logical_paths: dict[str, str] = {}
    for _, relative in files:
        logical_id = _logical_module_id(relative)
        logical_files[logical_id].append(relative.as_posix())
        logical_paths.setdefault(logical_id, str(Path(*logical_id.split("."))))

    edge_weights: dict[tuple[str, str], int] = defaultdict(int)
    diagnostics: list[dict[str, str]] = []

    for path, relative in files:
        source_id = _logical_module_id(relative)
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(relative))
        except (OSError, UnicodeError, SyntaxError) as exc:
            diagnostics.append({"path": relative.as_posix(), "error": str(exc)})
            continue

        package = _package_name(relative)
        for imported in _import_targets(
            tree,
            package=package,
            known_modules=known_modules,
            roots=root_names,
        ):
            target_id = _logical_module_from_import(imported)
            if target_id == source_id or target_id not in logical_files:
                continue
            edge_weights[(source_id, target_id)] += 1

    incoming: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, set[str]] = defaultdict(set)
    edges: list[dict[str, Any]] = []
    for (source_id, target_id), weight in sorted(edge_weights.items()):
        incoming[target_id].add(source_id)
        outgoing[source_id].add(target_id)
        edges.append(
            {
                "id": f"{source_id}->{target_id}",
                "source": source_id,
                "target": target_id,
                "kind": "python_import",
                "weight": weight,
            }
        )

    nodes: list[dict[str, Any]] = []
    for module_id in sorted(logical_files):
        module_files = logical_files[module_id]
        nodes.append(
            {
                "id": module_id,
                "label": module_id.split(".")[-1],
                "path": logical_paths[module_id],
                "category": _category(module_id),
                "level": "logical_module",
                "parent_id": module_id.rpartition(".")[0] or None,
                "file_count": len(module_files),
                "files": module_files,
                "incoming_count": len(incoming[module_id]),
                "outgoing_count": len(outgoing[module_id]),
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "nodes": nodes,
        "edges": edges,
        "diagnostics": diagnostics,
    }
