# 旧Body PR 移植分類台帳 v1.0.0

## 1. 目的

旧Body PR #159・#160・#163の変更を、最新`develop`のEmotion因果設計と責務境界へ合わせて再統合するため、変更を次の4区分へ分類する。

| 区分 | 意味 |
|---|---|
| `adopt` | 責務と依存方向が適切で、軽微な名前・import調整だけで再利用できる |
| `adapt` | 目的と主要ロジックは再利用するが、最新因果契約または責務分離へ合わせて修正する |
| `replace` | 目的は必要だが、肥大化・依存逆転・方針不一致のため構造を作り直す |
| `discard` | 最新実装と重複するか、現在の方針では不要な経路 |

旧PRをマージしてから整理するのではなく、本台帳に従って責務単位で最新`develop`へ移植する。

## 2. 正規の依存方向

```text
Core心理状態・Activity結果
  → Interaction Intention
  → Interaction Expression Projection
  → Body Activity Context
  → Body Affect / Attention / Speech Inputs
  → Continuous Pose Controller
  → BodyPoseFrame
  → Output Port
  → HTTP / WebSocket Adapter
  → Stick Mock / Live2D / 3D Adapter
```

逆向きの依存を禁止する。

- GUIはBody判断を行わない
- TransportはPoseを生成しない
- ControllerはHTTP・SSE・Live2D固有Parameterを知らない
- BodyはEmotion・Motivation・Activityを決定しない
- 身体指示は通常表現へ重ねる一時制約であり、Bodyの主原因ではない

## 3. PR #159 分類

### 3.1 Domain・Port

| 対象 | 分類 | 理由・移植方針 |
|---|---|---|
| `app/domain/body_pose_frame.py` | `adapt` | モデル非依存契約は採用する。ただし数学プリミティブ、骨格、BlendShape、注意候補、内的運動状態、2D補助投影、Frameが1ファイルに集中しているため分割する |
| `app/ports/body_pose_output.py` | `adopt` | 小さなProtocolで単一責務。TransportのBackpressure方針を実装へ強制しすぎない範囲で採用する |
| `app/domain/body_speech.py` | `adapt` | SpeechとBody時計の同期契約として再利用する。TTS・Character・Pose制御を同じ型へ混ぜない |
| `app/domain/avatar_performance.py` | `adapt` | 既存Compatibility契約として維持する。連続Frameの主契約にはしない |
| `app/domain/character/*` | `discard` | Body再統合と直接関係しないCharacter Profile変更は別責務。必要差分は独立タスクで扱う |

### 3.2 Pose生成・Controller

| 対象 | 分類 | 理由・移植方針 |
|---|---|---|
| `app/runtime/procedural_body_controller.py` | `replace` | 注意選択、確率過程、呼吸、瞬き、身体指示、物理積分、Frame生成が1クラスへ集中。サブシステムへ分割して再実装する |
| `app/runtime/body_pose_3d_projector.py` | `adapt` | Canonical 2D補助軸から3D骨格へ投影する純粋変換は再利用可能。Controller状態を持たせず独立Projectorに限定する |
| `app/runtime/living_body_runtime.py` | `adapt` | Tick Loopと入力Snapshot取得、Frame公開だけを担う薄いRuntimeへ再構成する |
| `app/runtime/body_pose_lab_controller.py` | `replace` | Lab用状態管理と本番Controllerロジックを分離する。Labは本番の公開Portを呼ぶHarnessに限定する |
| `app/runtime/conversational_body_expression_planner.py` | `replace` | 会話意図の独自判断はPhase 5の`InteractionExpressionProjector`と重複。発話時間に伴うBody入力生成だけを独立サービスとして作り直す |

`ProceduralBodyController`は次へ分割する。

```text
BodyAttentionSelector
BodyAmbientMotionGenerator
BodyBreathingOscillator
BodyBlinkScheduler
BodyExternalConstraintPlayer
BodyPoseTargetComposer
BodyPoseIntegrator
BodyPoseFrameAssembler
```

各クラスは独立した状態と単体テストを持つ。薄いControllerが呼び出し順だけを管理する。

### 3.3 入力・身体指示

| 対象 | 分類 | 理由・移植方針 |
|---|---|---|
| `avatar_body_command_normalizer.py` | `adapt` | 身体指示を一時制約へ正規化する入口として再利用。主Motion選択器にはしない |
| `avatar_body_command_action_planner.py` | `replace` | ActivityやBodyの主計画を作らず、検証済み一時制約DTOへ変換する責務へ縮小する |
| `body_spatial_command_resolver.py` | `adapt` | 左右・上下・部位の意味解決は再利用する。Raw text再解釈ではなくStructuredInputMeaningを優先する |
| `cognitive_direction_parsers.py` | `adapt` | 汎用方向値の純粋Parserとして分離する |
| `cognitive_direction_services.py` | `adapt` | Perception・Meaning層へ配置し、Body Runtime固有依存を除く |
| `spatial_input_meaning_normalizer.py` | `adapt` | 入力意味の正規化責務として維持。Body Controllerから参照しない |
| `avatar_aware_internal_directive_normalizer.py` | `discard` | Internal DirectiveからBody主命令を作る経路は廃止。必要な実行制約はActivity検証側で扱う |
| `avatar_performance_action_planner.py` | `adapt` | Compatibility Performance出力として限定。連続Poseの原因にはしない |

