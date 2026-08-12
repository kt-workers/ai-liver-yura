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

Build Command:

```bash
pip install -r requirements.txt
```

Start Command:

```bash
python gui/yura-system-architecture-visualizer/server.py
```

Renderが設定する `PORT` をそのまま使用します。

## 表示内容

- `app/<module>` を基本とする論理モジュール
- `app/plugins/<plugin>` はpluginごとに分割
- `gui/<tool>` はGUIツールごとに分割
- Python ASTで検出した内部 `import` / `from ... import ...`

方向は `依存元 -> import先` です。

詳細設計は `docs/gui/yura_system_architecture_visualizer_design.md` を参照してください。
