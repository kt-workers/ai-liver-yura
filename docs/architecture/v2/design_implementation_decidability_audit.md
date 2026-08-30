# V2 実装決定可能性 再監査

Owner: #445
Root: #317
Status: **D10 PASS — 2026-08-31**
Current sequence authority: `production_sequence_authority.md`
Historical sequence source: `project_sync_manifest.md`

## 1. 目的

V2 Design Completion GateはD1〜D9を一度PASSしたが、#339の製造再開時に、canonicalだけでは実装者が追加判断しなければ製造できない箇所が見つかった。

D10では「設計書が存在する」ことではなく、**実装担当が重要な意味・Authority・数値変換・failure・freshness・lifecycle・依存順を発明せず、正本どおりに製造できること**を設計完了条件とした。

2026-08-31時点で、計画済みV2 Work / Integrationのcanonicalをこの観点で再監査し、発見したblocking design gapを正本へ補完した。D10の設計上のblocking gapは0件とする。

## 2. 製造順Authority

current V2製造順Authorityは `production_sequence_authority.md` とする。

- 同書は2026-08-13 `project_sync_manifest.md` の`工程`を元工程として保持する。
- `project_sync_manifest.md`はProject #6、旧Status、旧Start/Targetを含む履歴資料であり、current Project stateのAuthorityではない。
- current Project管理先はProject #7 `プロジェクトゆらv2`。
- 工程番号が小さいWorkを先に扱う。
- Parentは子Work/Integrationの完成管理であり、Parent自身へ重複実装しない。
- Integrationは直接依存WorkのUnit/Adjacent完了後に行う。
- 日付から工程を逆算しない。
- Project #7 Start date / Target date刷新は、D10後の全Issue状態監査・current工程確定後に行う。
- Project #6を変更しない。

## 3. 後発Taskの取り込み規則

元工程作成後に必要性が判明した機能・Bug・設計補修・Verificationを取りこぼさない。

1. 既存Workの未完了責務/owner amendmentか、独立した新責務かを判定する。
2. 既存Workの完了条件に含まれるならowner Workへ回収する。
3. 独立責務なら既存Issueを優先して再利用し、同義Issueを重複作成しない。必要な場合だけ新Issue化する。
4. direct dependency、Priority、Issue level、Area、検証境界を確定する。
5. 元工程を破棄せず、依存関係上の正しい位置へ工程を挿入する。
6. Post-D10全Issue監査でstateとcurrent工程を確定する。
7. その後Project #7の日程を再計画する。
8. 下流Integration/System Verificationのcompletion pathへ反映する。

## 4. D10監査Dimension

### 4.1 実装決定可能性

- 型だけでなく値の意味が一意。
- 正規化値から物理量・Provider量への変換Authorityと規則が明示される。
- quaternion / scalar DOF / 座標frame等の数学表現に逆変換の曖昧さを残さない。
- tolerance、iteration budget、epsilon、completion判定、threshold、retry/backoff、grace等を実装者が任意選択しない。
- ID/ref/自由文から意味や座標、policyを推測しない。
- `bounded` / `configurable` / `policy`だけを書き、値域・単位・missing時挙動を実装へ丸投げしない。

### 4.2 Data sufficiency

- canonicalが要求する計算に必要な入力値がschemaに存在する。
- provenance / revision / generation / fingerprintが必要な境界に存在する。
- balance / contact / timing / threshold / retry等に必要な情報が存在する。
- versioned policy identity/revisionが必要なasync freshness境界へbindされる。

### 4.3 Completion-state consistency

D10ではIssue stateそのものを正しいと仮定しない。

- 部分実装をWork全体完了へ昇格しない。
- Integrationを未完了upstreamより先に完了扱いしない。
- Parent / Integration / Managementのcompletionを実証拠から判定できる。

**Open/Closed全件の実state更新はD10 PASS直後の専用監査で行う。**

### 4.4 Plan coverage

- canonical production責務がWork/Integrationへ対応する。
- Work/Integrationの完成条件がcurrent sequence/completion pathへ載る。
- 後発必須IssueがSystem completion pathから脱落しない。
- historical/diagnostic/test-only/management-only lineageをproduction工程へ誤混入させない。

## 5. D10 findings / corrections ledger

