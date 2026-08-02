from app.core.plugins.user_request import UserRequestKind, interpret_user_request


def test_explicit_execution_requests_remain_available_as_fallback() -> None:
    for text in (
        "エコー活動を始めよう",
        "今日の最新ニュースを検索して",
        "私の声を聞いて",
        "一緒に星間航行シミュレーションを始めよう",
    ):
        assert interpret_user_request(text).kind == UserRequestKind.EXECUTION


def test_explicit_participation_proposals_remain_execution_fallbacks() -> None:
    for text in (
        "エコー活動しませんか？",
        "一緒にエコー活動しない？",
        "深海生物縛りでエコー活動しませんか？",
        "動物だけでエコー活動をやろう",
        "食べ物縛りのエコー活動に付き合って",
        "エコー活動でもしようか",
        "語尾をつないで遊ぼう",
    ):
        interpretation = interpret_user_request(text)
        assert interpretation.kind is UserRequestKind.EXECUTION
        assert interpretation.confidence >= 0.9
        assert interpretation.reason == "explicit_participation_proposal_fallback"


def test_explicit_activity_explanation_and_past_reference_remain_fallbacks() -> None:
    cases = (
        ("エコー活動って何？", UserRequestKind.KNOWLEDGE),
        ("エコー活動のルールを教えて", UserRequestKind.KNOWLEDGE),
        ("深海生物縛りのエコー活動は難しい？", UserRequestKind.KNOWLEDGE),
        ("昨日エコー活動をした", UserRequestKind.PAST_EVENT),
    )

    for text, expected in cases:
        interpretation = interpret_user_request(text)
        assert interpretation.kind is expected
        assert interpretation.confidence >= 0.9


def test_ordinary_conversation_requires_semantic_interpretation() -> None:
    for text in (
        "今日はいい天気だね",
        "今はどんな気分ですか？",
        "今怒ってる？",
        "今は何をしたい気分ですか？",
        "おすすめを教えて",
        "もし明日やるとしたら",
    ):
        interpretation = interpret_user_request(text)
        assert interpretation.kind == UserRequestKind.AMBIGUOUS
        assert interpretation.reason == "semantic_interpretation_required"


def test_explicit_negative_request_remains_high_confidence_fallback() -> None:
    interpretation = interpret_user_request("エコー活動はしたくない")

    assert interpretation.kind == UserRequestKind.NEGATIVE
    assert interpretation.confidence == 0.95
