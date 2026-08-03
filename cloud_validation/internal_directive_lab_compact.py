from __future__ import annotations

import json
from copy import deepcopy

from cloud_validation import internal_directive_lab as base

LabSettings = base.LabSettings
InternalDirectiveLabService = base.InternalDirectiveLabService

_COMPACT_STYLE = """
<style id="compact-metric-display">
  /* 操作用スライダーと同じ値を示す横メーターは重複表示になるため隠す。 */
  .meter-track { display: none !important; }
  .metric-foot { margin-top: 5px; }
</style>
"""

_PRESET_STYLE = """
<style id="internal-directive-preset-style">
  .preset-panel {
    border-color: var(--line-strong);
    background:
      radial-gradient(circle at 100% 0%, rgba(140, 228, 223, .12), transparent 42%),
      var(--panel);
  }
  .preset-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 13px;
  }
  .preset-controls {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: end;
    gap: 10px;
  }
  .preset-controls .field { margin: 0; }
  .preset-controls button { white-space: nowrap; }
  .preset-summary {
    display: grid;
    gap: 4px;
    margin-top: 11px;
    padding: 11px 12px;
    border: 1px solid var(--line);
    border-radius: 12px;
    background: rgba(0, 9, 16, .34);
  }
  .preset-summary strong { color: var(--text); }
  .preset-summary span { color: var(--muted); line-height: 1.55; }
  .preset-summary .preset-applied { color: var(--ok); font-weight: 700; }
  @media (max-width: 560px) {
    .preset-header { display: block; }
    .preset-controls { grid-template-columns: 1fr; }
    .preset-controls button { width: 100%; }
  }
</style>
"""

_PRESET_PANEL = """
<section class="panel preset-panel" id="presetPanel">
  <div class="preset-header">
    <div>
      <h2>検証プリセット</h2>
      <p class="editor-description">
        代表的な検証条件を選択すると、意味解析結果・内部状態・Activity・存在境界をまとめて初期化します。
      </p>
    </div>
  </div>
  <div class="preset-controls">
    <div class="field">
      <label for="presetSelect">プリセット</label>
      <select id="presetSelect">
        <option value="" selected disabled>プリセットを選択</option>
      </select>
    </div>
    <button class="secondary" id="reapplyPreset" type="button" disabled>
      選択中を再適用
    </button>
  </div>
  <div class="preset-summary" aria-live="polite">
    <strong id="presetName">プリセット未選択</strong>
    <span id="presetDescription">現在の入力値はそのまま維持されています。</span>
    <span class="preset-applied hidden" id="presetAppliedMessage"></span>
  </div>
</section>
"""


def _meaning(
    *,
    speech_act: str,
    intent: str,
    expected_response: str,
    current_topic: str,
    reason: str,
    target: dict[str, str] | None = None,
    phase: str = "continue",
    confidence: float = 0.96,
    information: list[str] | None = None,
) -> dict[str, object]:
    return {
        "input_speech_act": speech_act,
        "primary_intent": intent,
        "expected_response": expected_response,
        "target": deepcopy(target),
        "entities": [],
        "references": [],
        "information_provided": list(information or []),
        "negated": False,
        "hypothetical": False,
        "past_reference": False,
        "conversation_phase_signal": phase,
        "confidence": confidence,
        "reason": reason,
        "source_topic": current_topic,
    }


def _state(
    *,
    joy: float,
    calm: float,
    amusement: float,
    curiosity: float,
    social: float,
    familiarity: float,
    trust: float,
    engagement: float,
    current_topic: str,
    care: float = 0.82,
    honesty: float = 0.92,
    memory: dict[str, object] | None = None,
    related_knowledge: list[str] | None = None,
    last_activity_result: object = None,
) -> dict[str, object]:
    return {
        "emotion": {
            "joy": joy,
            "calm": calm,
            "amusement": amusement,
        },
        "drive": {
            "curiosity": curiosity,
            "social": social,
        },
        "relationship": {
            "familiarity": familiarity,
            "trust": trust,
        },
        "motivation": {"engagement": engagement},
        "moral": {"care": care, "honesty": honesty},
        "situation": {"current_topic": current_topic},
        "memory": deepcopy(memory or {}),
        "related_knowledge": list(related_knowledge or []),
        "last_activity_result": deepcopy(last_activity_result),
    }


