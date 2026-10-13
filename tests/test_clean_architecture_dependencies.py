"""純粋なDomainと外部呼出しUseCaseの依存方向を確認する。"""

from __future__ import annotations

import ast
from pathlib import Path

from app.usecases.appraisal import DeepAppraisalInterpreter
from app.usecases.input_meaning import InputMeaningInterpreter
from app.usecases.ports.llm import LLMRolePort

_ROOT = Path(__file__).resolve().parents[1]


def test_appraisal_and_input_meaning_domain_do_not_depend_on_outer_layers() -> None:
    violations: list[str] = []
    for package in ("appraisal", "input_meaning"):
        folder = _ROOT / "app" / "domain" / package
        for path in sorted(folder.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules: tuple[str, ...] = ()
                if isinstance(node, ast.Import):
                    modules = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    modules = (node.module,) if node.module is not None else ()
                for name in modules:
                    if name == "app" or (
                        name.startswith("app.")
                        and name != "app.domain"
                        and not name.startswith("app.domain.")
                    ):
                        violations.append(f"{path.relative_to(_ROOT)}:{node.lineno}: {name}")
    assert not violations, "Domainから外側への逆依存:\n" + "\n".join(violations)


def test_llm_interpreters_are_application_services() -> None:
    assert DeepAppraisalInterpreter.__module__ == "app.usecases.appraisal"
    assert InputMeaningInterpreter.__module__ == "app.usecases.input_meaning"
    assert LLMRolePort.__module__ == "app.usecases.ports.llm"
