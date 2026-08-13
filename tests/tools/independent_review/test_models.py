from tools.independent_review.models import ProviderReviewCandidate, ReviewVerdict


def test_provider_candidate_roundtrip() -> None:
    item = ProviderReviewCandidate(verdict_candidate=ReviewVerdict.PASS, summary="問題ありません")
    decoded = ProviderReviewCandidate.model_validate_json(item.model_dump_json())
    assert decoded == item
