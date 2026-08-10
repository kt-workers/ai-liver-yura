# Character Reference Cloud Lab

Issue #240 / Draft PR #241。

## 目的

参考動画をGoogle Driveへ追加した後、ユーザーが動画ごとにローカルASRを実行・整理しなくても、日本語文字起こしをクラウド上で生成・保存できるようにする。

参考動画は `reference_only` である。元映像・元音声・声・セリフ・固有口癖・語尾・モーション・キャラクター固有設定を、星波ゆらの素材やRuntimeデータとして直接再利用しない。

## 定常運用

```text
Google Driveへ参考動画を追加
  ↓
Character Reference Labを開く
  ↓
一覧でサムネイル / 動画長 / ファイルサイズ / 解析状態を確認
  ↓
「未処理を順番に解析」
  ↓
一時領域へ動画取得
  ↓
一時MP3へ音声抽出
  ↓
OpenAI日本語ASR
  ↓
Driveへ manifest / transcript JSON / transcript TXT を保存
  ↓
一時動画・一時音声を削除
```

同じDrive file revisionはmanifestで検出し、通常操作では再度ASRへ送信しない。失敗済みrevisionを再実行する場合のみ明示的なretryとする。

## 一覧表示メタデータ

Drive APIのファイルメタデータから以下を表示する。

- ファイル名
- 動画長
- ファイルサイズ
- Driveサムネイル（利用可能な場合）
- ASR / audio / visual の解析状態

動画長とサイズの表示だけのために動画本体をRenderへダウンロードしない。Driveの `videoMediaMetadata.durationMillis` / `size` を利用する。

Driveの `thumbnailLink` は短命かつ認証が必要になる場合があるため、ブラウザへ元URLを公開せず、Labの `/api/thumbnail/{reference_id}` で認証付きプロキシする。サムネイルが利用できない場合は `No preview` 表示へフォールバックする。

## Google Drive認証

### 個人のMy Driveを使う場合（推奨）

ユーザーOAuth refresh tokenを使用する。

1. Google Cloud ConsoleでGoogle Drive APIを有効化する。
2. OAuth consent screenを設定する。
3. Desktop app用OAuth clientを作成し、client secrets JSONをローカルへ保存する。
4. リポジトリのPython環境で一度だけ次を実行する。

```bash
python -m tools.character_reference_analysis.google_drive_oauth_setup /path/to/client_secret.json
```

ブラウザでGoogle Driveアクセスを許可すると、次の3値が表示される。

- `YURA_REFERENCE_GOOGLE_OAUTH_CLIENT_ID`
- `YURA_REFERENCE_GOOGLE_OAUTH_CLIENT_SECRET`
- `YURA_REFERENCE_GOOGLE_OAUTH_REFRESH_TOKEN`

これらはRenderのSecret environment variablesへ設定し、Issue / PR / Gitへ貼り付けない。

### Shared Drive / Workspaceを使う場合

必要に応じてサービスアカウントを使用できる。

- `YURA_REFERENCE_GOOGLE_SERVICE_ACCOUNT_JSON`

サービスアカウントに対象Driveへの必要な権限を与える。個人My Driveの通常運用ではユーザーOAuthを優先する。

### 認証の優先順

1. OAuth client ID + client secret + refresh token
2. service account JSON
3. Application Default Credentials

## Render環境変数

必須:

```text
OPENAI_API_KEY
YURA_REFERENCE_DRIVE_INBOX_FOLDER_ID
YURA_REFERENCE_LAB_USERNAME
YURA_REFERENCE_LAB_PASSWORD
```

個人My Drive利用時:

```text
YURA_REFERENCE_GOOGLE_OAUTH_CLIENT_ID
YURA_REFERENCE_GOOGLE_OAUTH_CLIENT_SECRET
YURA_REFERENCE_GOOGLE_OAUTH_REFRESH_TOKEN
```

結果保存先をInboxと分ける場合:

```text
YURA_REFERENCE_DRIVE_RESULTS_FOLDER_ID
```

未指定ならInbox folderを結果保存先にも使用する。

ASR modelは既定で:

```text
YURA_REFERENCE_ASR_MODEL=gpt-4o-transcribe-diarize
```

## Render Blueprint

`render.character-reference-lab.yaml` を使用する。

- build: `requirements-character-reference-lab.txt`
- start: `cloud_validation.character_reference_asr_lab:app`
- health: `/healthz`
- Basic Auth必須

## 保存されるもの

Drive結果folderへ、revision keyごとに以下を保存する。

- manifest JSON
- normalized transcript JSON
- readable transcript TXT

ファイル名はrevision keyのhashを使い、Drive `appProperties` にrevision key / result kindを保持する。

## 保存しないもの

- Gitリポジトリ内の第三者動画
- Gitリポジトリ内の第三者音声
- 一時抽出MP3
- 一時フレーム
- 原動画を再利用する素材ライブラリ

## Reference-only境界

ASR結果は「本人の正式な台詞素材」ではなく観察補助である。

```text
Transcript / Audio / Visual analysis
  ↓
ReferenceObservation
  ↓
複数資料比較
  ↓
YuraDesignCandidate
  ↓
Human review
  ↓
#236 Character Bible
```

`ReferenceObservation`には原映像・原音声・モーション列を保持しない。`YuraDesignCandidate`はHuman reviewなしでCharacter Bibleへ昇格しない。

## 検証順

1. Module: DTO / usage policy / OpenAI response normalization
2. Adjacent: Drive source / metadata / manifest / duplicate prevention / temporary media cleanup
3. Lab: Basic Auth / list / thumbnail proxy / single analyze / sequential unprocessed analyze
4. Cloud: 実Drive + 実OpenAIで1動画を処理
5. Driveにmanifest / transcript JSON / TXTが作成されることを確認
6. 同じ動画を再実行してASRがskipされることを確認
7. #236で結果を参考観察として利用できることを確認

実Cloud検証が完了するまではIssue #240 / PR #241をVerification完了扱いにしない。
