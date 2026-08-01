# Core発話成立とTopic Memory保存設計 v1.0.1

## 1. 目的

VOICEVOXや音声再生先が存在しない、または一時的に利用不能であっても、Core単体で会話・自律発話・記憶・話題進行を継続できるようにする。

音声出力は発話内容を届ける任意の出力チャネルであり、Coreの発話成立条件ではない。発話テキストがCoreの統一出力境界を通過した時点で発話成立とし、その後段にあるVOICEVOX、音声再生、Live2D、字幕などの成否は個別チャネルの状態として扱う。

## 2. 実動作で確認した問題

一言入力後に放置した実動作では、VOICEVOX未接続中に同じ自律話題の発話が短い間隔で連続した。終了は内部の自然停止ではなく、利用者がターミナルでCtrl+Cを入力したことによる。

ログでは発話テキストがWeb／コンソールへ出力され、Topic Memoryにも保存されていた一方、自律発話側では次が繰り返されていた。

```text
activity_executor_thread:autonomous_memory_not_saved
reason=speak_not_completed
```

従来は`SPEAK` Actionの完了を音声再生成功と同一視していたため、テキストを実際に出力してもVOICEVOX失敗時には次が更新されなかった。

- 自律発話ターン数
- 最終自律発話時刻
- 話題の消耗度
- 話題継続強度
- 自律Activity終了判定

結果として、外部音声プラグインの障害がCoreの自律進行を停止させていた。

## 3. 発話成立点

### 3.1 採用する境界

Coreの発話成立点は、`SPEAK`実行経路で次が完了した後とする。

1. Conversation Output Publisherへのテキスト出力
2. コンソールへのテキスト表示
3. Short Term Memoryへの発話コミット

この処理の後に音声合成・再生を行う。したがって、音声処理へ到達した時点ではCoreの発話テキストはすでに外部観測可能な出力として成立している。

### 3.2 採用しない境界

LLMが発話テキストを生成しただけの段階は発話成立としない。

生成後でも、次の理由で出力されない可能性があるためである。

- Response Validatorによる拒否
- Activityのキャンセル
- ユーザー割り込み
- 出力優先度による破棄
- Safety／Authority判定
- FIFO出力前の停止

発話成立は「生成したか」ではなく「Coreの出力境界を通過したか」で判断する。

## 4. Coreと任意出力チャネルの分離

### Coreの責務

テキスト出力がコミットされた場合、Coreは次を成立させる。

- `SPEAK` Actionの完了
- 自律発話出力の記録
- 自律話題ターン数の更新
- 話題継続・終了判定
- Short Term Memory保存
- Topic History保存
- 構成済みの場合のTopic Memory DB保存
- 次回発話間隔の更新

### 音声チャネルの責務

VOICEVOXやAudio Playerは、成立済みの発話を音声として配送する任意チャネルである。

失敗時は次を行う。

- `audio_fallback`を記録
- `optional_voice_output_degraded`を記録
- エラー種別と内容をTraceへ残す
- Coreの`SPEAK`完了を取り消さない
- 自律発話ターンを未完了へ戻さない
- Topic Memory保存を止めない

音声成功を偽装するのではなく、Core発話成功と音声チャネル失敗を別の事実として扱う。

## 5. Topic Memory保存

テキスト出力コミット後は音声結果に関係なくTopic Memory処理へ進む。

保存処理は構成に応じて次を行う。

- Topic分類
- Topic History追加
- Memory Summary生成
- Embedding生成
- PostgreSQL Topic Memory保存

必要なClassifier、Embedding Generator、Topic Memory Storeが存在しない場合は、既存どおり各処理をskipし、Core発話自体は成功のまま維持する。

`metadata.skip_topic_memory=true`は音声状態に関係なく最優先する。

## 6. Trace

音声失敗後もCore発話を成立させた場合は次を記録する。

```text
execute_action_usecase:speak:optional_voice_output_degraded
reason=text_output_already_committed
```

Topic Memory処理を継続する場合は次も記録する。

```text
execute_action_usecase:speak:topic_memory_allowed_after_audio_failure
reason=text_output_committed
```

音声側の元エラーは`audio_fallback`と`audio_error`に保持する。

## 7. 受入条件

1. VOICEVOX未接続でもWeb／コンソールへテキストが出力される
2. `SPEAK` ActionがCore上で`completed`になる
3. 自律発話が`record_autonomous_output`へ渡される
4. 自律話題のターン数と消耗度が更新される
5. 発話間隔と話題終了判定が音声有無に依存しない
6. Topic HistoryとDB保存が音声結果に依存しない
7. `skip_topic_memory=true`では保存しない
8. VOICEVOXエラーはTraceから確認できる
9. DB機能が無効でもCore発話完了は維持される
10. 発話テキスト生成だけでは発話済みと判定しない

## 8. 非対象

- VOICEVOX接続設定の変更
- 音声プラグインの再接続制御
- 音声チャネル専用の永続的Health管理
- Live2Dや字幕チャネルの個別実装変更
- Topic Memoryスキーマ変更
- LLM生成直後を発話成立点にすること
