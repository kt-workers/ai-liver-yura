from __future__ import annotations

from cloud_validation import internal_directive_lab_compact as compact
from cloud_validation import internal_directive_lab_workspace as workspace

LabSettings = compact.LabSettings
InternalDirectiveLabService = compact.InternalDirectiveLabService

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


# workspace側で組み立て済みの完成HTMLを基準にする。
# DOMや既存JavaScriptを再生成せず、対象プリセットの値だけを訂正する。
_REVIEWED_INDEX_HTML = _correct_existence_preset_html(
    workspace._WORKSPACE_INDEX_HTML
)


def create_app(
    *,
    settings: LabSettings | None = None,
    service: InternalDirectiveLabService | None = None,
):
    """存在境界プリセット修正版の検証ラボを生成する。"""

    compact.base._INDEX_HTML = _REVIEWED_INDEX_HTML
    return compact.base.create_app(settings=settings, service=service)


app = create_app()
