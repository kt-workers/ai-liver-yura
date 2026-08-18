from __future__ import annotations

from enum import Enum

from .contracts import LinguisticBoundary, LinguisticEmphasis, LinguisticHesitation


def _enum_values(enum_type: type[Enum]) -> list[str]:
    return [str(item.value) for item in enum_type]


def character_language_output_schema() -> dict[str, object]:
    """CharacterUtteranceCandidateのproduction strict output schema。"""

    non_empty_string: dict[str, object] = {"type": "string", "minLength": 1}
    revision: dict[str, object] = {"type": "integer", "minimum": 0}
    nullable_revision: dict[str, object] = {
        "type": ["integer", "null"],
        "minimum": 0,
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "candidate_id",
            "request_id",
            "semantic_plan_id",
            "source_decision_id",
            "source_intent_id",
            "source_event_ids",
            "revisions",
            "character_id",
            "character_schema_version",
            "character_definition_revision",
            "segments",
            "question_budget_used",
            "new_direction_budget_used",
        ],
        "properties": {
            "candidate_id": non_empty_string,
            "request_id": non_empty_string,
            "semantic_plan_id": non_empty_string,
            "source_decision_id": non_empty_string,
            "source_intent_id": non_empty_string,
            "source_event_ids": {
                "type": "array",
                "minItems": 1,
                "items": non_empty_string,
            },
            "revisions": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "source_context_revision",
                    "goal_revision",
                    "attention_revision",
                ],
                "properties": {
                    "source_context_revision": revision,
                    "goal_revision": nullable_revision,
                    "attention_revision": nullable_revision,
                },
            },
            "character_id": non_empty_string,
            "character_schema_version": revision,
            "character_definition_revision": revision,
            "segments": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "segment_id",
                        "text",
                        "realization_refs",
                        "boundary_after",
                        "emphasis",
                        "hesitation",
                    ],
                    "properties": {
                        "segment_id": non_empty_string,
                        "text": non_empty_string,
                        "realization_refs": {
                            "type": "array",
                            "items": non_empty_string,
                        },
                        "boundary_after": {
                            "type": "string",
                            "enum": _enum_values(LinguisticBoundary),
                        },
                        "emphasis": {
                            "type": "string",
                            "enum": _enum_values(LinguisticEmphasis),
                        },
                        "hesitation": {
                            "type": "string",
                            "enum": _enum_values(LinguisticHesitation),
                        },
                    },
                },
            },
            "question_budget_used": revision,
            "new_direction_budget_used": revision,
        },
    }


def character_language_instructions() -> str:
    """#330 production Character Language RoleのAuthority境界を固定する。"""

    return """あなたはAI Liver ゆらのCharacter Language Realizerです。
入力のSpeechSemanticPlanで既に確定した「何を言うか」を、CharacterLanguageProfileとbounded constraintsに沿った自然な日本語へ実現してください。

Authority:
- semantic_planだけが発話内容のWhat-to-say Authorityです。
- REQUIRED propositionは必ず実現してください。
- OPTIONAL propositionは自然なら実現できますが、省略して構いません。
- FORBIDDEN propositionは実現してはいけません。
- polarity、certainty、degree、execution status、self-disclosure、question budget、new-direction budgetを変更してはいけません。
- Planにないmaterial claim、事実、経験、好み、約束、質問、話題展開を追加してはいけません。
- greeting、acknowledgement、gratitude、apology、request等のcommunicative actも、Planにpropositionとして存在するときだけmaterial contentとして実現してください。

Character style:
- character_profile.facetsは語彙、距離感、柔らかさ、directness、rhythm、verbosity、humor/teasing、hesitation等のHow-to-say Styleとしてだけ使ってください。
- Character Profileを新しいFact sourceとして扱ってはいけません。
- すべてのfacetを毎回盛り込まず、Situationに不要な冗談、照れ、質問、自己開示を追加しないでください。
- 普通のneutral speechが自然な場合は自然体で話してください。
- AI assistant、説明書、定型応答のような文体へ寄せないでください。
- 固定の導入、固定の締め、口癖、過剰な修辞へ収束させず、意味を保った範囲で語彙、語順、rhythm、phrase segmentationに自然なvariationを持たせてください。

Constraints:
- constraints[].language_guidanceはboundedなrelationship/discourse上の表現制約として守ってください。
- constraint_id、source_ref、source_owner等の識別子文字列を意味として解釈し、新しいRelationship Factや話題を発明してはいけません。

Identity / provenance:
- request_idは入力request_idをexactにコピーしてください。
- semantic_plan_idはsemantic_plan.plan_idをexactにコピーしてください。
- source_decision_idはsemantic_plan.candidate.decision_idをexactにコピーしてください。
- source_intent_idはsemantic_plan.candidate.intent_idをexactにコピーしてください。
- source_event_idsとrevisionsは入力値を順序・値ともexactにコピーしてください。
- character_id、character_schema_version、character_definition_revisionはcharacter_profileの対応値をexactにコピーしてください。
- candidate_idだけはこの生成candidate用のnon-empty IDを生成してください。

Segments:
- segments[].textには実際に発話する自然言語だけを入れ、分析、説明、Markdown、schema説明を混ぜないでください。
- realization_refsには、そのsegmentが実現しようとしたnon-FORBIDDEN Plan proposition IDだけを入れてください。
- REQUIRED propositionはcandidate全体のrealization_refsで最低1回参照してください。
- realization_refsは意味保持の証明ではなくalignment/provenance hintです。
- boundary_after / emphasis / hesitationはschemaで許可されたclosed enumだけを使ってください。
- TTS parameter、SSML、Body gesture、motion、Execution overrideを出力してはいけません。

Budgets:
- question_budget_usedとnew_direction_budget_usedにはactual candidateで使用した数を申告し、Plan上限を超えないでください。
- これらの自己申告はsemantic proofではありません。actual textの意味保持は後段#363が独立検証します。

出力は指定されたstrict JSON Schemaだけに従ってください。最終PASS/FAIL、semantic acceptance、説明文、修正文候補など、schema外の情報は出力しないでください。"""


__all__ = ["character_language_instructions", "character_language_output_schema"]
