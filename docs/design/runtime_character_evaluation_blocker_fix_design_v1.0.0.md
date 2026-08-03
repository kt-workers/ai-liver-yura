# 実動作評価阻害要因 修正設計 v1.1.0

## 1. 目的

PR #118で導入したDesire／Motivation／Moral／Response Content Planを実環境で評価した際に確認された、次の評価阻害要因を修正する。

1. Situation Evaluatorが通常会話を`conversation_with_user / continue`として返し、Situation契約のschema validationで拒否される
2. 短い相槌を含むすべてのユーザー入力が同じDrive刺激として扱われ、Curiosity／Engagementが短時間で1.0へ飽和する
3. Coreの発話成立がVOICEVOX・音声再生の成功に依存し、自律発話の記録・間隔・話題終了判定が進まない

VOICEVOXは任意のプラグイン／サブシステムである。未接続や障害時でもCore単体で会話、自律発話、記憶、話題進行を継続できなければならない。

発話境界の詳細は次を正とする。

- `docs/design/text_output_topic_memory_persistence_design_v1.0.0.md`

## 2. 実動作ログから確認した事実

### 2.1 Situation Evaluator

実動作では通常会話の意味解析結果として、複数ターンで次の組み合わせが返された。

```text
activity_type = conversation_with_user
operation = continue
```

一方、Situation Analysisの正規契約では通常会話をActivity候補ではなく次のsentinelで表す。

```text
activity_type = conversation
operation = discuss | explain | null
```

`conversation_with_user`はActivity Managerが実行するCore内部のActivity名であり、Situation Evaluatorの候補契約ではない。この語彙差により、内容としては妥当なLLM結果が候補外Activityとして拒否され、Fallbackへ遷移していた。

### 2.2 Activity Registry

対象起動構成では、PluginがActivity Definitionを公開していなかったため、`ActivityRegistry`の定義数は0件だった。

これは「通常会話Activityが未登録」という異常ではない。Activity RegistryはPlugin Activity候補を管理する境界であり、Coreの通常会話sentinelを登録する場所ではない。

したがって、通常会話用の`ActivityDefinition`をPlugin Registryへ追加する対応は行わない。

### 2.3 Drive更新

修正前はUSER_TEXT、YOUTUBE_COMMENT、USER_SPEECHの本文に関係なく、毎回固定値を加算していた。

```text
curiosity +0.1
engagement +0.2
boredom -0.3
energy -0.03
```

`うん`、`ふむふむ`、`そうなんだ`のような相槌も実質的な新情報と同じ刺激となり、DriveStateの0〜1 clampによってCuriosity／Engagementが数ターンで1.0へ張り付いていた。

### 2.4 Core発話成立

VOICEVOX未接続中でも、採用済み発話テキストはWebまたはコンソールへ出力され、Short Term MemoryやTopic Memoryへ保存されていた。一方、自律発話側では次が繰り返されていた。

```text
activity_executor_thread:autonomous_memory_not_saved
reason=speak_not_completed
```

音声合成・再生の失敗によって`SPEAK` Action自体まで失敗扱いになり、次のCore状態が更新されなかったためである。

- 自律発話ターン数
- 最終自律発話時刻
- 話題の消耗度
- 話題継続強度
- 自律Activity終了判定
- 次回発話間隔

プロセスが終了したのは自然終了ではなく、利用者がターミナルでCtrl+Cを入力したためである。これを自律Activityの正常終了として評価しない。

## 3. Situation Evaluator修正

### 3.1 Prompt契約

Situation Evaluator Promptへ次を明示する。

- 通常会話は`activity_type=conversation`
- 通常会話のoperationは`discuss`または`explain`
- `conversation_with_user`はRuntime内部名であり出力しない
- `start / continue / stop`はavailable activityまたはongoing activityだけに使用する
- `available_activities=[]`でも通常会話は`conversation / discuss`で表現できる

### 3.2 Port境界の互換正規化

Promptだけでは既存モデルの出力揺れを完全には防げないため、Situation role Adapterで次の限定的な正規化を行う。

```text
conversation_with_user + start    -> conversation + discuss
conversation_with_user + continue -> conversation + discuss
```

次は変更しない。

- Plugin Activity名
- 不正JSON
- Character role出力
- Response Validator role出力
- goal、constraints、speech_act、confidence等の他フィールド

これにより、LLMのRuntime内部語彙混入だけを吸収し、候補外Activityを一般的に許容することはしない。

## 4. Drive飽和対策

### 4.1 入力分類

ユーザー入力を次の段階へ分類する。

| 種別 | 例 | 刺激係数 |
|---|---|---:|
| acknowledgement | うん、ふむふむ、そうなんだ | 0.25 |
| greeting | こんにちは、こんばんは | 0.60 |
| substantive | 質問、意見、具体的な話題 | 1.00 |
| unknown | 本文を取得できない入力 | 0.50 |

