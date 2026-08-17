# V2 Semantic Verification Lab UI 仕様

Issue #427 の Render Lab は、production #363 Semantic Verification を実LLMで反復確認する validation-only UI である。Semantic判定ロジックをLabへ複製せず、入力・実行・観測・Exportを安定して行う。

## UI原則

- デスクトップでは主要操作と結果要約を固定し、内容の長さで画面全体を上下に動かさない。
- 左に検証入力、右に本番検証結果を並べ、長いJSONは各ペイン内部だけスクロールする。
- Role A / Role B / Runtime / Full JSON はセクション単位で折りたたみ、初期状態は閉じる。
- Provider/Schemaエラー時だけ最初の失敗箇所を確認しやすいようRole Aを自動展開してよい。
- 海中系ダーク背景、半透明カード、青緑アクセントで既存のゆら検証Labと視覚的一貫性を持たせる。
- 実LLM実行ボタンの直下にExport導線を置く。
- 狭幅では1カラムへフォールバックする。

## プリセット

内部case IDは英語のstable IDを維持し、UIでは日本語表示名と説明を表示する。プリセット選択時は説明を更新し、`選択内容を適用`で入力JSON全体を選択caseの値へ置換する。英語IDはExport・GitHub記録・再現性のため残す。

表示メタデータは `v2_semantic_verification_presets_ja.json` へ分離し、semantic fixture自体には混入させない。

## 結果表示

常時表示する要約は、最終判定、期待結果、total latency、input/output token。詳細はRole A、Role B、Runtime、完全結果JSONの順に折りたたみ表示する。

## Live fixture timing

Labは#362/#330 Authorityを通すために1ms単位のsynthetic provenance timestampを生成する。Render実LLMでは、このsynthetic timeline全体を実時計より十分過去へ配置する。

人工timestampを現在時刻より未来へ進めてはならない。そうするとproduction `validate_role_exchange()`がProvider開始時刻よりrequest作成時刻の方が新しいと正しく判定し、`POLICY_VIOLATION`でfail-closedするためである。

Render entrypointではsynthetic baseを実時計より100ms過去に置く。現在の7ms synthetic timeline + request作成1msを差し引いても90ms以上の余裕を残す `test_render_fixture_does_not_create_future_transport_timestamps` を回帰Gateとする。

この補修はvalidation fixtureの時刻生成だけに限定し、#363 verifier / #357 adapterのtransport invariantを緩めない。自動Gate通過後、Render上の同一 `exact_preservation` caseを再実行してtransport violationが解消したことを確認する。

## Export

Exportには日本語プリセット名、stable case ID、expected/actual、latency、検証入力JSON、本番検証結果JSONを含める。

## Authority境界

UIの日本語表示名・説明・期待値は観測補助であり、production #363のSemantic Acceptanceを決める入力Authorityへ渡さない。Lab固有のkeyword / phrase / regex semantic matcherを追加しない。
