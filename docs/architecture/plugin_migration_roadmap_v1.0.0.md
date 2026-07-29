# Plugin移行ロードマップ v1.0.0

## 1. 目的

Plugin分離を安全に進めるため、`app/bootstrap/runtime.py`に残る具体Plugin依存を段階的に除去する順序、各段階の前提条件、並行可能な作業範囲を定義する。

本書は、Games PluginのFactory／Loader基盤が導入済みで、Runtime側の静的import除去のみが未完了である状態を起点とする。

## 2. 基本方針

- Coreは任意Pluginの具体クラスをimportしない。
- Pluginの生成は文字列モジュール名とFactory契約を通じて行う。
- 無効Pluginはimportしない。
- Pluginロード失敗はPlugin単位で隔離し、既存の縮退方針に従う。
- 1つのPRで複数Pluginを同時移行しない。
- 各Plugin移行後に境界テストのbaselineを縮小する。
- `runtime.py`全体の大規模リファクタリングとPlugin移行を同一PRに混在させない。

## 3. 現在の状態

### 完了済み

- Plugin Factory契約
- Plugin Loader
- Games Plugin Factory
- Factory経由ロード補助
- Factory経由でPlugin Managerへ登録する共通補助
- Games Factory／Loader／登録補助の単体テスト

### 未完了

- `app/bootstrap/runtime.py`から`GamesPlugin`の静的import削除
- `GamesPlugin(...)`直接生成のFactory経由登録への置換
- Gamesに関する境界baselineの削除

## 4. 移行優先順位

### Phase A: Games Plugin Runtime統合

対象:

- `app.plugins.games`

実施内容:

- `runtime.py`の静的importを削除
- 直接生成をFactory経由登録へ置換
- 無効時にimportしないことをRuntime統合テストで確認
- 境界baselineからGames例外を削除

このPhaseは、以降のPlugin移行に対する標準実装例とする。

### Phase B: Voice Output Plugin

対象候補:

- `app.plugins.voice_output`

優先理由:

- Coreのテキスト出力は維持しつつ、音声合成・再生を任意Pluginとして切り離せる。
- Plugin無効時の縮退結果が明確である。

前提条件:

- FactoryContextへ`SpeechSynthesizer`と`AudioPlayer`を安全に渡せること。
- Voice Output無効時でも通常会話とテキスト出力が成立すること。

### Phase C: Relationship Memory / Agent Memory Plugin

対象候補:

- `app.plugins.relationship_memory`
- `app.plugins.agent_memory`

優先理由:

- 概念としてのMemoryはCoreに残し、具体Store実装と永続化をPlugin側へ寄せる方針を検証できる。

注意事項:

- Memory概念そのものをPluginへ移動しない。
- Plugin無効時はCore内の空またはインメモリ状態で継続可能にする。
- Storeのロード失敗でCore全体を停止させない既存方針を維持する。

### Phase D: LLM Provider Plugin

対象候補:

- `app.plugins.llm_provider`

優先理由:

- Response Generator PortはCore、具体ProviderはPlugin／Adapterという最終境界へ近づけられる。

注意事項:

- 既存のrole別Provider構成を壊さない。
- dummy応答によるCore単独起動を維持する。
- Character／Situation Evaluator／Response Validatorの役割境界を同時に変更しない。

### Phase E: Streaming系Plugin

対象候補:

- YouTube
- OBS
- 配信進行
- 配信セッション
- コメント・ランキング
- Streaming Admin

前提条件:

- Games／Voice／Memory／LLMでFactory移行パターンが安定していること。
- Streaming用Composition Rootの分割方針が確定していること。

Streaming系は依存範囲が広いため、1つずつではなく責務境界ごとの専用設計を先に作成する。

## 5. 並行可能な作業

Games Runtime統合と並行して実施可能:

- 各PluginのFactory入力依存の棚卸し
- FactoryContextに必要なservice一覧の整理
- Pluginごとの無効時縮退仕様の明文化
- 境界テストbaselineの現状一覧化
- Streaming系依存関係の設計整理
- 次のPlugin用テストfixtureの準備

Games Runtime統合完了前に実施しない:

- 他Pluginの`runtime.py`静的import除去
- 複数Pluginの同時Factory移行
- Plugin Loader契約の破壊的変更
- Streaming Composition Rootの大規模変更

## 6. Pluginごとの完了条件

各Plugin移行PRは、以下をすべて満たす。

- Core側の具体Plugin importが削除されている。
- 具体Pluginの直接生成が削除されている。
- Factory／Loader経由で生成される。
- 無効時にPluginモジュールをimportしない。
- 無効時もCoreの必須機能が継続する。
- 有効時の既存機能が維持される。
- 境界テストbaselineが縮小される。
- 関連テストと全体テストが成功する。
- PRはCI成功までDraftを維持する。

## 7. 推奨PR単位

1. Games Runtime Factory統合
2. Voice Output Factory化
3. Voice Output Runtime統合
4. Relationship Memory Factory化
5. Relationship Memory Runtime統合
6. Agent Memory Factory化
7. Agent Memory Runtime統合
8. LLM Provider Factory化
9. LLM Provider Runtime統合
10. Streaming系責務分割設計

Factory追加とRuntime統合は、影響範囲が大きい場合は別PRに分割する。

## 8. テスト方針

各Pluginについて最低限、以下を用意する。

- Factory単体テスト
- Loader経由生成テスト
- 無効時にimportしないテスト
- Plugin Manager登録テスト
- Runtime統合テスト
- 境界テスト
- Core単独起動テスト

外部サービスへ実接続せず、dummy／fake／in-memory構成を利用する。

## 9. 次の具体作業

最優先はGames PluginのRuntime統合である。

その作業と並行して、次の実装候補としてVoice Output PluginのFactory入力依存を調査し、Factory化に必要な契約・設定・serviceを明確化する。
