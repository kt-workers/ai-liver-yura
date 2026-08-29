# Loop Engineering 自己改善系統

所有Issue: #465
親Issue: #462
Root: #317
Mission: #450
状態: 正本補足 / 実装契約

## 1. 目的

Loop Engineeringを「不足が原因で停止してから人間が保守する」仕組みにしない。通常実行中にLoop自身の反復失敗、進捗停止（no-progress）、不要な人間介入、反復手動操作、古い状態、重複割当、反復復旧を型付き健全性証拠として観測し、改善が必要ならLoop Engineering自身のWorkを自動生成して通常Schedulerへ投入する。

自己改善系統（Self-Improvement Lane）はMissionの別停止モードではない。回復可能な改善候補が存在してもMissionは`ACTIVE`を維持し、製品Workと同じ依存関係・優先度・実行可能性の規則で選択する。

## 2. 境界

正規配置:

```text
tools/loop_engine/
├─ health.py
├─ maintenance.py
├─ github_issues.py
└─ existing supervisor modules
```

製品実行系`app/**`は自己改善系統を取り込まない。

自己改善系統は次を所有しない。

- AI Liver ゆらのCore State / Goal / Attention / Body / Memoryの正本
- 製品実行時の割当
- OpenAIレビューワー認証情報・判定の正本
- PostgreSQL運用記憶の正本
- GitHub Project #6対応

## 3. Loop健全性事象

```text
LoopHealthEvent
- kind
- fingerprint
- occurrence_count
- affected_work_ids[]
- source_refs[]
- blocked_work_count
- manual_intervention_required
```

`fingerprint`は生のエラー本文ではなく、秘密情報を含まない安定した分類identityとする。外部接続層から受け取る指紋（fingerprint）と証拠参照は信頼できない入力であり、メモリ内観測であってもGitHub Checkpointへ永続化する前に不可逆かつ上限付きの正規identityへ変換する。許可文字だけの絞込みでは認証情報らしい値が通過し得るため使用しない。復元後も同じ正規identityを用い、再起動前後で同一健全性事象の相関を変えない。

初期`kind`:

- `REPEATED_FAILURE`
- `NO_PROGRESS`
- `MANUAL_INTERVENTION`
- `MANUAL_OPERATION_REPEAT`
- `STALE_STATE_RECURRENCE`
- `DUPLICATE_SCHEDULING`
- `RECOVERY_REPETITION`

Supervisor自身が観測できる重複抑止、古い状態の競合、人間介入の実行結果は、実行ごとに累積健全性スナップショットへ反映する。CI、レビューワー、外部接続層、操作者操作などの実行層も、同じ型付き事象契約へ秘密情報を含まない証拠を供給できる。

健全性スナップショットはCheckpointへ永続化可能な型とし、PostgreSQL導入前でもGitHub上の永続Checkpointから次回実行へ復元できる。

## 4. 発火方針

1回の偶発失敗ですぐ改善Issueを量産しない。初期しきい値は次とする。

| 種別 | しきい値 |
| --- | ---: |
| `REPEATED_FAILURE` | 3 |
| `NO_PROGRESS` | 2 |
| `MANUAL_INTERVENTION` | 2 |
| `MANUAL_OPERATION_REPEAT` | 2 |
| `STALE_STATE_RECURRENCE` | 2 |
| `DUPLICATE_SCHEDULING` | 2 |
| `RECOVERY_REPETITION` | 2 |

しきい値は決定論的方針とし、LLMの自由判断にしない。

## 5. 優先度と日程

- 人間介入を要求する、またはWorkを停止させる改善: `P0`
- 反復失敗、進捗停止、反復手動操作、古い状態、反復復旧: 原則`P1`
- 重複抑止など停止を伴わない効率改善: `P2`

改善Issueには必ず開始予定日と目標予定日を生成する。

- `P0`: 開始は当日 / 目標は+2日
- `P1`: 開始は当日 / 目標は+4日
- `P2`: 開始は当日 / 目標は+7日

日程は品質判定を緩めない。

## 6. 改善キーと重複抑止

```text
improvement_key = SHA256(
  kind + fingerprint + affected_work_ids
)
```

Issue本文へ次の永続印を埋め込む。

```text
<!-- loop-improvement-key:<sha256> -->
```

同じkeyのopen `loop-engineering` Issueが存在する場合は新しいIssueを作らない。公開処理は先頭固定件数ではなく、GitHubの全ページを走査して永続印を探索する。探索からIssue作成、Project #7設定までを、`improvement_key`ごとの信頼済みホスト助言ロック（advisory lock）で直列化する。#465はPostgreSQL共有記憶を所有しないため、複数ホストから同じkeyを同時公開する構成は安全側停止で禁止する。単一信頼済みホスト内の並行実行は同じロックを共有し、ロック取得後に必ず印を再探索してから作成を許可する。

