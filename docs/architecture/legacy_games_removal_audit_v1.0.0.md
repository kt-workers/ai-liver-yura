# 旧Games Plugin／しりとり削除監査 v1.0.0

## 1. 文書情報

- 基準ブランチ: `feature/plugin-separation-development`
- 基準コミット: `4dd5b02a4f40ff76accd21400424af0c16dce140`
- 調査日: 2026-07-30
- 対象: `app/plugins/games/**`、しりとり実装、Core Runtime登録、Config、テスト、文書
- 性質: 削除実装前の監査。コード、Config、schema、migrationは変更しない
- 優先方針:
  - `docs/architecture/subsystem_architecture_policy_v1.0.0.md`
  - `docs/architecture/subsystem_migration_roadmap_v1.0.0.md`

> 実施状況（2026-07-30）: PR AはPR #100で完了し、PR Bで本監査の分類に従って旧Games Pluginとしりとりを物理削除した。PR Cでは旧実装を再利用せず、Game Subsystemの中立DTO、Gateway Protocol、Null Gatewayだけを新規追加した。本書の「現在」は監査時点の過去構成を示し、削除後の現行仕様は`subsystem_architecture_policy_v1.0.0.md`、`game_subsystem_contract_v1.0.0.md`、`source_file_plan.md`を正本とする。

## 2. 結論

現在のGames Pluginは、汎用Game Integrationではなく、実質的にしりとり専用の同一プロセス内実装である。

- `GamesPlugin`は`ShiritoriGameDefinition`、`ShiritoriGameService`、`ShiritoriState`を直接生成・参照する
- capabilityは`games.shiritori`を直接公開する
- Activity定義、開始・継続・停止フレーズ、constraint schemaがしりとり専用である
- Configの既定値ではGamesとしりとりが有効である
- Core Runtime Plugin SetupがGames Factory登録、LLM可用性判定、初期化状態を所有する
- Game Engine、Intent Interpreter、Activity Factory等の汎用に見える部品も、現在の利用先はしりとりだけである

したがって、既存実装を将来のGame Subsystem外枠として流用しない。旧Games Pluginとしりとりを削除し、Game Subsystem契約は削除完了後に新規設計する。

削除は一括PRにせず、次の三段階に分ける。

1. Core Runtime／Configから旧Games Plugin登録を除去
2. Games Plugin／しりとり実装と専用テストを削除
3. Game Subsystemの契約外枠とNull Gatewayを新規追加

## 3. 現在の構造

```text
Core Runtime
  -> runtime_plugin_setup.py
       -> module name "app.plugins.games"
       -> GamesPluginFactory
            -> GamesPlugin
                 -> GameEngine
                 -> GameIntentInterpreter
                 -> GameCommandValidator
                 -> TransientGameActivityFactory
                 -> ShiritoriGameDefinition
                 -> ShiritoriGameService
                 -> ShiritoriState
```

現在はPlugin Loaderにより無効時のimportを回避できるが、設定モデル、Runtime setup、Activity／Intent協調、テスト期待値はGames Pluginの存在を前提としている。

## 4. 削除対象

### 4.1 Games Pluginパッケージ

原則として`app/plugins/games/**`を全削除対象とする。

主な対象:

```text
app/plugins/games/__init__.py
app/plugins/games/factory.py
app/plugins/games/plugin.py
app/plugins/games/settings.py
app/plugins/games/activity_factory.py
app/plugins/games/activity_matcher.py
app/plugins/games/engine.py
app/plugins/games/game_engine.py
app/plugins/games/game_session.py
app/plugins/games/session.py
app/plugins/games/intent/**
app/plugins/games/shiritori/**
```

判断:

- `factory.py`: 旧Games Plugin生成専用のため削除
- `plugin.py`: しりとり capability、Activity、session snapshotを直接所有するため削除
- `settings.py`: `plugins.games`と`shiritori`専用のため削除
- `engine.py`／`game_engine.py`／`session.py`: 将来Subsystemへコピーせず削除
- `intent/**`: Core内Pluginとしてゲーム入力を分類する設計のため削除
- `activity_factory.py`／`activity_matcher.py`: しりとり開始表現とPlugin Activity生成専用のため削除
- `shiritori/**`: 製品要件ではないため完全削除

### 4.2 Core Runtime登録

`app/bootstrap/runtime_plugin_setup.py`から次を削除する。

