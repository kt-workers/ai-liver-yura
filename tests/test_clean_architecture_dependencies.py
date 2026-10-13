"""Domainから外側の層への逆依存を防止する構造検査。"""

from __future__ import annotations

import ast
from pathlib import Path

from app.domain.llm.ports import LLMRolePort
from app.usecases.ports.llm import LLMRolePort as LegacyLLMRolePort


_DOMAIN = Path(__file__).resolve().parents[1] / "app" / "domain"


def test_domain_does_not_import_outer_layers() -> None:
    violations: list[str] = []
    for path in sorted(_DOMAIN.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                modules = tuple(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules = (node.module,) if node.module is not None else ()
            for module in modules:
                if module == "app" or (
                    module.startswith("app.")
                    and module != "app.domain"
                    and not module.startswith("app.domain.")
                ):
                    violations.append(f"{path.relative_to(_DOMAIN)}:{node.lineno} -> {module}")
    assert not violations, "Domainから外側の層を参照しています:\n" + "\n".join(violations)


def test_previous_llm_port_import_is_same_contract() -> None:
    assert LegacyLLMRolePort is LLMRolePort
