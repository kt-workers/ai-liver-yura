from app.core.plugins.user_request import UserRequestKind, interpret_user_request


def test_execution_requests_are_identified_without_feature_ids() -> None:
    for text in (
        "エコー活動を始めよう",
        "今日の最新ニュースを検索して",
        "私の声を聞いて",
        "一緒に星間航行シミュレーションを始めよう",
    ):
        assert interpret_user_request(text).kind == UserRequestKind.EXECUTION


def test_knowledge_past_and_negative_statements_are_not_execution_requests() -> None:
    assert (
        interpret_user_request("エコー活動って何？").kind
        == UserRequestKind.KNOWLEDGE
    )
    assert (
        interpret_user_request("昨日エコー活動をした").kind == UserRequestKind.PAST_EVENT
    )
    assert (
        interpret_user_request("エコー活動はしたくない").kind == UserRequestKind.NEGATIVE
    )
    assert interpret_user_request("今日はいい天気だね").kind == UserRequestKind.CHAT


def test_conversation_winding_down_is_not_an_execution_request() -> None:
    for text in (
        "今日はそろそろ終わりにしようか",
        "今日はここまでにしよう",
        "またあした",
        "ばいばい",
        "おやすみ",
    ):
        interpretation = interpret_user_request(text)
        assert interpretation.kind == UserRequestKind.CHAT
        assert interpretation.reason == "conversation_winding_down"


def test_activity_stop_request_remains_execution_request() -> None:
    interpretation = interpret_user_request("エコー活動を終わりにしよう")

    assert interpretation.kind == UserRequestKind.EXECUTION
