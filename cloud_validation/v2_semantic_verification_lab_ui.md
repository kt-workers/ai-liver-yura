# V2 Semantic Verification Lab UI 仕様

Issue #427 の Render Lab は、production #363 Semantic Verification を実LLMで反復確認する validation-only UI である。Semantic判定ロジックをLabへ複製せず、入力・実行・観測・Exportを安定して行う。

## UI原則

- デスクトップでは主要操作と結果要約を固定し、内容の長さで画面全体を上下に動かさない。
- 左に検証入力、右に本番検証結果を並べ、長いJSONは各ペイン内部だけスクロールする。
- Role A / Role B / Runtime / Full JSON はセクション単位で折りたたみ、初期状態は閉じる。
- 海中系ダーク背景、半透明カード、青緑アクセントで既存のゆら検証Labと視覚的一貫性を持たせる。
- 実LLM実行ボタンの直下にExport導線を置く。
- 狭幅では1カラムへフォールバックする。

## プリセット

内部case IDは英語のstable IDを維持し、UIでは日本語表示名と説明を表示する。プリセット適用時は入力JSON全体を選択caseの値へ置換する。英語IDはExport・GitHub記録・再現性のため残す。

## 結果表示

常時表示する要約は、最終判定、期待結果、total latency、input/output token。詳細はRole A、Role B、Runtime、完全結果JSONの順に折りたたみ表示する。Provider/Schemaエラー時は最初の失敗を確認しやすいようRole A詳細だけ自動展開してよい。

## Authority境界

UIの日本語表示名・説明・期待値は観測補助であり、production #363のSemantic Acceptanceを決める入力Authorityへ渡さない。Lab固有のkeyword / phrase / regex semantic matcherを追加しない。
