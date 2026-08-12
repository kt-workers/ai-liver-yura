from __future__ import annotations

from cloud_validation import character_response_lab as base
from cloud_validation.character_semantic_response_lab_ui import (
    CHARACTER_SEMANTIC_RESPONSE_LAB_HTML,
)


def test_semantic_lab_uses_dedicated_compact_ui() -> None:
    html = CHARACTER_SEMANTIC_RESPONSE_LAB_HTML

    assert "height:100vh" in html
    assert "overflow:hidden" in html
    assert 'class="workspace"' in html
    assert 'id="runState"' in html
    assert 'data-state="idle"' in html


def test_semantic_lab_state_values_default_to_graph_mode_with_json_toggle() -> None:
    html = CHARACTER_SEMANTIC_RESPONSE_LAB_HTML

    assert 'id="stateJsonToggle" type="checkbox"' in html
    assert 'id="stateCharts" class="state-charts"' in html
    assert 'id="stateJson" class="state-json hidden"' in html
    assert 'id="emotionChart"' in html
    assert 'id="driveChart"' in html
    assert "flattenNumeric" in html
    assert "renderStateCharts" in html
    assert "setStateJsonMode(false);" in html


def test_preset_load_and_run_clear_previous_result_before_work() -> None:
    html = CHARACTER_SEMANTIC_RESPONSE_LAB_HTML

    load_handler = html.split("$('load').onclick = () => {", 1)[1].split("};", 1)[0]
    run_handler = html.split("$('run').onclick = async () => {", 1)[1].split("};", 1)[0]

    assert "clearResult('loaded', 'プリセット読込済み');" in load_handler
    assert load_handler.index("clearResult") < load_handler.index("apply(preset.data)")
    assert "clearResult('running', '実行中', '実行中…');" in run_handler
    assert "postCharacterResponse(requestData())" in run_handler


def test_clear_result_resets_result_and_all_kpis() -> None:
    html = CHARACTER_SEMANTIC_RESPONSE_LAB_HTML
    clear_body = html.split("function clearResult", 1)[1].split("}\n\nfunction flattenNumeric", 1)[0]

    assert "lastResult = null" in clear_body
    assert "$('result').textContent = resultText" in clear_body
    assert "$('resultStatus').textContent = '-'" in clear_body
    assert "$('attempts').textContent = '-'" in clear_body
    assert "$('elapsed').textContent = '-'" in clear_body


def test_semantic_lab_adds_all_presets_execution_option() -> None:
    html = CHARACTER_SEMANTIC_RESPONSE_LAB_HTML

    assert "const ALL_PRESETS_KEY = '__all_presets__';" in html
    assert "すべて実行（全プリセット）" in html
    assert "async function runAllPresets()" in html
    assert "Object.entries(presets)" in html
    assert "for (const [index, [key, preset]] of entries.entries())" in html
    assert "await postCharacterResponse(batchRequestData(preset.data))" in html
    assert "request_ok: false" in html
    assert "execution_mode: 'all_presets'" in html
    assert "summary:" in html
    assert "results" in html


def test_batch_execution_keeps_single_api_path_and_applies_prompt_toggle() -> None:
    html = CHARACTER_SEMANTIC_RESPONSE_LAB_HTML

    assert "async function postCharacterResponse(data)" in html
    assert "fetch('/api/character-response'" in html
    assert "function batchRequestData(data)" in html
    assert "include_prompts: $('includePrompts').checked" in html
    assert "await runAllPresets();" in html


def test_prompt_toggle_is_in_toolbar_not_constraints_details() -> None:
    html = CHARACTER_SEMANTIC_RESPONSE_LAB_HTML

    toolbar = html.split('<div class="toolbar">', 1)[1].split('</div>\n<div class="workspace">', 1)[0]
    constraints = html.split('<details><summary>Constraints / Character</summary>', 1)[1].split('</details>', 1)[0]

    assert 'id="includePrompts" type="checkbox"' in toolbar
    assert "Promptも結果に含める" in toolbar
    assert 'id="includePrompts"' not in constraints
    assert 'class="switch-label prompt-toggle"' in toolbar


def test_all_presets_selection_disables_load_without_rewriting_input_form() -> None:
    html = CHARACTER_SEMANTIC_RESPONSE_LAB_HTML
    sync_controls = html.split("function syncPresetControls()", 1)[1].split("}\n\nasync function loadPresets", 1)[0]
    batch_body = html.split("async function runAllPresets()", 1)[1].split("}\n\n$('stateJsonToggle')", 1)[0]

    assert "$('load').disabled = allSelected || $('run').disabled" in sync_controls
    assert "apply(preset.data)" not in batch_body


def test_semantic_module_overrides_only_its_process_ui() -> None:
    # Importing the semantic lab module installs the dedicated HTML before create_app().
    from cloud_validation import character_semantic_response_lab as semantic

    assert semantic.app is not None
    assert base._INDEX_HTML == CHARACTER_SEMANTIC_RESPONSE_LAB_HTML
