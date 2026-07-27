# 現行アーキテクチャ監査

## 1. 目的

`develop`を基準に、今後の構造改善を安全に進めるため、コード、設定、依存関係、巨大クラス、Composition Rootの現状を整理する。

本監査は実装変更を行わず、次の実施順序の基準を確定するためのものである。

1. コード・設定・依存関係の現状監査
2. 依存方向テストの追加
3. 話題選択ロジックの分離
4. `AgentLifeService`の責務分割
5. その他の巨大クラス・関数の分割
6. 型付き設定モデルの導入
7. 設定ファイルの分割
8. Composition Rootの整理
9. 依存違反の段階的解消
10. 回帰テストと設計資料更新

## 2. 現状サマリー

### 2.1 全体構造

現在の主要パッケージは次の責務を持つ。

- `app/domain`: 状態、値オブジェクト、ドメインモデル
- `app/ports`: 外部機能との抽象境界
- `app/usecases`: ユースケース
- `app/runtime`: Agentの実行制御、状態更新、Activity管理
- `app/adapters`: LLM、TTS、DB、OBS、YouTube等の具象実装
- `app/plugins`: 機能単位のPlugin
- `app/bootstrap`: 具象実装の生成と接続
- `app/shared`: Plugin契約や共有基盤

方向性自体はポート・アダプタ型に近いが、`runtime`に複数責務が集中し、`bootstrap`と設定ファイルが巨大化している。

### 2.2 既に改善済みの点

- Runtimeには公開拡張口があり、主要なモンキーパッチは解消済み
- 感情評価はService、Validator、Model Adapter、Runtime接続に分離済み
- 設定値は多くがdataclassへ変換済み
- Streaming PluginとCoreの接続はComposition Root内のAdapterで行われている
- Plugin契約とCore内部モデルの変換境界が存在する

## 3. 主要な監査結果

## 3.1 依存方向テスト

### 判定

未対応。

### 根拠

通常の単体テスト・統合テストは多数存在するが、次のようなパッケージ依存規則を機械的に検査する専用テストは確認できていない。

- `domain`が`runtime`、`adapters`、`plugins`、`bootstrap`へ依存しない
- `ports`が具象Adapterへ依存しない
- `usecases`が`bootstrap`へ依存しない
- `runtime`が外部SDKへ直接依存しない
- PluginがCoreのPrivate実装へ依存しない
- Adapter同士が相互依存しない

### 次工程

Python ASTを使用した依存方向テストを追加する。

最初は全面禁止ではなく、既知の例外を明示できるベースライン方式とする。

推奨ブランチ:

```text
refactor/dependency-boundary-tests
```

## 3.2 話題選択・話題継続ロジック

### 判定

未分離。

### 現在の配置

`AgentLifeService`が次を直接担当している。

- 自律発話結果から話題状態を生成
- 興味度、未完了度、疲弊度の算出
- 類似度評価
- 話題の中断、再開、完了
- 継続終了判定
- 再導入要否の評価結果反映
- 最近の自律発話履歴の保持
- 自律発話イベント生成時の話題選択結果付与

`TopicContinuationEvaluator`は存在するが、話題状態の生成・更新・選択・終了判定は`AgentLifeService`側に残っている。

### 問題

- Agent状態更新と話題戦略が密結合
- 話題ロジックだけを独立テストしにくい
- `SequenceMatcher`や固定ヒューリスティックがService内部に埋め込まれている
- 将来の外部トレンド、話題ランキング、話題記憶統合を追加しにくい

### 分離候補

- `AutonomousTopicTracker`
- `AutonomousTopicMetricsEvaluator`
- `AutonomousTopicContinuationPolicy`
- `AutonomousTopicSelectionResult`

最初の分離では挙動を変えず、既存ロジックを移動する。

推奨ブランチ:

```text
refactor/autonomous-topic-selection
```

## 3.3 AgentLifeService

### 判定

分割が必要。

### 規模

約1,100行。

### 現在の責務

