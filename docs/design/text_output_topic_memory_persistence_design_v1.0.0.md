# Core発話成立とTopic Memory保存設計 v1.1.0

## 1. 目的

VOICEVOXや音声再生先が存在しない、または一時的に利用不能であっても、Core単体で会話・自律発話・記憶・話題進行を継続できるようにする。

音声出力は、成立済みの発話を音声として届ける任意チャネルであり、Coreの発話成立条件ではない。Coreが採用済み発話テキストを統一出力境界へコミットした事実と、VOICEVOX・Audio Playerなど後段チャネルの配送結果を分離して扱う。

## 2. 実動作で確認した問題

一言入力後に放置した実動作では、VOICEVOX未接続中に同じ自律話題の発話が短い間隔で連続した。終了は内部の自然停止ではなく、利用者がターミナルでCtrl+Cを入力したことによる。

ログでは発話テキストがWebまたはコンソールへ出力され、Topic Memoryにも保存されていた一方、自律発話側では次が繰り返されていた。

```text
activity_executor_thread:autonomous_memory_not_saved
reason=speak_not_completed
```

従来は、自律発話の成立判定を`SPEAK` Actionの通常完了だけに限定していた。音声合成または再生が失敗すると、Coreテキスト出力済みでもAction結果が`failed`となり、次が更新されなかった。

- 自律発話ターン数
- 最終自律発話時刻
- 話題の消耗度
- 話題継続強度
- 自律Activity終了判定

結果として、外部音声プラグインの障害がCoreの自律進行を阻害していた。

## 3. 発話成立点

### 3.1 採用する境界

Coreの発話成立点は、採用済み`SPEAK` Actionが通常のテキスト出力処理を通過し、Core側の発話記録へコミットされた時点とする。

現在の実行順は次のとおりである。

1. `SPEECH_STARTED` Eventを発行する
2. Conversation Output Publisherへテキスト配送を試行する
3. 正規のコンソール出力を行う
4. Short Term Memoryへ発話を保存する
5. 音声合成・再生を試行する
6. `SPEECH_FINISHED` Eventを発行する

Conversation Output Publisherは任意の表示先であり、未構成または一時失敗してもCore全体を停止させない。Core発話成立の基準は、採用済みActionが上記のテキスト出力コミット区間を通過したことであり、後段の音声配送成功ではない。

### 3.2 採用しない境界

LLMが発話候補テキストを生成しただけの段階は発話成立としない。

生成後でも、次の理由で採用・出力されない可能性があるためである。

- Response Validatorによる拒否
- Activityのキャンセル
- ユーザー割り込み
- 出力優先度制御による破棄
- Safety／Authority判定
- FIFO出力開始前の停止

発話成立は「生成したか」ではなく「採用済みテキストがCoreの出力境界を通過したか」で判断する。

## 4. 二層の結果契約

音声チャネルが失敗した場合、Core発話成立とチャネル障害を同じ成功・失敗値へ潰さない。

### 4.1 Action実行結果

VOICEVOXまたはAudio Playerの失敗は診断可能な事実として保持する。

- `ActionExecutionResult.status=failed`
- `error=optional_output_degraded:channel=voice;error=...`
- Activity Outputの既存集約規則は変更しない
- 音声配送成功として偽装しない

`optional_output_degraded`は、必須のCoreテキスト出力後に任意チャネルだけが縮退したことを示す安定した識別子である。

### 4.2 Core発話成立判定

自律話題進行など、実際に発話テキストが出力されたかを判断する処理では、`completed_speech_text()`を使用する。

同関数は次を発話成立として扱う。

- `SPEAK` Actionが`completed`
- `SPEAK` Actionが`failed`だが、エラーが`optional_output_degraded`である

次は発話成立に含めない。

- Actionのキャンセル
- 出力境界へ到達する前の失敗
- 任意出力縮退ではない通常のAction失敗
- `SPEAK`以外のAction

これにより、Activity Outputでは音声障害を観測可能なまま、自律発話ターン数・話題進行・自然終了判定をVOICEVOXから独立させる。

## 5. 自律発話への反映

`ActivityExecutorThread`は`completed_speech_text()`が返した発話本文を`AgentLifeService.record_autonomous_output()`へ渡す。

VOICEVOX未接続でもCore出力境界を通過済みであれば、次が更新される。

- 自律発話ターン数
- 最終自律発話時刻
- 話題の興味・未完了度・消耗度
- 話題継続強度
- 自律Activity終了判定
- 次回自律発話の間隔判定

Ctrl+Cによるプロセス終了は外部からの強制停止であり、自然終了判定の成功事例には数えない。

## 6. Topic Memory保存

テキスト出力コミット後は、音声配送結果と記憶保存可否を分離する。

次が構成済みであれば、音声失敗後も記憶処理を継続する。

- Topic History
- Topic Classifier
- Embedding Generator
- Topic Memory Store

保存処理は次を行う。

- Topic分類
- Topic History追加
- Memory Summary生成
- Embedding生成
- PostgreSQL Topic Memory保存

必要な依存が不足している場合は、既存どおり該当処理をskipする。依存不足を保存成功として偽装しない一方、Core発話成立判定はDB構成に依存させない。

`metadata.skip_topic_memory=true`は音声状態に関係なく最優先する。

## 7. Trace

音声失敗時は次を記録する。

```text
execute_action_usecase:speak:optional_voice_output_degraded
reason=text_output_already_committed
```

Topic Memory処理を継続する場合は次も記録する。

```text
execute_action_usecase:speak:topic_memory_allowed_after_audio_failure
reason=text_output_committed
```

音声側の元エラーは`audio_fallback`および`audio_error`に保持する。

## 8. 受入条件

1. VOICEVOX未接続でもWebまたはコンソールへテキストが出力される
2. 音声失敗は`optional_output_degraded`としてAction結果に残る
3. Core発話成立判定は同縮退結果を発話済みとして認識する
4. 自律発話が`record_autonomous_output()`へ渡される
5. 自律話題のターン数と消耗度が更新される
6. 発話間隔と話題終了判定が音声有無に依存しない
7. Topic HistoryとDB保存が音声配送成功に依存しない
8. `skip_topic_memory=true`では保存しない
9. DB機能が無効でもCore発話成立は維持される
10. キャンセル・出力前失敗・通常Action失敗は発話済みと判定しない
11. 発話候補テキストを生成しただけでは発話済みと判定しない
12. Ctrl+C終了を自然終了として評価しない

## 9. 非対象

- VOICEVOX接続設定の変更
- 音声プラグインの再接続制御
- 音声チャネル専用の永続的Health管理
- Live2Dや字幕チャネルの個別実装変更
- Topic Memoryスキーマ変更
- LLM生成直後を発話成立点にすること
- Activity Output全体の成功・部分成功集約規則の変更
