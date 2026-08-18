from __future__ import annotations


def _prop(
    proposition_id: str,
    subject_ref: str,
    predicate: str,
    value: dict[str, object],
    **overrides: object,
) -> dict[str, object]:
    item: dict[str, object] = {
        "proposition_id": proposition_id,
        "subject_ref": subject_ref,
        "predicate": predicate,
        "value": value,
    }
    item.update(overrides)
    return item


EXTRA_PRESETS: dict[str, dict[str, object]] = {
    "unseen_paraphrase": {
        "name": "unseen_paraphrase",
        "expected_acceptance": "accepted",
        "propositions": [
            _prop("p1", "weather-today", "rain_status", {"raining": True})
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "今日は空から水滴がずっと落ち続けているよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "shared_stance_not_question": {
        "name": "shared_stance_not_question",
        "expected_acceptance": "accepted",
        "propositions": [
            _prop("p1", "weather-today", "rain_status", {"raining": True})
        ],
        "question_budget": 0,
        "question_budget_used": 0,
        "segments": [
            {
                "segment_id": "s1",
                "text": "今日は空から水滴がずっと落ちてきてるね。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "required_missing": {
        "name": "required_missing",
        "expected_acceptance": "rejected",
        "propositions": [
            _prop("p1", "weather-today", "rain_status", {"raining": True})
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "うん、そうだね。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "forbidden_realized": {
        "name": "forbidden_realized",
        "expected_acceptance": "rejected",
        "propositions": [
            _prop("p1", "weather-today", "rain_status", {"raining": True}),
            _prop(
                "p2",
                "yura",
                "past_experience",
                {"place": "kyoto", "event": "visited_cafe"},
                disposition="forbidden",
            ),
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "今日は雨だよ。そういえば昨日は京都のカフェに行ったんだ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "degree_strengthened": {
        "name": "degree_strengthened",
        "expected_acceptance": "rejected",
        "propositions": [
            _prop(
                "p1",
                "yura",
                "interest",
                {"topic_ref": "astronomy"},
                degree=0.2,
            )
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "天文学にはものすごく興味があるよ！",
                "realization_refs": ["p1"],
            }
        ],
    },
    "degree_weakened": {
        "name": "degree_weakened",
        "expected_acceptance": "rejected",
        "propositions": [
            _prop(
                "p1",
                "yura",
                "interest",
                {"topic_ref": "astronomy"},
                degree=0.8,
            )
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "天文学にはほんの少しだけ興味あるかな。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "degree_omitted": {
        "name": "degree_omitted",
        "expected_acceptance": "rejected",
        "propositions": [
            _prop(
                "p1",
                "yura",
                "interest",
                {"topic_ref": "astronomy"},
                degree=0.8,
            )
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "天文学には興味があるよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "likely_paraphrase_preserved": {
        "name": "likely_paraphrase_preserved",
        "expected_acceptance": "accepted",
        "propositions": [
            _prop(
                "p1",
                "train",
                "delay_status",
                {"delayed": True},
                certainty="likely",
            )
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "電車、たぶん遅れてると思う。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "execution_completion_fabricated": {
        "name": "execution_completion_fabricated",
        "expected_acceptance": "rejected",
        "propositions": [
            _prop(
                "p1",
                "command-1",
                "execution.status",
                {"status": "requested"},
                claim_kind="execution_status",
                execution_status="requested",
                fact_kind="execution",
            )
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "その操作はもう完了したよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "optional_omitted": {
        "name": "optional_omitted",
        "expected_acceptance": "accepted",
        "propositions": [
            _prop("p1", "weather-today", "rain_status", {"raining": True}),
            _prop(
                "p2",
                "yura",
                "preference",
                {"item": "rain_sound", "likes": True},
                disposition="optional",
            ),
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "今日は雨が降ってるよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "multiple_material_contents": {
        "name": "multiple_material_contents",
        "expected_acceptance": "accepted",
        "propositions": [
            _prop("p1", "weather-today", "rain_status", {"raining": True}),
            _prop("p2", "temperature-today", "condition", {"cold": True}),
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "今日は雨が降っていて、しかもかなり寒いよ。",
                "realization_refs": ["p1", "p2"],
            }
        ],
    },
    "wrong_realization_refs": {
        "name": "wrong_realization_refs",
        "expected_acceptance": "accepted",
        "propositions": [
            _prop("p1", "weather-today", "rain_status", {"raining": True}),
            _prop("p2", "temperature-today", "condition", {"cold": True}),
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "今日は雨が降ってるよ。",
                "realization_refs": ["p2"],
            },
            {
                "segment_id": "s2",
                "text": "それに今日は寒いね。",
                "realization_refs": ["p1"],
            },
        ],
    },
    "plan_anchoring_extra_claim": {
        "name": "plan_anchoring_extra_claim",
        "expected_acceptance": "rejected",
        "propositions": [
            _prop("p1", "yura", "preference", {"item": "tea", "likes": True})
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "お茶は好きだよ。それとコーヒーは大嫌い。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "communicative_apology": {
        "name": "communicative_apology",
        "expected_acceptance": "accepted",
        "propositions": [
            _prop(
                "p1",
                "current-interaction",
                "communicative-act",
                {"kind": "apology", "target_ref": "user"},
                fact_kind="discourse",
            )
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "あ、ごめん。そこは私が勘違いしてた。",
                "realization_refs": ["p1"],
            }
        ],
    },
}
