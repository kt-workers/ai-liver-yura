from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest

from tools.development_tooling import (
    ArchitectureEdge,
    ArchitectureEdgeEvidence,
    ArchitectureGraphProjector,
    DevelopmentAuditService,
    GitHubIssueProjector,
    IssueGraphEdge,
    MediaAnalysisProvenance,
    ReferenceAnalysisProjector,
    SourceReference,
    ToolingEvidenceArtifact,
    ToolingFinding,
    ToolingServerConfig,
    ToolKind,
)
from tools.development_tooling.untrusted import parse_bounded_json_object

NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)
CANONICAL = SourceReference("docs/architecture/v2/development_tooling_contracts.md", "80d1d96")
MEDIA_ANALYSIS = MediaAnalysisProvenance(
    "model-1",
    {"language": "ja", "sample_rate": "48000"},
    "retention-policy-1",
)


def test_github_token_is_absent_from_browser_payload_and_raw_payload_is_rejected() -> None:
    config = ToolingServerConfig("development-tooling", "generation-1", "ghs_very_secret")

    assert "ghs_very_secret" not in repr(config)
    assert config.browser_config(healthy=True).to_dict() == {
        "service_name": "development-tooling",
        "deployment_generation": "generation-1",
        "healthy": True,
    }

    projector = GitHubIssueProjector()
    with pytest.raises(ValueError):
        projector.project_node(
            {
                "id": "353",
                "title": "開発支援",
                "state": "OPEN",
                "authorization": "Bearer ghs_very_secret",
            }
        )


def test_safe_issue_graph_projection_is_read_only_and_layout_has_no_issue_authority() -> None:
    raw_issue = {
        "id": "353",
        "title": "開発支援",
        "state": "OPEN",
        "relations": {"parent": "345"},
    }
    graph = GitHubIssueProjector().project_graph(
        [raw_issue, {"id": "345", "title": "Subsystem", "state": "OPEN"}],
        [IssueGraphEdge("353", "345", "parent")],
        [CANONICAL],
    )

    assert graph.to_browser_dict() == {
        "nodes": [
            {
                "issue_id": "353",
                "title": "開発支援",
                "state": "OPEN",
                "relation_metadata": {"parent": "345"},
            },
            {"issue_id": "345", "title": "Subsystem", "state": "OPEN", "relation_metadata": {}},
        ],
        "edges": [{"source_issue_id": "353", "target_issue_id": "345", "relation": "parent"}],
        "source_refs": [CANONICAL.to_dict()],
    }
    assert raw_issue == {
        "id": "353",
        "title": "開発支援",
        "state": "OPEN",
        "relations": {"parent": "345"},
    }
    with pytest.raises(TypeError):
        graph.nodes[0].relation_metadata["layout_x"] = "100"  # type: ignore[index]

    with pytest.raises(ValueError):
        GitHubIssueProjector().project_graph(
            [{"id": "353", "title": "開発支援", "state": "OPEN"}], [], []
        )


def test_inferred_architecture_edge_is_explicitly_labelled_and_not_canonical() -> None:
    edge = ArchitectureGraphProjector().inferred_edge(
        source_module="repository_scan",
        target_module="app.domain.memory",
        relation="directory_contains",
        source_ref=SourceReference("app/domain/memory", "80d1d96"),
    )
    graph = ArchitectureGraphProjector().project([edge])

    assert graph.to_browser_dict()["edges"] == [
        {
            "source_module": "repository_scan",
            "target_module": "app.domain.memory",
            "relation": "directory_contains",
            "evidence": ArchitectureEdgeEvidence.INFERRED.value,
            "inferred": True,
            "source_refs": [{"source_ref": "app/domain/memory", "source_revision": "80d1d96"}],
        }
    ]


def test_explicit_architecture_edge_retains_canonical_provenance() -> None:
    edge = ArchitectureEdge(
        "development_tooling",
        "public_contracts",
        "reads",
        ArchitectureEdgeEvidence.CANONICAL,
        (CANONICAL,),
    )

    browser_edges = cast(
        list[dict[str, object]],
        ArchitectureGraphProjector().project([edge]).to_browser_dict()["edges"],
    )
    projected_edge = browser_edges[0]
    assert projected_edge["inferred"] is False


