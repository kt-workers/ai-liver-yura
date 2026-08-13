# GitHub独立AIレビュー統括・Gemini接続 実装設計

状態: Issue #371 の正本実装設計
親Issue: #369
依存Issue: #370
上位正本: `docs/architecture/v2/independent_ai_review_architecture.md`
領域: 開発基盤
適用日: 2026-08-13

## 1. 目的

Issue #370で確定した独立AIレビュー契約をGitHub Pull Request上で実行可能にする。

最小実装ではGitHub Actionsを信頼済みの起動・制御系とし、レビュー実行基盤はV2基幹上の提供元非依存Pythonモジュール、最初の主独立レビューワー接続はGemini APIとする。

```text
信頼済み既定ブランチ `main`
  .github/workflows/independent-ai-review.yml
        |
        | pull_request_target
        | 秘密情報 + 必要最小権限
        v
信頼済みV2基幹の変更不能SHAだけを取得
        |
        v
V2レビュー実行基盤
  tools/independent_review/
        |
        +--> GitHub文脈収集
        +--> GeminiReviewerBackend -> ProviderReviewCandidate
        +--> 決定論的検証 -> ReviewDecision
        +--> PRレビューコメント
        +--> PR先端SHAの状態 `yura/independent-ai-review`
              PASS              -> success
              CHANGES_REQUESTED -> failure
              BLOCKED/error     -> error
```

レビューワー接続自身は承認、マージ、ブランチ更新を行わない。

## 2. 信頼境界と起動方式

### 2.1 秘密情報を持つ起動系

PR側で変更可能なワークフロー定義に秘密情報を与えない。

信頼済み制御ワークフローは既定ブランチ `main` に置き、`pull_request_target` を使用する。

PR先端コード、PRマージ参照、PR内スクリプトを秘密情報付き処理から実行しない。

### 2.2 対象

- 基準ブランチ: `rebuild/v2-foundation`
- 対象イベント: `opened`, `ready_for_review`, `synchronize`, `reopened`
- 下書きPR: 実レビューしない
- V2 PR: `v2` ラベル必須
- 正規開発系統: 同一リポジトリ内ブランチ

外部リポジトリ由来PRは、安全境界を満たす実装が明示されるまでレビュー不能として停止する。

### 2.3 信頼済み実行基盤SHA

長期間開いているPRでは、PRメタデータ上の `base.sha` が現在のV2基幹HEADより古い場合がある。

したがって秘密情報付き制御系が実行するレビュー実行基盤は、固定された信頼済み参照 `refs/heads/rebuild/v2-foundation` をGitHub APIで解決し、その時点の変更不能SHAへ固定する。

- PR作成者は実行基盤参照を選べない
- PR先端、PR本文、ラベル、差分、コメントは実行基盤参照を選べない
- 信頼済み参照解決失敗時にPRコードへ代替しない
- 解決後のチェックアウトは変更不能SHAを使用する

詳細は `docs/architecture/v2/review_orchestrator_live_base_resolution.md` を参照する。

## 3. 順序付き2段階実装

既定ブランチとV2基幹では信頼境界が異なるため、#371は順番を固定した2段階とする。同時に2本の実装系統を進行させない。

### 第1段階: V2レビュー実行基盤

基準: `rebuild/v2-foundation`

成果物:

- #371の正本・補足設計
- `tools/independent_review/**`
- `tests/tools/independent_review/**`

秘密情報付きGitHubワークフローは追加しない。

単体試験、偽結合試験、静的確認、副レビューワー確認後にV2基幹へマージする。

### 第2段階: 信頼済みGitHub制御系

第1段階のマージ完了後にだけ開始する。

基準: `main`

成果物:

- `.github/workflows/independent-ai-review.yml` のみ

製品コードやV2製品実装を `main` へ持ち込まない。

## 4. GitHub権限

信頼済みワークフローは必要最小権限とする。

```yaml
permissions:
  contents: read
  pull-requests: write
  issues: read
  actions: read
  statuses: write
```

用途:

