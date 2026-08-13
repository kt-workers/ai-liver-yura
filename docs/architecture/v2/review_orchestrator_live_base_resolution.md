# 独立AIレビュー — 信頼済み最新V2基準SHAの解決

状態: Issue #371 の正本補足
適用日: 2026-08-13

依存正本:
- `docs/architecture/v2/independent_ai_review_architecture.md`
- `docs/architecture/v2/review_orchestrator_implementation.md`

## 1. 問題

`pull_request_target` は既定ブランチ側の信頼済み制御ワークフローを使用できるが、長期間開いているPRでは `pull_request.base.sha` が現在のV2基幹HEADと一致するとは限らない。

旧試行のPR #368では、PR関係上の基準SHAが古いまま保持され、後からV2基幹へ追加されたレビュー実行基盤を参照できない状態を確認した。

したがって、PR関係上の `base.sha` をレビュー実行基盤や正本文書Authorityの最新基準として扱ってはならない。

## 2. Authority

#371のレビュー実行基盤および正本文書Authorityを選ぶ信頼済み参照は固定する。

`refs/heads/rebuild/v2-foundation`

PR作成者はこの参照を選べない。

次は信頼できないPRデータであり、実行基盤・正本Authorityの参照を選択できない。

- PR先端SHA
- PRマージ参照
- PR本文
- ラベル
- 差分
- コメント
- レビュー
- その他PR側から変更可能な値

## 3. 解決契約

信頼済みワークフローはチェックアウト前に次を行う。

1. 基準リポジトリのGitHub APIから `refs/heads/rebuild/v2-foundation` を解決する。
2. 返された変更不能コミットSHAを取得する。
3. 空値または不正形式のSHAを拒否する。
4. 解決したSHAを `actions/checkout` の明示的な `ref` として使用する。
5. レビュー実行基盤はそのSHAからだけ実行する。
6. 同じSHAを `YURA_TRUSTED_BASE_SHA` としてレビュー実行基盤へ渡す。
7. レビュー実行基盤は正本文書を同じ `YURA_TRUSTED_BASE_SHA` から取得する。

信頼済みワークフローは次を行わない。

- `pull_request.head.sha` をチェックアウトする
- PRマージ参照をチェックアウトする
- PR先端から取得したコードを秘密情報付き処理で実行する
- PR側から変更可能な入力に実行参照を選ばせる
- 信頼済み基準SHAの解決失敗時にPRコードへ代替する
- レビュー実行基盤SHAと正本文書Authority SHAを別々に解決する

## 4. 2種類の基準SHA

レビュー文脈では次を区別して保持する。

### PR関係基準SHA

GitHub PRがどの基準コミットとの関係で作られたかを示す履歴情報。

`ReviewTarget.base_sha`

監査情報として保持するが、現在の正本文書Authorityを選ばない。

### 信頼済みV2基準SHA

信頼済み固定参照から制御系が解決した、現在実行のレビュー実行基盤・正本文書Authorityの基準。

`ReviewTarget.trusted_base_sha`

このSHAだけを次へ使用する。

- レビュー実行基盤のチェックアウト
- Issueが列挙する正本文書の取得
- レビュー入力における正本Authorityの基準

## 5. 安全性の理由

この方式は次を同時に満たす。

- **鮮度:** 古いPR基準スナップショットではなく、信頼済みV2基幹の解決時点HEADを使用する
- **実行中の不変性:** ブランチ名ではなく解決済みSHAを使用するため、実行中にV2基幹が動いてもその実行内容は変化しない
- **Authority一致:** レビュー実行基盤と正本文書を同じSHAから取得し、異なる時点の正本と実装を混在させない

## 6. 失敗方針

次の場合は安全側へ停止する。

- 信頼済みV2基幹参照を解決できない
- 解決SHAが40桁の16進小文字SHAではない
- チェックアウトに失敗
- 期待するレビュー実行基盤がそのSHAに存在しない
- `YURA_TRUSTED_BASE_SHA` がレビュー実行基盤へ渡されていない
- 正本文書を信頼済みV2基準SHAから取得できない

いずれの場合もGeminiを呼び出さず、合格を公開しない。

## 7. 検証

単体・偽結合:

- PR関係基準SHAと信頼済みV2基準SHAを別項目として保持
- 正本文書取得に信頼済みV2基準SHAを使用
- PR関係基準SHAを正本取得へ使用しない
- 不正形式の信頼済みV2基準SHAを拒否

実環境:

- 信頼済み実行基盤SHAが解決時点の `rebuild/v2-foundation` HEADと一致
- チェックアウト実行基盤SHAと `YURA_TRUSTED_BASE_SHA` が一致
- 正本文書取得SHAが同じ値
- PR先端・マージ参照コードを実行しない
- Geminiレビュー対象SHAとPR先端SHAが一致
- `yura/independent-ai-review` 状態が同じPR先端SHAへ書かれる