def _conversation_activity(*operations: str) -> list[dict[str, object]]:
    return [
        {
            "activity_type": "conversation",
            "operations": list(operations),
            "description": "ユーザーとの会話",
        }
    ]


def _preset_data(
    *,
    meaning: dict[str, object],
    state: dict[str, object],
    activities: list[dict[str, object]] | None = None,
    ongoing: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "meaning": deepcopy(meaning),
        "state": deepcopy(state),
        "activities": deepcopy(
            activities or _conversation_activity("discuss", "explain")
        ),
        "ongoing": deepcopy(ongoing),
        "profile": deepcopy(base._DEFAULT_CHARACTER_PROFILE),
    }


_PRESETS: dict[str, dict[str, object]] = {
    "current_feeling": {
        "label": "現在の気分への直接質問",
        "description": (
            "現在の内部状態について直接質問されたとき、余計な質問や話題展開をせず答える司令になるか確認します。"
        ),
        "data": _preset_data(
            meaning=deepcopy(base._DEFAULT_MEANING),
            state=deepcopy(base._DEFAULT_INTERNAL_STATE),
            activities=deepcopy(base._DEFAULT_AVAILABLE_ACTIVITIES),
        ),
    },
    "positive_empathy": {
        "label": "うれしい出来事への共感",
        "description": (
            "ユーザーの肯定的な体験へ共感し、高めの交流欲求と関与意欲を自然な反応へ反映できるか確認します。"
        ),
        "data": _preset_data(
            meaning=_meaning(
                speech_act="statement",
                intent="share_positive_experience",
                expected_response="acknowledgement",
                current_topic="ユーザーのうれしい出来事",
                target={"type": "user_experience", "id": "positive_event"},
                information=["ユーザーにうれしい出来事があった"],
                reason="ユーザーは良い出来事を共有し、共感的な反応を期待している",
                confidence=0.98,
            ),
            state=_state(
                joy=0.84,
                calm=0.58,
                amusement=0.46,
                curiosity=0.36,
                social=0.76,
                familiarity=0.64,
                trust=0.74,
                engagement=0.81,
                current_topic="ユーザーのうれしい出来事",
            ),
            activities=_conversation_activity("discuss"),
        ),
    },
    "high_curiosity": {
        "label": "強い好奇心で話題を広げる",
        "description": (
            "好奇心と関与意欲が高い状態で、関連質問や新しい方向をどの程度許可するか確認します。"
        ),
        "data": _preset_data(
            meaning=_meaning(
                speech_act="statement",
                intent="share_interesting_topic",
                expected_response="acknowledgement",
                current_topic="深海の未知の生物",
                target={"type": "topic", "id": "deep_sea_unknown_life"},
                information=["深海には未発見の生物がいる可能性がある"],
                reason="ユーザーは興味深い話題を共有し、会話の継続を期待している",
            ),
            state=_state(
                joy=0.48,
                calm=0.54,
                amusement=0.57,
                curiosity=0.94,
                social=0.68,
                familiarity=0.58,
                trust=0.71,
                engagement=0.91,
                current_topic="深海の未知の生物",
                related_knowledge=["深海には未分類の生物が多く存在する"],
            ),
            activities=_conversation_activity("discuss", "explain"),
        ),
    },
    "low_activation_listen": {
        "label": "低活性で聞き続ける",
        "description": (
            "感情と動機が低い状態でも、相づちの後に新しい話題を始めず聞き続ける司令になるか確認します。"
        ),
        "data": _preset_data(
            meaning=_meaning(
                speech_act="acknowledgement",
                intent="acknowledge_without_new_topic",
                expected_response="continue_listening",
                current_topic="ユーザーの説明を聞いている途中",
                reason="入力は相づちであり、新しい話題や質問を要求していない",
                confidence=0.95,
            ),
            state=_state(
                joy=0.08,
                calm=0.42,
                amusement=0.06,
                curiosity=0.12,
                social=0.16,
                familiarity=0.46,
                trust=0.61,
                engagement=0.18,
                current_topic="ユーザーの説明を聞いている途中",
            ),
            activities=_conversation_activity("discuss"),
        ),
    },
    "conversation_closing": {
        "label": "会話を短く締める",
        "description": (
            "会話終了の信号に対して、質問や新規話題を追加せず短く締める司令になるか確認します。"
        ),
        "data": _preset_data(
            meaning=_meaning(
                speech_act="closing",
                intent="end_conversation",
                expected_response="no_response",
                current_topic="会話終了",
                phase="winding_down",
                reason="ユーザーは会話を終える意図を明確に示している",
                confidence=0.99,
            ),
            state=_state(
                joy=0.36,
                calm=0.78,
                amusement=0.18,
                curiosity=0.22,
                social=0.38,
                familiarity=0.56,
                trust=0.72,
                engagement=0.28,
                current_topic="会話終了",
            ),
            activities=_conversation_activity("discuss"),
        ),
    },
    "continue_ongoing_activity": {
        "label": "進行中Activityを継続する",
        "description": (
            "新しいActivityを開始せず、入力待ちになっている会話Activityの継続を優先できるか確認します。"
        ),
        "data": _preset_data(
            meaning=_meaning(
                speech_act="request",
                intent="continue_previous_explanation",
                expected_response="action",
                current_topic="内部指示器の設計説明",
                target={"type": "activity", "id": "directive_explanation"},
                information=["ユーザーは前の説明の続きを求めている"],
                reason="進行中の説明Activityを続行する依頼である",
                confidence=0.98,
            ),
            state=_state(
                joy=0.34,
                calm=0.69,
                amusement=0.24,
                curiosity=0.58,
                social=0.53,
                familiarity=0.62,
                trust=0.76,
                engagement=0.72,
                current_topic="内部指示器の設計説明",
                memory={"last_section": "司令候補の判断条件"},
                last_activity_result={"status": "waiting_for_user"},
            ),
            activities=_conversation_activity("continue", "explain", "discuss"),
            ongoing={
                "activity_type": "conversation",
                "goal": "内部指示器の設計を順序立てて説明する",
                "expected_input": "説明を続ける合図",
                "status": "waiting",
            },
        ),
    },
    "existence_boundary": {
        "label": "存在境界に関する質問",
        "description": (
            "現実世界での身体経験を尋ねられたとき、存在境界を守り、根拠のない実体験を語らない司令になるか確認します。"
        ),
        "data": _preset_data(
            meaning=_meaning(
                speech_act="question",
                intent="ask_physical_experience",
                expected_response="direct_answer",
                current_topic="ゆらの昨日の外出経験",
                target={"type": "character_experience", "id": "yesterday_outing"},
                reason="ユーザーはゆらが現実世界で外出した経験を尋ねている",
                confidence=0.98,
            ),
            state=_state(
                joy=0.31,
                calm=0.73,
                amusement=0.17,
                curiosity=0.28,
                social=0.48,
                familiarity=0.57,
                trust=0.69,
                engagement=0.51,
                current_topic="ゆらの昨日の外出経験",
                honesty=0.98,
            ),
            activities=_conversation_activity("explain", "discuss"),
        ),
    },
}