- `contents: read`: 信頼済み実行基盤と正本文書取得
- `pull-requests: write`: PRレビューコメント記録
- `issues: read`: 関連作業Issue取得
- `actions: read`: 対象SHAへ結び付いた検証証拠取得
- `statuses: write`: PR先端SHAへレビュー状態記録

`contents: write` は付与しない。

## 5. PR先端SHAの状態

固定状態識別子:

`yura/independent-ai-review`

状態値はGitHub APIの固定値を使用する。

- レビュー開始: `pending`
- `PASS`: `success`
- `CHANGES_REQUESTED`: `failure`
- `BLOCKED`、内部失敗、古い実行: `error`

表示説明は日本語とする。

状態にはGitHub Actions実行URLを `target_url` として付与する。

#373でこの状態識別子を最終マージ判定へ統合する。

## 6. PRレビュー記録

GitHub Review APIは `COMMENT` を使用する。

- AIの合格を人間承認と混同しない
- AIレビューワーにマージ権限を与えない
- 最終マージ判定の信頼済み状態は対象SHAへ結び付ける

機械識別用マーカー:

```text
<!-- yura-independent-ai-review:v1 -->
```

自然言語の表示項目は日本語とする。

記録項目:

- 判定
- レビュー対象SHA
- レビュー担当AI識別子
- レビュー実行識別子
- 提供元
- モデル
- 循環識別子
- 信頼度
- 要約
- 指摘

同一レビュー実行の二重投稿は抑止する。

同じPR先端SHAであっても、異なる信頼済み実行識別子を持つ再実行は別の監査記録として保存できなければならない。

詳細は `docs/architecture/v2/review_orchestrator_execution_consistency.md` を参照する。

## 7. AI識別

レビュー担当:

```text
role = REVIEWER
provider = google-gemini
model = GEMINI_REVIEW_MODEL
agent_id = yura-independent-reviewer-gemini
session_id = github-actions:<run id>:<attempt>:<PR head SHA>
principal = github-actions[bot]
credential_scope = REVIEW_WRITE
```

現在の実装担当系統識別:

```text
agent_id = github-pr-author:<login>
session_id = implementation-lineage:<PR number>:<head SHA>
credential_scope = IMPLEMENTATION_WRITE
```

#372でローカルCodex実装担当を導入した後は、明示的な実装担当AI・実行識別へ置き換える。

レビュー担当と実装担当で `agent_id` または `session_id` が一致した結果を合格にしない。

## 8. レビュー文脈

GitHub APIから取得するもの:

- 現在PRメタデータ
- 基準・先端SHA
- 差分
- 関連作業Issue
- 作業Issueが指す正本文書
- 対象先端SHAのGitHub Actions検証証拠

PR本文に書かれた「試験合格」等の主張は信頼済み検証証拠ではない。

### 8.1 関連作業Issue

PR本文の日本語記法から候補を抽出する。

標準記法:

```text
関連Issue: #371
```

認識したIssue参照行に複数の `#N` がある場合は全番号を抽出し、
作業Issueが1件だけという制約により曖昧入力を拒否する。

必要に応じて次の日本語語頭も使用可能とする。

- `対象Issue: #N`
- `解決: #N`
- `修正: #N`
- `対応: #N`

一意な `v2` ラベル付き作業Issueを要求する。0件または複数ならレビュー不能。

英語の自然言語記法を入力契約として要求しない。

### 8.2 正本文書

Issue本文の日本語 `正本:` ブロックから `docs/**/*.md` のパスを取得する。

```text
正本:
- `docs/architecture/v2/example.md`
```

PR自身が新しい正本候補を追加する場合、そのファイルはマージ前には既存正本を上書きする権限を持たない。必要な場合はPR本文で「このPRで追加する正本補足」として明示する。

### 8.3 正本文書を読むSHA

レビュー実行基盤と正本Authorityは同じ信頼済み最新V2基準へ結び付ける。

PRメタデータ上の古い `base.sha` を最終Authorityにしない。

第2段階の信頼済み制御系が解決したV2基幹SHAを、レビュー実行基盤SHAと正本取得SHAの両方に使用する。

