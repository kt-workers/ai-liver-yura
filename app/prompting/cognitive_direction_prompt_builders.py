from __future__ import annotations

import json

from app.domain.cognitive_direction import StructuredInputMeaning


class InputMeaningPromptBuilder:
    """観測入力を、入力側の意味だけを表す契約へ変換する。"""

    def build(self, planning_input: dict[str, object]) -> str:
        event_value = planning_input.get("event")
        event = dict(event_value) if isinstance(event_value, dict) else {}
        observed_input = {
            "event_type": event.get("type"),
            "source_event_id": event.get("source_event_id"),
            "text": event.get("user_text"),
            "authority_role": event.get("authority_role"),
            "instruction_trusted": event.get("instruction_trusted"),
            "modality": event.get("modality", "text"),
            "prosody": event.get("prosody"),
            "visual_observation": event.get("visual_observation"),
            "contact_target": event.get("contact_target"),
            "contact_region": event.get("contact_region"),
            "interaction_type": event.get("interaction_type"),
        }
        reference_context = {
            "conversation_history": planning_input.get("conversation_history", []),
            "current_topic": self._current_topic(planning_input),
            "ongoing_activity": self._ongoing_reference(planning_input),
        }
        schema = {
            "input_speech_act": (
                "greeting|statement|question|answer|acknowledgement|closing|"
                "request|proposal|command"
            ),
            "primary_intent": "string",
            "expected_response": (
                "direct_answer|acknowledgement|continue_listening|action|"
                "clarification|no_response"
            ),
            "target": {"type": "string", "id": "string"},
            "entities": "array[object]",
            "references": "array[object]",
            "information_provided": "array[string]",
            "negated": "boolean",
            "hypothetical": "boolean",
            "past_reference": "boolean",
            "conversation_phase_signal": (
                "greeting|opening|continue|winding_down"
            ),
            "confidence": "number 0.0..1.0",
            "reason": "string",
        }
        return "\n".join(
            [
                "あなたはInput Meaning Interpreterです。入力側が何を意味したかだけを解析する。",
                "入力者が行った発話行為をinput_speech_actへ分類する。"
                "ゆらが次に行う発話行為を分類してはいけない。",
                "questionはユーザーがゆらから回答を得ようとしている入力、answerは直前の"
                "ゆらの質問や確認に対する回答である。",
                "『今は何をしたい気分ですか？』『今怒ってる？』『楽しい？』はquestionであり、"
                "ゆらが回答する必要があることはexpected_response=direct_answerで表す。",
                "ゆら『どこへ行ったの？』の後の『しまなみ海道だよ』はanswerである。",
                "『了解』はacknowledgement、『今日はこのくらいかな』はclosingである。",
                "疑問符、語尾、固定語句だけで分類せず、直近の会話履歴と対象を使う。",
                "この役割ではActivity、response_mode、initiative_level、question_budget、"
                "new_direction_budget、ゆらの発話内容を決めない。",
                "内部状態は曖昧参照の解決以外に利用しない。",
                "# ObservedInput",
                json.dumps(observed_input, ensure_ascii=False, default=str),
                "# ReferenceContext",
                json.dumps(reference_context, ensure_ascii=False, default=str),
                "# 出力JSONスキーマ",
                json.dumps(schema, ensure_ascii=False),
                "JSONオブジェクトだけを返す。targetがない場合はnullにする。",
            ]
        )

    @staticmethod
    def _current_topic(planning_input: dict[str, object]) -> object:
        situation = planning_input.get("situation")
        if not isinstance(situation, dict):
            return None
        return situation.get("current_topic") or situation.get("topic")

    @staticmethod
    def _ongoing_reference(planning_input: dict[str, object]) -> object:
        ongoing = planning_input.get("ongoing_activity")
        if not isinstance(ongoing, dict):
            return None
        return {
            "activity_type": ongoing.get("activity_type"),
            "goal": ongoing.get("goal"),
            "expected_input": ongoing.get("expected_input"),
            "recent_turns": ongoing.get("recent_turns"),
        }