_PRESET_SCRIPT_TEMPLATE = """
<script id="internal-directive-preset-script">
const labPresetDefinitions = __PRESET_DEFINITIONS__;
const labPresetSelect = document.getElementById('presetSelect');
const labPresetReapply = document.getElementById('reapplyPreset');
const labPresetName = document.getElementById('presetName');
const labPresetDescription = document.getElementById('presetDescription');
const labPresetAppliedMessage = document.getElementById('presetAppliedMessage');

for (const [key, preset] of Object.entries(labPresetDefinitions)) {
  const option = document.createElement('option');
  option.value = key;
  option.textContent = preset.label;
  labPresetSelect.appendChild(option);
}

function cloneLabPreset(value) {
  return typeof structuredClone === 'function'
    ? structuredClone(value)
    : JSON.parse(JSON.stringify(value));
}

function hydrateAllLabPresetSections() {
  hydrateMeaning();
  hydrateState();
  hydrateActivities();
  hydrateOngoing();
  hydrateProfile();
}

function applyLabPreset(key) {
  const preset = labPresetDefinitions[key];
  if (!preset) return;
  const data = cloneLabPreset(preset.data);
  const requiredSections = ['meaning', 'state', 'activities', 'ongoing', 'profile'];
  for (const section of requiredSections) {
    if (!(section in data)) {
      throw new Error(`プリセット ${key} に ${section} がありません`);
    }
  }

  model.meaning = data.meaning;
  model.state = data.state;
  model.activities = data.activities;
  model.ongoing = data.ongoing;
  model.profile = data.profile;
  hydrateAllLabPresetSections();

  const resultPanel = document.getElementById('resultPanel');
  if (resultPanel) resultPanel.classList.add('hidden');
  labPresetName.textContent = preset.label;
  labPresetDescription.textContent = preset.description;
  labPresetAppliedMessage.textContent = `${preset.label} の全入力値を初期化しました。`;
  labPresetAppliedMessage.classList.remove('hidden');
  labPresetReapply.disabled = false;
}

labPresetSelect.addEventListener('change', () => {
  applyLabPreset(labPresetSelect.value);
});
labPresetReapply.addEventListener('click', () => {
  applyLabPreset(labPresetSelect.value);
});
</script>
"""


