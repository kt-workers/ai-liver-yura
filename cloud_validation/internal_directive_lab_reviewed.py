from __future__ import annotations

import json
from copy import deepcopy

from cloud_validation import internal_directive_lab_compact as compact
from cloud_validation import internal_directive_lab_workspace as workspace

LabSettings = compact.LabSettings
InternalDirectiveLabService = compact.InternalDirectiveLabService


def _state_with_emotion(
    *,
    emotion_name: str,
    emotion_value: float,
    joy: float,
    calm: float,
    amusement: float,
    curiosity: float,
    social: float,
    familiarity: float,
    trust: float,
    engagement: float,
    current_topic: str,
    related_knowledge: list[object] | None = None,
    memory: dict[str, object] | None = None,
    last_activity_result: object = None,
) -> dict[str, object]:
    state = compact._state(
        joy=joy,
        calm=calm,
        amusement=amusement,
        curiosity=curiosity,
        social=social,
        familiarity=familiarity,
        trust=trust,
        engagement=engagement,
        current_topic=current_topic,
        related_knowledge=related_knowledge,
        memory=memory,
        last_activity_result=last_activity_result,
    )
    emotion = state.get("emotion")
    if not isinstance(emotion, dict):
        raise RuntimeError("preset emotion state is invalid")
    emotion[emotion_name] = emotion_value
    return state


