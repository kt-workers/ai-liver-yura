# V2 実装決定可能性 再監査

Owner: #445
Root: #317
Status: Architecture-only reconciliation
Current sequence authority: `production_sequence_authority.md`
Historical sequence source: `project_sync_manifest.md`

## 1. 目的

V2 Design Completion GateはD1〜D9を一度PASSしたが、#339の製造再開時に、canonicalだけでは実装者が追加判断しなければ製造できない箇所が見つかった。

本再監査では「設計書が存在する」ことではなく、**実装担当が重要な意味・Authority・数値変換・failure・freshness・lifecycle・依存順を発明せず、正本どおりに製造できること**を設計完了条件とする。

設計不足が残る間はproduction implementationを増やさない。

## 2. 製造順のAuthority

current V2製造順Authorityは `production_sequence_authority.md` とする。

- 同書は2026-08-13 `project_sync_manifest.md` の`工程`を元工程としてexact preserveする。
- `project_sync_manifest.md`自体はProject #6、旧Status、旧Start/Targetを含むhistorical synchronization recordであり、current Project stateのAuthorityではない。
- current Project管理先はProject #7 `プロジェクトゆらv2`。
- 工程番号が小さいWorkを先に扱う。
- Parentは子Work/Integrationの完成管理であり、Parent自身へ重複実装しない。
- Integrationは直接依存WorkのUnit/Adjacent完了後に行う。
- 日付は工程・依存関係・current stateから作る予定情報であり、日付から工程を逆算しない。
- Project #7 Start date / Target dateの刷新はD10後の全Issue状態監査・current工程確定の後に行う。
- Project #6を変更しない。

## 3. 後発Taskの取り込み規則

元工程作成後に必要性が判明した機能・Bug・設計補修・Verificationを、単に「元計画にない」ことを理由に未対応のまま残してはならない。

必須Taskを発見した場合:

1. 既存Workの未完了責務/owner amendmentか、独立した新責務かを判定する。
2. 既存Workの完了条件に含まれるなら、そのowner Workのcompletionへ回収する。
3. 独立して完成・検証できる責務ならIssue化する。
4. direct dependency、Priority、Issue level、Area、検証境界を確定する。
5. 元工程を破棄せず、依存関係上の正しい位置へ工程を挿入する。
6. Post-D10全Issue監査でstateとcurrent工程を確定する。
7. その後Project #7の日程を新しい工程に合わせて再計画する。
8. 下流Integration/System Verificationのcompletion pathへ漏れなく反映する。

計画外TaskをBacklogへ置くだけでV2完成条件から外すことは禁止する。

## 4. 再監査Dimension

D8の15観点に加え、次を必須とする。

### 4.1 Implementation decidability

- 型だけでなく値の意味が一意か。
- 正規化値から物理量・Provider量へ変換するAuthorityと規則が明示されているか。
- quaternion / scalar DOF /座標frame等の数学表現に逆変換の曖昧さがないか。
- tolerance、iteration budget、epsilon、completion判定、threshold、retry/backoff、grace等を実装者が任意に選ぶ必要がないか。
- ID/ref/自由文から意味や座標、policyを推測する必要がないか。
- 「bounded」「configurable」「policy」とだけ書いて実質的な値域・単位・missing時挙動を実装へ丸投げしていないか。

### 4.2 Data sufficiency

- canonicalが要求する計算に必要な入力値がschemaに存在するか。
- provenance / revision / generation / fingerprintが必要な境界に存在するか。
- balance / contact / timing / threshold / retry等の計算に必要な情報が欠落していないか。
- versioned policyを使う場合、policy identity/revisionが必要なasync freshness境界へbindされているか。

### 4.3 Completion-state consistency — D10の責務範囲

D10では**Issue stateを書き換えない**。production設計の完成可否を判断するため、少なくとも既知のstate inconsistencyを記録し、Post-D10全Issue監査で判定できるcompletion evidence schema/手順を完成させる。

- 部分実装をWork全体完了へ昇格してはならない。
- Integrationが未完了upstreamより先に完了扱いになり得る設計を許さない。
- Parent / Integration / Managementのcompletionを、子Work/Gateのactual evidenceから判定できること。
- D10中に個別Issueを便宜的にopen/closeして「0件」に見せない。

**実際のOpen/Closed全件監査とstate mutationはD10 PASS直後の必須専用フェーズで行う。**

### 4.4 Plan coverage

- canonicalに存在するproduction責務が必ずWork/Integrationへ対応しているか。
- Work/Integrationに存在する完成条件がcurrent sequence/completion pathへ載るか。
- 後発必須IssueがSystem completion pathから脱落していないか。
- historical/diagnostic/management-only Issueをproduction工程へ誤混入させないか。

## 5. D10 findings / corrections ledger

D10で検出したgapは、Issue stateではなくこのledgerとcanonical correctionで追跡する。