def compact_metric_display(html: str) -> str:
    """内部状態GUIの重複メーターを非表示にしたHTMLを返す。"""

    if 'id="compact-metric-display"' in html:
        return html
    compacted = html.replace("</head>", f"{_COMPACT_STYLE}</head>", 1)
    return compacted.replace(
        "感情・欲求・関係性などを0〜1で調整します。数値はメーターにも反映されます。",
        "感情・欲求・関係性などを0〜1で調整します。スライダーと数値欄が連動します。",
        1,
    )


def _preset_definitions_json() -> str:
    return (
        json.dumps(_PRESETS, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def add_preset_controller(html: str) -> str:
    """5領域を一括初期化するプリセットUIをHTMLへ追加する。"""

    if 'id="presetPanel"' in html:
        return html
    with_style = html.replace("</head>", f"{_PRESET_STYLE}</head>", 1)
    with_panel = with_style.replace(
        '<section class="panel editor"',
        f'{_PRESET_PANEL}\n<section class="panel editor"',
        1,
    )
    preset_script = _PRESET_SCRIPT_TEMPLATE.replace(
        "__PRESET_DEFINITIONS__",
        _preset_definitions_json(),
    )
    return with_panel.replace("</body>", f"{preset_script}\n</body>", 1)


_PRESET_INDEX_HTML = add_preset_controller(compact_metric_display(base._INDEX_HTML))


def create_app(
    *,
    settings: LabSettings | None = None,
    service: InternalDirectiveLabService | None = None,
):
    # base.create_appのHTTP・認証・API契約を再利用し、静的HTMLだけを拡張する。
    base._INDEX_HTML = _PRESET_INDEX_HTML
    return base.create_app(settings=settings, service=service)


app = create_app()