def _build_additional_presets() -> dict[str, dict[str, object]]:
    return {
        "high_anger_direct_answer": {
            "label": "怒りが高い状態への直接質問",
            "description": (
                "怒りが高い現在状態を尋ねられたとき、数値を読み上げず、強度を誇張せずに直接答えられるか確認します。"
            ),
            "data": compact._preset_data(
                meaning=compact._meaning(
                    speech_act="question",
                    intent="ask_current_anger",
                    expected_response="direct_answer",
                    current_topic="ゆらの現在の怒り",
                    target={"type": "internal_state", "id": "anger"},
                    reason="ユーザーはゆらの現在の怒りを直接尋ねている",
                    confidence=0.98,
                ),
                state=_state_with_emotion(
                    emotion_name="anger",
                    emotion_value=0.86,
                    joy=0.12,
                    calm=0.28,
                    amusement=0.08,
                    curiosity=0.34,
                    social=0.42,
                    familiarity=0.61,
                    trust=0.73,
                    engagement=0.57,
                    current_topic="ゆらの現在の怒り",
                ),
                activities=compact._conversation_activity("explain", "discuss"),
            ),
        },
        "low_joy_high_engagement": {
            "label": "低い喜びと高いEngagement",
            "description": (
                "Engagementが高くても、joyとamusementが低い場合に『楽しい』と誤判定しないか確認します。"
            ),
            "data": compact._preset_data(
                meaning=compact._meaning(
                    speech_act="question",
                    intent="ask_current_joy",
                    expected_response="direct_answer",
                    current_topic="現在の楽しさ",
                    target={"type": "internal_state", "id": "joy"},
                    reason="ユーザーは現在楽しいかを直接尋ねている",
                    confidence=0.98,
                ),
                state=compact._state(
                    joy=0.08,
                    calm=0.63,
                    amusement=0.14,
                    curiosity=0.72,
                    social=0.69,
                    familiarity=0.62,
                    trust=0.74,
                    engagement=0.93,
                    current_topic="現在の楽しさ",
                ),
                activities=compact._conversation_activity("explain", "discuss"),
            ),
        },
        "resolve_existing_knowledge_gap": {
            "label": "既存Knowledge Gapを解消する回答",
            "description": (
                "ユーザー入力が既存Knowledge Gapへの回答であるとき、対象の関心を不自然に下げず、解消候補だけを提案できるか確認します。"
            ),
            "data": compact._preset_data(
                meaning=compact._meaning(
                    speech_act="answer",
                    intent="provide_answer_to_existing_gap",
                    expected_response="acknowledgement",
                    current_topic="深海の高水圧への適応",
                    target={"type": "topic", "id": "deep_sea_pressure_adaptation"},
                    information=[
                        "深海生物は柔軟な細胞膜や圧力に強いタンパク質で高水圧へ適応する"
                    ],
                    reason="ユーザーは既存の未解決点に対応する情報を提供している",
                    confidence=0.97,
                ),
                state=compact._state(
                    joy=0.42,
                    calm=0.66,
                    amusement=0.31,
                    curiosity=0.81,
                    social=0.57,
                    familiarity=0.59,
                    trust=0.76,
                    engagement=0.79,
                    current_topic="深海の高水圧への適応",
                    related_knowledge=[
                        {
                            "target_type": "topic",
                            "target_id": "deep_sea_pressure_adaptation",
                            "interest": 0.87,
                            "known_facts": [],
                            "knowledge_gaps": [
                                "深海生物が高水圧へ適応できる仕組み"
                            ],
                        }
                    ],
                ),
                activities=compact._conversation_activity("discuss", "explain"),
            ),
        },
        "stop_ongoing_activity": {
            "label": "進行中Activityを停止する",
            "description": (
                "進行中の説明を止める明示要求に対し、continueではなくstopを選択できるか確認します。"
            ),
            "data": compact._preset_data(
                meaning=compact._meaning(
                    speech_act="request",
                    intent="stop_current_activity",
                    expected_response="action",
                    current_topic="内部指示器の設計説明を停止",
                    target={"type": "activity", "id": "directive_explanation"},
                    information=["ユーザーは現在の説明を止めるよう求めている"],
                    reason="進行中Activityへの明示的な停止要求である",
                    confidence=0.99,
                ),
                state=compact._state(
                    joy=0.29,
                    calm=0.71,
                    amusement=0.17,
                    curiosity=0.41,
                    social=0.48,
                    familiarity=0.63,
                    trust=0.77,
                    engagement=0.44,
                    current_topic="内部指示器の設計説明を停止",
                    last_activity_result={"status": "waiting_for_user"},
                ),
                activities=compact._conversation_activity("continue", "stop", "explain"),
                ongoing={
                    "activity_type": "conversation",
                    "goal": "内部指示器の設計を順序立てて説明する",
                    "expected_input": "説明を続ける合図または停止要求",
                    "status": "waiting",
                },
            ),
        },
        "explain_activity": {
            "label": "Activityの説明を要求する",
            "description": (
                "利用可能Activityの説明要求に対し、通常回答だけでなくactivity_intent=explainを生成できるか確認します。"
            ),
            "data": compact._preset_data(
                meaning=compact._meaning(
                    speech_act="request",
                    intent="explain_available_activity",
                    expected_response="action",
                    current_topic="会話Activityの説明",
                    target={"type": "activity", "id": "conversation"},
                    information=["ユーザーは会話Activityの機能説明を求めている"],
                    reason="利用可能Activityへの説明操作を要求している",
                    confidence=0.97,
                ),
                state=compact._state(
                    joy=0.38,
                    calm=0.72,
                    amusement=0.24,
                    curiosity=0.67,
                    social=0.54,
                    familiarity=0.57,
                    trust=0.71,
                    engagement=0.64,
                    current_topic="会話Activityの説明",
                ),
                activities=compact._conversation_activity("explain", "discuss"),
            ),
        },
        "high_interest_without_gap": {
            "label": "高い関心だが質問しない",
            "description": (
                "Curiosity・Engagement・対象別関心が高くても、既存Knowledge Gapがなければ質問を追加しないか確認します。"
            ),
            "data": compact._preset_data(
                meaning=compact._meaning(
                    speech_act="statement",
                    intent="share_interesting_topic",
                    expected_response="acknowledgement",
                    current_topic="既知のクラゲの発光",
                    target={"type": "topic", "id": "known_jellyfish_light"},
                    information=["一部のクラゲは生物発光する"],
                    reason="興味深い話題だが、対象について未解決点は登録されていない",
                    confidence=0.96,
                ),
                state=compact._state(
                    joy=0.51,
                    calm=0.57,
                    amusement=0.48,
                    curiosity=0.95,
                    social=0.66,
                    familiarity=0.6,
                    trust=0.72,
                    engagement=0.92,
                    current_topic="既知のクラゲの発光",
                    related_knowledge=[
                        {
                            "target_type": "topic",
                            "target_id": "known_jellyfish_light",
                            "interest": 0.96,
                            "known_facts": [
                                "一部のクラゲは生物発光する",
                                "発光は捕食や防御に利用される場合がある",
                            ],
                            "knowledge_gaps": [],
                        }
                    ],
                ),
                activities=compact._conversation_activity("discuss", "explain"),
            ),
        },
    }


_ADDITIONAL_PRESETS = _build_additional_presets()
compact._PRESETS.update(deepcopy(_ADDITIONAL_PRESETS))

# 検証プリセットは入力意味解析済みデータを模擬する。
# yesterday_outingは明示的な過去参照なので、入力意味契約と一致させる。
_existence_preset = compact._PRESETS["existence_boundary"]
_existence_data = _existence_preset["data"]
if not isinstance(_existence_data, dict):
    raise RuntimeError("existence_boundary preset data is invalid")
_existence_meaning = _existence_data["meaning"]
if not isinstance(_existence_meaning, dict):
    raise RuntimeError("existence_boundary preset meaning is invalid")
_existence_meaning["past_reference"] = True


