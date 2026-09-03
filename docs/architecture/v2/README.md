# V2アーキテクチャ正本索引

## 設計完了・製造順

- `system_architecture.md` — システム全体の正本アーキテクチャ
- `foundation_contracts.md` — #321 Event / Revision / Authority / Capability / ExecutionResult等の共有typed Foundation契約
- `design_completion_matrix.md` — #445 全V2詳細設計の完了状態とD10後の製造起点統合Gate
- `design_cross_audit_report.md` — D8 正本性・依存関係・真実境界・revision・並行性・作業系列の横断監査
- `design_implementation_decidability_audit.md` — #445 D10 実装決定可能性・計画Coverage・Post-D10監査順序の正本
- `production_plan_current.md` — #550 Post-D10 GitHub live監査後のcurrent production execution plan
- `production_sequence_authority.md` — D10で保存したoriginal sequence baseline。Post-D10 current execution順の単独Authorityではない
- `project_sync_manifest.md` — 初期V2工程・Project #6同期を記録した履歴資料。current Project/日程Authorityではない
- `project_sync_runbook.md` — live ID取得、dry-run、Project field、正式Parent/Sub-issue同期手順
- `legacy_migration_matrix.md` — V1要件・failure knowledgeのV2移行表

## Brain / Foundation / Character

- `brain_architecture.md` — Brainのモジュール構成と正本責務
- `brain_integration_contracts.md` — #334 Brainの非直列構成、trigger、revision、並行統合契約
- `cognitive_llm_architecture.md` — 認知処理とLLM役割の設計
- `goal_commitment_architecture.md` — 永続Goal / Commitment状態とライフサイクル
- `concurrency_architecture.md` — 非停止実行系とLLM呼出し構成
- `runtime_kernel_contracts.md` — 上限付きqueue、scheduler、cancellation、lifecycle契約
- `runtime_lifecycle_contracts.md` — 縮退運転、可用性、再試行、安全停止契約
- `runtime_operational_numeric_contracts.md` — #322/#350 queue/concurrency、cancel grace、retry/backoff、diagnostic rate limit、shutdown grace数値契約
- `snapshot_consistency_contracts.md` — multi-owner snapshotの上限付き安定読取とfail-closed規則
- `llm_role_contracts.md` — 可変論理LLM役割と構造化要求・結果契約
- `llm_execution_numeric_contracts.md` — #323/#357 timeout、attempt、token、temperature、retry数値契約
- `llm_provider_adapter_contracts.md` — LLM提供元SDK境界、model方針解決、型付き失敗正規化
- `llm_provider_operational_diagnostics_contracts.md` — #437 提供元運用失敗の安全な分類、再試行の真実境界、可観測性
- `../../character/v2/yura_character_bible.md` — 星波ゆらの人物設定正本
- `character_projection_contracts.md` — 人間可読Character Definitionから型付きRuntime Profileへの投影契約
- `character_psychological_projection_contracts.md` — Character精神構造Layers 1–6、因果参照、動的Layer 7境界
- `brain_operational_bounds_contracts.md` — Brain/Speech context・output・evidenceの共通容量・overflow契約

## Input / Appraisal / Executive / Goal / Activity / Attention

- `input_gateway_contracts.md` — 複数入力形式の正規化、session、touch境界
- `input_meaning_contracts.md` — 自然言語の型付き意味、参照、versioned acceptance policy、確定境界
- `appraisal_internal_state_contracts.md` — 主観評価候補と因果状態reducer
- `appraisal_decay_numeric_contracts.md` — #327 half-life decay式、rule選択、missing policy、freshness数値契約
- `executive_appraisal_facts_contracts.md` — 評価事実snapshotとExecutive鮮度境界
- `executive_authority_contracts.md` — Executive Goal・Action正本と型付き決定確定判定
- `goal_commitment_state_contracts.md` — 永続Goal・Commitment状態と原子的ライフサイクルreducer
- `goal_planning_contracts.md` — #361 active Goalから依存グラフ型ActivityPlanへの計画Authority契約
- `activity_execution_contracts.md` — Activity受付、Capability事前確認、実行事実の正本
- `attention_turn_contracts.md` — #333 Focus / Turn / response obligation、bounded source scheduling、fairness契約
- `attention_source_owner_lifecycle_contracts.md` — #333 source owner/lifecycle、refresh/resolve/expiry境界
- `attention_turn_contracts_amendment_2026-08-16.md` — #333 live freshness・claim等の補足正本

## Speech

