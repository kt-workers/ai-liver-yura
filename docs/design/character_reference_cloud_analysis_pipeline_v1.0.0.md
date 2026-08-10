# Character Reference Cloud Analysis Pipeline v1.0.0

## 1. 目的

Issue #240 / #236 の Character Definition を支援するため、参考動画をローカル端末で手作業処理せず、クラウド上で日本語ASR・音声表現解析・映像観察へつなげる再利用可能な解析パイプラインを定義する。

このパイプラインの目的は、参考キャラクターの素材を再利用することではない。複数の参考資料から「どのような表現の方向性が存在するか」を観察し、星波ゆら固有の Character Definition を検討するための選択肢を増やすことである。

## 2. 責務境界

### 2.1 本パイプラインが行うこと

- Google Drive 等の共有ストレージに置かれた参考動画を検出する
- 日本語発話をタイムスタンプ付きでASRする
- 発話内容とは独立して、話速・間・ピッチ変化・エネルギー変化等の音声表現を解析する
- 表情・視線・頭部・Body等の観察結果を同一 reference ID へ関連付ける
- 複数資料を比較できる抽象的な観察項目へ変換する
- #236 Character Bible の検討材料として参照可能にする

### 2.2 行わないこと

- 参考動画の映像・音声を製品素材として利用する
- 参考キャラクターの声を複製・クローンする
- セリフ、固有の口癖、語尾、台本をそのまま星波ゆらへ移植する
- モーションや表情シーケンスをそのまま再生データとして取り込む
- 世界観・固有設定をそのまま Character Bible へコピーする
- 解析結果から Character Bible を自動確定する
- ゆら Runtime / 本番STTプラグインの責務を変更する

## 3. Reference-only 原則

すべての reference source は次の利用境界を持つ。

```text
source_usage = reference_only
verbatim_reuse_allowed = false
voice_clone_allowed = false
motion_copy_allowed = false
asset_reuse_allowed = false
character_setting_auto_adoption = false
```

原資料から Runtime へ直接流せるデータ経路を作らない。

```text
Reference Video
  ↓
Observation / Analysis
  ↓
Abstract Character Possibilities
  ↓
Human review
  ↓
Yura-specific design decision
  ↓
Character Bible
  ↓
CharacterProfile / Voice Style / Body Style
```

## 4. 運用フロー

### 4.1 基本フロー

```text
Google Drive / reference inbox
  ↓
Scan
  ↓
ReferenceSource 登録
  ↓
一時作業領域へ取得
  ├─ ASR
  ├─ Audio Expression Analysis
  └─ Visual Observation
  ↓
reference_id 単位で解析結果保存
  ↓
Character Reference Lab
  ↓
複数資料を比較
  ↓
「ゆらへ取り込む方向性」を人が決定
```

ユーザーの定常作業は、原則として参考動画を共有フォルダへ追加することだけとする。

### 4.2 自動実行

初期実装では以下の2経路を許容する。

1. Character Reference Lab の `未処理を解析` 操作
2. スケジューラによる未処理ファイルの定期走査

API費用や誤処理を避けるため、同一 Drive file ID / revision を二重解析しない。

## 5. データモデル

### 5.1 ReferenceSource

```json
{
  "reference_id": "drive:<file_id>",
  "source_kind": "google_drive_video",
  "source_locator": "<private locator>",
  "display_name": "reference-001.mov",
  "content_hash": "...",
  "created_at": "...",
  "analysis_status": "pending",
  "usage_policy": {
    "source_usage": "reference_only",
    "verbatim_reuse_allowed": false,
    "voice_clone_allowed": false,
    "motion_copy_allowed": false,
    "asset_reuse_allowed": false
  }
}
```

`source_locator` は解析基盤内部でのみ扱い、Character BibleやRuntime設定へ出力しない。

### 5.2 TranscriptSegment

```json
{
  "start_seconds": 12.4,
  "end_seconds": 14.8,
  "text": "...",
  "language": "ja",
  "speaker": null,
  "asr_confidence": null
}
```

ASRは観察補助であり、認識結果を「本人の正式な台詞データ」として扱わない。

### 5.3 AudioExpressionObservation

例:

```json
{
  "time_range": [12.4, 14.8],
  "speech_rate": "faster_than_baseline",
  "pause_pattern": "short_phrases",
  "pitch_movement": "expanded",
  "energy_movement": "expanded",
  "delivery_notes": ["interest-related activation candidate"]
}
```

絶対的な声質コピー用パラメータではなく、同一資料内・資料間比較に使う観察値を主とする。

### 5.4 ReferenceObservation