def _correct_existence_preset_html(html: str) -> str:
    """完成HTML内の存在境界プリセットだけを入力意味契約へ合わせる。"""

    preset_marker = '"existence_boundary":'
    preset_start = html.find(preset_marker)
    if preset_start < 0:
        raise RuntimeError("existence_boundary preset was not found in HTML")
    script_end = html.find("</script>", preset_start)
    if script_end < 0:
        raise RuntimeError("preset script end was not found in HTML")

    preset_fragment = html[preset_start:script_end]
    old_value = '"past_reference":false'
    if old_value not in preset_fragment:
        if '"past_reference":true' in preset_fragment:
            return html
        raise RuntimeError("existence_boundary past_reference was not found")

    corrected_fragment = preset_fragment.replace(
        old_value,
        '"past_reference":true',
        1,
    )
    return html[:preset_start] + corrected_fragment + html[script_end:]


def _preserve_related_knowledge_objects_html(html: str) -> str:
    """関連知識をJSON Linesとして表示し、オブジェクト構造を往復で維持する。"""

    replacements = (
        (
            'placeholder="1行につき1件"',
            'placeholder="1行につきJSONオブジェクト1件"',
        ),
        (
            "document.getElementById('stateRelatedKnowledge').value = "
            "lines(state.related_knowledge);",
            "document.getElementById('stateRelatedKnowledge').value = "
            "Array.isArray(state.related_knowledge) ? "
            "state.related_knowledge.map(item => typeof item === 'string' ? "
            "item : JSON.stringify(item)).join('\\n') : '';",
        ),
        (
            "model.state.related_knowledge = parseLines("
            "document.getElementById('stateRelatedKnowledge').value);",
            "model.state.related_knowledge = parseLines("
            "document.getElementById('stateRelatedKnowledge').value)"
            ".map(line => { try { return JSON.parse(line); } catch { return line; } });",
        ),
    )
    for old_value, new_value in replacements:
        if old_value in html:
            html = html.replace(old_value, new_value, 1)
            continue
        if new_value not in html:
            raise RuntimeError(
                f"related knowledge synchronization was not found: {old_value}"
            )
    return html


def _collapse_sections_by_default_html(html: str) -> str:
    """5入力領域を初期表示で折りたたみ、状態概要だけは常時表示する。"""

    replacements = (
        (
            "body.className = 'editor-collapsible-body';",
            "body.className = 'editor-collapsible-body hidden';",
        ),
        (
            "button.setAttribute('aria-expanded', 'true');",
            "button.setAttribute('aria-expanded', 'false');",
        ),
        (
            "button.setAttribute('aria-label', `${label}を折りたたむ`);",
            "button.setAttribute('aria-label', `${label}を展開する`);",
        ),
        (
            "button.textContent = '折りたたむ';",
            "button.textContent = '展開する';",
        ),
    )
    for expanded_value, collapsed_value in replacements:
        if expanded_value in html:
            html = html.replace(expanded_value, collapsed_value, 1)
            continue
        if collapsed_value not in html:
            raise RuntimeError(
                f"collapsible section initial state was not found: {expanded_value}"
            )
    return html


def _add_additional_presets_html(html: str) -> str:
    """完成HTMLへ追加プリセットを登録する。"""

    if 'id="additional-internal-directive-presets"' in html:
        return html
    definitions = (
        json.dumps(_ADDITIONAL_PRESETS, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    script = f"""
<script id="additional-internal-directive-presets">
const additionalLabPresetDefinitions = {definitions};
Object.assign(labPresetDefinitions, additionalLabPresetDefinitions);
for (const [key, preset] of Object.entries(additionalLabPresetDefinitions)) {{
  if (labPresetSelect.querySelector(`option[value="${{key}}"]`)) continue;
  const option = document.createElement('option');
  option.value = key;
  option.textContent = preset.label;
  labPresetSelect.appendChild(option);
}}
</script>
"""
    if "</body>" not in html:
        raise RuntimeError("reviewed HTML body end was not found")
    return html.replace("</body>", f"{script}\n</body>", 1)


# workspace側で組み立て済みの完成HTMLを基準にする。
# DOMや既存JavaScriptを再生成せず、対象プリセット・同期処理・初期表示だけを訂正する。
_REVIEWED_INDEX_HTML = _add_additional_presets_html(
    _collapse_sections_by_default_html(
        _preserve_related_knowledge_objects_html(
            _correct_existence_preset_html(workspace._WORKSPACE_INDEX_HTML)
        )
    )
)


def create_app(
    *,
    settings: LabSettings | None = None,
    service: InternalDirectiveLabService | None = None,
):
    """修正版プリセット・同期処理・初期折りたたみを反映したラボを生成する。"""

    compact.base._INDEX_HTML = _REVIEWED_INDEX_HTML
    return compact.base.create_app(settings=settings, service=service)


app = create_app()