### 3.4 Lifecycle・Bootstrap

| 対象 | 分類 | 理由・移植方針 |
|---|---|---|
| `runtime_host_controller.py` | `adapt` | Thread終了待ちとPlugin shutdown順の改善を独立移植する。Body固有ロジックを入れない |
| `console_input_receiver.py` | `adapt` | macOS／Unixでの`loop.add_reader()`化は入力Adapterの独立修正として扱う |
| `body_runtime_setup.py` | `replace` | 旧機能を足すと設定解析、Port生成、Controller選択、Runtime生成、bindが集中する。Settings Loader・Output Factory・Runtime Factoryへ分割する |

### 3.5 Adapter・GUI

| 対象 | 分類 | 理由・移植方針 |
|---|---|---|
| `http_avatar_output.py` | `adapt` | Compatibility Performance Adapterとして維持。BodyPoseFrame Transportと分離する |
| `avatar_performance_character_prompt_builder.py` | `discard` | CharacterへBody動作選択を要求する経路は主因果から外す。高レベルExpression Intentionのみを扱う |
| `gui/yura-body-pose-lab/*` | `adapt` | Controllerの単体検証Harnessとして再利用。本番判断をGUI側へ複製しない |
| `gui/yura-avatar-runtime-lab/*` | `discard` | Body再統合と無関係な画面修正を混ぜない。必要なUI修正は別PRへ分離する |
| `render.yaml` | `adapt` | Labを残す場合のみサービス定義を追加する。Core実装PRとデプロイ設定を分離可能か確認する |

## 4. PR #160 分類

### 4.1 Transport・Runtime

| 対象 | 分類 | 理由・移植方針 |
|---|---|---|
| `http_body_pose_output.py` | `adopt` | Queueサイズ1、latest-frame-wins、I/Oを別Taskで実行する責務が明確。Configと送信Workerを将来分割できる構造を維持する |
| `core_body_pose_runtime.py` | `replace` | Activity、身体命令、Controller、Outputを同時に扱う旧Runtimeは使わず、入力SnapshotとTick・PublishだけのRuntimeへ統合する |
| `core_command_body_controller.py` | `replace` | 身体命令中心のControllerは最新方針と不一致。一時制約Playerへ必要な軌道だけ移植する |
| `body_runtime_setup.py` | `replace` | PR #159と同じComposition Root分割方針を適用する |

### 4.2 参照解決

| 対象 | 分類 | 理由・移植方針 |
|---|---|---|
| `contextual_reference_resolver.py` | `adapt` | Body専用キャッシュを使わない汎用方針は採用。ただしDTO、repeat判定、明示参照、履歴収集、候補生成、採点が1ファイルへ集中しているため分割する |

分割先:

```text
ResolvedContextualReference        domain DTO
ContextualReferenceRequestDetector repeat等の参照要求判定
ExplicitReferenceResolver          StructuredInputMeaning.references解決
ConversationHistoryCollector       履歴位置の収集・重複排除
ReferenceCandidateFactory          履歴Turnから候補生成
ReferenceCandidateRanker           実行結果・構造化意味による採点
ContextualReferenceResolver        上記を束ねる薄いFacade
```

Body以外の再説明・Activity再開にも利用できるCoreサービスとして配置する。

### 4.3 身体指示

| 対象 | 分類 | 理由・移植方針 |
|---|---|---|
| `avatar_body_command_normalizer.py` | `adapt` | PR #159と同じ一時制約入口へ統合する |
| `avatar_body_command_action_planner.py` | `replace` | 実行権限を持たないConstraint Request生成へ縮小する |
| `body_spatial_command_resolver.py` | `adapt` | 純粋な空間・部位解決器として利用する |
| `body_speech.py` | `adapt` | Speech時計契約へ統合する |

### 4.4 棒人形モック

| 対象 | 分類 | 理由・移植方針 |
|---|---|---|
| `gui/yura-core-stick-mock/server.py` | `adopt` | 表示専用という責務境界を守っている。機能追加時はFrame Hub、HTTP/SSE API、起動処理へ分割する |
| `gui/yura-core-stick-mock/web/*` | `adapt` | Canonical Frame表示を再利用。判断・補間・Emotion解釈をブラウザへ追加しない |
| `body-pose-skeleton.js` | `adapt` | 棒人形描画の共有部品として再利用し、画面状態管理から分離する |

