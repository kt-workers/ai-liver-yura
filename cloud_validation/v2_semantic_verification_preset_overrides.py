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
    }
}