PR関係上の基準SHAは監査用に保持してよいが、正本Authority SHAと区別する。

この要件は #381 と `docs/architecture/v2/review_orchestrator_live_base_resolution.md` に従う。

### 8.4 文脈容量

容量超過を黙って切り詰めて合格にしない。安全側にレビュー不能とする。

## 9. 検証証拠

対象先端SHAに結び付いたGitHub Actions実行結果だけを文脈へ含める。

別SHAの証拠を現在SHAの証拠として採用しない。

必須検証集合そのものは#373で確定するため、#371は取得・SHA結合を実装し、空集合を許容する。

## 10. Gemini接続

### 10.1 SDK

レビュー基盤専用依存として `google-genai>=2,<3` を使用する。

製品依存へ追加せず、`tools/independent_review/requirements.txt` に隔離する。

### 10.2 モデル

既定モデル識別子:

`gemini-3.6-flash`

`GEMINI_REVIEW_MODEL` で上書き可能とする。

### 10.3 秘密情報

GitHub Actions秘密情報:

`GEMINI_API_KEY`

未設定ならレビュー不能。値をログ・レビュー本文へ出力しない。

### 10.4 API利用

GeminiのInteractions API、`system_instruction`、JSON Schemaによる構造化出力を使用し、`store=False` とする。

Geminiが返す `ProviderReviewCandidate` はPydantic検証後も信頼済みではない。

決定論的検証を通過した場合だけ `ReviewDecision` へ昇格する。

### 10.5 プロンプト上の信頼境界

入力見出しは日本語とする。

```text
[信頼済み事実: レビュー対象]
[権限情報: Issue責務]
[権限情報: 正本要件]
[信頼済み事実: 検証証拠]
[信頼できないデータ: PRメタデータ]
[信頼できないデータ: PR差分]
```

PR差分、PR本文、コメント、Markdown内の命令をシステム指示として扱わない。

## 11. 実行時構成

```text
tools/independent_review/
├── __init__.py
├── requirements.txt
├── models.py
├── github_client.py
├── context_builder.py
├── reviewer_backend.py
├── gemini_backend.py
├── validator.py
├── persistence.py
├── orchestrator.py
└── main.py

tests/tools/independent_review/
├── test_models.py
├── test_context_builder.py
├── test_validator.py
├── test_persistence.py
├── test_orchestrator.py
└── test_main.py
```

ネットワーク処理と純粋な検証処理を分離し、単体試験では偽GitHub・偽レビューワーを使用する。

## 12. 実行開始時SHA固定

GitHubイベントから得たPR先端SHAを `expected_head_sha` として固定する。

同一実行内でPR先端が動いても新SHAへ追従しない。

確認点:

1. レビュー開始前
2. レビュー入力構築時
3. AI応答後の決定論的検証時
4. PRコメント公開直前
5. 最終状態書込前

いずれかで現在PR先端SHAが `expected_head_sha` と一致しなければ、その実行は古い実行として停止する。

レビューしたSHAと状態を書き込むSHAを異ならせない。

## 13. 決定論的検証

必須:

- 現在PR先端 == `expected_head_sha`
- `ReviewTarget.head_sha == expected_head_sha`
- Geminiが返した `echoed_head_sha == expected_head_sha`
- `echoed_head_sha` の欠落・空文字を拒否
- レビュー担当AI識別子 != 実装担当AI識別子
- レビュー担当実行識別子 != 実装担当実行識別子
- レビュー担当資格情報範囲に実装書込・統括権限なし
- 指摘IDとfingerprintの一意性
- 各指摘fingerprintを無害化済みレビュー監査記録へ永続化
- `PASS` と `BLOCKING` 指摘の同時存在を拒否
- `CHANGES_REQUESTED` は1件以上の `BLOCKING` 指摘を要求
- `BLOCKED` をコード欠陥指摘の代用にしない
- 必須正本・文脈欠損時に合格しない
- 出力量上限を超えた候補を拒否
- summary、指摘タイトル・説明・根拠・修正方向の各公開自然言語が、
  Unicode上の日本語文字を1文字以上含むこと

