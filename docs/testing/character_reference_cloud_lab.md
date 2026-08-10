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
「解析」または「未処理を順番に解析」
  ↓
カード内の工程 / 経過時間 / モデルを確認
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

通常の参考動画は `gpt-4o-mini-transcribe` を使う。複数話者を区別する必要がある資料だけ、環境変数で `gpt-4o-transcribe-diarize` へ切り替える。

同じDrive file revisionはmanifestで検出するが、**manifestが存在するだけでは解析済みとみなさない**。`asr_status=completed` の場合だけ通常操作でpaid ASRをskipする。

## 一覧表示メタデータ

Drive APIのファイルメタデータから以下を表示する。

- ファイル名
- 動画長
- ファイルサイズ
- サムネイル
- ASR / audio / visual の解析状態
- 解析中の現在工程 / 進捗率
- 解析経過時間
- ASRモデル

動画長とサイズの表示だけのために動画本体をRenderへダウンロードしない。Driveの `videoMediaMetadata.durationMillis` / `size` を利用する。

Driveが `thumbnailLink` を提供する動画は、元URLをブラウザへ公開せずLabの `/api/thumbnail/{reference_id}` で認証付きプロキシする。

`.mov` などDriveがサムネイルを提供しない動画は、初回プレビュー要求時だけ一時領域へ動画を取得し、ffmpegで小さなJPEGを1枚生成する。生成後は結果folderへ `preview_thumbnail` として保存し、2回目以降は小さなJPEGだけを再利用する。元動画と生成処理中の一時ファイルはRenderへ永続保存しない。複数の未生成サムネイルが同時に要求されても生成並列数を制限する。

このJPEGは参考資料を見分けるための `reference_only` UIプレビューであり、星波ゆらの画像素材・学習素材・Runtime入力として再利用しない。

## 解析プログレス

Labの解析操作はバックグラウンドジョブとして開始し、ブラウザは進捗APIを定期的にポーリングする。1つのreferenceについて実行中ジョブがある場合、同じreferenceを再度押しても新しいpaid ASRジョブは作らず既存ジョブを返す。

工程ベースの目安:

```text
0%    待機
5%    Driveから動画取得開始
30%   動画取得完了
35%   音声抽出開始
45%   音声抽出完了
50%   重複解析確認
55%   ASR準備
60%   OpenAI日本語ASR開始
85%   ASR完了・結果保存開始
95%   manifest最終保存
100%  完了 / 失敗 / 中断 / 重複skip
```

これはファイルの実バイト処理率ではなく、解析パイプラインの工程位置を示す。OpenAI Audio Transcriptions APIがprovider内部の細かな進捗率を返さないため、ASR待機中は `60% / 日本語ASR処理中` のままになる。その代わりUIで `経過 mm:ss` と利用モデルを表示する。

## ASR timeout

OpenAI ASRはasync HTTPで実行し、socket単位のtimeoutだけでなく総時間timeoutを設定する。

既定:

```text
YURA_REFERENCE_ASR_TIMEOUT_SECONDS=90
```

90秒を超えるとjobは `failed` になり、Drive manifestへ失敗理由を保存する。長い参考動画を扱う場合はRender環境変数で延長する。

## キャンセル

解析中カードには `キャンセル` を表示する。

```text
POST /api/analyze/cancel/{job_id}
```

キャンセル時はasync ASR requestを停止し、manifestを `interrupted` にする。temporary video / audioは一時領域終了時に削除される。`interrupted` は完了扱いではなく、後から通常操作で再解析できる。

## Render停止・再起動時

解析jobのprogressはRenderプロセス内だけにあるため、スピンダウン・再起動・デプロイで消える。一方、永続的な解析状態はGoogle Drive上のmanifest / transcriptを正本とする。

起動後の復旧:

```text
completed
  → paid ASRをskip

processing + transcriptあり
  → completedへ復旧
  → paid ASRを再実行しない

processing + transcriptなし
  → interruptedとして扱う
  → 再解析可能

interrupted
  → 再解析可能

failed
  → retryで再解析
```

OpenAIが処理を終えた直後、transcriptをDriveへ保存する前にプロセス自体が強制終了した場合だけは、provider側実行済みかを完全には判断できず、再試行時に二重課金の可能性が残る。この区間を除き、保存済みtranscriptを優先して復旧する。

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

既定ASR:

```text
YURA_REFERENCE_ASR_MODEL=gpt-4o-mini-transcribe
YURA_REFERENCE_ASR_TIMEOUT_SECONDS=90
```

複数話者のspeaker annotationが必要な検証だけ:

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
- Drive純正サムネイルがない場合のreference-only preview JPEG

ファイル名はrevision keyのhashを使い、Drive `appProperties` にrevision key / result kindを保持する。

## 保存しないもの

- Gitリポジトリ内の第三者動画
- Gitリポジトリ内の第三者音声
- 一時抽出MP3
- 一時生成JPEG
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
2. Module: strict timeout / cancel / interrupted recovery
3. Adjacent: Drive source / metadata / manifest / duplicate prevention / temporary media cleanup
4. Lab: Basic Auth / list / thumbnail / elapsed progress / cancel / sequential unprocessed analyze
5. Cloud: 実Drive + 実OpenAIで10〜30秒程度の動画1本をminiモデルで処理
6. Driveにmanifest / transcript JSON / TXTが作成されることを確認
7. 同じ動画を再実行してASRがskipされることを確認
8. cancel後にinterruptedとして再実行できることを確認
9. #236で結果を参考観察として利用できることを確認

実Cloud検証が完了するまではIssue #240 / PR #241をVerification完了扱いにしない。
