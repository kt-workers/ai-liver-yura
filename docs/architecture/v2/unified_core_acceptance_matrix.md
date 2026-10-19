# 統合本体 — 設計・試験・実装の受入対応表

状態: 2026-10-19 再構築時の受入正本補足。実装完了証明ではない。

## 1. 判定のAuthority

機能と構造の正本は[統合本体](unified_core_architecture.md)と各Domain契約であり、本書は**その期待結果を試験でどう観測するか**を定める。System全体は[System Integration](system_integration_contracts.md)、Brainの非直列性は[Brain Integration](brain_integration_contracts.md)、Speechの各意味契約は各Speech詳細設計に従う。これらの意味・数値規則を本書で再定義しない。

順序は **正本の整合・不足の補修 → 試験の期待値確定 → 試験の実行 → 製品実装の修正 → 同一試験と全体試験の再実行** とする。設計の不足・矛盾を見つけた場合は具体的根拠を示して訂正し、実装の現状を正しい仕様として取り込まない。

判定は次を区別する。

- **局所PASS:** 指定した関数・Owner・Portの一契約を確認しただけ。全体製品の合格ではない。
- **統合PASS:** 同一の正式起動で全必須Ownerを保持し、対象経路の実際の状態遷移・結果・出典を観測した。
- **実環境PASS:** 実LLM、実DB、音声等、その試験で要求する実接続を用いて事実と品質を確認した。
- **未達:** 試験未実装、設計に反するテスト期待値、製品未実装、未実行、結果不合格のいずれか。未達をskip/xfailや小構成で合格に置き換えない。

決定論的なテストでは外部Portをfakeに置き換えてよいが、Goal・Activity・Memory・Speech等の**Domain責務そのものは省かない**。本番起動と部分的な単体試験を混同しない。

## 2. 必須受入の対応表

| ID | 正本と要求する事実 | 判定用の試験と観測内容 | 現在の不足 |
| --- | --- | --- | --- |
| UC-01 | 統合本体 §3、System Integration §3–5：標準起動に全必須Ownerを構成 | `python -m app` 相当の正式入口が必須Ownerの欠落を起動成功にしない。成功経路では登録Ownerと単一runを実測 | Memory・Speech・Body・Reflectionの成功経路は未受入 |
| UC-02 | 統合本体 §2：Clean Architectureの責務と依存方向 | 関数・クラスとimportの依存方向、組立てと実行の分離、単一の正規Ownerを検証 | ASTの文字列確認だけで全責務を証明できない |
| UC-03 | Brain Integration §19：入力と内部契機 | 通常入力／内部triggerが意味解析・評価・Attention・Executiveへ届き、対象traceの結果だけが一致する | 部分結合を全構成の成功としない |
| UC-04 | Brain Integration §19：Goalと活動事実 | Goal/Plan/Activityの各Ownerの版・失敗と、実際の完了事実の区別を観測 | 本体標準起動の端から端は未受入 |
| UC-05 | 統合本体 §4：Memoryと保存Port | Speechの設定に無関係に正規Memoryを接続。未登録は起動成功不可。DB失敗は型付き失敗、復元・再起動・出典を照合 | Memory借用の局所試験はあるが本番供給・復元は未受入 |
| UC-06 | 統合本体 §4、Brain Integration §10：Speech意味経路 | TTS/Presentation未配備でもSpeech Semantic/Character/Verifier等の本体Ownerを保持し、未提示を成功扱いしない | Speech未登録で起動成功する旧試験は受入に使用不可 |
| UC-07 | System Integration §10–11：Body連続意図 | 本体意図→Bodyの時間連続更新と、Avatar/物理機器の未接続を区別する | 本体標準起動との結合は未受入 |
| UC-08 | 統合本体 §3、Brain Integration §19：取消・並行・停止 | slow LLM/Reflection中の会話継続、backpressure、stale結果の拒否、借用資源非解放、所有資源回収 | 個別の局所試験成功のみでは不十分 |
| UC-09 | 統合本体 §5、System Integration §24：実環境の受入 | Python 3.10.5、実PostgreSQL、実LLM、実発話、自律活動、再起動の結果を分離して確認 | 既存CI成功は実LLM・実発話・全本体の証明ではない |

## 3. 監査で発見した誤判定の候補

- `tests/bootstrap/test_speech_production_configuration.py::test_speech_not_configured_keeps_cognition_only` は、Speech Owner不在を起動成功として期待する。**外部Speech提示の無効**と**本体のSpeech意味責務の欠落**を区別した試験へ修正する必要がある。
- `tests/bootstrap/test_runtime_owners.py::test_default_runtime_owners_keep_explicit_empty_bindings` は、Memoryなしの構成DTOを確認する局所試験であり、標準製品の起動成功を裏付けない。正式入口の未登録拒否を別途試験する。
- `tests/architecture/test_unified_core_contract.py::test_core_components_reject_partial_brain_registration` は、実行結果でなくソース中の文字列の有無を検査している。実際に不足Ownerを拒否する動作試験へ改める。
- `tests/bootstrap/test_system_cognition_configuration.py::test_supplied_memory_owner_is_wired_without_speech_and_remains_borrowed` は、Memory Ownerの同一性と借用終了だけを検証する**部分的な構成試験**である。正式製品の合格と解釈しない。

## 4. 完了条件と移行時の扱い

各IDは **設計上の根拠 → 正しい試験 → 実装 → 同一HEADの検証結果** を揃えた場合だけ合格とする。未受入のIDが一つでも残る間はPRをDraftに維持し、製品完成と宣言しない。設計・試験の先行により失敗する試験は欠陥検出として扱い、期待値を実装へ合わせて緩めない。CI緑はあくまで現行収録試験の結果であり、この表の全IDのPASSではない。
