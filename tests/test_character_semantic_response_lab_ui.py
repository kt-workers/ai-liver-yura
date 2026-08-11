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
    assert run_handler.index("clearResult") < run_handler.index("fetch('/api/character-response'")


def test_clear_result_resets_result_and_all_kpis() -> None:
    html = CHARACTER_SEMANTIC_RESPONSE_LAB_HTML
    clear_body = html.split("function clearResult", 1)[1].split("}\n\nfunction flattenNumeric", 1)[0]

    assert "lastResult = null" in clear_body
    assert "$('result').textContent = resultText" in clear_body
    assert "$('resultStatus').textContent = '-'" in clear_body
    assert "$('attempts').textContent = '-'" in clear_body
    assert "$('elapsed').textContent = '-'" in clear_body


def test_semantic_module_overrides_only_its_process_ui() -> None:
    # Importing the semantic lab module installs the dedicated HTML before create_app().
    from cloud_validation import character_semantic_response_lab as semantic

    assert semantic.app is not None
    assert base._INDEX_HTML == CHARACTER_SEMANTIC_RESPONSE_LAB_HTML
