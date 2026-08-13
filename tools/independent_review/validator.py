from __future__ import annotations

from datetime import datetime, timezone

from .models import (
    AgentIdentity,
    CredentialScope,
    FindingSeverity,
    ProviderReviewCandidate,
    ReviewDecision,
    ReviewTarget,
    ReviewVerdict,
)


class ReviewValidationError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


def _raise(message: str, *, retryable: bool) -> None:
    raise ReviewValidationError(message, retryable=retryable)


_MAX_PROVIDER_TEXT_CHARS = 12_000


def _string_size(value: object) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_string_size(item) for item in value.values())
    if isinstance(value, list):
        return sum(_string_size(item) for item in value)
    return 0


def _contains_japanese(value: str) -> bool:
    return any(
        "\u3041" <= char <= "\u3096"
        or "\u30a1" <= char <= "\u30fa"
        or "\u3400" <= char <= "\u9fff"
        for char in value
    )


def _validate_japanese_output(candidate: ProviderReviewCandidate) -> None:
    fields = [("要約", candidate.summary)]
    for item in candidate.findings:
        fields.extend(
            [
                ("指摘タイトル", item.title),
                ("指摘説明", item.explanation),
                *(("指摘根拠", evidence) for evidence in item.evidence),
            ]
        )
        if item.suggested_direction is not None:
            fields.append(("修正方向", item.suggested_direction))
    for name, value in fields:
        if not _contains_japanese(value):
            _raise(f"{name}に日本語が含まれていません", retryable=True)


def validate_candidate(
    candidate: ProviderReviewCandidate,
    *,
    target: ReviewTarget,
    current_head_sha: str,
    implementer_identity: AgentIdentity,
    reviewer_identity: AgentIdentity,
    context_complete: bool,
) -> ReviewDecision:
    if current_head_sha != target.head_sha:
        _raise(
            "レビュー対象が古くなっています。現在のPR先端SHAが変化しました",
            retryable=False,
        )
    if not candidate.echoed_head_sha or not candidate.echoed_head_sha.strip():
        _raise("レビューワーが先端SHAを返しませんでした", retryable=True)
    if candidate.echoed_head_sha != target.head_sha:
        _raise("レビューワーが異なる先端SHAを返しました", retryable=True)
    if reviewer_identity.agent_id == implementer_identity.agent_id:
        _raise("レビュー担当と実装担当のAI識別子が同一です", retryable=False)
    if reviewer_identity.session_id == implementer_identity.session_id:
        _raise("レビュー担当と実装担当の実行識別子が同一です", retryable=False)
    if reviewer_identity.credential_scope not in {
        CredentialScope.READ_ONLY,
        CredentialScope.REVIEW_WRITE,
    }:
        _raise("レビュー担当に禁止された資格情報権限が付与されています", retryable=False)
    if not context_complete:
        _raise("必須レビュー情報が不足しています", retryable=False)
    if len(candidate.findings) > 50:
        _raise("レビューワーが返した指摘数が上限を超えています", retryable=True)
    if len(candidate.summary) > 8_000:
        _raise("レビューワーの要約が安全上限を超えています", retryable=True)
    if _string_size(candidate.model_dump(mode="json")) > _MAX_PROVIDER_TEXT_CHARS:
        _raise("レビューワー出力の文字数合計が安全上限を超えています", retryable=True)
    for item in candidate.findings:
        if len(item.title) > 500 or len(item.explanation) > 8_000:
            _raise("レビューワーの指摘本文が安全上限を超えています", retryable=True)
        if len(item.evidence) > 20 or any(len(value) > 2_000 for value in item.evidence):
            _raise("レビューワーの指摘根拠が安全上限を超えています", retryable=True)
    _validate_japanese_output(candidate)

    finding_ids = [item.finding_id for item in candidate.findings]
    fingerprints = [item.fingerprint for item in candidate.findings]
    if len(finding_ids) != len(set(finding_ids)):
        _raise("finding_id が重複しています", retryable=True)
    if len(fingerprints) != len(set(fingerprints)):
        _raise("指摘fingerprintが重複しています", retryable=True)

    blocking = [
        item.finding_id for item in candidate.findings if item.severity == FindingSeverity.BLOCKING
    ]
    if candidate.verdict_candidate == ReviewVerdict.PASS and blocking:
        _raise("PASSにBLOCKING指摘を含めることはできません", retryable=True)
    if candidate.verdict_candidate == ReviewVerdict.CHANGES_REQUESTED and not blocking:
        _raise("CHANGES_REQUESTEDにはBLOCKING指摘が必要です", retryable=True)
    if candidate.verdict_candidate == ReviewVerdict.BLOCKED and blocking:
        _raise("BLOCKEDをコード欠陥の代用として使用できません", retryable=True)

    return ReviewDecision(
        verdict=candidate.verdict_candidate,
        reviewed_head_sha=target.head_sha,
        reviewer_identity=reviewer_identity,
        findings=candidate.findings,
        blocking_finding_ids=blocking,
        summary=candidate.summary,
        confidence=candidate.confidence,
        created_at=datetime.now(timezone.utc),
    )
