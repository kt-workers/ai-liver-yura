# Yura System Architecture Visualizer

`ai-liver-yura` のPython実装をread-only解析し、論理モジュール間のimport依存をノード・方向付きエッジで表示する開発支援GUIです。

## 起動

リポジトリルートで:

```bash
python gui/yura-system-architecture-visualizer/server.py
```

既定では `http://localhost:8765` で起動します。

環境変数:

- `HOST`: bind address。既定 `0.0.0.0`
- `PORT`: listen port。既定 `8765`

## Render

既存GUI用のルート `render.yaml` とは分離し、Architecture Visualizer専用Blueprintを使用します。

Blueprint file:

```text
render-system-architecture-visualizer.yaml
```

Render DashboardでBlueprintを作成または更新するとき、**Blueprint Path** に次を指定します。

```text
render-system-architecture-visualizer.yaml
```

このBlueprintは `yura-system-architecture-visualizer` の1サービスだけを管理します。既存のInner State / Configuration Harbor / Avatar Runtime Labを重複作成しません。

Build Command:

```bash
pip install -r requirements.txt && python -m compileall gui/yura-system-architecture-visualizer
```

Start Command:

```bash
python gui/yura-system-architecture-visualizer/server.py
```

Health Check:

```text
/api/health
```

Renderが設定する `PORT` をそのまま使用します。

## 表示内容

- `app/<module>` を基本とする論理モジュール
- `app/plugins/<plugin>` はpluginごとに分割
- `gui/<tool>` はGUIツールごとに分割
- Python ASTで検出した内部 `import` / `from ... import ...`

方向は `依存元 -> import先` です。

詳細設計は `docs/gui/yura_system_architecture_visualizer_design.md` を参照してください。