- `speech_semantics_contracts.md` — 発話内容Authority、型付き`SpeechSemanticPlan`、単純・複雑確定判定
- `character_language_contracts.md` — #330 言い方、`CharacterUtterance`、正本性と鮮度契約
- `character_language_provider_contracts.md` — #330 本番Character Language役割と提供元schema境界
- `character_language_variation_contracts.md` — #330 上限付き過去実現参照と意味を壊さないvariation
- `character_language_semantic_repair_contracts.md` — #330 同一Planに対する意味安全な再生成入力契約
- `semantic_verification_contracts.md` — #363 独立意味観測と閉じた受け入れ契約
- `semantic_verification_observer_strategy.md` — #363 Plan非参照在庫観測とPlan関係観測の構成
- `semantic_verification_relation_edge_contract.md` — #363 関係edgeと証拠再調整の詳細
- `semantic_verification_self_disclosure_relation_contract.md` — #363 自己開示の関係境界
- `semantic_verification_speech_act_contract.md` — #363 発話行為の観測・受け入れ境界
- `semantic_verification_transport_identity_contract.md` — #363/#438 提供元通信identityの結び付け
- `speech_performance_contracts.md` — #331 `CharacterUtterance`＋Voice Style＋Expressionからengine非依存`SpeechPerformancePlan`への変換
- `speech_expression_projection_contracts.md` — #331 Character Voice Style / Internal StateからSpeech Expressionへの投影方針
- `speech_pipeline_architecture.md` — 発話準備と提示の並行処理
- `speech_runtime_presentation_contracts.md` — #348 準備、修復、queue、再検証、提示確定
- `speech_operational_numeric_contracts.md` — #348/#358 queue、expiry、repair、speculative TTS、Provider値変換の数値契約
- `tts_provider_contracts.md` — #358 TTS音声結び付け、提供元対応、音声成果物、時刻、縮退

## Memory / Persistence

- `memory_store_retrieval_contracts.md` — #332 Memory Store正本、再調整、矛盾、上限付き検索
- `memory_reflection_contracts.md` — #364 上限付き情報源証拠、候補提案、支持観測、Reflection受理
- `memory_operational_numeric_contracts.md` — #332/#364 ranking、recency、token budget、Reflection件数の数値契約
- `persistence_repository_contracts.md` — #359 Memory repository、restart-safe snapshot、migration、rehydration基盤

## Body

- `body_architecture.md` — Body正本、生成的動作、実時間制御
- `body_expression_contracts.md` — #337 Internal State / Focus / Character Styleから正規化`BodyExpressionContext`への投影契約
- `body_expression_projection_policy.md` — Yura confirmed Body Styleとdynamic stateを正規化Body Expression軸へ写すproduction policy
- `body_motion_planning_contracts.md` — #338 Executive BODY意図からsolver安全な高水準`BodyMotionPlan`への変換
- `body_solver_controller_contracts.md` — #339 IK/FK、制限、平衡、軌道、連続`BodyState`確定正本
- `body_physical_numeric_contracts.md` — #336/#338/#339 scalar DOF、target geometry、extent、CoM/contact、dynamic limit、solver数値policy
- `body_trajectory_timing_contracts.md` — #339 relative duration weightから実秒trajectoryへの決定論的time-scaling
- `body_realtime_layers_contracts.md` — #340 視線、瞬き、呼吸、viseme、微細な実時間重ね合わせ契約
- `body_realtime_numeric_contracts.md` — #340 gaze/blink/breath/articulation/subtle motionの更新式・rate/frame bound
- `body_integration_contracts.md` — #341 Executive BodyIntentから連続`BodyPoseFrame`への統合、並行性、縮退

## Plugin / Infrastructure / Subsystems

- `plugin_architecture.md` — Core拡張とCapabilityのアーキテクチャ
- `plugin_registry_contracts.md` — #343 Plugin manifest、Registry lifecycle、権限、健全性、Capability投影契約
- `plugin_registry_permission_principal_contracts.md` — #343 Plugin権限付与主体の分離と失効の安全契約
- `plugin_integration_contracts.md` — #344 Plugin 0件、Capability実行、effect fence、世代統合契約
- `subsystem_architecture.md` — Streaming、Game Skill、Avatar、専用AIの境界
- `avatar_presentation_contracts.md` — #346 正本`BodyPoseFrame`からStick / Live2D / 3D rendererへの投影と縮退
- `avatar_binding_numeric_contracts.md` — #346 canonical Body座標・回転・channelからrenderer値への数値変換
- `streaming_subsystem_contracts.md` — #347/#394/#396 Core Decision、Streaming実行、外部観測、comment取込契約
- `game_skill_runtime_contracts.md` — #365 高水準Core Goalと実時間game認識・戦術・action・runtime契約
- `subsystem_realtime_numeric_contracts.md` — #347/#365 Streaming window/backpressure、Game tick/deadline/no-catch-up数値契約
- `gui_admin_contracts.md` — #351 不変Read Model、型付き管理Command、秘密情報を守るGUI境界
- `validation_lab_contracts.md` — #352 本番経路Validation Harness、出自、timeline、人間文脈、Export
- `development_tooling_contracts.md` — #353 読取専用の開発証拠、可視化、参照解析、安全境界
- `external_surface_operational_numeric_contracts.md` — #344/#351/#352/#353/#359/#360 Plugin/GUI/Lab/Tooling/Persistence/Systemの容量・timeout・machine SLO数値契約
- `system_integration_contracts.md` — #360 段階的構成、縮退起動、系統間遅延、System Verification契約

## 現在状態

D1〜D9は2026-08-23にPASS。D10は2026-08-31に実装決定可能性・データ十分性・計画Coverageの再監査を完了しPASSし、PR #502で`rebuild/v2-foundation`へ統合済み。

#549でV1 blocking contamination 0を確認した後、#550でD10が要求したOpen/Closed全V2 Issue・PR・branch・Human VerificationのPost-D10 state reconciliationを実施した。current execution順は`production_plan_current.md`を参照する。

`project_sync_manifest.md`のProject #6情報は履歴資料でありcurrent Authorityではない。current Project日程AuthorityはProject #7 `プロジェクトゆらv2`。Project #6は変更しない。