1. AgentStateの保持
2. Driveの時間経過更新
3. Emotionの時間経過更新
4. EventによるDrive更新
5. EventによるEmotion更新
6. EventによるRelationship更新
7. 重複Event排除
8. 短期記憶更新
9. エピソード記憶更新
10. 感情履歴更新
11. 関係記憶の永続化
12. Agent記憶の永続化
13. ActivityManagerとの同期
14. 自律発話タイミング判定
15. 会話再開理由判定
16. 話題状態管理
17. 自律発話候補の却下バックオフ
18. State Observer通知

### 分割方針

話題ロジック分離後、次の単位で段階的に分割する。

- `AgentStateTransitionService`
- `AgentMemoryRecorder`
- `AgentActivityStateSynchronizer`
- `AutonomousEventPlanner`
- `ProcessedEventTracker`

既存の公開APIを一度に変更せず、`AgentLifeService`をFacadeとして残しながら内部委譲へ移行する。

## 3.4 その他の巨大クラス・関数

### `app/config/app_config.py`

約1,100行。

責務:

- 全設定dataclass定義
- YAML読込
- 型変換
- デフォルト値
- バリデーション
- 全機能設定の集約

### `app/bootstrap/runtime.py`

多数のAdapter、Plugin、Usecase、Runtimeを一つのモジュールで生成・接続している。

Composition Rootで具象型へ依存すること自体は正しいが、機能別Composerへの分割が必要。

### Streaming Composition

`app/bootstrap/streaming.py`はCoreとPluginを接続する境界として妥当。ただし次の課題がある。

- `Any`の利用が多い
- Repository Factoryの戻り値が`Any`
- `configure_lifecycle_gate`、`configure_comment_moderation`の引数が`Any`
- Runtime状態表示が設定構造を直接参照

## 3.5 型付き設定モデル

### 判定

部分対応済み。

### 実装済み

- `AppConfig`以下、多数のdataclass
- 一部設定の`__post_init__`バリデーション
- YAMLから型付き設定への変換

### 未完了

- `ServiceSettings`が全サービス共通のOptionalフィールド集合
- 設定定義、読込、変換、検証が一ファイルに集中
- `dict[str, ...]`が多く、キー誤りを静的に検出しにくい
- Plugin設定の構造とYAMLキーに不一致の可能性がある
- 機能別設定の独立ロードができない

### 改善候補

- `OpenAIServiceSettings`
- `OllamaServiceSettings`
- `VoiceVoxServiceSettings`
- `YouTubeServiceSettings`
- `ObsServiceSettings`
- `PostgresServiceSettings`

設定モデル分割は、設定ファイル分割より先に実施する。

## 3.6 設定ファイル

### 判定

分割が必要。

現在の`config/config.yaml`は次を一つに保持している。

- アプリ基本設定
- Trace
- 外部サービス
- モデル
- LLM役割
- 音声
- 話題分類
- Memory
- Character
- Input Receiver
- Confirmation
- Streaming
- Plugin

約300行であり、機能追加に伴ってさらに肥大化する。

### 分割候補

```text
config/
  app.yaml
  services.yaml
  models.yaml
  character.yaml
  runtime.yaml
  speech.yaml
  memory.yaml
  streaming.yaml
  plugins.yaml
```

ただし、先に型付き設定モデルと統合ローダーの境界を整理し、互換性を保った段階移行を行う。

## 3.7 Composition Root

### 判定

部分対応済みだが整理が必要。

### 良い点

- 具象Adapter生成が`bootstrap`に集約されている
- PluginとCoreの橋渡しAdapterがComposition Rootに存在する
- Streaming構成が専用モジュールへ一部分離されている

### 問題

- `app/bootstrap/runtime.py`が多数の機能を生成
- Core Runtime、Memory、LLM、TTS、Plugin、Streamingの組立が混在
- 生成関数同士の依存関係を追いにくい
- テスト用構成と本番構成の差し替えが一部`replace()`による設定加工

### 分割候補

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

最終的な`application.py`だけが各Composerを呼び出す。

## 4. 依存違反候補

現時点では確定違反ではなく、依存方向テスト導入前に確認すべき候補である。