### 4.2 上限付近の逓減

Curiosity／Engagementの増加は単純加算ではなく、残余幅に比例させる。

```text
next = current + (1.0 - current) * rate
```

これにより、上限へ近づくほど同じ入力による増加量が小さくなる。

対象は次に限定する。

- ユーザー入力によるCuriosity／Engagement増加
- 時間経過によるCuriosity増加

既存の次の契約は変更しない。

- STREAM_STARTED
- USER_INTERACTION
- SPEECH_FINISHED
- ACTION_FAILED
- boredom／energyの既存方向性

### 4.3 観測性

Drive更新Traceへ次を追加する。

```text
input_kind
stimulus_scale
```

相槌判定や刺激量が実動作ログから確認できるようにする。

## 5. Core発話境界修正

### 5.1 発話成立点

Coreの発話成立点は、LLMが候補文を生成した時点ではなく、採用済み`SPEAK` ActionがCoreの正規テキスト出力境界を通過した時点とする。

具体的には次が完了した後である。

1. Conversation Output Publisherへの配送試行
2. 正規のコンソール出力
3. Short Term Memoryへの発話保存
4. `execute_action_usecase:speak:committed` Trace記録

Validator拒否、キャンセル、ユーザー割り込み、出力開始前の停止などにより採用・出力されなかった候補文は発話成立に含めない。

### 5.2 任意音声チャネル

VOICEVOXとAudio PlayerはCore発話成立後の任意チャネルとして扱う。

- 音声成功時も失敗時も、Core出力境界通過済みの`SPEAK`は`completed`
- 音声障害だけでは`ACTION_FAILED`を発生させない
- 音声障害は`execute_action_usecase:speak:optional_channel_degraded`へ記録する
- Topic History／Topic Memory処理を音声成功に依存させない
- `metadata.skip_topic_memory=true`は従来どおり優先する

### 5.3 自律進行

`ActionScheduler`が完了済み`SPEAK`を集約し、`completed_speech_text()`が発話本文を返す。`ActivityExecutorThread`はその本文を`AgentLifeService.record_autonomous_output()`へ渡す。

これにより、VOICEVOX未接続時も自律発話ターン数・発話間隔・話題消耗・終了判定が進行する。

## 6. 変更しない範囲

- Activity RegistryへCore通常会話定義を登録しない
- Moral候補限定適用を有効化しない
- Activity候補の追加・削除を行わない
- Authority／Capability／Constraint／Safety契約を変更しない
- Response Content Plan生成規則を変更しない
- VOICEVOX接続設定や再接続処理を変更しない
- 音声障害を音声配送成功として偽装しない
- Desire／Moral永続化を追加しない

## 7. 受入条件

1. `conversation_with_user / continue`が`conversation / discuss`へ正規化される
2. 正規化後の通常会話結果がSituation schema validationを通過できる
3. Plugin Activity出力は変更されない
4. Character／Validator roleは正規化されない
5. Promptが通常会話sentinelを明示する
6. 相槌のDrive刺激が実質的入力より小さい
7. Curiosity／Engagementが相槌数回で1.0へ張り付かない
8. VOICEVOX未接続でもCore出力済み`SPEAK`が`completed`となる
9. 音声障害がTraceに残り、Core発話結果へ逆流しない
10. 自律発話が`record_autonomous_output()`へ記録される
11. Topic History／Topic Memory保存が音声成功に依存しない
12. 発話候補の生成だけでは発話済みと判定しない
13. Ctrl+C終了を自然終了として評価しない
14. 既存Runtime／Plugin／Architecture境界テストが通過する
15. 機能フラグ未設定時の限定選択OFFを維持する

## 8. 再評価手順

修正後は、前回と同じ固定会話を限定選択OFFで再実行する。

確認項目:

- Situation Evaluator Traceが`stage=parsed`となる
- `fallback_used=false`となる
- Behavior Planの`planner_type=llm`が採用される
- `input_kind=acknowledgement`が相槌で記録される
- Curiosity／Engagementが数ターンで1.0へ到達しない
- VOICEVOXを停止した状態でも`SPEAK`が完了する
- `execute_action_usecase:speak:optional_channel_degraded`が記録される
- `record_autonomous_output()`が発話ごとに実行される
- 発話間隔と話題終了判定が音声有無に依存しない
- Response Content Planと実発話の対応を再評価できる

Plugin Activity候補が存在しない起動構成では、Moral候補限定適用の評価は引き続き対象外である。限定適用の評価は、意味・Authority・Capability・Constraint・Safetyが同等なPlugin Activity候補群を別途用意した後に行う。
