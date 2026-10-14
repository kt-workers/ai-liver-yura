"""移動した実行責務を起動入口や外側の実装へ戻さない。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "path",
    [
        "app/usecases/brain_input_meaning.py",
        "app/usecases/task_cleanup.py",
        "app/usecases/ports/cancellation.py",
    ],
)
def test_extracted_execution_dependencies_point_inward(path: str) -> None:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    forbidden = (
        "app.application",
        "app.composition",
        "app.config",
        "app.adapters",
        "app.infrastructure",
        "app.subsystems",
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "実行責務の依存先を明示する"
            modules = [node.module or ""]
        else:
            continue
        for module in modules:
            assert not any(module == item or module.startswith(item + ".") for item in forbidden)


def test_entrypoint_no_longer_implements_input_meaning_or_task_reaping() -> None:
    tree = ast.parse((ROOT / "app/application.py").read_text(encoding="utf-8"))
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert definitions.isdisjoint(
        {
            "InputMeaningBrainWorkPayload",
            "InputMeaningBrainModulePort",
            "UnavailableInputMeaningLiveContextPort",
            "_reap_cleanup",
        }
    )


@pytest.mark.parametrize(
    "path",
    [
        "app/composition/system_cognition_configuration.py",
        "app/composition/core_provider.py",
        "app/adapters/llm/core.py",
    ],
)
def test_consumers_do_not_get_task_cleanup_from_entrypoint(path: str) -> None:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.application":
            assert "_reap_cleanup" not in {item.name for item in node.names}
