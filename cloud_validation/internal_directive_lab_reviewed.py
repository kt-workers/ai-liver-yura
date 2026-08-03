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

# 修正済みプリセットから完成HTMLを再構築する。
_REVIEWED_PRESET_INDEX_HTML = compact.add_preset_controller(
    compact.compact_metric_display(compact.base._INDEX_HTML)
)
_REVIEWED_INDEX_HTML = workspace.add_workspace_controls(
    _REVIEWED_PRESET_INDEX_HTML
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
