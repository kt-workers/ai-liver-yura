"""Appraisal候補のProvider非依存な出力構造と生成指示。"""


def appraisal_output_schema() -> dict[str, object]:
    """呼出ごとに独立したstrict出力schemaを返す。"""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "candidate_id",
            "dimensions",
            "proposals",
            "salience",
            "relevance",
            "evidence_refs",
        ],
        "properties": {
            "candidate_id": {"type": "string"},
            "dimensions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "value", "target_ref"],
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "pleasantness",
                                "novelty",
                                "goal_congruence",
                                "controllability",
                                "certainty",
                                "social_meaning",
                            ],
                        },
                        "value": {"type": "number", "minimum": -1, "maximum": 1},
                        "target_ref": {"type": ["string", "null"]},
                    },
                },
            },
            "proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "facet_kind",
                        "state_key",
                        "target_ref",
                        "delta",
                        "confidence",
                        "cause_refs",
                    ],
                    "properties": {
                        "facet_kind": {
                            "type": "string",
                            "enum": [
                                "emotion",
                                "desire",
                                "drive",
                                "motivation",
                                "value",
                                "interest",
                                "relationship",
                                "energy",
                                "arousal",
                            ],
                        },
                        "state_key": {"type": "string"},
                        "target_ref": {"type": ["string", "null"]},
                        "delta": {"type": "number", "minimum": -1, "maximum": 1},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "cause_refs": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "salience": {"type": "number", "minimum": 0, "maximum": 1},
            "relevance": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
        },
    }


def appraisal_instructions() -> str:
    """状態変更権限を与えず、bounded入力から候補だけを生成させる。"""
    return (
        "入力されたcurrent event、structured meaning、bo"
        "undedなInternal Stateとcontextだけを評価してください。"
        "出力は指定schemaに一致するAppraisalCandidateの候補だけと"
        "し、schema外の説明文を返さないでください。current Internal"
        " Stateを直接変更せず、Goal・Attention・Actionを選択しな"
        "いでください。状態facetの絶対値ではなくtyped delta propos"
        "alを返してください。evidence_refs・cause_refs・targ"
        "et_refにはbounded inputに存在する参照だけを使用し、参照や因果"
        "を捏造しないでください。変化のないfacetにdelta=0のproposalを"
        "作らず、Interest・Relationshipには対象参照を付けてください。"
        "これらは状態commitの指示ではありません。"
    )