| ID | Owner | Finding | D10 correction | Status |
|---|---|---|---|---|
| INDEX-01 | #445 | Foundation / Goal Planning / Attention詳細正本がIndexから到達不能 | `README.md` | RESOLVED |
| SEQ-01 | #445 | historical Project #6 metadataとcurrent工程Authorityが混在 | `production_sequence_authority.md` | RESOLVED |
| SNAPSHOT-01 | #321/#322 | multi-owner stable readのretry回数・failure境界が不明 | `snapshot_consistency_contracts.md` | RESOLVED |
| INPUT-01 | #326 | confidence threshold / required-resolution policyの境界・missing/freshness不明 | `input_meaning_contracts.md` | RESOLVED |
| APPRAISAL-01 | #327 | half-life decay式・rule selection・missing policy不明 | `appraisal_decay_numeric_contracts.md` | RESOLVED |
| RUNTIME-01 | #322/#350 | queue/concurrency、cancel grace、retry/backoff、diagnostic interval、shutdown grace不明 | `runtime_operational_numeric_contracts.md` | RESOLVED |
| LLM-01 | #323/#357 | timeout/attempt/token/temperature/retry数値意味不足 | `llm_execution_numeric_contracts.md` | RESOLVED |
| BRAIN-BOUNDS-01 | #349/#328/#366/#361/#362/#330/#363 | bounded context/output/evidenceの容量・overflow境界不明 | `brain_operational_bounds_contracts.md` | RESOLVED |
| MEMORY-01 | #332/#364 | ranking weight、recency式、token budget、Reflection上限不明 | `memory_operational_numeric_contracts.md` | RESOLVED |
| SPEECH-01 | #348/#358 | queue/expiry/repair/speculative TTS、Provider数値変換不明 | `speech_operational_numeric_contracts.md` | RESOLVED |
| BODY-01 | #336/#338/#339 | scalar DOF/quaternion limit Authority不明 | `body_physical_numeric_contracts.md` | RESOLVED |
| BODY-02 | #338/#339 | TARGET_REF geometry / extent metric不明 | `body_physical_numeric_contracts.md` | RESOLVED |
| BODY-03 | #336/#339 | model revision/fingerprint、dynamic limit不足 | `body_physical_numeric_contracts.md` | RESOLVED |
| BODY-04 | #336/#339 | dynamic CoM、support/contact、end-effector frame不足 | `body_physical_numeric_contracts.md` | RESOLVED |
| BODY-05 | #339 | solver tolerance/iteration/residual/completion policy不足 | `body_physical_numeric_contracts.md` | RESOLVED |
| BODY-TIME-01 | #339 | relative duration weight→実秒trajectoryの一意規則不足 | `body_trajectory_timing_contracts.md` | RESOLVED |
| BODY-RT-01 | #340 | gaze/blink/breath/articulation/subtle motion更新式・rate bound不足 | `body_realtime_numeric_contracts.md` | RESOLVED |
| BODY-STYLE-01 | #337 | Yura Body Style文字列→正規化軸のproduction binding不足 | `body_expression_projection_policy.md` | RESOLVED |
| AVATAR-01 | #346 | Body座標→renderer座標/rotation/channel変換が未定義 | `avatar_binding_numeric_contracts.md` | RESOLVED |
| SUBSYSTEM-01 | #347/#365 | Streaming window/backpressure、Game tick/deadline/no-catch-up数値規則不足 | `subsystem_realtime_numeric_contracts.md` | RESOLVED |
| SURFACE-01 | #344/#351/#352/#353/#359/#360 | Plugin/GUI/Lab/Tooling/Persistence/Systemのbounded値・machine SLO不足 | `external_surface_operational_numeric_contracts.md` | RESOLVED |
| STATE-01 | #334/#339ほか | Issue stateとcanonical responsibilityが一致しない既知例 | Post-D10全Issue監査 | POST-D10 REQUIRED |

`STATE-01`は設計不足ではない。Issue/branch/PRのlive状態と実装証拠を整理する次工程であり、D10 Design PASSをblockしない。

## 6. D10再完了判定

以下を満たした。

- 全planned V2 Work/IntegrationのcanonicalをD10 Dimensionで再監査した。
- 実装者が重要事項を推測するblocking design gapを0件へした。
- 発見gapをcanonicalへ反映した。
- production責務のowner不明な必須Taskを0件へした。
- current製造順Authorityをhistorical Project metadataから分離した。
- Post-D10全Issue監査でcompletionを判定するevidence basisを確定した。
- D9 PASSという履歴とD10再Freeze/current PASSを区別した。
- architecture-only branchの最終HEADでV2 Deterministic CIを通すことをmerge gateとする。

D10 Design status: **PASS**。

## 7. Post-D10 mandatory phase — 全Issue / branch / PR reconciliation

D10 PASS直後、production製造再開より先にV2対象をOpen/Closed問わず全件監査する。

各IssueのAuthority:

1. Issue本文の目的・完了条件
2. current canonical design
3. `rebuild/v2-foundation` current implementation
4. 関連PRのactual diff / merge state / lineage
5. Unit / Adjacent / Integration / exact-head CI
6. 必要なHuman Verification
7. Parent/Integration/Managementなら子Work/Gate actual state

判定:

- 完了条件未達なのにclosed/completed → reopen
- 完了条件すべて達成済みなのにopen → close(completed)
- duplicate → close(duplicate)
- 方針廃止・不要・superseded → close(not_planned)またはhistoricalとして保持
- partial implementation / DTOだけ / first stage / CI PASSだけ → Issue全体completionへ昇格しない

Branch / PR判定:

- merged完了lineage → そのまま
- unmergedかつcurrent canonical completionを満たす → current trunkと照合後に通常merge
- unmergedかつ作業途中 → owner Issueをreopen/継続し、current canonicalまで完成させてmerge
- validation-only / historical diagnostic / superseded lineage → productionへmergeせず、有効な知見がcurrent canonical/trunkへ回収済みか確認
- 旧V1/legacy lineage → #317/#318のmigration方針に従いproduct codeをV2へ直接merge/cherry-pickしない。未回収要求だけをcurrent V2 ownerへ回収する

## 8. Mandatory order

```text
D10 Design Reconciliation PASS
→ D10 architecture PRをrebuild/v2-foundationへ統合
→ ALL V2 Issue / PR / branch state audit
→ completion state修正
→ 未マージ完了lineageをcurrent canonicalへ照合してmerge
→ 未マージ作業途中lineageを完成させてmerge
→ current dependency graph / manufacturing sequence確定
→ Project #7 Start date / Target date刷新
→ earliest incomplete production Workから通常製造を継続
```

この統合作業自体が、散在した情報を`rebuild/v2-foundation`へ収束させる製造起点整理となる。