- `register_optional_plugin_from_factory(... plugin_id="games" ...)`
- `config.plugins.games.enabled`の参照
- Games用`game_model`解決
- Games用`llm_available`設定
- `initialize_enabled_plugins()`の`"games"`項目

削除後、Runtime Plugin SetupはGames package、Games設定、ゲーム用LLMモデルを認識しない。

### 4.3 Config／schema

削除対象:

- `AppConfig`内の`plugins.games`
- Games Plugin設定型への参照
- `config/plugins/index.yaml`等のGames設定
- Games専用環境override、validation、referenced model収集
- `intent_interpreter.model`
- `shiritori.max_generation_retries`

重要事項:

現在の`GamesPluginSettings.enabled`と`ShiritoriPluginSettings.enabled`は既定で`True`である。単純にコードだけ削除すると、既存Configの`plugins.games`がunknown keyとなり起動を壊す可能性がある。

移行方法は次のどちらかを削除PRで明示的に選択する。

A. 同一PRでConfigから`plugins.games`を削除し、production／sample設定も同時更新する

B. 一時的な廃止キー受理をConfig Loader外縁に限定して追加し、警告後に別PRで削除する

本監査ではAを推奨する。現時点で後方互換利用者を維持する製品要件がなく、互換層を増やす利点がない。

### 4.4 Core Runtime／会話フローへの影響

確認・修正対象:

- Plugin Activity定義の収集
- Plugin Intent Interpreter dispatch
- Plugin Command dispatch
- active plugin activity同期
- ongoing activityとゲームsessionの紐付け
- rollback／cancel処理
- prompt context／memory policy provider
- Activity Plannerのしりとり開始判定期待値
- 通常会話へのフォールバック期待値

shared Plugin契約やCore側の汎用Plugin dispatch基盤は削除しない。Games以外の将来Pluginでも利用できるためである。

削除するのはGames固有のprovider、capability、command、Activity定義、テスト期待値である。

### 4.5 テスト

削除候補:

```text
tests/test_game_engine.py
tests/test_game_command_validator.py
tests/test_game_intent_interpreter.py
tests/test_games_plugin_factory.py
tests/test_shiritori_game.py
```

内容確認後に削除または再分類する候補:

```text
tests/test_plugin_activity_coordinator.py
tests/test_plugin_ongoing_activity_synchronizer.py
tests/test_runtime_plugin_setup.py
tests/test_runtime_factory.py
tests/test_behavior_planner.py
tests/test_activity_planner_thread.py
tests/test_autonomous_common_pipeline.py
tests/test_plugin_separation_boundaries.py
tests/test_plugin_loader.py
tests/test_plugin_factory_loader.py
```

後者はCoreの汎用Plugin基盤を検証するため、Games fixtureを汎用sample pluginへ置換して残す。

### 4.6 文書／サンプル

更新・削除対象:

- Games Pluginを現行機能として記載する設計文書
- しりとり実行例
- Config例
- READMEのゲーム操作説明
- Plugin移行進捗表
- Source file plan

過去の監査記録やマージ済みPR履歴は削除しない。現在の正式方針と矛盾する文書には「過去方針」であることを明示する。

## 5. 残すもの

次はGames削除と同時に削除しない。

- `PluginManager`
- `PluginLoader`
- `PluginFactoryContext`
- Plugin capability、command、intent、activity共通契約
- Core側の汎用Plugin Activity dispatch
- Core側の汎用ongoing activity同期
- sample echo plugin等の境界テストfixture
- Activity／Event／Actionの共通モデル

これらはGames固有ではなく、LLM Provider、Voice Output、Memory Plugin、将来の軽量Pluginにも関係する。

## 6. 削除後の期待動作

### 6.1 Core起動

- `app/plugins/games`が物理的に存在しなくても`python -m app`相当のimportが成功する
- ConfigにGames設定を必要としない
- Games用LLMモデル解決を行わない
- Plugin ManagerはGamesなしで正常初期化する

### 6.2 会話

- 「しりとりしよう」等を専用Activityとして開始しない
- 同入力は通常の会話入力として扱う
- LLMが会話上しりとりを提案・説明することまでは禁止しないが、ゲームsessionは開始しない
- active game、state version、turn handoff等のゲーム状態をCoreに保持しない

### 6.3 自律活動・感情・記憶

- 自律活動計画が回帰しない
- 通常会話の割り込み・再開が回帰しない
- 感情更新が回帰しない
- Relationship Memory／Agent Memory／Topic Memoryが回帰しない
- Voice Outputが回帰しない