ReferenceObservation は最も重要な境界DTOである。

```json
{
  "category": "interaction_style",
  "observation": "平常時は落ち着き、関心が上がった時だけ発話テンポと表情変化が増える",
  "evidence_refs": ["drive:<file_id>#12.4-18.1"],
  "abstraction_level": "behavioral_pattern",
  "adoption_status": "unreviewed"
}
```

ここには元セリフ、音声波形、具体的なモーション列を Character 設定として保存しない。

### 5.5 YuraDesignCandidate

参考資料そのものと、ゆら向け設計案を分離する。

```json
{
  "candidate_id": "...",
  "derived_from_observations": ["..."],
  "yura_specific_design": "普段は柔らかく落ち着いているが、好奇心が高まると自然にテンポと反応量が増える",
  "status": "candidate"
}
```

YuraDesignCandidate は必ず人間の確認を経て Character Bible へ昇格する。

## 6. ASR境界

ASR backend はインターフェースで分離する。

```text
ReferenceAudio
  ↓
TranscriptionBackend
  ↓
TranscriptDocument
```

要件:

- 日本語 `ja` を明示できる
- タイムスタンプ付きセグメントを返す
- backend名・model名・実行時刻をmetadataへ保持する
- 認識できない箇所を後段で捏造しない
- provider固有レスポンスをCharacter層へ漏らさない

クラウドAPI型を標準運用とし、ローカルWhisperは必須依存にしない。

## 7. 音声表現解析境界

文字起こしと音声表現解析は独立処理とする。

```text
Audio
 ├─ ASR → words / segments
 └─ Acoustic analysis → pitch / energy / pause / speech rhythm
               ↓
       Timeline alignment
```

これによりASR精度が低い場合でも、音声表現の観察は継続できる。

## 8. 保存方針

### 8.1 クラウド正本

ローカルPCを正本にしない。

reference IDごとに最低限以下を保持する。

```text
reference/<reference_id>/
  manifest.json
  transcript.json
  transcript.txt
  audio_expression.json
  visual_observations.json
  reference_observations.json
  review.json
```

原動画は元の共有ストレージに置いたままとし、Gitリポジトリへコピーしない。

### 8.2 GitHubへ入れるもの

- schema / DTO
- pipeline code
- tests
- documentation
- 参考資料利用ポリシー

### 8.3 GitHubへ入れないもの

- 原動画
- 原音声
- モデルキャッシュ
- 第三者動画の大量な逐語 transcript
- 一時抽出フレーム
- 一時音声

## 9. Character Reference Lab

Labは一覧・解析状態・比較・採用判断を扱う。

最低限の表示:

- reference name
- processed / failed / pending
- ASR status
- audio analysis status
- visual analysis status
- abstract observations
- Yura candidate
- `採用候補 / 保留 / 不採用`

Labは元素材をCharacter素材ライブラリ化するUIにはしない。

## 10. 参考動画追加時の理想UX

```text
1. 共有Driveへ動画を追加
2. 自動またはLabから解析開始
3. 数分後にReference Labへ観察結果が追加
4. ChatGPT / ユーザーが複数参考例を比較
5. 「ゆらとしてどうするか」を決める
6. 確定した設計だけ #236 Character Bible へ反映
```

動画ごとにローカルコマンドを実行したり、transcriptファイルを手動整理したりする運用は要求しない。

## 11. 障害時

- ASR失敗とaudio analysis失敗を別statusで保持する
- 一部工程失敗でも成功済み観察を破棄しない
- 同じsource revisionを再解析する場合は明示的なretryとする
- 元動画の削除後も、reference observation自体のレビュー履歴は保持可能とする

## 12. 検証

### Module

- ReferenceSource / TranscriptDocument / ReferenceObservation schema
- usage policyが常にreference-onlyとなること
- 同一ファイルの重複処理防止
- ASR backend adapter境界
- 保存manifest

### Adjacent contract

- Drive source → pipeline
- ASR → TranscriptDocument
- audio analysis → timeline
- observation → YuraDesignCandidate

### Integration

- 共有フォルダへ参考動画追加
- クラウド処理
- 結果保存
- Lab表示
- #236で人間が採用判断

## 13. #236 / #237との関係

#240は参考資料の解析を支援するだけであり、#236 Character Bibleの責務を代替しない。

```text
#240 Reference Analysis
  ↓ candidate evidence only
#236 Character Bible
  ↓ confirmed Yura definition
#237 CharacterProfile projection
  ↓ runtime contract
#227 / #228 / #214
```

この一方向依存を守り、参考資料由来データをRuntimeへ短絡させない。
