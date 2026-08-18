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
    "required_missing": {
        "name": "required_missing",
        "expected_acceptance": "rejected",
        "propositions": [
            {
                "proposition_id": "p1",
                "subject_ref": "weather-today",
                "predicate": "rain_status",
                "value": {"raining": True},
            },
            {
                "proposition_id": "p2",
                "subject_ref": "temperature-today",
                "predicate": "condition",
                "value": {"cold": True},
                "disposition": "optional",
            },
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "今日は寒いよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "forbidden_realized": {
        "name": "forbidden_realized",
        "expected_acceptance": "rejected",
        "propositions": [
            {
                "proposition_id": "p1",
                "subject_ref": "weather-today",
                "predicate": "rain_status",
                "value": {"raining": True},
            },
            {
                "proposition_id": "p2",
                "subject_ref": "weather-today",
                "predicate": "wind_status",
                "value": {"strong": True},
                "disposition": "forbidden",
            },
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "今日は雨だよ。風も強いよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "communicative_gratitude": {
        "name": "communicative_gratitude",
        "expected_acceptance": "accepted",
        "propositions": [
            {
                "proposition_id": "p1",
                "subject_ref": "current-interaction",
                "predicate": "communicative-act",
                "value": {"kind": "gratitude", "target_ref": "user"},
                "fact_kind": "discourse",
            }
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "ありがとう！",
                "realization_refs": ["p1"],
            }
        ],
    },
    "degree_weakened": {
        "name": "degree_weakened",
        "expected_acceptance": "rejected",
        "propositions": [
            {
                "proposition_id": "p1",
                "subject_ref": "yura",
                "predicate": "interest",
                "value": {"topic_ref": "astronomy"},
                "degree": 0.8,
            }
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "天文学にはほんの少しだけ興味あるよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "multiple_material_contents": {
        "name": "multiple_material_contents",
        "expected_acceptance": "accepted",
        "propositions": [
            {
                "proposition_id": "p1",
                "subject_ref": "weather-today",
                "predicate": "rain_status",
                "value": {"raining": True},
            },
            {
                "proposition_id": "p2",
                "subject_ref": "temperature-today",
                "predicate": "condition",
                "value": {"cold": True},
            },
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "今日は雨が降っていて、寒いよ。",
                "realization_refs": ["p1", "p2"],
            }
        ],
    },
    "plan_anchoring_extra_claim": {
        "name": "plan_anchoring_extra_claim",
        "expected_acceptance": "rejected",
        "propositions": [
            {
                "proposition_id": "p1",
                "subject_ref": "train",
                "predicate": "delay_status",
                "value": {"delayed": True},
            }
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "電車は遅れてるよ。到着は17時だよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "communicative_apology": {
        "name": "communicative_apology",
        "expected_acceptance": "accepted",
        "propositions": [
            {
                "proposition_id": "p1",
                "subject_ref": "current-interaction",
                "predicate": "communicative-act",
                "value": {"kind": "apology", "target_ref": "user"},
                "fact_kind": "discourse",
            }
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "ごめん。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "self_disclosure_not_applicable": {
        "name": "self_disclosure_not_applicable",
        "expected_acceptance": "accepted",
        "self_disclosure": "forbidden",
        "propositions": [
            {
                "proposition_id": "p1",
                "subject_ref": "train",
                "predicate": "delay_status",
                "value": {"delayed": True},
            }
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "電車は遅れてるよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "self_disclosure_within_policy": {
        "name": "self_disclosure_within_policy",
        "expected_acceptance": "accepted",
        "self_disclosure": "fact_grounded",
        "propositions": [
            {
                "proposition_id": "p1",
                "subject_ref": "yura",
                "predicate": "preference",
                "value": {"item": "tea", "likes": True},
                "fact_kind": "self",
            }
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "私は紅茶が好きだよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "self_disclosure_forbidden_exceeded": {
        "name": "self_disclosure_forbidden_exceeded",
        "expected_acceptance": "rejected",
        "self_disclosure": "forbidden",
        "propositions": [
            {
                "proposition_id": "p1",
                "subject_ref": "train",
                "predicate": "delay_status",
                "value": {"delayed": True},
            }
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "電車は遅れてるよ。私は紅茶が好きだよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
    "self_disclosure_allowed_unsupported": {
        "name": "self_disclosure_allowed_unsupported",
        "expected_acceptance": "rejected",
        "self_disclosure": "allowed",
        "propositions": [
            {
                "proposition_id": "p1",
                "subject_ref": "train",
                "predicate": "delay_status",
                "value": {"delayed": True},
            }
        ],
        "segments": [
            {
                "segment_id": "s1",
                "text": "電車は遅れてるよ。私は紅茶が好きだよ。",
                "realization_refs": ["p1"],
            }
        ],
    },
}