日本語判定は固定語句や英単語辞書ではなく、各公開自然言語フィールドに
ひらがな字母（U+3041〜U+3096）、カタカナ字母（U+30A1〜U+30FA）、
CJK統合漢字のいずれかが存在することを決定論的に確認する。
中黒・長音記号等の記号だけでは日本語要件を満たさない。
コード識別子やパスの併記は許可するが、日本語を含まない候補は再生成対象とする。

## 14. AI応答再試行

再試行単位には、Gemini API呼出しだけでなく候補の決定論的意味検証まで含める。

次は上限回数まで再試行可能:

- Gemini接続失敗
- JSON Schema不適合
- 構造化候補の意味的不整合
- `PASS` と `BLOCKING` の同時返却
- 必須指摘不足等、同一入力でも再生成で回復し得る候補不整合
- `echoed_head_sha` の欠落・空・不一致
- 公開自然言語の日本語要件違反

次は再試行せず即時停止する:

- PR先端SHA変化
- 対象基準ブランチ変化
- `v2` ラベル除去
- 下書き化
- 外部リポジトリ由来への変更
- 正本欠損
- GitHub文脈取得不能
- 資格情報・権限境界違反

上限回数まで有効候補を得られなければレビュー不能とする。

## 15. 実行直前の対象範囲再確認

イベント時の対象情報だけを信頼しない。

Gemini呼出し前にGitHubから現在PRを再取得し、次をすべて再確認する。

- 現在先端SHA == `expected_head_sha`
- 基準リポジトリ == 対象リポジトリ
- 基準参照 == `rebuild/v2-foundation`
- 先端リポジトリ == 対象リポジトリ
- `v2` ラベルが存在
- 下書きではない

1つでも変化していればGeminiを呼び出さず停止する。

## 15.1 正本世代固定

レビュー入力構築時に、次の信頼済みAuthority入力を正規化してSHA-256世代識別子へ固定する。

- 信頼済みV2基準SHA
- PR関係基準SHA
- レビュー対象SHA
- 関連Issue番号・タイトル・本文
- Issue本文から解決した正本一覧と、信頼済みV2基準SHAから取得した各内容
- レビュー対象SHAに結び付く検証証拠

関連番号をGitHub Issue APIで取得した結果がPull Requestを表す場合は、作業Issue Authorityとして拒否する。
検証証拠は信頼済み制御系が明示したworkflow IDの許可集合に一致する実行だけを採用し、
未指定・PR側追加・出所未確認のworkflow runを信頼済み事実へ昇格しない。
許可集合は信頼済み制御系が `YURA_TRUSTED_WORKFLOW_IDS` で渡し、PRデータから構築しない。
PR側で複製可能なworkflow名だけを出所Authorityにしない。

PR Review公開直前にGitHub live状態からReviewContextを再構築し、世代識別子の完全一致を要求する。
PR関係基準SHA、Issue本文、正本一覧・内容、対象SHAの検証証拠のいずれかが変化した場合、生成済み判定は
古い世代として破棄し、PASS・CHANGES_REQUESTED・BLOCKEDのいずれも公開しない。

既存レビューの重複確認後、Review API呼出しの直前にもlive PR対象範囲を再取得する。
この最終確認ではReviewContextを再構築して開始時Authority世代との完全一致も要求する。
最終確認とコメント作成の間には、別のI/Oやページネーションを挟まない。

## 16. 重複防止と再実行

信頼済みワークフローはPR番号単位の並行処理制御を行い、同一PRの古い実行を取り消せるようにする。

Python側の循環識別子は少なくとも次を含む。

- PR番号
- レビュー対象SHA
- レビュー担当AI識別子
- レビュー実行識別子

同一実行の二重公開だけを抑止する。

既存レビューは件数にかかわらず全ページを取得し、先頭100件だけの確認で
同一循環が存在しないと判断しない。
同一循環の既存記録として採用するのは、設定済みReviewer principalと投稿者が一致する
レビューだけとし、別主体が複製したmarker・循環識別子では公開を抑止しない。
重複が見つかった場合も全ページ取得後の最終Authority世代確認を省略せず、
一致確認後にだけ同一循環の未投稿終了を採用する。

