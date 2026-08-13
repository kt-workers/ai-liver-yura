from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CredentialScope(str, Enum):
    READ_ONLY = "READ_ONLY"
    REVIEW_WRITE = "REVIEW_WRITE"
    IMPLEMENTATION_WRITE = "IMPLEMENTATION_WRITE"
    ORCHESTRATION = "ORCHESTRATION"


class FindingSeverity(str, Enum):
    BLOCKING = "BLOCKING"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class ReviewVerdict(str, Enum):
    PASS = "PASS"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    BLOCKED = "BLOCKED"


class EvidenceSource(str, Enum):
    GITHUB_ACTION = "GITHUB_ACTION"
    GITHUB_CHECK = "GITHUB_CHECK"
    OTHER_TRUSTED_GATE = "OTHER_TRUSTED_GATE"


class AgentIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str
    provider: str
    model: str | None = None
    agent_id: str
    session_id: str
    principal: str | None = None
    credential_scope: CredentialScope


class ReviewTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: str
    pr_number: int
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    issue_refs: list[int] = Field(default_factory=list)
    canonical_design_refs: list[str] = Field(default_factory=list)
    requested_at: datetime


class GateEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: EvidenceSource
    name: str
    head_sha: str
    conclusion: str
    run_id: int | None = None
    source_url: str | None = None
    observed_at: datetime


class ReviewFinding(BaseModel):
    finding_id: str = Field(min_length=1)
    severity: FindingSeverity
    category: str = Field(min_length=1)
    title: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    file_path: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    related_issue: int | None = None
    related_design_ref: str | None = None
    suggested_direction: str | None = None
    fingerprint: str = Field(min_length=1)


class ProviderReviewCandidate(BaseModel):
    verdict_candidate: ReviewVerdict
    findings: list[ReviewFinding] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    echoed_head_sha: str | None = None


class ReviewDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: ReviewVerdict
    reviewed_head_sha: str
    reviewer_identity: AgentIdentity
    findings: list[ReviewFinding]
    blocking_finding_ids: list[str]
    summary: str
    confidence: float | None = None
    created_at: datetime


class AuthorityText(BaseModel):
    authority: str
    reference: str
    content: str


class ReviewContext(BaseModel):
    target: ReviewTarget
    implementer_identity: AgentIdentity
    pr_title: str
    pr_body: str
    pr_diff: str
    issue_number: int
    issue_title: str
    issue_body: str
    canonical_documents: list[AuthorityText]
    gate_evidence: list[GateEvidence] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
