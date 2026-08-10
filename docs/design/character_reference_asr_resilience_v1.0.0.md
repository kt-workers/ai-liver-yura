# Character Reference ASR Resilience v1.0.0

Issue #240 / Draft PR #241。

## 1. 目的

Character Reference Lab のクラウド日本語ASRについて、短い参考動画が長時間待機したり、Render Free のスピンダウン・再起動・ユーザーキャンセルで中断した際に解析済み状態を誤判定しないようにする。

参考動画は引き続き `reference_only` であり、元映像・元音声・逐語セリフ・固有口癖・声・モーションを星波ゆらの素材として再利用しない。

## 2. 通常ASRモデル

通常の参考動画文字起こしは `gpt-4o-mini-transcribe` を既定とする。

理由:

- Character Definition の通常観察では、毎回の話者分離は不要
- `gpt-4o-transcribe-diarize` は複数話者の区別が必要な資料に限定できる
- 通常処理のコストと待ち時間を抑える

詳細な話者分離・タイムライン確認が必要な資料だけ、設定で `gpt-4o-transcribe-diarize` へ切り替える。

## 3. 厳密な総時間タイムアウト

OpenAI ASR 呼び出しは async HTTP client で行い、socket単位のtimeoutだけでなく、解析リクエスト全体を `asyncio.wait_for` で囲む。

既定:

```text
YURA_REFERENCE_ASR_TIMEOUT_SECONDS=90
```

90秒を超えた場合:

```text
ASR request
  ↓ timeout
manifest.asr_status = failed
last_error = timeout
job.state = failed
UI = 再試行可能
```

長い参考動画を扱う場合はRender環境変数で延長できる。

## 4. Manifest判定

manifestの存在だけで解析済みとは判定しない。

```text
COMPLETED
  → paid ASRをskip

PROCESSING
  → 前回中断候補
  → transcriptが保存済みならCOMPLETEDへ復旧してskip
  → transcriptがなければINTERRUPTEDへ更新して再実行可能

INTERRUPTED
  → 通常操作で再実行可能

FAILED
  → explicit retryで再実行

PENDING
  → 実行可能
```

`PROCESSING` は永続的な完了状態ではない。

## 5. 保存順と復旧

正常系:

```text
manifest=processing
→ OpenAI ASR
→ transcript JSON/TXT保存
→ manifest=completed
```

`transcript保存 → completed manifest保存` の間でRenderが停止した場合、次回起動時に transcript の存在を確認して `completed` へ復旧する。OpenAIを再度呼ばない。

OpenAIが処理を完了した直後、transcript保存前にプロセス自体が強制終了した場合だけは、provider側実行済みかを完全には判定できない。この狭い区間は再試行時に二重課金の可能性が残るため、timeout/cancelと永続化をできるだけ短い境界で扱う。

## 6. キャンセル

UIから実行中jobをキャンセルできる。

```text
POST /api/analyze/cancel/{job_id}
```

キャンセル時:

- async HTTP requestをcancelする
- temporary video / audioはTemporaryDirectory終了時に削除する
- manifestを `interrupted` にする
- 同じreferenceを再実行可能にする
- job UIは `canceled` として終了する

## 7. プログレス表示

解析全体を単一の推測進捗率として扱わず、**観測可能な実進捗と工程位置を分けて表示する**。

### 7.1 Drive動画取得: 5〜30%

Google Driveからの動画取得中は `MediaIoBaseDownload` が返す実ダウンロード割合を利用し、0〜100%の取得率をLab全体の5〜30%へ線形マッピングする。

```text
Drive download 0%   → Lab 5%
Drive download 40%  → Lab 15%
Drive download 100% → Lab 30%
```

これにより、大きい動画やRender側の回線が遅い場合に `5% / 動画取得中` のまま長時間停止して見える状態を避け、少なくともDrive取得工程の内部では実際にデータが進んでいるかを観測できる。

この割合は**動画解析全体の実処理率ではなく、Driveファイル取得量だけの実進捗**である。Drive APIからprogress情報を取得できない互換Inboxでは、従来どおり5%開始→30%完了の工程表示へ縮退する。

### 7.2 音声抽出以降: 工程ベース

