# 本番設定分割 完了監査

> 履歴注記（2026-07-30）: 本書は設定分割完了時点の記録である。記載された`plugins.games`設定はPR #100で本番・legacy設定とCore Configから削除済みであり、現行設定ではない。

## 1. 監査対象

本資料は、`feature/core-development`へ統合された本番設定分割の最終状態を記録する。

基準となる完了マージコミットは次である。

```text
39b44dfe4c38005002a58511fefd12bbf6bb6377
```

既存の`docs/audits/current_architecture_audit.md`に記録された段階移行のうち、複数YAML loader導入後から`application.yaml`廃止までの最終結果を補完する。

## 2. 最終判定

本番設定のトップレベルownership分割は完了した。

- 通常起動のroot設定入口は`config/index.yaml`
- 各トップレベルキーは専用owner fileへ完全割当
- 暫定集約`config/application.yaml`は削除済み
- legacy `config/config.yaml`は互換、比較、切り戻し用途として維持
- legacyとmanifestはraw mappingが完全一致
- `config_path`を除く`AppConfig`が完全一致
- strict parser、ownership、参照グラフ、source追跡を本番ファイルで検証
- Runtime、Speech、Memory、Streaming、Plugin、Streaming Adminの回帰を確認

## 3. 本番設定構成

```text
config/
  index.yaml
  runtime.yaml
  character.yaml
  speech.yaml
  memory.yaml
  services.yaml
  models.yaml
  llm.yaml
  streaming.yaml
  plugins.yaml

  config.yaml                    # legacy互換
  pronunciation_dictionary.yaml
  run_of_show/
```

## 4. ownership一覧

| owner file | トップレベルキー |
| --- | --- |
| `config/runtime.yaml` | `app`、`trace`、`input_receivers`、`confirmation` |
| `config/character.yaml` | `character` |
| `config/speech.yaml` | `speech` |
| `config/memory.yaml` | `memory` |
| `config/services.yaml` | `services` |
| `config/models.yaml` | `models` |
| `config/llm.yaml` | `response_generator`、`llm_roles`、`topic_classifier` |
| `config/streaming.yaml` | `streaming` |
| `config/plugins.yaml` | `plugins` |

`config/index.yaml`の割当集合と各owner fileのトップレベルキー集合は完全一致する。

次は存在しない。

- 未割当キー
- owner file内の余剰キー
- 重複ownership
- deep merge
- override
- nested imports
- 暗黙的なYAML自動探索

## 5. 設定入口と互換性

### 5.1 通常入口

```text
load_app_config()
→ config/index.yaml
```

### 5.2 明示入口

```text
load_app_config(Path("config/index.yaml"))
→ manifest

load_app_config(Path("config"))
→ config/index.yaml

load_app_config(Path("config/config.yaml"))
→ legacy単一設定
```

### 5.3 環境変数

`AI_LIVER_CONFIG_PATH`はfile、manifest、directory指定を引き続き受理する。

入口の優先順位は次のままである。

1. `load_app_config(path)`の明示引数
2. 空でない`AI_LIVER_CONFIG_PATH`
3. 既定の`config/index.yaml`

### 5.4 config_path

`AppConfig.config_path`はimport先ではなくroot設定入口の絶対pathを表す。

通常起動とStreaming Adminでは`config/index.yaml`を示し、legacy明示指定時だけ`config/config.yaml`を示す。

## 6. 値とpath規則

分割工程では設定値を変更していない。

次を含め、legacyの値とコメントをowner fileへ移動した。

- service type、URL、timeout、環境変数名
- model名、service参照、dimension
- LLM role、temperature、timeout、fallback response
- VoiceVox speaker ID、voice profile、player
- Agent、Relationship、Topic Memory
- Streaming readiness、OBS、moderation、ranking、response
- Plugin registry、Games、intent interpreter、shiritori

設定値内の相対path解決規則も変更していない。

- 発音辞書
- Agent Memory
- Relationship Memory
- run-of-show
- ログ等の既存相対path

manifest import pathだけが`index.yaml`のdirectory基準である。

## 7. source追跡

型、範囲、未知キー、参照グラフのエラーは、該当トップレベルキーの実owner fileを`ConfigError.source_file`として返す。

代表例：

| エラーpath | source file |
| --- | --- |
| `speech.service` | `config/speech.yaml` |
| `memory.topic_memory.embedding_model` | `config/memory.yaml` |
| `services.openai.timeout_seconds` | `config/services.yaml` |
| `models.openai_chat.service` | `config/models.yaml` |
| `response_generator.model` | `config/llm.yaml` |
| `streaming.health_timeout_seconds` | `config/streaming.yaml` |
| `plugins.games.intent_interpreter.model` | `config/plugins.yaml` |

参照先ではなく、参照を記述したowner fileをsourceとする。

