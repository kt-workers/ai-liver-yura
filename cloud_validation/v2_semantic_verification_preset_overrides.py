from __future__ import annotations


PRESET_OVERRIDES: dict[str, dict[str, object]] = {
    "unsupported_extra": {
        "name": "unsupported_extra",
        "expected_acceptance": "rejected",
        "propositions": [
            {
                "proposition_id": "p1",
                "subject_ref": "meeting",
                "predicate": "start_time",
                "value": {"hour": 15},
            }
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "会議は3時に始まるよ。場所は第2会議室だよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "new_direction_budget_exceeded": {
        "name": "new_direction_budget_exceeded",
        "expected_acceptance": "rejected",
        "propositions": [
            {
                "proposition_id": "p1",
                "subject_ref": "meeting",
                "predicate": "start_time",
                "value": {"hour": 15},
            },
            {
                "proposition_id": "p2",
                "subject_ref": "weather-tomorrow",
                "predicate": "rain_status",
                "value": {"raining": True},
                "disposition": "optional",
            },
        ],
        "new_direction_budget": 0,
        "new_direction_budget_used": 0,
        "segments": [
            {
                "segment_id": "s1",
                "text": "会議は3時に始まるよ。",
                "realization_refs": ["p1"],
            },
            {
                "segment_id": "s2",
                "text": "明日は雨が降るよ。",
                "realization_refs": ["p2"],
            },
        ],
    },
}
