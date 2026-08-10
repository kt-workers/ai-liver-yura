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
カード内のプログレスで現在工程を確認
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

同じDrive file revisionはmanifestで検出する。`asr_status=completed` の場合だけpaid ASRをskipする。`processing` のままRenderが停止した場合は、保存済みtranscriptの有無を確認して復旧し、途中状態を完了扱いしない。

## 一覧表示メタデータ

Drive APIのファイルメタデータから以下を表示する。

- ファイル名
- 動画長
- ファイルサイズ
- サムネイル
- ASR / audio / visual の解析状態
- 解析中の現在工程 / 進捗率
- ASR待機中の経過時間 / model名

動画長とサイズの表示だけのために動画本体をRenderへダウンロードしない。Driveの `videoMediaMetadata.durationMillis` / `size` を利用する。

Driveが `thumbnailLink` を提供する動画は、元URLをブラウザへ公開せずLabのサムネイルAPIで認証付きプロキシする。

`.mov` などDriveがサムネイルを提供しない動画は、初回プレビュー要求時だけ一時領域へ動画を取得し、ffmpegで小さなJPEGを1枚生成する。生成後は結果folderへ `preview_thumbnail` として保存し、2回目以降は小さなJPEGだけを再利用する。元動画と生成処理中の一時ファイルはRenderへ永続保存しない。複数の未生成サムネイルが同時に要求されても生成並列数を制限する。

このJPEGは参考資料を見分けるための `reference_only` UIプレビューであり、星波ゆらの画像素材・学習素材・Runtime入力として再利用しない。

## 一覧の障害分離

1件の古いmanifestや途中manifestの読み込みに失敗しても、一覧全体を503にしない。該当カードに `manifest:` warningを表示し、他の参考動画は継続表示する。

Render再起動後にDrive上のmanifestが `processing` のままで、現在プロセス内に対応するjobが存在しない場合、一覧上は `interrupted` と表示する。再解析時にtranscriptが既に保存済みならcompletedへ復旧し、保存されていなければASRを再実行する。

API例外は `ExceptionType: message` の形で画面へ表示し、Safari等で一般化されたエラー文だけにならないようにする。

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
100%  完了 / 失敗 / 重複skip / cancel
```

これはファイルの実バイト処理率ではなく、解析パイプラインの工程位置を示す。OpenAI Audio Transcriptions APIがリクエスト処理中の細かな進捗率を返さないため、ASR待機中は `60% / 日本語ASR処理中` と表示し、同時に経過時間を表示する。

通常ASRの既定modelは `gpt-4o-mini-transcribe`。話者分離が必要な資料のみ `gpt-4o-transcribe-diarize` へ明示的に切り替える。

ASRの総時間timeoutは既定90秒。`YURA_REFERENCE_ASR_TIMEOUT_SECONDS` で変更できる。timeout / cancel時はmanifestを完了扱いしない。

## Render停止・再起動

解析ジョブの進捗はRenderプロセス内にあるため、デプロイ・スピンダウン・プロセス再起動で消える。一方、manifest / transcript / previewはGoogle Driveを正本とする。

```text
completed
  → provider再実行なし
processing + transcriptあり
  → completedへ復旧、provider再実行なし
processing + transcriptなし
  → interruptedとして再解析可能
failed
  → 明示retry
cancel
  → interruptedとして再解析可能
```

## Lab認証

ブラウザ標準のBasic Authポップアップは使用しない。

`YURA_REFERENCE_LAB_USERNAME` / `YURA_REFERENCE_LAB_PASSWORD` は引き続き認証秘密情報としてRenderへ設定するが、初回認証後は署名付きHttpOnly Cookieを発行し、同じブラウザで180日保持する。

- Cookie: HttpOnly / Secure / SameSite=Lax
- Render再デプロイ後もusername/passwordが変わらない限りCookieは有効
- 既存Basic Auth資格情報をブラウザが送信した場合は、初回アクセス時にCookieへ自動移行できる
- Cookieが無い場合のみLab内の認証画面を表示する
- APIが未認証の場合も `WWW-Authenticate` を返さないため、ブラウザのBasic Authダイアログを出さない

認証を完全撤去しない理由は、参考動画一覧・サムネイルが非公開資料であり、さらに解析APIからOpenAI利用料金を発生させられるためである。

## Google Drive認証

### 個人のMy Driveを使う場合

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

ASR:

```text
YURA_REFERENCE_ASR_MODEL=gpt-4o-mini-transcribe
YURA_REFERENCE_ASR_TIMEOUT_SECONDS=90
```

## Render Blueprint

`render.character-reference-lab.yaml` を使用する。

- build: `requirements-character-reference-lab.txt`
- start: `cloud_validation.character_reference_asr_lab:app`
- health: `/healthz`
- Lab認証: persistent signed Cookie

## 保存されるもの

Drive結果folderへ、revision keyごとに以下を保存する。

- manifest JSON
- normalized transcript JSON
- readable transcript TXT
- Drive純正サムネイルがない場合のreference-only preview JPEG

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
2. Adjacent: Drive source / metadata / manifest / duplicate prevention / temporary media cleanup
3. Lab: persistent Cookie / list / native thumbnail proxy / generated thumbnail fallback / analysis progress / cancel
4. Cloud: 実Drive + 実OpenAIで1動画を処理
5. Driveにmanifest / transcript JSON / TXTが作成されることを確認
6. 同じ動画を再実行してASRがskipされることを確認
7. Render再起動相当のprocessing状態から復旧できることを確認
8. #236で結果を参考観察として利用できることを確認

実Cloud検証が完了するまではIssue #240 / PR #241をVerification完了扱いにしない。