## 8. 検証履歴

設定分割の各段階でGitHub Actionsの全体テストが成功している。

| Run | 対象 |
| --- | --- |
| #203 | runtime・character分割 |
| #204 | speech・memory分割 |
| #205 | services・models分割 |
| #206 | LLM関連設定分割 |
| #207 | streaming・plugins分割、`application.yaml`削除 |

最終工程のRun #207は成功した。

テストでは最低限、次を固定している。

- 本番YAMLが正しいroot mappingである
- manifestが正常に読める
- legacyとmanifestのraw mappingが一致する
- `config_path`を除く`AppConfig`が一致する
- owner source mapが正しい
- owner fileの設定エラーsourceが正しい
- default、directory、legacy明示入口が動作する
- Runtime Composition Rootが構築できる
- Speech Factoryが構築できる
- Streaming RuntimeとAdminがroot manifestを保持する
- `config/application.yaml`が存在しない

## 9. 完了した課題

次は完了扱いとする。

1. service type別の型付き設定
2. strict parserと未知キー拒否
3. model／service参照グラフ検証
4. Plugin設定境界の整理
5. 複数YAML manifest loader
6. top-level ownership完全一致検証
7. source file追跡
8. `AI_LIVER_CONFIG_PATH`
9. 本番設定の機能別分割
10. 暫定`application.yaml`の廃止
11. legacy／manifest等価性の回帰固定
12. 通常起動のmanifest化

## 10. 残存課題と優先順位

### 優先度1：emotion appraisalの統合

現状、`emotion_appraisal`は標準`AppConfig`へ統合されず、`app/bootstrap/emotion_runtime.py`側の互換経路で同一YAMLを再読込している。

問題：

- 設定入口が二重化している
- manifestのownership／source追跡対象外である
- deprecated warningが継続する
- legacy廃止判断の前提を満たさない

次工程では、挙動を変えずに次を行う。

1. typed settingsを`AppConfig`へ統合
2. 専用owner fileまたは既存ownerへの配置方針を確定
3. 二重読込を廃止
4. source追跡とlegacy等価性テストを追加
5. deprecated warningを解消

推奨ブランチ：

```text
refactor/integrate-emotion-appraisal-config
```

### 優先度2：依存方向テスト

ASTベースの依存方向テストを導入する。

最初から全面禁止にせず、既知例外をベースラインとして記録し、新規違反だけを防ぐ。

主な規則候補：

- `domain`は`runtime`、`adapters`、`plugins`、`bootstrap`へ依存しない
- `ports`は具象Adapterへ依存しない
- `usecases`は`bootstrap`へ依存しない
- `runtime`は外部SDKへ直接依存しない
- PluginはCore private実装へ依存しない
- Adapter同士は直接依存しない

推奨ブランチ：

```text
refactor/dependency-boundary-tests
```

### 優先度3：環境別override設計

overrideは未実装である。

導入する場合は、単純なdeep mergeを追加しない。次を先に決定する必要がある。

- override対象キー
- 配列の扱い
- 削除表現
- type変更の可否
- source追跡
- secretと通常設定の分離
- base／environment間の参照グラフ検証

設計確定前に実装しない。

### 優先度4：legacy `config/config.yaml`廃止判断

現時点では削除しない。

廃止条件候補：

- 全実行経路が`config/index.yaml`を使用
- emotion appraisalの二重読込が解消
- Render、ローカル、CI、管理画面の運用実績が蓄積
- rollback手順が確立
- legacy明示指定の利用箇所がゼロ
- migration案内と削除時期が合意済み

条件を満たした後、deprecation期間を設けて別PRで判断する。

### 優先度5：Composition Root分割

`app/bootstrap/runtime.py`の機能別Composer分離を進める。

候補：

```text
app/bootstrap/
  core_runtime.py
  llm.py
  memory.py
  speech.py
  topic.py
  plugins.py
  streaming.py
  application.py
```

設定分割が完了したため、各設定ownerとComposerの責務を対応させやすい状態になった。

### 優先度6：AgentLifeService責務分割

話題選択ロジックを先に分離し、その後`AgentLifeService`をFacadeとして段階的に内部委譲へ移す。

候補：

- `AgentStateTransitionService`
- `AgentMemoryRecorder`
- `AgentActivityStateSynchronizer`
- `AutonomousEventPlanner`
- `ProcessedEventTracker`

## 11. 次工程

次に着手する工程は、優先度1のemotion appraisal設定統合とする。

この工程では次を行わない。

- 感情評価ロジックの変更
- 感情パラメータの調整
- override導入
- legacy設定削除
- Composition Root全体分割
- unrelatedなリファクタリング

設定入口の一元化、typed settings統合、二重読込廃止、回帰テスト追加だけを対象とする。
