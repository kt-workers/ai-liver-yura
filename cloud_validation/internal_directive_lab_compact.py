from __future__ import annotations

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


_COMPACT_INDEX_HTML = compact_metric_display(base._INDEX_HTML)


def create_app(
    *,
    settings: LabSettings | None = None,
    service: InternalDirectiveLabService | None = None,
):
    # base.create_appのHTTP・認証・API契約をそのまま再利用し、静的HTMLだけを差し替える。
    base._INDEX_HTML = _COMPACT_INDEX_HTML
    return base.create_app(settings=settings, service=service)


app = create_app()