1. `runtime`が`shared.contracts.plugins`へ直接依存している箇所
2. `bootstrap/streaming.py`がCoreモデルとPluginモデルを同時に扱う境界
3. `app/config`が全機能の具体設定を一括所有している構造
4. 一部UsecaseとRuntimeの責務重複
5. Plugin公開層からCore内部型への参照有無
6. Adapter間の直接参照有無

これらは依存方向テストで現状を可視化してから段階的に解消する。

## 5. 改訂後の実施順序

1. 本監査資料を完成させる
2. ASTベースの依存方向テストを追加する
3. 話題状態管理と選択ロジックを`AgentLifeService`から分離する
4. `AgentLifeService`をFacade化し、状態遷移・記憶・Activity同期・自律計画へ分割する
5. `app_config.py`と`runtime.py`以外の巨大クラス・関数も抽出する
6. サービス別・機能別の型付き設定モデルへ分割する
7. YAML設定を段階的に分割する
8. Composition Rootを機能別Composerへ分割する
9. 依存方向テストで検出された違反を段階的に解消する
10. 全回帰テストを実行し、設計資料を更新する

## 6. 安全方針

- 各段階で挙動変更と構造変更を混在させない
- 既存の公開APIを維持し、内部委譲から始める
- 1ブランチ1目的を原則とする
- 各分割前に既存挙動を固定するテストを追加する
- 依存方向テストは最初から完全禁止にせず、既知例外を明示して徐々に減らす
- 設定ファイル分割時は旧`config.yaml`の互換読込期間を設ける

## 7. 設定スキーマ補完後の境界

複数YAML化に先立ち、単一`config/config.yaml`の構造を維持したまま次を整理した。

- `ServiceSettings`の全Optionalフィールド集合を廃止し、`type`ごとのfrozen
  dataclassへ分離した
- YAML読込時に未知service type、不要キー、必須キー不足、型・範囲不正を拒否する
- 全`models.*.service`と、有効な機能が参照するmodel/serviceを`AppConfig`生成時に
  一括検証する
- StreamingとPlugin設定では、文字列から数値・booleanへの暗黙変換を行わない
- 型付きCore領域の未知キーを完全なYAML path付きの設定エラーにする
- Games固有設定型とparserは`app/plugins/games/settings.py`が所有し、Coreの
  Composition Rootは型付き設定をPluginへ渡すだけとした
- `plugins.registry`は動的ロードへ未接続の予約領域であり、非空ならwarningを出す
- 未知Pluginの設定mappingはCoreが内部キーを検証しないopaque領域として保持する
- loaderが生成するservices、models、voice profile、ranking weights、Plugin mappingと、
  Characterのlist設定をimmutable化した

### disabled時の参照検証

`models.<key>.service`は、model定義自体の整合性として常に検証する。
一方、`speech.enabled=false`、`memory.topic_memory.enabled=false`、
`plugins.games.enabled=false`、`response_generator.type=dummy`の場合は、その機能だけが
必要とするmodel/service参照を要求しない。無効化によって外部サービス設定が不要になる
既存挙動を維持するためである。

### 予約・deprecated設定

`input_receivers`は型・strict validationを維持するが、現在の入力receiver選択は
`YURA_WEB_CONVERSATION_ENABLED`などの起動時環境変数を使用する。入力システム全体の
再設計を避けるため、本工程では予約設定として明記し、実行経路への接続は後続課題とする。

`emotion_appraisal`は標準`app.__main__`のComposition Rootには接続されていない。
`app/bootstrap/emotion_runtime.py`だけが同一YAMLを再読込する互換経路であり、
`load_emotion_appraisal_settings()`はdeprecated warningを出す。複数設定ローダー導入時に
`AppConfig`へ統合し、二重読込を廃止する。

### 次工程

今回、`config/config.yaml`の分割、キー移動、manifest/import、設定パス環境変数、
相対パス基準の変更は行っていない。次工程では単一ファイル互換を維持する統合ローダーを
追加し、トップレベルキー単位の重複拒否とsource情報を備えた上で段階的にYAMLを分割する。

## 8. 複数YAMLローダー導入後の設定入口