class InternalDirectivePromptBuilder:
    """構造化済み入力と内部状態から、実行前の内部司令候補を作る。"""

    def build(
        self,
        meaning: StructuredInputMeaning,
        planning_input: dict[str, object],
        *,
        character_profile: dict[str, object],
    ) -> str:
        directive_input = {
            "structured_input_meaning": meaning.as_context(),
            "internal_state": {
                "emotion": planning_input.get("emotion", {}),
                "drive": planning_input.get("drive", {}),
                "relationship": planning_input.get("relationship", {}),
                "motivation": planning_input.get("motivation", {}),
                "moral": planning_input.get("moral", {}),
                "situation": planning_input.get("situation", {}),
                "memory": planning_input.get("memory", {}),
                "related_knowledge": planning_input.get("related_knowledge", []),
                "last_activity_result": planning_input.get("last_activity_result"),
            },
            "ongoing_activity": planning_input.get("ongoing_activity"),
            "available_activities": planning_input.get("available_activities", []),
            "character_profile": character_profile,
            "existence_boundaries": self._existence_boundaries(character_profile),
        }
        schema = {
            "response_mode": "answer|listen|react|ask|speak|observe",
            "response_goal": "string",
            "activity_intent": {
                "activity_type": "available activity type",
                "operation": "start|continue|stop|explain|discuss",
                "constraints": "object",
            },
            "initiative_level": "number 0.0..1.0",
            "question_budget": "integer 0..3",
            "new_direction_budget": "integer 0..3",
            "self_disclosure_level": "number 0.0..1.0",
            "content_requirements": "array[string]",
            "forbidden_claims": "array[string]",
            "target_interest_updates": [
                {
                    "target_type": "string",
                    "target_id": "string",
                    "interest_change": (
                        "increase|slightly_increase|unchanged|"
                        "slightly_decrease|decrease"
                    ),
                    "resolved_knowledge_gaps": "array[string]",
                    "new_knowledge_gaps": "array[string]",
                }
            ],
            "state_update_proposals": "array[object]",
            "reason": "string",
        }
        return "\n".join(
            [
                "あなたはInternal Directive Plannerです。構造化された入力意味と現在状態から、"
                "次に何をするかの候補だけを決める。",
                "Raw User Textを再解釈してはいけない。structured_input_meaningを意味の"
                "唯一の主入力として扱う。",
                "ユーザーの直接質問はresponse_mode=answerとし、原則question_budget=0、"
                "new_direction_budget=0にする。",
                "acknowledgementでは新しい話題を始めず、listenまたはreactを選ぶ。",
                "closingでは会話を締め、question_budget=0にする。",
                "全体的なdrive.curiosityだけを理由に質問しない。対象別関心、knowledge gap、"
                "未解決点が具体的にある場合だけaskを選択できる。",
                "joyやamusementとengagementを混同しない。内部状態への直接質問では対象の"
                "感情値を根拠にし、関心の高さを楽しさとして断定しない。",
                "Character Profileと存在境界に反する身体経験・現実空間での実体験を"
                "content_requirementsまたはforbidden_claimsで明示的に防ぐ。",
                "Activityはavailable_activitiesに対する意図だけを出す。Capability、Authority、"
                "Safety、Constraint、実行成功を確定しない。",
                "自由文章のCharacter LLMプロンプトを書かない。発話本文も生成しない。",
                "関心の数値を確定せず、target_interest_updatesには増減と知識ギャップだけを提案する。",
                "# DirectiveInput",
                json.dumps(directive_input, ensure_ascii=False, default=str),
                "# 出力JSONスキーマ",
                json.dumps(schema, ensure_ascii=False),
                "JSONオブジェクトだけを返す。activity_intentがない場合はnullにする。",
            ]
        )

    @staticmethod
    def _existence_boundaries(profile: dict[str, object]) -> list[str]:
        existence = profile.get("existence")
        if not isinstance(existence, dict):
            return [
                "物理的な身体を持たない",
                "実体験は根拠がある場合だけ語る",
            ]
        boundaries: list[str] = []
        for key in (
            "physical_capabilities",
            "sensory_capabilities",
            "experience_boundaries",
        ):
            value = existence.get(key)
            if isinstance(value, (list, tuple)):
                boundaries.extend(str(item) for item in value)
        relationship = existence.get("world_relationship")
        if relationship:
            boundaries.append(str(relationship))
        return boundaries