| ID | Owner | Finding | D10 correction | Design status |
|---|---|---|---|---|
| BODY-01 | #336/#338/#339 | scalar DOF/quaternion limit Authority不明 | `body_physical_numeric_contracts.md` | corrected / owner re-audit pending |
| BODY-02 | #338/#339 | TARGET_REF geometry / extent metric不明 | 同上 | corrected / owner re-audit pending |
| BODY-03 | #336/#339 | model revision/fingerprint、dynamic limit不足 | 同上 | corrected / owner re-audit pending |
| BODY-04 | #336/#339 | dynamic CoM、support/contact、end-effector frame不足 | 同上 | corrected / owner re-audit pending |
| BODY-05 | #339 | solver tolerance/iteration/residual/completion policy不足 | 同上 | corrected / owner re-audit pending |
| INDEX-01 | #445 | Foundation / Goal Planning / Attention detailed canonicalsがArchitecture Indexから到達不能 | `README.md` index補修 | resolved |
| INPUT-01 | #326 | confidence threshold / required resolution policyの値域・境界・missing/freshness不明 | `input_meaning_contracts.md` D10 policy supplement | corrected / owner re-audit pending |
| APPRAISAL-01 | #327 | half-life decayの式・rule selection・missing policy不明 | `appraisal_decay_numeric_contracts.md` | corrected / owner re-audit pending |
| RUNTIME-01 | #322/#350 | queue/concurrency numeric、cancel grace、retry/backoff、diagnostic interval、shutdown grace不明 | `runtime_operational_numeric_contracts.md` | corrected / owner re-audit pending |
| LLM-01 | #323/#357 | timeout/attempt/token/temperature/retry numeric semantics不十分 | `llm_execution_numeric_contracts.md` | corrected / owner re-audit pending |
| SEQ-01 | #445 | historical `project_sync_manifest.md`にProject #6/旧Status/旧日程が混在し、current工程Authorityとして誤読可能 | `production_sequence_authority.md`へ元工程のみ分離 | resolved |
| STATE-01 | #334/#339ほか | Issue stateとcanonical responsibilityが一致しない既知例あり | Post-D10全Issue監査をmandatory phaseとして固定 | known / mutation intentionally deferred |

この表で`corrected`は**D10 design patchが存在する**ことを意味し、owner areaの再監査完了やproduction implementation完了を意味しない。

## 6. Body initial gap detail

#339製造再開時に検出した初期gap:

1. `BodyPose` local quaternionとX/Y/Z scalar hard limit間のauthoritative coordinate不足。
2. quaternion decomposition順序・特異点・同値回転の扱いが未定義。
3. `TARGET_REF` identityからworld/local geometryを誰がどのrevisionで供給するか未定義。
4. `DIRECTION.extent`からphysical targetへのdeterministic metric policy不足。
5. Canonical Body Model revision/fingerprint binding不足。
6. velocity / acceleration / jerk / root movement hard physical bound policy不足。
7. dynamic CoMに必要なsegment mass-center不足。
8. support/contact polygon geometry不足。
9. task-space end-effector local offset/orientation frame不足。
10. solver epsilon / iteration / residual / completion tolerance Authority不足。

これらの設計補修は`body_physical_numeric_contracts.md`へ正本化した。D10を閉じる前に#336/#338/#339および隣接#337/#340/#341との整合を再監査する。

## 7. D10再完了条件

#445を再びDesign Completionとするには:

- 全planned V2 Work/IntegrationのcanonicalをD10 Dimensionで再監査済み。
- 実装者が重要事項を推測するblocking design gapが0件。
- 発見したgapはcanonicalへ反映済み。
- production責務のownerが不明な必須Taskが0件。owner amendmentかindependent mandatory workかを分類できる状態。
- current製造順Authorityがhistorical Project metadataから分離されている。
- Post-D10全Issue監査でcompletionを判定するためのevidence basisが設計上不足していない。
- D9 PASS済みというhistorical factとD10再Freezeというcurrent metadataが矛盾しない。
- architecture-only exact HEADでCI / independent architecture reviewを通す。

**D10 PASSの条件に、全IssueのOpen/Closed state mutation完了を含めない。** それはユーザー指定順序どおり、D10直後に全件で実施する。

## 8. Post-D10 mandatory phase — ALL Issue state reconciliation

D10 PASS直後、production製造再開より先に`ktan514/ai-liver-yura`のV2対象IssueをOpen/Closedを問わず全件監査する。

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
- 方針廃止・不要 → close(not_planned)
- partial implementation / DTOだけ / first stage / CI PASSだけ → Issue全体completionへ昇格しない

その後にlater mandatory workのcurrent dependency/工程を確定し、Project #7 Start date / Target dateを刷新する。

## 9. Production Freeze during reconciliation

本再監査中:

- PR #501を含むproduction branchへ新しい製造変更を追加しない。
- architecture-only branchだけを変更する。
- 既存production成果は履歴として保全する。
- Post-D10全Issue監査完了まで次のproduction対象を確定しない。

## 10. Mandatory order

```text
D10 Design Reconciliation PASS
→ ALL V2 Issue state audit / state mutation
→ current dependency graph / manufacturing sequence確定
→ Project #7 Start date / Target date刷新
→ original/current工程先頭からearliest incomplete WorkをResume Gate
→ production製造再開
```
