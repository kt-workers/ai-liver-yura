from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


TEST_ROOT = Path("tests")


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    category: str
    detail: str


class TestVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.findings: list[Finding] = []
        self.test_functions = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name.startswith("test_"):
            self.test_functions += 1
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node.name.startswith("test_"):
            self.test_functions += 1
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _qualified_name(node.func)
        category = _classify_call(name)
        if category is not None:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    category=category,
                    detail=name,
                )
            )
        self.generic_visit(node)


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _classify_call(name: str) -> str | None:
    if name in {"time.sleep", "asyncio.sleep"}:
        return "real_wait"
    if name.endswith(".join") or name in {"Event.wait", "Condition.wait"}:
        return "thread_wait"
    if name.startswith(("requests.", "httpx.", "urllib.")):
        return "network"
    if name.startswith(("subprocess.", "os.system")):
        return "subprocess"
    if name.startswith(("socket.", "sqlite3.", "psycopg.")):
        return "external_io"
    return None


def main() -> int:
    files = sorted(TEST_ROOT.rglob("test_*.py"))
    findings: list[Finding] = []
    test_count = 0

    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            print(f"PARSE_ERROR {path}: {exc}")
            continue
        visitor = TestVisitor(path)
        visitor.visit(tree)
        findings.extend(visitor.findings)
        test_count += visitor.test_functions

    by_category = Counter(item.category for item in findings)
    by_file = Counter(str(item.path) for item in findings)

    print(f"test_files={len(files)}")
    print(f"test_functions={test_count}")
    print("\n[category summary]")
    for category, count in sorted(by_category.items()):
        print(f"{category}: {count}")

    print("\n[files with timing or external-I/O candidates]")
    for path, count in by_file.most_common():
        print(f"{count:3d} {path}")

    print("\n[details]")
    for item in sorted(findings, key=lambda value: (str(value.path), value.line)):
        print(f"{item.path}:{item.line}: {item.category}: {item.detail}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