型変換より前段に`app/config/config_loader.py`を追加した。`load_raw_config(path)`は従来どおり
単一のYAML mappingだけを読む低レベル関数であり、manifest解決は行わない。
`load_app_config()`は`load_config_bundle()`を経由し、次の順でroot設定入口を決定する。

1. `load_app_config(path)`の明示引数
2. 空白除去後に空でない`AI_LIVER_CONFIG_PATH`
3. 従来の`config/config.yaml`

相対的な入口pathは現在の作業ディレクトリ基準で解決する。入口がdirectoryなら、その直下の
`index.yaml`だけをmanifestとして読む。directory内のYAML自動走査は行わず、
`index.yaml`がない、通常設定である、またはfileでない場合は設定エラーとする。
明示的な空文字列pathは誤指定として拒否し、環境変数の空文字列は未指定として扱う。

### 単一設定とmanifestの判定

fileのroot mappingに`imports`がなければ従来の単一設定として扱う。ただし、
`index.yaml`という名前のfileはmanifest専用とし、`imports`を必須とする。
`imports`があればmanifestとして扱い、manifestのトップレベルには`imports`以外を
許可しない。通常設定キーとの混在はownershipを曖昧にするため拒否する。

manifestは次のようにトップレベルキーごとの所有fileを宣言する。

```yaml
imports:
  app: runtime.yaml
  trace: runtime.yaml
  services: services.yaml
```

import値は空でない文字列pathに限定する。相対importはmanifest自身のdirectory基準、
絶対importはそのまま解決する。project root外のimportとsymlinkは一律禁止せず、
`Path.resolve()`後の実体pathを同一file判定に使う。

### ownership、重複、循環

同じfileを複数キーのownerに指定できるが、そのfileのトップレベルキー集合はmanifestで
そのfileへ割り当てた集合と完全一致しなければならない。未割当キーの暗黙混入、指定キーの
欠落、YAML mapping内の重複キー、複数ownerによる重複はすべて拒否し、deep merge、
前勝ち、後勝ちは実装しない。同じ実体fileはローカルキャッシュから一度だけ読む。

import先の`imports`、manifest自身へのimport、symlinkや相対path正規化後にmanifest自身と
なるimportを拒否する。nested importsはownershipとsource追跡を単純に保つため未実装であり、
将来対応する場合も循環グラフ検証と併せて設計する。

現行`AppConfig`の必須トップレベルキーはmanifest統合時点で割当を検証する。
`plugins`と`streaming`は任意である。`emotion_appraisal`は独立再読込のdeprecated経路に
残り、`AppConfig`の公開fieldではないため、曖昧に無視せずmanifest import対象外として
明示的に拒否する。単一設定内の互換キーとしては引き続き受理する。

### source追跡とconfig_path

`ConfigSourceBundle`は統合済みraw mapping、root入口の絶対path、トップレベルキーから
実際のowner fileへの読み取り専用source mapを保持する。manifest構文と割当のエラーは
manifestをsourceとし、import先のYAML・ownershipエラーはimport先fileをsourceとする。
型・範囲・参照グラフのエラーは、エラーpathのトップレベルキーからownerを引き、
たとえば`speech.service`なら`speech.yaml`を`ConfigError.source_file`へ設定する。

`AppConfig.config_path`は単一file、manifest file、またはdirectory指定時に解決した
`index.yaml`という「ユーザーまたは環境が指定したroot設定入口」の絶対pathを表す。
import先fileには置き換えないため、Streaming Adminなど既存表示側の意味も維持される。

### 互換範囲と次工程

`config/config.yaml`、既存Factory、Composition Root、`AppConfig`の公開fieldは変更して
いない。ログ、辞書、memory、run-of-showなど設定値中の相対path解決規則も変更しておらず、
import元file基準への切替は行わない。環境別override、Plugin別YAML移行、deep merge、
単一設定互換の廃止はいずれも未決定・未実装である。

次工程では、このloaderを利用してまずruntime領域とcharacter領域の本番設定を段階的に
分割する。移行中はlegacy単一設定との等価性をテストし、単一`config.yaml`廃止の可否は
運用実績を確認してから別途決定する。
