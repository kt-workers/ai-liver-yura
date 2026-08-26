"""任意レビュー支援の不変契約。"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Final

MAX_FINDINGS: Final = 50
MAX_TEXT_LENGTH: Final = 8_000
MAX_PATH_LENGTH: Final = 512


class ReviewAdvisoryAvailability(str, Enum):
    """任意backendの結果を、Gateと切り離して表す。"""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    STALE_TARGET = "STALE_TARGET"


class OptionalReviewOutputError(ValueError):
    """backendが構造化出力の変換失敗だけを明示するための専用例外。"""


def _require_text(value: str, field_name: str, maximum: int = MAX_TEXT_LENGTH) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} は空でない文字列である必要があります。")
    if len(value) > maximum:
        raise ValueError(f"{field_name} が上限を超えています。")


def _require_sha(value: str, field_name: str) -> None:
    _require_text(value, field_name, 64)
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} は40文字の小文字SHAである必要があります。")


def _sanitize_presentation(value: str) -> str:
    """モデル由来表示値を、通知・HTML・Markdown制御なしの平文へ正規化する。"""

    _require_text(value, "表示値")
    result = "".join(
        character
        for character in value
        if character in "\n\t" or not unicodedata.category(character).startswith("C")
    )
    result = result.replace("@", "＠")
    for source, replacement in (
        ("<", "＆lt;"),
        (">", "＆gt;"),
        ("[", "［"),
        ("]", "］"),
        ("`", "｀"),
    ):
        result = result.replace(source, replacement)
    return result


def _require_safe_repository_path(value: str) -> None:
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("finding path にcontrol characterは使用できません。")


@dataclass(frozen=True)
class ReviewTarget:
    """明示要求時点に固定する読取専用review対象。"""

    repository: str
    pull_request_number: int
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str

    def __post_init__(self) -> None:
        _require_text(self.repository, "repository", 256)
        if self.repository.count("/") != 1:
            raise ValueError("repository は owner/name 形式である必要があります。")
        if (
            not isinstance(self.pull_request_number, int)
            or isinstance(self.pull_request_number, bool)
            or self.pull_request_number <= 0
        ):
            raise ValueError("pull_request_number は正の整数である必要があります。")
        _require_text(self.base_ref, "base_ref", 256)
        _require_text(self.head_ref, "head_ref", 256)
        _require_sha(self.base_sha, "base_sha")
        _require_sha(self.head_sha, "head_sha")

    @property
    def identity_key(self) -> str:
        return f"{self.repository}#{self.pull_request_number}:{self.head_sha}"


@dataclass(frozen=True)
class ReviewerIdentity:
    """backend出力と別に監査するconfigured reviewer identity。"""

    agent_id: str
    session_id: str
    provider: str

    def __post_init__(self) -> None:
        _require_text(self.agent_id, "agent_id", 256)
        _require_text(self.session_id, "session_id", 256)
        _require_text(self.provider, "provider", 256)


@dataclass(frozen=True)
class AdvisoryFinding:
    """backendが返した、まだ表示安全化されていないfinding。"""

    title: str
    explanation: str
    path: str | None = None
    line: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.title, "finding title", 500)
        _require_text(self.explanation, "finding explanation")
        if self.path is not None:
            _require_text(self.path, "finding path", MAX_PATH_LENGTH)
            _require_safe_repository_path(self.path)
            if self.path.startswith("/") or ".." in self.path.split("/"):
                raise ValueError("finding path はrepository相対の安全なpathである必要があります。")
        if self.line is not None and (
            not isinstance(self.line, int) or isinstance(self.line, bool) or self.line <= 0
        ):
            raise ValueError("finding line は正の整数である必要があります。")


@dataclass(frozen=True)
class AdvisoryCandidate:
    """任意backendから受け取る未信頼候補。"""

    echoed_head_sha: str
    summary: str
    findings: tuple[AdvisoryFinding, ...] = ()

    def __post_init__(self) -> None:
        _require_sha(self.echoed_head_sha, "echoed_head_sha")
        _require_text(self.summary, "summary")
        if len(self.findings) > MAX_FINDINGS:
            raise ValueError("findings が上限を超えています。")
        if any(not isinstance(finding, AdvisoryFinding) for finding in self.findings):
            raise ValueError("findings の要素が不正です。")


@dataclass(frozen=True)
class ReviewContextInput:
    """read-only sourceから受け取る、target以外の収集済み入力。"""

    implementer: ReviewerIdentity
    reviewer: ReviewerIdentity
    issue_references: tuple[int, ...]
    canonical_references: tuple[str, ...]
    gate_evidence: tuple[str, ...]
    untrusted_pr_data: str

    def __post_init__(self) -> None:
        if not isinstance(self.implementer, ReviewerIdentity) or not isinstance(
            self.reviewer, ReviewerIdentity
        ):
            raise ValueError("identity が不正です。")
        if any(
            not isinstance(reference, int) or isinstance(reference, bool) or reference <= 0
            for reference in self.issue_references
        ):
            raise ValueError("issue_references が不正です。")
        if len(set(self.issue_references)) != len(self.issue_references):
            raise ValueError("issue_references は重複できません。")
        for reference in (*self.canonical_references, *self.gate_evidence):
            _require_text(reference, "trusted reference", 1_024)
        _require_text(self.untrusted_pr_data, "untrusted_pr_data")


@dataclass(frozen=True)
class ReviewContext:
    """trusted targetとuntrusted review dataを明示分離する収集結果。"""

    target: ReviewTarget
    implementer: ReviewerIdentity
    reviewer: ReviewerIdentity
    issue_references: tuple[int, ...]
    canonical_references: tuple[str, ...]
    gate_evidence: tuple[str, ...]
    untrusted_pr_data: str
    collected_at: datetime
    context_generation: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.target, ReviewTarget):
            raise ValueError("target が不正です。")
        if not isinstance(self.implementer, ReviewerIdentity) or not isinstance(
            self.reviewer, ReviewerIdentity
        ):
            raise ValueError("identity が不正です。")
        if (
            self.implementer.agent_id == self.reviewer.agent_id
            or self.implementer.session_id == self.reviewer.session_id
        ):
            raise ValueError("implementerとreviewerは同じagent/sessionを使用できません。")
        if any(
            not isinstance(reference, int) or isinstance(reference, bool) or reference <= 0
            for reference in self.issue_references
        ):
            raise ValueError("issue_references が不正です。")
        if len(set(self.issue_references)) != len(self.issue_references):
            raise ValueError("issue_references は重複できません。")
        for reference in (*self.canonical_references, *self.gate_evidence):
            _require_text(reference, "trusted reference", 1_024)
        _require_text(self.untrusted_pr_data, "untrusted_pr_data")
        if self.collected_at.tzinfo is None:
            raise ValueError("collected_at はtimezone-awareである必要があります。")
        generation_source = json.dumps(
            {
                "target": {
                    "repository": self.target.repository,
                    "pull_request_number": self.target.pull_request_number,
                    "base_ref": self.target.base_ref,
                    "base_sha": self.target.base_sha,
                    "head_ref": self.target.head_ref,
                    "head_sha": self.target.head_sha,
                },
                "implementer": {
                    "agent_id": self.implementer.agent_id,
                    "session_id": self.implementer.session_id,
                    "provider": self.implementer.provider,
                },
                "reviewer": {
                    "agent_id": self.reviewer.agent_id,
                    "session_id": self.reviewer.session_id,
                    "provider": self.reviewer.provider,
                },
                "issue_references": self.issue_references,
                "canonical_references": self.canonical_references,
                "gate_evidence": self.gate_evidence,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        object.__setattr__(
            self, "context_generation", sha256(generation_source.encode()).hexdigest()
        )

    @classmethod
    def now(
        cls,
        *,
        target: ReviewTarget,
        implementer: ReviewerIdentity,
        reviewer: ReviewerIdentity,
        issue_references: tuple[int, ...],
        canonical_references: tuple[str, ...],
        gate_evidence: tuple[str, ...],
        untrusted_pr_data: str,
    ) -> ReviewContext:
        return cls(
            target=target,
            implementer=implementer,
            reviewer=reviewer,
            issue_references=issue_references,
            canonical_references=canonical_references,
            gate_evidence=gate_evidence,
            untrusted_pr_data=untrusted_pr_data,
            collected_at=datetime.now(timezone.utc),
        )


@dataclass(frozen=True)
class ReviewAdvisory:
    """Gate Authorityへ昇格しない、表示安全化済みの助言。"""

    target: ReviewTarget
    context_generation: str
    collected_at: datetime
    availability: ReviewAdvisoryAvailability
    summary: str
    findings: tuple[AdvisoryFinding, ...] = ()
    diagnostic_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, ReviewTarget):
            raise ValueError("target が不正です。")
        if not isinstance(self.availability, ReviewAdvisoryAvailability):
            raise ValueError("availability が不正です。")
        _require_text(self.context_generation, "context_generation", 64)
        if self.collected_at.tzinfo is None:
            raise ValueError("collected_at はtimezone-awareである必要があります。")
        _require_text(self.summary, "summary")
        if self.diagnostic_code is not None:
            _require_text(self.diagnostic_code, "diagnostic_code", 128)
        if len(self.findings) > MAX_FINDINGS:
            raise ValueError("findings が上限を超えています。")
        if any(not isinstance(finding, AdvisoryFinding) for finding in self.findings):
            raise ValueError("findings の要素が不正です。")