## 7. 削除PRの推奨分割

### PR A: Core RuntimeとConfigからGames登録を除去

目的:

- CoreがGames packageとGames設定を認識しない状態を先に作る

主な変更:

- `runtime_plugin_setup.py`からGames登録を削除
- `AppConfig`／Config Loader／YAMLからGames設定を削除
- Games用model reference validationを削除
- Games無効前提のCoreテストへ更新

完了条件:

- Games packageをblockしてCore import／Runtime構築が成功
- Plugin Managerに`games`が登録されない
- Configに`plugins.games`が存在しない
- 全体テスト成功

rollback:

- Runtime登録とConfig項目だけを戻せる

### PR B: 旧Games Pluginとしりとりを物理削除

先行:

- PR A

主な変更:

- `app/plugins/games/**`を削除
- Games／しりとり専用テストを削除
- 汎用Pluginテストをsample pluginへ置換
- README／設計文書の現行機能記載を更新

完了条件:

- リポジトリに`shiritori`の実装参照がない
- `app.plugins.games`の実行時参照がない
- Games／しりとり専用Configがない
- Core-only全体テスト成功

rollback:

- 物理削除のみを戻せる。Runtime登録はPR Aで既に外れているため、復元しても自動有効化されない

### PR C: Game Subsystem契約外枠

先行:

- PR B

主な変更:

```text
app/integrations/games/
  contracts.py
  gateway.py
  null_gateway.py
  events.py

subsystems/games/
  README.md
  contracts/
```

実装範囲:

- 共通status／command／event DTO
- `GameSubsystemGateway` Protocol
- `NullGameSubsystemGateway`
- 未接続状態のcontract test

対象外:

- ゲームエンジン
- しりとり
- HTTP APIサーバー
- DB
- session persistence
- LLMによるゲーム進行

## 8. 必須境界テスト

### PR A

1. `app.bootstrap.runtime`をimportしても`app.plugins.games`をロードしない
2. `app.plugins.games`をimport blockしてRuntime構築できる
3. Plugin ManagerにGames capabilityが存在しない
4. Games設定なしでproduction Configが読み込める
5. 「しりとりしよう」が通常会話経路へ流れる

### PR B

1. `app/plugins/games`が存在しない
2. `shiritori`実装参照がない
3. source ASTに`app.plugins.games` importがない
4. 汎用Plugin基盤テストがsample pluginで成功
5. 全体テスト成功

### PR C

1. Null Gatewayは`DISCONNECTED`または`UNAVAILABLE`を返す
2. Null Gateway利用時にCore起動失敗しない
3. Integration契約はCore Runtime、個別ゲーム、Subsystem実装をimportしない
4. `subsystems/games`はCore具象をimportしない

## 9. 主なリスク

### 9.1 Config互換

既存Configの`plugins.games`が残るとstrict parserで失敗する可能性がある。コード削除とConfig更新を同一PRで行う。

### 9.2 汎用Plugin基盤の誤削除

Gamesが広く利用しているため、Plugin command／intent／activity共通契約までGames専用に見える危険がある。利用者検索を行い、Games以外の利用または将来契約として明確なものは残す。

### 9.3 通常会話テストの期待値

過去にGames無効時の通常会話フォールバックを調整している。Games完全削除後は「無効時」ではなく「存在しない通常状態」に期待値を統一する。

### 9.4 大量テスト削除

専用テストを削除するだけではCoreの境界保証が弱くなる。削除行数ではなく、Core-only／package-block／通常会話fallbackテストを追加して保証を置き換える。

## 10. 実装前チェックリスト

- 最新`feature/plugin-separation-development`から分岐
- PR Baseは`feature/plugin-separation-development`
- `develop`へ直接変更しない
- PR A、B、Cを混在させない
- 変更前にGames／shiritori参照一覧を保存
- Configの全fixture／sample／productionを確認
- 関連テスト、全体pytest、変更ファイルRuff、`git diff --check`を実行
- CI成功前はDraftを維持
- 通常マージを使用し、squash／rebaseしない

## 11. 最終判断

旧Games Pluginとしりとりは完全削除する。

既存コードをGame Subsystem外枠として移動・改名・再利用しない。まずCore RuntimeとConfigから依存を外し、次に物理削除し、その後に最小のGame Subsystem契約を新規追加する。

この順序により、削除と新設を混ぜず、Core-only状態を各段階で検証できる。
