"""#353の安全な投影・監査サービス。外部I/OとGitHub mutationは所有しない。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from .contracts import (
    ArchitectureEdge,
    ArchitectureEdgeEvidence,
    ArchitectureGraph,
    CharacterFindingKind,
    IssueGraph,
    IssueGraphEdge,
    IssueGraphNode,
    MediaAnalysisProvenance,
    ReferenceCharacterFinding,
    SourceReference,
    ToolingEvidenceArtifact,
    ToolingFailureCategory,
    ToolingFinding,
    ToolingResultStatus,
    ToolKind,
    bounded_text_sequence,
)


class GitHubIssueProjector:
    """認証済みserver-side adapterが得た最小Issue情報だけをbrowser DTOへ投影する。"""

    _SAFE_ISSUE_FIELDS = frozenset({"id", "number", "title", "state", "relations"})

    def project_node(self, raw_issue: Mapping[str, object]) -> IssueGraphNode:
        unknown = set(raw_issue).difference(self._SAFE_ISSUE_FIELDS)
        if unknown:
            raise ValueError("raw GitHub payloadはprojection前にsanitize済みである必要があります")
        issue_identity = raw_issue.get("id", raw_issue.get("number"))
        if not isinstance(issue_identity, (str, int)):
            raise ValueError("safe Issue payloadにはidまたはnumberが必要です")
        title = raw_issue.get("title")
        state = raw_issue.get("state")
        if not isinstance(title, str) or not isinstance(state, str):
            raise ValueError("safe Issue payloadにはtitleとstateが必要です")
        relations = raw_issue.get("relations", {})
        if not isinstance(relations, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in relations.items()
        ):
            raise ValueError("relationsは文字列mappingである必要があります")
        return IssueGraphNode(str(issue_identity), title, state, relations)

    def project_graph(
        self,
        raw_issues: Sequence[Mapping[str, object]],
        edges: Sequence[IssueGraphEdge],
        source_refs: Sequence[SourceReference],
    ) -> IssueGraph:
        return IssueGraph(
            tuple(self.project_node(issue) for issue in raw_issues),
            tuple(edges),
            tuple(source_refs),
        )


class ArchitectureGraphProjector:
    """canonicalまたは明示的tooling設定を明確に分けて構造を可視化する。"""

    def project(self, edges: Sequence[ArchitectureEdge]) -> ArchitectureGraph:
        return ArchitectureGraph(tuple(edges))

    def inferred_edge(
        self,
        *,
        source_module: str,
        target_module: str,
        relation: str,
        source_ref: SourceReference,
    ) -> ArchitectureEdge:
        return ArchitectureEdge(
            source_module,
            target_module,
            relation,
            ArchitectureEdgeEvidence.INFERRED,
            (source_ref,),
        )


class ReferenceAnalysisProjector:
    """参照分析を候補観測として扱い、Character Definitionを書き換えない。"""

    def observation(
        self,
        *,
        finding_id: str,
        source_media: SourceReference,
        analysis_provenance: MediaAnalysisProvenance,
        observed_feature: str,
        evidence_interval: tuple[float, float] | None,
        confidence: float | None,
    ) -> ReferenceCharacterFinding:
        return ReferenceCharacterFinding(
            finding_id,
            CharacterFindingKind.OBSERVATION,
            source_media,
            analysis_provenance,
            observed_feature,
            evidence_interval,
            confidence,
        )

    def interpretation(
        self,
        *,
        finding_id: str,
        source_media: SourceReference,
        analysis_provenance: MediaAnalysisProvenance,
        observed_feature: str,
        evidence_interval: tuple[float, float] | None,
        confidence: float | None,
        interpretation_notes: str,
    ) -> ReferenceCharacterFinding:
        return ReferenceCharacterFinding(
            finding_id,
            CharacterFindingKind.INTERPRETATION,
            source_media,
            analysis_provenance,
            observed_feature,
            evidence_interval,
            confidence,
            interpretation_notes,
        )


class DevelopmentAuditService:
    """読み取り専用候補をartifact化する。発見結果から変更を実行しない。"""

    def report(
        self,
        *,
        artifact_id: str,
        tool_kind: ToolKind,
        source_refs: Sequence[SourceReference],
        generated_at: datetime,
        methodology_revision: str,
        findings: Sequence[ToolingFinding],
        limitations: Sequence[str] = (),
        processing_duration_ms: float = 0.0,
        deployment_generation: str = "local",
        result_status: ToolingResultStatus = ToolingResultStatus.SUCCEEDED,
        failure_category: ToolingFailureCategory | None = None,
    ) -> ToolingEvidenceArtifact:
        return ToolingEvidenceArtifact(
            artifact_id=artifact_id,
            tool_kind=tool_kind,
            source_refs=tuple(source_refs),
            generated_at=generated_at,
            methodology_revision=methodology_revision,
            findings=tuple(findings),
            limitations=bounded_text_sequence(limitations, "limitations"),
            processing_duration_ms=processing_duration_ms,
            deployment_generation=deployment_generation,
            result_status=result_status,
            failure_category=failure_category,
        )