同一SHAで一時的な `BLOCKED` 後に別実行で `PASS` した場合、新しい合格記録を公開可能とする。

過去記録は削除せず監査履歴として残す。

## 17. エラー方針

- Gemini接続失敗: 上限付き再試行後にレビュー不能
- 構造化候補の意味的不整合: 上限付き再試行後にレビュー不能
- GitHub文脈失敗: レビュー不能
- PR先端移動: 古い結果を公開せずレビュー不能
- 秘密情報未設定: レビュー不能
- 文脈容量超過: レビュー不能
- 生の提供元エラーや秘密情報を公開コメントへ出さない
- 状態書込失敗を合格として扱わない

## 18. 検証

### 18.1 単体試験

- 型の直列化
- AI識別・実行識別衝突
- 判定・指摘不変条件
- 古いSHA・echoed SHA不一致
- echoed SHA欠落・空
- 公開自然言語の日本語要件
- 正本世代識別子の決定性と公開直前の世代変化拒否
- 日本語 `正本:` 解決
- 日本語 `関連Issue:` 解決
- PR内命令を信頼できないデータとして保持
- 同一実行の重複記録防止
- 同一SHAの別実行を別監査記録として保存
- 文脈容量
- 状態写像
- 公開文章の無害化

### 18.2 偽結合試験

偽GitHub + 偽レビューワーで確認する。

- `PASS` -> コメント + 成功状態
- `CHANGES_REQUESTED` -> コメント + 失敗状態
- `BLOCKED` -> コメント + エラー状態
- レビュー入力構築前のSHA変化 -> AIを呼ばず停止
- AI実行中のSHA変化 -> 結果を公開しない
- 同一実行重複 -> コメントを重複しない
- 同一SHAの別実行 -> 新しいレビュー記録を作る
- 対象基準変更、ラベル除去、下書き化 -> AIを呼ばず停止
- 意味的不正候補 -> 上限回数まで再試行
- 公開直前の正本世代変化 -> 結果を公開しない

### 18.3 実環境確認

第1段階・第2段階の実装後に、実際のV2 PRを対象として確認する。

- 信頼済み最新V2基準SHAの解決
- レビュー実行基盤SHAと正本Authority SHAの一致
- PR先端SHA固定
- Geminiレビュー結果の対象SHA一致
- `yura/independent-ai-review` 状態の対象SHA一致
- レビュー担当によるブランチ変更がない
- 必要最小権限
- 秘密情報非露出

Gemini APIが利用上限に達している場合、実Gemini確認は利用可能になるまで保留する。これを副レビューワーだけの合格で代替しない。

## 19. 起動時特例

#371はレビュー基盤そのものを作るため、第1段階と第2段階を完成済みの主独立レビューワーで事前自動レビューできない期間が存在する。

その間は次を必須とする。

- 正本先行
- 単体・偽結合試験
- 静的確認
- GitHub Codex Reviewによる副レビュー
- 人間が読める差分・監査証跡

Geminiが利用可能になった時点で主独立レビューを追加する。

この特例を#372以降の通常実装へ一般化しない。

## 20. 完了条件

第1段階:

- V2レビュー実行基盤と試験を実装
- 正本と実装が一致
- SHA競合、対象範囲競合、意味的不正候補、再実行監査を検証
- 合流履歴を残すマージ方式でV2基幹へ統合

第2段階:

- `main` に信頼済み制御ワークフローだけを実装
- PR先端・マージ参照コードを秘密情報付き環境で実行しない
- 信頼済み最新V2基準SHAを実行基盤・正本Authorityの両方へ使用
- 合流履歴を残すマージ方式で `main` へ統合

最終確認:

- Gemini利用可能時に実PRで主独立レビューを実施
- 対象SHA、状態、権限、正本Authority、非変更境界を確認

#371完了後、#372の自動修正循環実装へ進む。