def test_reference_analysis_creates_candidate_only_and_never_updates_character_definition() -> None:
    finding = ReferenceAnalysisProjector().observation(
        finding_id="finding-1",
        source_media=SourceReference("reference/yura.mp4", "sha256:abc"),
        analysis_provenance=MEDIA_ANALYSIS,
        observed_feature="発話開始時に視線が下がる",
        evidence_interval=(1.2, 2.0),
        confidence=0.7,
    )

    assert finding.to_dict() == {
        "finding_id": "finding-1",
        "finding_kind": "observation",
        "source_media": {"source_ref": "reference/yura.mp4", "source_revision": "sha256:abc"},
        "analysis_provenance": {
            "tool_revision": "model-1",
            "parameters": {"language": "ja", "sample_rate": "48000"},
            "retention_policy_ref": "retention-policy-1",
        },
        "observed_feature": "発話開始時に視線が下がる",
        "evidence_interval": [1.2, 2.0],
        "confidence": 0.7,
        "interpretation_notes": None,
        "disposition": "candidate_only",
    }
    assert "CharacterDefinition" not in Path("tools/development_tooling/service.py").read_text(
        encoding="utf-8"
    )


def test_reference_observation_and_interpretation_are_separate() -> None:
    projector = ReferenceAnalysisProjector()
    media = SourceReference("reference/yura.mp4", "sha256:abc")

    observation = projector.observation(
        finding_id="observation-1",
        source_media=media,
        analysis_provenance=MEDIA_ANALYSIS,
        observed_feature="肩の動き",
        evidence_interval=None,
        confidence=None,
    )
    interpretation = projector.interpretation(
        finding_id="interpretation-1",
        source_media=media,
        analysis_provenance=MEDIA_ANALYSIS,
        observed_feature="肩の動き",
        evidence_interval=None,
        confidence=0.5,
        interpretation_notes="緊張の可能性",
    )

    assert observation.to_dict()["interpretation_notes"] is None
    assert interpretation.to_dict()["interpretation_notes"] == "緊張の可能性"


def test_media_analysis_provenance_retains_tool_parameters_and_retention_policy() -> None:
    assert MEDIA_ANALYSIS.to_dict() == {
        "tool_revision": "model-1",
        "parameters": {"language": "ja", "sample_rate": "48000"},
        "retention_policy_ref": "retention-policy-1",
    }


def test_public_source_and_media_parameters_reject_secret_like_values() -> None:
    with pytest.raises(ValueError):
        SourceReference("https://example.invalid/media?token=secret", "revision-1")
    with pytest.raises(ValueError):
        MediaAnalysisProvenance("model-1", {"api_key": "secret"}, "retention-policy-1")


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b"[]",
        b'{"command":"rm -rf /"}',
        b"x" * 32,
    ],
)
def test_malformed_or_untrusted_payload_is_bounded_data_only(payload: bytes) -> None:
    if payload == b'{"command":"rm -rf /"}':
        assert parse_bounded_json_object(payload) == {"command": "rm -rf /"}
    else:
        with pytest.raises(ValueError):
            parse_bounded_json_object(payload, maximum_bytes=16)


def test_audit_only_creates_evidence_without_implicit_mutation() -> None:
    source_refs = (CANONICAL,)
    finding = ToolingFinding("audit-1", "リンク候補", source_refs, 0.8, ("人間確認が必要",))
    artifact = DevelopmentAuditService().report(
        artifact_id="artifact-1",
        tool_kind=ToolKind.MIGRATION_AUDIT,
        source_refs=source_refs,
        generated_at=NOW,
        methodology_revision="method-1",
        findings=(finding,),
    )

    assert isinstance(artifact, ToolingEvidenceArtifact)
    assert artifact.to_dict()["findings"] == [finding.to_dict()]
    assert not {name for name in dir(DevelopmentAuditService) if "mutat" in name.lower()}


def test_evidence_artifact_requires_source_provenance_and_methodology_revision() -> None:
    finding = ToolingFinding("finding-1", "確認", (CANONICAL,))
    with pytest.raises(ValueError):
        ToolingEvidenceArtifact(
            "artifact-1", ToolKind.ISSUE_GRAPH, (), NOW, "method-1", (finding,)
        )
    with pytest.raises(ValueError):
        ToolingEvidenceArtifact(
            "artifact-1", ToolKind.ISSUE_GRAPH, (CANONICAL,), NOW, "", (finding,)
        )


def test_production_runtime_does_not_import_development_tooling() -> None:
    imports: set[str] = set()
    for path in Path("app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.add(node.module)

    assert not any(
        name == "tools" or name.startswith("tools.development_tooling") for name in imports
    )
