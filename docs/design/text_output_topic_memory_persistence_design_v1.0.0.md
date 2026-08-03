# Core発話確定と任意出力チャネル分離設計 v1.2.0

## 1. 目的

VOICEVOXや音声再生先が存在しない、または一時的に利用不能であっても、Core単体で会話・自律発話・記憶・話題進行を継続できるようにする。

音声出力は、成立済みの発話を音声として届ける任意チャネルである。Coreが採用済み発話テキストを統一出力境界へコミットした事実と、VOICEVOX・Audio Playerなど後段チャネルの配送結果を分離する。

## 2. 実動作で確認した問題

一言入力後に放置した実動作では、VOICEVOX未接続中に同じ自律話題の発話が短い間隔で連続した。終了は内部の自然停止ではなく、利用者がターミナルでCtrl+Cを入力したことによる。

ログでは発話テキストがWebまたはコンソールへ出力され、Topic Memoryにも保存されていた一方、自律発話側では次が繰り返されていた。

```text
activity_executor_thread:autonomous_memory_not_saved
reason=speak_not_completed
```

音声合成または再生の失敗によって`SPEAK` Actionまで失敗扱いとなり、次が更新されなかったことが原因である。

- 自律発話ターン数
- 最終自律発話時刻
- 話題の消耗度
- 話題継続強度
- 自律Activity終了判定
- 次回発話間隔

外部音声プラグインの障害がCoreの自律進行を阻害しており、プラグイン境界として不適切だった。

## 3. 発話確定点

### 3.1 採用する境界

Coreの発話確定点は、採用済み`SPEAK` ActionがActionSchedulerから実行され、Coreの会話出力境界とShort Term Memoryへコミットされた時点とする。

実行順は次のとおりである。

1. `SPEECH_STARTED` Eventを発行する
2. Conversation Output Publisherへテキスト配送を試行する
3. 正規のコンソール出力を行う
4. Short Term Memoryへ発話を保存する
5. `execute_action_usecase:speak:committed`を記録する
6. 任意の音声合成・再生を試行する
7. 表現時間の終了後に`SPEECH_FINISHED` Eventを発行する
8. Topic HistoryおよびTopic Memory処理を行う

Conversation Output Publisher自体も任意の表示先であり、未構成または一時失敗してもCore全体を停止させない。確定条件は、採用済みActionがCoreの正規出力コミット区間を通過したことである。

### 3.2 採用しない境界

LLMが発話候補テキストを生成しただけの段階は発話確定としない。

生成後でも、次の理由で採用・出力されない可能性があるためである。

- Response Validatorによる拒否
- Activityのキャンセル
- ユーザー割り込み
- 出力優先度制御による破棄
- Safety／Authority判定
- FIFO出力開始前の停止

発話確定は「生成したか」ではなく「採用済みテキストがCoreの出力境界を通過したか」で判断する。

## 4. 結果契約

### 4.1 CoreのSPEAK結果

Core出力境界を通過した`SPEAK`は`completed`とする。

VOICEVOXまたはAudio Playerの失敗だけを理由に、次へ変換しない。

- `ActionExecutionResult.status=failed`
- Activity Outputの`partially_completed`
- `ACTION_FAILED` Event

これにより、外部プラグインの有無がCoreの行動結果を変更しない。

### 4.2 任意チャネルの障害

音声配送成功として偽装はしない。音声障害はCore Action結果とは別の診断情報として記録する。

```text
execute_action_usecase:speak:optional_channel_degraded
channel=audio
core_speech_committed=true
```

将来は音声プラグインまたはサブシステムのHealth／Capability状態へ接続できるが、Core発話結果へ逆流させない。

### 4.3 SPEECH_FINISHEDの意味

`SPEECH_FINISHED`は「VOICEVOXの再生成功」ではなく、Coreが確定した発話の表現時間が終了したことを表す。

- 音声利用可能時: 実音声再生終了後
- 音声利用不能時: テキスト長から見積もった表現時間終了後

このイベントにより、音声未接続でも発話間隔・Drive更新・次のActivity進行を維持する。

## 5. 自律発話への反映

ActionSchedulerは音声未接続時も`SPEAK`を`completed`として集約する。`completed_speech_text()`は通常の完了済み発話本文を返し、`ActivityExecutorThread`が`AgentLifeService.record_autonomous_output()`へ渡す。

これにより次が更新される。

- 自律発話ターン数
- 最終自律発話時刻
- 話題の興味・未完了度・消耗度
- 話題継続強度
- 自律Activity終了判定
- 次回自律発話の間隔判定

Ctrl+Cによるプロセス終了は外部からの強制停止であり、自然終了判定の成功事例には数えない。

## 6. Topic Memory保存

テキスト出力コミット後は音声配送結果に関係なく、構成済みの記憶処理を実行する。

- Topic分類
- Topic History追加
- Memory Summary生成
- Embedding生成
- PostgreSQL Topic Memory保存

必要な依存が不足している場合は該当処理をskipする。依存不足を保存成功として偽装せず、Core発話確定はDB構成に依存させない。

`metadata.skip_topic_memory=true`は音声状態に関係なく最優先する。

## 7. Trace

Core確定時:

```text
execute_action_usecase:speak:committed
commit_point=core_conversation_output
```

音声障害時:

```text
execute_action_usecase:speak:optional_channel_degraded
channel=audio
core_speech_committed=true
```

記憶保存成功時:

```text
execute_action_usecase:speak:topic_memory_saved
```

## 8. 受入条件

1. VOICEVOX未接続でもWebまたはコンソールへテキストが出力される
2. Core出力境界を通過した`SPEAK`は`completed`となる
3. 音声障害は任意チャネル劣化としてTraceへ残る
4. 音声障害だけでは`ACTION_FAILED`を発生させない
5. 自律発話が`record_autonomous_output()`へ渡される
6. 自律話題のターン数と消耗度が更新される
7. 発話間隔と話題終了判定が音声有無に依存しない
8. Topic HistoryとDB保存が音声配送成功に依存しない
9. `skip_topic_memory=true`では保存しない
10. DB機能が無効でもCore発話確定は維持される
11. キャンセル・出力前失敗・通常Action失敗は発話済みと判定しない
12. 発話候補テキストを生成しただけでは発話済みと判定しない
13. Ctrl+C終了を自然終了として評価しない

## 9. 非対象

- VOICEVOX接続設定の変更
- 音声プラグインの再接続制御
- 音声チャネル専用の永続的Health管理
- Live2Dや字幕チャネルの個別実装変更
- Topic Memoryスキーマ変更
- LLM生成直後を発話確定点にすること