## 5. PR #163 分類

### 5.1 Domain・Context

| 対象 | 分類 | 理由・移植方針 |
|---|---|---|
| `app/domain/body.py` | `discard` | Phase 5で最新`develop`へInteraction Intention対応が統合済み。旧差分を再適用しない |
| `body_activity_context_builder.py` | `discard` | 工程1で最新`develop`上のBuilderをすでに責務分離したため、旧実装は使用しない |

### 5.2 State-driven Body

| 対象 | 分類 | 理由・移植方針 |
|---|---|---|
| `state_driven_body_controller.py` | `replace` | 約400行で時間管理、Emotion基礎表情、Character表情解決、envelope、姿勢、発話口形、BlendShape、3D射影が集中。分割後にロジック単位で移植する |
| `state_driven_body_pose_runtime.py` | `adapt` | Activity Context、Expression Request、Speech入力、Tickを束ねる薄いRuntimeへ縮小する |
| `http_body_pose_output.py` | `adopt` | PR #160と同一系統。1つの正本だけを採用する |
| `body_runtime_setup.py` | `replace` | Factory分割後のComposition Rootへ再実装する |

旧`state_driven_body_controller.py`の分割先:

```text
BodyAffectBaselineProjector
BodyFacialExpressionResolver
BodyExpressionEnvelope
BodyPoseExpressionComposer
BodySpeechMouthDriver
BodyBlendShapeMerger
BodyPose3DProjector
StateDrivenBodyController  # 薄いオーケストレーター
```

`Emotion`と`Drive`を互いに独立したBody命令として扱わず、Emotion由来の状態と採用済みExpression Intentionを入力Snapshotへまとめる。

### 5.3 GUI・Tests

| 対象 | 分類 | 理由・移植方針 |
|---|---|---|
| `gui/yura-core-stick-mock/*` | `adapt` | PR #160版との差分を比較し、表示機能だけを最新化する |
| `tests/test_state_driven_living_body.py` | `adapt` | 期待する意味・連続性は再利用し、分割した各責務へテストを配分する |
| `tests/test_state_driven_stick_mock_contract.py` | `adopt` | 表示専用境界の契約テストとして再利用可能 |
| `tests/test_body_runtime_application_wiring.py` | `adapt` | Factory分割後のComposition Root契約へ書き換える |

## 6. テスト移植方針

旧テストはファイル単位でコピーせず、保証している振る舞いを責務へ配分する。

| 保証内容 | 移植先 |
|---|---|
| Quaternion正規化・有限値・重複ID拒否 | BodyPoseFrame Domain tests |
| Attention候補選択 | BodyAttentionSelector tests |
| 呼吸・瞬き・微動 | Ambient Motion component tests |
| 現在姿勢からの連続復帰 | BodyPoseIntegrator tests |
| 身体指示の一時制約 | BodyExternalConstraintPlayer tests |
| 発話中の口形 | BodySpeechMouthDriver tests |
| Emotion／Expressionから顔・姿勢 | Affect Projector / Composer tests |
| latest-frame-wins | Transport tests |
| Runtime停止順 | Lifecycle tests |
| 棒人形が表示専用 | Stick Mock contract tests |
| 「もう一回」の参照解決 | Contextual Reference component tests |

## 7. 移植順

依存関係に従い、次の順で実装する。

1. Runtime停止・Lifecycleの独立修正
2. BodyPoseFrameのDomain契約分割
3. Output PortとHTTP latest-frame-wins Adapter
4. Body入力Snapshot契約
5. Affect／ExpressionのProjector群
6. Attention・呼吸・瞬き・一時制約の部品
7. Pose Target ComposerとIntegrator
8. 薄いState-driven Controller
9. 薄いBody RuntimeとFactory群
10. 棒人形・Body Pose Lab
11. 汎用参照解決の分割移植
12. 旧PRの閉鎖

参照解決はBodyPoseの必須依存ではないため、Body基礎動作の後に独立して移植できる。

## 8. 責務肥大化の停止条件

次の状態になった時点で、その工程内で分割してから進む。

- Domain契約ファイルが数学型、心理状態、Transport Payloadを同時に持つ
- Controllerが3種類以上の時間発展状態を直接保持する
- Runtimeが入力解釈またはPose計算を始める
- Adapterが再試行方針以外のBody判断を持つ
- GUIが欠落値をEmotionやIntentから再推定する
- 1つのテストが複数責務の内部実装を同時に準備しないと成立しない

## 9. 結論

そのまま採用できる中心部品は、Output Port、latest-frame-wins HTTP Adapter、棒人形の表示専用境界である。

BodyPoseFrame、参照解決、連続Controller、State-driven Controller、Runtime配線は目的を維持しつつ責務分離して再構築する。

CharacterまたはInternal DirectiveからBody主命令を直接生成する旧経路は移植しない。