Checkpointですでに同じkeyを送出済みの場合も、同一観測から重複生成しない。

終了済みIssueの原因が後に再発した場合は、新しい実行証拠として再作成を許可する。

## 7. Issue大量生成の防止

1回のSupervisor判断から新規改善候補を最大3件に制限する。

候補順位:

1. `P0 > P1 > P2`
2. 発生回数の降順
3. 種別・指紋の安定順

大量の失敗をIssue大量生成へ変換しない。

## 8. GitHub Issue公開

改善Workの人間向けGitHub文章は日本語とする。自動生成Issueには`loop-engineering`ラベルだけを使用し、V2製品用`v2`ラベルを付けない。

信頼済みホスト公開処理は固定Repository `ktan514/ai-liver-yura`だけを対象にする。

```text
ImprovementCandidate
→ ImprovementIssueIntent
→ key単位の公開ロック
→ open Issue重複確認 / 再確認
→ gh issue create
→ Project #7現在状態の再取得
→ Project #7 item追加 / 再利用
→ 現在field / option ID解決
→ Ready / Priority / Area / Work / Start / Target
→ 新しいWrite Gate
→ 変更
→ 所有fieldの効果再取得 / 次Observation
```

Project #6およびProject #7以外は明示拒否する。Project項目探索も先頭固定件数へ依存せず、全ページを走査して既存項目identityを解決する。Projectのfield/option IDを保存・固定値として保持しない。

Project変更の直前にはproject、item、field、option identityを現在状態から再取得し、変更後にはitem field valueの効果を再取得する。効果の再取得は任意ではなく、効果を持つ変更意図の必須事後条件である。再取得不能、欠落、不一致の場合は`MUTATION_EFFECT_MISMATCH`として安全側停止にし、`project_configured=True`を返してはならない。

初期Project値:

- Status: `Ready`
- Priority: 候補の重要度
- Area: `Subsystem/Development Tooling`
- Issue level: `Work`
- Start date: 候補開始日
- Target date: 候補目標日

## 9. 信頼境界と秘密情報保護

- Issue / PR本文をコマンドとして実行しない
- `gh`は固定形状の引数列で起動し、shell展開しない
- 標準エラー、生の提供元データ、token、`.env`、DB URLをIssueへ転記しない
- titleは型付き種別から固定日本語文言を生成する
- 指紋・証拠は秘密情報を含まない安定参照だけを入力にする
- レビューワー認証情報を公開処理へ渡さない

## 10. Scheduler統合

改善IssueがProject #7の`Ready`になった後は、特殊な別queueへ隔離しない。通常`WorkSnapshot`として観測し、既存Schedulerの依存関係、優先度、実行可能性、現在作業系列の継続性に従う。

このため:

- 現在製品Workが実行可能なら無条件に横取りしない
- 現在Workが待機専用で、改善Workが依存関係を満たして実行可能なら選択できる
- P0改善が通常候補群に入ればP0規則で選択される
- 改善Work自身も再開判定、CI、厳密HEAD正本レビュー、統合判定に従う

## 11. 失敗時の意味

自己改善公開処理の失敗をMission完了として扱わない。

- 決定論的Coreは候補を保持できる
- GitHub/Project変更失敗は型付き運用失敗として次回実行で再試行できる
- Issue作成済み・Project設定途中の場合、永続印で同一Issueを再利用してProject設定を修復する
- 回復可能な公開失敗だけで`MISSION_COMPLETE`にしない
- 本当に権限または人間判断が必要な場合だけ`INTERVENTION_REQUIRED`

## 12. 受け入れ条件

- 2回目の同一人間介入でP0改善候補が生成される
- 反復失敗がしきい値へ到達してもMissionを止めず候補生成する
- 同じopen improvement keyを重複作成しない
- 後方ページにある永続印も見落とさない
- 1回の実行で最大3候補
- Issue本文に永続keyと開始・目標日を持つ
- `loop-engineering`ラベルでIssue作成
- Project #7へ現在ID解決後にReady/Priority/Area/Work/Start/Targetを設定
- Project変更前の新しいWrite Gateと変更後の効果再取得
- Project #6を明示拒否
- 製品`app/**`へ依存しない
- 生成した改善Workを通常Schedulerが選択できる
- 自己改善失敗だけでMission完了を主張しない
- 対象試験 / Ruff / 厳格Mypy / 全pytest / compileall / 差分確認 / 厳密HEAD CI
- 厳密HEAD正本レビューを実施する
