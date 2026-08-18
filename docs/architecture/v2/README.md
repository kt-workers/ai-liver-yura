# V2 Architecture Canonical Index

- `system_architecture.md` — system-wide canonical architecture
- `brain_architecture.md` — Brain modules and authority
- `cognitive_llm_architecture.md` — cognitive and LLM role design
- `goal_commitment_architecture.md` — persistent Goal / Commitment state and lifecycle
- `concurrency_architecture.md` — non-blocking runtime / LLM invocation topology
- `runtime_kernel_contracts.md` — bounded queue / scheduler / cancellation / lifecycle contracts
- `runtime_lifecycle_contracts.md` — degraded operation / availability / retry / graceful shutdown contracts
- `llm_role_contracts.md` — variable logical LLM role / structured request-result contracts
- `llm_provider_adapter_contracts.md` — provider SDK boundary / model policy resolution / typed failure normalization
- `input_gateway_contracts.md` — multimodal input normalization / session / touch boundary
- `input_meaning_contracts.md` — natural-language typed meaning / reference / commit boundary
- `appraisal_internal_state_contracts.md` — subjective appraisal candidate / causal state reducer
- `executive_appraisal_facts_contracts.md` — Appraisal facts snapshot / Executive freshness boundary
- `executive_authority_contracts.md` — Executive Goal・Action Authority / typed decision commit gate
- `goal_commitment_state_contracts.md` — persistent Goal・Commitment State / atomic lifecycle reducer
- `activity_execution_contracts.md` — Activity admission / Capability preflight / Actual Execution Fact authority
- `speech_semantics_contracts.md` — What-to-say Authority / typed SpeechSemanticPlan / simple・complex commit gate
- `character_language_contracts.md` — #330 SpeechSemanticPlan→CharacterUtterance How-to-say realization / live freshness / #363 boundary contracts
- `character_projection_contracts.md` — Human-readable Character Definition / structured document / typed Runtime Profile projection contracts
- `character_psychological_projection_contracts.md` — Character精神構造Layers 1–6 / causal refs / dynamic Layer 7 boundary
- `speech_pipeline_architecture.md` — speech preparation/presentation concurrency
- `body_architecture.md` — canonical body, generative motion, realtime control
- `body_expression_contracts.md` — #337 Internal State / Focus / Character Style→normalized BodyExpressionContext projection contracts
- `plugin_architecture.md` — Core extension / capability architecture
- `plugin_registry_contracts.md` — #343 Plugin manifest / Registry lifecycle / permission / health / CapabilityDescriptor projection contracts
- `plugin_registry_permission_principal_contracts.md` — #343 Plugin permission grant principal isolation / revocation security contracts
- `subsystem_architecture.md` — Streaming, Game Skill, Avatar and specialized AI boundaries
- `legacy_migration_matrix.md` — V1 requirement migration
- `project_sync_manifest.md` — GitHub Project synchronization manifest
- `project_sync_runbook.md` — live ID取得・dry-run・Project fields・formal Parent/Sub-issue同期手順

Status: Draft / V2 Design Gate.
