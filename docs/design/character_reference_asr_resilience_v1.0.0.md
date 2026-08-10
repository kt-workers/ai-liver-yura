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

ASR provider内部の正確な進捗率は得られないため、工程ベースのpercentは維持する。ただし60%で停止して見えない問題を避けるため、jobの経過秒数を返す。

例:

```text
日本語ASR処理中
60%
経過 00:37
モデル: gpt-4o-mini-transcribe
[キャンセル]
```

`60%` はprovider内部の60%完了を意味しない。

## 8. Render停止時

Render process内だけにあるもの:

- 実行中task
- job progress
- temporary video/audio

Google Driveに永続化するもの:

- manifest
- transcript JSON/TXT
- reference-only preview JPEG

Renderが停止するとin-memory jobは消えるが、次回一覧取得時にDrive manifestを正本として復旧する。

## 9. 検証

Module:

- 通常モデルが `gpt-4o-mini-transcribe`
- strict timeoutでprovider待機が終了する
- completedだけがduplicate skip対象
- processing + transcriptありをcompletedへ復旧
- processing + transcriptなしをinterruptedへ復旧
- cancelでmanifestがinterruptedになる

Lab:

- elapsed time表示
- cancel button
- canceled/interrupted referenceを再実行可能
- failed referenceはretry経路へ進む

Cloud Verification:

1. 10〜30秒の参考動画1本でmini ASR
2. 経過時間が更新される
3. transcriptがDriveへ保存される
4. 同一revision再実行がproviderを呼ばずskip
5. cancel後にinterruptedとなり再実行可能
6. Render再起動後にprocessingを完了扱いしない