Drive取得後は次の工程位置を表示する。

```text
30%  動画取得完了
35%  音声抽出開始
45%  音声抽出完了
50%  重複解析確認
55%  ASR準備
60%  OpenAI日本語ASR開始
85%  ASR完了・結果保存開始
95%  manifest最終保存
100% 完了 / 失敗 / 重複skip / cancel
```

ASR provider内部の正確な進捗率は得られないため、`60%` はprovider内部の60%完了を意味しない。60%で停止して見えない問題を避けるため、ASR待機中はjobの経過秒数とmodel名を返す。

例:

```text
日本語ASR処理中
60%
経過 00:37
モデル: gpt-4o-mini-transcribe
[キャンセル]
```

したがってUI上の解釈は次のとおり。

- 5〜30%: Drive動画取得量の実進捗
- 30〜60%: 解析パイプラインの工程位置
- 60%の待機: OpenAI ASR処理中。経過時間で監視
- 85〜100%: 永続化・完了処理の工程位置

## 8. プレビューの安定性境界

Character Reference Labの主目的は、**Character Bibleを考えるための参考資料を文字起こし・観察可能にすること**である。サムネイル生成は補助機能であり、解析基盤の可用性より優先しない。

2026-08-10のRender実機で、Drive純正サムネイルを持たないMOVに対する自動fallback preview生成と同時期に、次を確認した。

```text
double free or corruption (!prev)
GET /api/thumbnail ... 503
Render instance exited with status 134
```

この時点ではクラッシュのnative root causeを断定しない。ただしASR開始前の一覧表示だけで動画本体取得・ffmpeg実行を発生させる設計は、本来のCharacter探索に対してコストと障害半径が大きい。

そのためRenderの通常UIでは次を標準とする。

```text
Drive thumbnailあり
  → 認証付きthumbnail proxyで表示

Drive thumbnailなし
  → No preview
  → 一覧表示だけでは動画本体を取得しない
  → 一覧表示だけではffmpegを起動しない
```

既存のgenerated-preview実装は解析本体とは分離して残せるが、通常UIから自動起動しない。将来再有効化する場合は、別job化・単独Verification・resource limit・native process failure isolationを満たしてから行う。

この縮退によって失うのは一覧上の補助画像だけであり、次は維持する。

- 動画名
- 動画長
- ファイルサイズ
- ASR状態
- 解析開始
- transcript生成
- Character Reference Observationへの利用

## 9. Render停止時

Render process内だけにあるもの:

- 実行中task
- job progress
- temporary video/audio

Google Driveに永続化するもの:

- manifest
- transcript JSON/TXT
- 過去に正常生成済みのreference-only preview JPEG

Renderが停止するとin-memory jobは消えるが、次回一覧取得時にDrive manifestを正本として復旧する。

## 10. 検証

Module:

- 通常モデルが `gpt-4o-mini-transcribe`
- strict timeoutでprovider待機が終了する
- completedだけがduplicate skip対象
- processing + transcriptありをcompletedへ復旧
- processing + transcriptなしをinterruptedへ復旧
- cancelでmanifestがinterruptedになる
- Drive downloaderの0〜100%実進捗がLabの5〜30%へ単調にマッピングされる
- progress非対応Inboxでは従来の工程表示へ安全に縮退する

Lab:

- Drive純正thumbnailがないreferenceは`No preview`となり、自動fallback生成を開始しない
- 一覧表示だけで元動画download / ffmpegが起動しない
- Drive取得中に5〜30%の途中値が更新される
- elapsed time表示
- cancel button
- canceled/interrupted referenceを再実行可能
- failed referenceはretry経路へ進む

Cloud Verification:

1. Render最新デプロイ後、一覧表示だけではinstanceが落ちない
2. Drive thumbnailなしMOVが`No preview`で表示される
3. 10〜30秒の参考動画1本でmini ASR
4. Drive動画取得中に5〜30%のprogressが進む
5. ASR待機中は経過時間が更新される
6. transcriptがDriveへ保存される
7. 同一revision再実行がproviderを呼ばずskip
8. cancel後にinterruptedとなり再実行可能
9. Render再起動後にprocessingを完了扱いしない
