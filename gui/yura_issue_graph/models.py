from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

_PARENT_RE = re.compile(r"(?im)^\s*Parent\s*:\s*#(\d+)\b")
_DEPENDS_LINE_RE = re.compile(r"(?im)^\s*(?:Depends\s+on|依存)\s*:\s*([^\n]+)")
_ISSUE_REF_RE = re.compile(r"#(\d+)\b")
_PR_RE = re.compile(r"(?i)\b(?:Draft\s+)?PR\s*#(\d+)\b")
_ISSUE_LEVEL_RE = re.compile(
    r"(?im)^\s*(?:\*\*)?(?:Issueレベル|Issue\s+level)(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*(Parent|Work|Integration|Management)\b"
)
_ISSUE_LEVEL_HEADING_RE = re.compile(
    r"(?im)^\s*#{1,6}\s*(?:Issueレベル|Issue\s+level)\s*$\s*^\s*(?:\*\*)?(Parent|Work|Integration|Management)(?:\*\*)?\s*$"
)


@dataclass(slots=True)
class IssueNode:
    number: int
    title: str
    body: str
    url: str
    state: str
    updated_at: str | None = None
    parent_number: int | None = None
    child_numbers: list[int] = field(default_factory=list)
    dependency_numbers: list[int] = field(default_factory=list)
    related_pr_numbers: list[int] = field(default_factory=list)
    status: str | None = None
    issue_level: str | None = None
    work_type: str | None = None
    area: str | None = None
    priority: str | None = None
    process: float | str | None = None
    start_date: str | None = None
    target_date: str | None = None
    project_item_id: str | None = None

    @property
    def summary(self) -> str:
        text = re.sub(r"```.*?```", " ", self.body, flags=re.S)
        text = re.sub(r"(?m)^#+\s*", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:420]

    def apply_compatibility_relations(self) -> None:
        if self.parent_number is None:
            parent = extract_parent_number(self.body)
            if parent != self.number:
                self.parent_number = parent
        if not self.dependency_numbers:
            self.dependency_numbers = extract_dependency_numbers(self.body, self.number)
        self.related_pr_numbers = sorted(
            set(self.related_pr_numbers) | set(extract_related_pr_numbers(self.body))
        )
        if self.issue_level is None:
            self.issue_level = extract_issue_level(self.body)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = self.summary
        return payload


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: int
    target: int
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_parent_number(body: str) -> int | None:
    match = _PARENT_RE.search(body or "")
    return int(match.group(1)) if match else None


def extract_dependency_numbers(body: str, self_number: int | None = None) -> list[int]:
    found: set[int] = set()
    for match in _DEPENDS_LINE_RE.finditer(body or ""):
        for value in _ISSUE_REF_RE.findall(match.group(1)):
            number = int(value)
            if number != self_number:
                found.add(number)
    return sorted(found)


def extract_related_pr_numbers(body: str) -> list[int]:
    return sorted({int(value) for value in _PR_RE.findall(body or "")})


def extract_issue_level(body: str) -> str | None:
    text = body or ""
    match = _ISSUE_LEVEL_RE.search(text) or _ISSUE_LEVEL_HEADING_RE.search(text)
    return match.group(1) if match else None


def build_edges(nodes: list[IssueNode]) -> list[GraphEdge]:
    numbers = {node.number for node in nodes}
    edges: set[tuple[int, int, str]] = set()
    for node in nodes:
        if node.parent_number in numbers and node.parent_number != node.number:
            edges.add((int(node.parent_number), node.number, "parent"))
        for child in node.child_numbers:
            if child in numbers and child != node.number:
                edges.add((node.number, child, "parent"))
        for dependency in node.dependency_numbers:
            if dependency in numbers and dependency != node.number:
                edges.add((dependency, node.number, "dependency"))
    return [GraphEdge(*edge) for edge in sorted(edges)]
