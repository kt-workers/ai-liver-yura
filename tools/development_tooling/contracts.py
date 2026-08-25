"""#353の不変な読み取り専用Development Tooling契約。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from types import MappingProxyType

_SENSITIVE_MARKERS = (
    "api_key",
    "authorization",
    "bearer",
    "credential",
    "password",
    "secret",
    "token",
)


def _require_text(value: str, field_name: str, *, maximum: int = 4_096) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name}は空でない文字列である必要があります")
    if len(value) > maximum:
        raise ValueError(f"{field_name}が許容長を超えています")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ValueError(f"{field_name}に制御文字が含まれています")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name}はタイムゾーン付きである必要があります")


def _reject_sensitive_text(value: str, field_name: str) -> None:
    normalized = value.casefold()
    if any(marker in normalized for marker in _SENSITIVE_MARKERS):
        raise ValueError(f"{field_name}に機密情報らしき値を含められません")


def _freeze_text_mapping(value: Mapping[str, str], field_name: str) -> Mapping[str, str]:
    frozen: dict[str, str] = {}
    for key, item in value.items():
        _require_text(key, f"{field_name} key", maximum=256)
        _require_text(item, f"{field_name}[{key}]", maximum=4_096)
        _reject_sensitive_text(key, f"{field_name} key")
        _reject_sensitive_text(item, f"{field_name}[{key}]")
        frozen[key] = item
    return MappingProxyType(frozen)


class ToolKind(str, Enum):
    ISSUE_GRAPH = "issue_graph"
    ARCHITECTURE_GRAPH = "architecture_graph"
    CHARACTER_REFERENCE = "character_reference"
    MEDIA_ANALYSIS = "media_analysis"
    MIGRATION_AUDIT = "migration_audit"


class ArchitectureEdgeEvidence(str, Enum):
    CANONICAL = "canonical"
    EXPLICIT_TOOLING_CONFIG = "explicit_tooling_config"
    INFERRED = "inferred"


class CharacterFindingKind(str, Enum):
    OBSERVATION = "observation"
    INTERPRETATION = "interpretation"


class ToolingResultStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ToolingFailureCategory(str, Enum):
    SOURCE_UNAVAILABLE = "source_unavailable"
    INPUT_INVALID = "input_invalid"
    TOOL_UNAVAILABLE = "tool_unavailable"
    PROCESSING_FAILED = "processing_failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class SourceReference:
    source_ref: str
    source_revision: str

    def __post_init__(self) -> None:
        _require_text(self.source_ref, "source_ref", maximum=2_048)
        _require_text(self.source_revision, "source_revision", maximum=512)
        _reject_sensitive_text(self.source_ref, "source_ref")
        _reject_sensitive_text(self.source_revision, "source_revision")

    def to_dict(self) -> dict[str, str]:
        return {"source_ref": self.source_ref, "source_revision": self.source_revision}


@dataclass(frozen=True, slots=True)
class ToolingFinding:
    finding_id: str
    summary: str
    source_refs: tuple[SourceReference, ...]
    confidence: float | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.finding_id, "finding_id", maximum=256)
        _require_text(self.summary, "summary")
        references = tuple(self.source_refs)
        if not references or any(
            not isinstance(reference, SourceReference) for reference in references
        ):
            raise ValueError("source_refsは空にできません")
        if len({reference.source_ref for reference in references}) != len(references):
            raise ValueError("source_refsのsource_refは一意である必要があります")
        object.__setattr__(self, "source_refs", references)
        if self.confidence is not None and (
            type(self.confidence) not in {int, float} or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidenceは[0, 1]の範囲である必要があります")
        limitations = tuple(self.limitations)
        for limitation in limitations:
            _require_text(limitation, "limitation")
        object.__setattr__(self, "limitations", limitations)

    def to_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "summary": self.summary,
            "source_refs": [reference.to_dict() for reference in self.source_refs],
            "confidence": self.confidence,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class ToolingEvidenceArtifact:
    artifact_id: str
    tool_kind: ToolKind
    source_refs: tuple[SourceReference, ...]
    generated_at: datetime
    methodology_revision: str
    findings: tuple[ToolingFinding, ...]
    limitations: tuple[str, ...] = ()
    processing_duration_ms: float = 0.0
    deployment_generation: str = "local"
    result_status: ToolingResultStatus = ToolingResultStatus.SUCCEEDED
    failure_category: ToolingFailureCategory | None = None

    def __post_init__(self) -> None:
        _require_text(self.artifact_id, "artifact_id", maximum=256)
        if not isinstance(self.tool_kind, ToolKind):
            raise ValueError("tool_kindが不正です")
        source_refs = tuple(self.source_refs)
        if not source_refs or any(
            not isinstance(reference, SourceReference) for reference in source_refs
        ):
            raise ValueError("source_refsは空にできません")
        object.__setattr__(self, "source_refs", source_refs)
        _require_aware(self.generated_at, "generated_at")
        object.__setattr__(self, "generated_at", self.generated_at.astimezone(timezone.utc))
        _require_text(self.methodology_revision, "methodology_revision", maximum=512)
        findings = tuple(self.findings)
        if any(not isinstance(finding, ToolingFinding) for finding in findings):
            raise ValueError("findingsが不正です")
        if len({finding.finding_id for finding in findings}) != len(findings):
            raise ValueError("findingsのfinding_idは一意である必要があります")
        object.__setattr__(self, "findings", findings)
        limitations = tuple(self.limitations)
        for limitation in limitations:
            _require_text(limitation, "limitation")
        object.__setattr__(self, "limitations", limitations)
        if (
            type(self.processing_duration_ms) not in {int, float}
            or not isfinite(self.processing_duration_ms)
            or self.processing_duration_ms < 0
        ):
            raise ValueError("processing_duration_msが不正です")
        object.__setattr__(self, "processing_duration_ms", float(self.processing_duration_ms))
        _require_text(self.deployment_generation, "deployment_generation", maximum=256)
        if not isinstance(self.result_status, ToolingResultStatus):
            raise ValueError("result_statusが不正です")
        if self.failure_category is not None and not isinstance(
            self.failure_category, ToolingFailureCategory
        ):
            raise ValueError("failure_categoryが不正です")
        if (self.result_status is ToolingResultStatus.FAILED) != (
            self.failure_category is not None
        ):
            raise ValueError("result_statusとfailure_categoryが一致しません")

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "tool_kind": self.tool_kind.value,
            "source_refs": [reference.to_dict() for reference in self.source_refs],
            "generated_at": self.generated_at.isoformat(),
            "methodology_revision": self.methodology_revision,
            "findings": [finding.to_dict() for finding in self.findings],
            "limitations": list(self.limitations),
            "processing_duration_ms": self.processing_duration_ms,
            "deployment_generation": self.deployment_generation,
            "result_status": self.result_status.value,
            "failure_category": None
            if self.failure_category is None
            else self.failure_category.value,
        }


@dataclass(frozen=True, slots=True)
class IssueGraphNode:
    issue_id: str
    title: str
    state: str
    relation_metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.issue_id, "issue_id", maximum=256)
        _require_text(self.title, "title")
        _require_text(self.state, "state", maximum=128)
        object.__setattr__(
            self,
            "relation_metadata",
            _freeze_text_mapping(self.relation_metadata, "relation_metadata"),
        )

    def to_browser_dict(self) -> dict[str, object]:
        return {
            "issue_id": self.issue_id,
            "title": self.title,
            "state": self.state,
            "relation_metadata": dict(self.relation_metadata),
        }


@dataclass(frozen=True, slots=True)
class IssueGraphEdge:
    source_issue_id: str
    target_issue_id: str
    relation: str

    def __post_init__(self) -> None:
        _require_text(self.source_issue_id, "source_issue_id", maximum=256)
        _require_text(self.target_issue_id, "target_issue_id", maximum=256)
        _require_text(self.relation, "relation", maximum=256)
        if self.source_issue_id == self.target_issue_id:
            raise ValueError("Issue graphでは自己edgeを許可しません")

    def to_browser_dict(self) -> dict[str, str]:
        return {
            "source_issue_id": self.source_issue_id,
            "target_issue_id": self.target_issue_id,
            "relation": self.relation,
        }


@dataclass(frozen=True, slots=True)
class IssueGraph:
    nodes: tuple[IssueGraphNode, ...]
    edges: tuple[IssueGraphEdge, ...]
    source_refs: tuple[SourceReference, ...]

    def __post_init__(self) -> None:
        nodes = tuple(self.nodes)
        if len({node.issue_id for node in nodes}) != len(nodes):
            raise ValueError("Issue graphのnode identityは一意である必要があります")
        node_ids = {node.issue_id for node in nodes}
        edges = tuple(self.edges)
        if any(
            edge.source_issue_id not in node_ids or edge.target_issue_id not in node_ids
            for edge in edges
        ):
            raise ValueError("Issue graphのedgeはgraph nodeを参照する必要があります")
        source_refs = tuple(self.source_refs)
        if not source_refs:
            raise ValueError("Issue graphにはsource_refsが必要です")
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)
        object.__setattr__(self, "source_refs", source_refs)

    def to_browser_dict(self) -> dict[str, object]:
        return {
            "nodes": [node.to_browser_dict() for node in self.nodes],
            "edges": [edge.to_browser_dict() for edge in self.edges],
            "source_refs": [reference.to_dict() for reference in self.source_refs],
        }


@dataclass(frozen=True, slots=True)
class ArchitectureEdge:
    source_module: str
    target_module: str
    relation: str
    evidence: ArchitectureEdgeEvidence
    source_refs: tuple[SourceReference, ...]

    def __post_init__(self) -> None:
        _require_text(self.source_module, "source_module", maximum=256)
        _require_text(self.target_module, "target_module", maximum=256)
        _require_text(self.relation, "relation", maximum=256)
        if self.source_module == self.target_module:
            raise ValueError("Architecture graphでは自己edgeを許可しません")
        if not isinstance(self.evidence, ArchitectureEdgeEvidence):
            raise ValueError("evidenceが不正です")
        references = tuple(self.source_refs)
        if not references or any(
            not isinstance(reference, SourceReference) for reference in references
        ):
            raise ValueError("source_refsは空にできません")
        object.__setattr__(self, "source_refs", references)

    def to_browser_dict(self) -> dict[str, object]:
        return {
            "source_module": self.source_module,
            "target_module": self.target_module,
            "relation": self.relation,
            "evidence": self.evidence.value,
            "inferred": self.evidence is ArchitectureEdgeEvidence.INFERRED,
            "source_refs": [reference.to_dict() for reference in self.source_refs],
        }


@dataclass(frozen=True, slots=True)
class ArchitectureGraph:
    edges: tuple[ArchitectureEdge, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "edges", tuple(self.edges))

    def to_browser_dict(self) -> dict[str, object]:
        return {"edges": [edge.to_browser_dict() for edge in self.edges]}


@dataclass(frozen=True, slots=True)
class MediaAnalysisProvenance:
    """外部model/tool由来の候補分析を再現可能な範囲で記録する。"""

    tool_revision: str
    parameters: Mapping[str, str]
    retention_policy_ref: str

    def __post_init__(self) -> None:
        _require_text(self.tool_revision, "tool_revision", maximum=512)
        _require_text(self.retention_policy_ref, "retention_policy_ref", maximum=512)
        object.__setattr__(self, "parameters", _freeze_text_mapping(self.parameters, "parameters"))

    def to_dict(self) -> dict[str, object]:
        return {
            "tool_revision": self.tool_revision,
            "parameters": dict(self.parameters),
            "retention_policy_ref": self.retention_policy_ref,
        }


@dataclass(frozen=True, slots=True)
class ReferenceCharacterFinding:
    finding_id: str
    finding_kind: CharacterFindingKind
    source_media: SourceReference
    analysis_provenance: MediaAnalysisProvenance
    observed_feature: str
    evidence_interval: tuple[float, float] | None
    confidence: float | None
    interpretation_notes: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.finding_id, "finding_id", maximum=256)
        _require_text(self.observed_feature, "observed_feature")
        if not isinstance(self.finding_kind, CharacterFindingKind):
            raise ValueError("finding_kindが不正です")
        if not isinstance(self.source_media, SourceReference):
            raise ValueError("source_mediaが不正です")
        if not isinstance(self.analysis_provenance, MediaAnalysisProvenance):
            raise ValueError("analysis_provenanceが不正です")
        if self.evidence_interval is not None:
            interval = tuple(self.evidence_interval)
            if len(interval) != 2 or any(type(point) not in {int, float} for point in interval):
                raise ValueError("evidence_intervalは二つの数値pointを含む必要があります")
            if not all(isfinite(point) for point in interval):
                raise ValueError("evidence_intervalは有限値である必要があります")
            if interval[0] < 0 or interval[1] < interval[0]:
                raise ValueError("evidence_intervalは非負かつ順序付きである必要があります")
            object.__setattr__(self, "evidence_interval", interval)
        if self.confidence is not None and (
            type(self.confidence) not in {int, float} or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidenceは[0, 1]の範囲である必要があります")
        if self.finding_kind is CharacterFindingKind.OBSERVATION and self.interpretation_notes:
            raise ValueError("observationにinterpretation_notesを含められません")
        if self.interpretation_notes is not None:
            _require_text(self.interpretation_notes, "interpretation_notes")

    def to_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "finding_kind": self.finding_kind.value,
            "source_media": self.source_media.to_dict(),
            "analysis_provenance": self.analysis_provenance.to_dict(),
            "observed_feature": self.observed_feature,
            "evidence_interval": list(self.evidence_interval) if self.evidence_interval else None,
            "confidence": self.confidence,
            "interpretation_notes": self.interpretation_notes,
            "disposition": "candidate_only",
        }


@dataclass(frozen=True, slots=True)
class BrowserToolingConfig:
    service_name: str
    deployment_generation: str
    healthy: bool

    def __post_init__(self) -> None:
        _require_text(self.service_name, "service_name", maximum=256)
        _require_text(self.deployment_generation, "deployment_generation", maximum=256)

    def to_dict(self) -> dict[str, object]:
        return {
            "service_name": self.service_name,
            "deployment_generation": self.deployment_generation,
            "healthy": self.healthy,
        }


@dataclass(frozen=True, slots=True)
class ToolingServerConfig:
    service_name: str
    deployment_generation: str
    github_token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_text(self.service_name, "service_name", maximum=256)
        _require_text(self.deployment_generation, "deployment_generation", maximum=256)
        if self.github_token is not None:
            _require_text(self.github_token, "github_token", maximum=8_192)

    def browser_config(self, *, healthy: bool) -> BrowserToolingConfig:
        return BrowserToolingConfig(self.service_name, self.deployment_generation, healthy)


def bounded_text_sequence(
    values: Sequence[str], field_name: str, *, maximum: int = 128
) -> tuple[str, ...]:
    result = tuple(values)
    if len(result) > maximum:
        raise ValueError(f"{field_name}が許容item数を超えています")
    for value in result:
        _require_text(value, field_name)
    return result
