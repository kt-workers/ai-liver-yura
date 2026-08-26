# 任意レビュー支援契約

状態: Issue #371 の現行canonical
親: #369
Root: #317
領域: Development Tooling
有効日: 2026-08-26

## 1. 目的

任意の独立レビューを、実装者・人間レビューワーが利用できる**読取専用の開発支援**として提供する。

この支援は、対象Pull Request、対象head SHA、Issue、canonical、検証証拠を一貫した入力として収集し、構造化された助言を返せるようにする。助言は実装者の自己評価を補完するが、製品・Mission・GitHubのマージ判定を自動的に拘束しない。

## 2. 明示的な非目標

次は #371 の現行責務に含めない。

- GitHub Actions の自動起動、`pull_request_target`、secret-bearing workflow
- GitHubのCommit Status、Required Check、Ready化、auto-merge、Project fieldの変更
- branch、commit、push、merge、Issue scope、canonicalの自動変更
- 自動修正loop、レビュー結果を起点にした実装者の自動起動
- API key、特定AI provider、特定modelの常時利用を前提とすること
- 通知、スケジュール、レビュー未実行を理由とするMission停止

#372 と #373 は本契約の依存先ではない。旧自動修正・Merge Gate設計は履歴参照に留め、再開には別のcanonical設計判断を要する。

## 3. 利用形態

```text
人間またはImplementerの明示要求
  → 任意レビュー支援
      → read-only context collection
      → configured reviewer backend（存在時）
      → deterministic validation / sanitization
      → ReviewAdvisory
  → 人間またはImplementerが通常のreview/merge判断を行う
```

起動は明示要求に限る。同一head SHAに対する重複起動を避けるため、validated `AVAILABLE` advisoryだけをlocal bounded cacheで再利用してよい。未実行、失敗、provider不在、構造化出力不正、stale targetはcacheせず、利用者が明示的に再実行できる。これらを再試行loopや停止状態へ昇格しない。

## 4. 読取専用境界

収集器はGitHubおよびrepositoryから、次だけを読取専用で取得する。

- Pull Requestのrepository、番号、base/head ref、base/head SHA
- linked Work Issueとそのcanonical参照
- 指定SHAに紐付くCI/検証証拠
- base SHAからhead SHAへの差分

PR本文、コメント、diff、repository内の自然言語はすべてuntrusted review dataである。これらはreviewer policy、実行対象、権限、canonical Authorityを変更できない。

対象は`ReviewTarget`としてimmutableに固定する。出力には少なくともrepository、PR番号、base SHA、head SHA、収集時刻、context generationを含める。headが収集後に変化した場合、助言は旧headへの記録として保持してよいがcurrent-head助言として表示しない。

## 5. 任意backendと可用性

backendはprovider-neutralなPortとする。Gemini、OpenAI、Codexその他のproviderは任意Adapterであり、特定providerをcanonicalの必須要件にしない。

credential未設定、quota、network失敗、backend未設定、構造化出力不正は`ReviewAdvisoryAvailability`のtyped状態として表現する。

- `AVAILABLE`: validated advisoryを返せた
- `UNAVAILABLE`: backendを利用できなかった
- `INVALID_OUTPUT`: backend出力をtrusted advisoryへ変換できなかった
- `STALE_TARGET`: 対象headが収集中または検証中に変化した

backend invocation自体で発生した設定・transport・provider準備その他の例外は`UNAVAILABLE`とする。`INVALID_OUTPUT`は、backendが明示的な出力変換失敗を通知した場合、または返却済みcandidateがschema / exact head binding / presentation validationを満たさない場合だけに用いる。backendの任意の`TypeError`や`ValueError`を出力不正と推測してはならない。

`UNAVAILABLE`、`INVALID_OUTPUT`、`STALE_TARGET`は、製品実装、CI、PR、Issue、Missionの成功/失敗を変更しない。利用者が再実行するか、通常の人間レビューだけで進めるかを選べる。

## 6. 助言の信頼境界

backendの自然言語とfindingはuntrusted presentation dataである。deterministic validationは次を満たす場合だけ`ReviewAdvisory`を構築する。

- trusted `ReviewTarget.head_sha`とのexact binding
- configured reviewer identityと実装者identityの監査可能な分離
- 上限付き件数・文字数・ネスト深さ
- 表示用Markdownのmention、HTML、link/image制御、Unicode control characterの安全化（許可した改行・tabを除く）
- evidence path/locationのbounded validation。pathはrepository相対で、control characterを拒否し、表示用advisoryへ渡す際にもmention / Markdown制御を安全化する

validated advisoryも**助言**であり、`PASS`、`CHANGES_REQUESTED`、confidenceその他の値をmerge gate、Actual Fact、canonical Authorityへ昇格しない。

## 7. 永続化と秘密情報

初期実装はローカルのbounded artifactまたは明示的に要求された安全な投稿先へ保存してよい。既定ではGitHubへのcomment/status書込みを行わない。

artifact、ログ、repr、診断へ次を含めない。

- API key、Authorization、Cookie、token、raw header
- raw provider response
- repository外の秘密パス
- promptに含まれる不要なraw user data

保存失敗は助言を失敗させても、対象PR・実装・CI・Mission状態を変更しない。

## 8. 最初の実装境界

初期の #371 実装は`tools/optional_review_support/**`と対応するtestsに限定する。

- production `app/**`はimportしない
- `.github/workflows/**`を追加・変更しない
- repository write credentialを要求しない
- GitHub APIはread-only operationに限定する
- provider SDKはoptional Adapterの後ろに置き、未導入でもcore contract testsを実行できる

Development Toolingはproduction Core/Subsystemから参照されない既存境界を維持する。

## 9. 検証

少なくとも次を直接検証する。

1. PR/head SHA/context generationのimmutable binding
2. stale headのcurrent advisory不採用
3. untrusted PR dataがpolicy/target/canonicalを変更できないこと
4. backend未設定・credentialなし・provider失敗がtyped availabilityとなり、実装/CI/Missionを変更しないこと
5. backend出力のsize/schema/sanitization境界
6. GitHub write operation、workflow、production importが存在しない静的境界
7. 同一targetのbounded idempotencyと、無限retry/pollがないこと

## 10. 完了条件

#371 の実装完了には、上記読取専用・任意・非ブロッキング境界の実装、対象試験、通常の品質gate、current-head reviewを要する。

provider実APIの成功、API key、GitHub Actions workflow、特定AI reviewerの可用性は完了条件ではない。実環境で任意backendを確認する場合も、失敗を製品またはMissionのSTOP条件として扱わない。
