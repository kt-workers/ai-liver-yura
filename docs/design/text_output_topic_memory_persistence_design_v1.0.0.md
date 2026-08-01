# テキスト出力済み発話のTopic Memory保存設計 v1.0.0

## 1. 目的

VOICEVOXまたは音声再生先が利用できない場合でも、発話テキストがWeb画面またはコンソールへ出力されたなら、その発話をTopic HistoryおよびTopic Memoryへ保存する。

音声出力は発話内容を届ける複数の出力チャネルの一つであり、音声だけの失敗を理由として、すでに利用者へ提示された発話内容を長期記憶から除外しない。

## 2. 変更前の問題

`ExecuteActionUsecase`は次の順で処理していた。

1. Web Conversationへテキストを送る
2. コンソールへテキストを表示する
3. Short Term Memoryへ保存する
4. 音声合成・再生を試行する
5. 音声が成功した場合だけTopic History・Topic Memoryを保存する

このため、テキストが利用者へ表示済みでもVOICEVOX未接続時には次の理由でDB保存が停止していた。

```text
reason=audio_delivery_failed
```

## 3. 保存条件

音声失敗時にもTopic Memory保存を継続する条件は次のすべてを満たす場合とする。

- Action種別が`SPEAK`
- 発話テキストが通常の出力処理へコミット済み
- `skip_topic_memory`が`true`ではない
- Topic Historyが構成済み
- Topic Classifierが構成済み
- Embedding Generatorが構成済み
- Topic Memory Storeが構成済み

DB保存構成が不足している場合は、保存できない状態を成功として偽装せず、従来の音声失敗結果を維持する。

## 4. 出力結果と記憶結果の分離

音声失敗時も次の二つを分離する。

### 発話内容の記憶

テキスト出力済みであれば次を実行する。

- Topic分類
- Topic History追加
- Memory Summary生成
- Embedding生成
- PostgreSQL Topic Memory保存

### Action実行結果

VOICEVOXまたは音声再生に失敗した事実は維持する。

- `ActionExecutionResult.status=failed`
- Activity全体では既存の集約規則により部分成功として扱える
- 音声エラー文字列を保持する
- 音声成功として偽装しない

## 5. 保存対象外ポリシー

`metadata.skip_topic_memory=true`は音声状態に関係なく最優先する。

ゲーム中の短い返答、一時的なシステム発話、記憶へ残すべきでない出力は従来どおり保存しない。

## 6. Trace

音声失敗後も保存を許可した場合は次を記録する。

```text
execute_action_usecase:speak:topic_memory_allowed_after_audio_failure
reason=text_output_committed
```

音声側では従来どおり`audio_fallback`を記録し、DB保存側では`topic_memory_saved`または各失敗理由を記録する。

## 7. 非対象

この変更では次を行わない。

- VOICEVOX接続設定の変更
- 音声失敗を成功扱いに変更
- Topic Classifier失敗時のカテゴリ推定
- Embedding失敗時のDB保存
- `ASK`、`REACT`、`OBSERVE`など非`SPEAK` ActionのTopic Memory保存
- Topic Memoryのスキーマ変更

## 8. 検証条件

回帰テストでは次を確認する。

- VOICEVOX失敗でもWeb出力とコンソール出力が成立する
- Topic Historyへ発話が追加される
- Embeddingが生成される
- Topic Memory Storeへ1件保存される
- Action結果は音声失敗のまま
- `skip_topic_memory=true`では保存されない
