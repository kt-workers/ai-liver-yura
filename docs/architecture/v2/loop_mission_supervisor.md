# Loop Mission Supervisor / Work Scheduler

Owner Issue: #465
Parent: #462
Root: #317
Mission: #450
Status: Canonical design / implementation contract

## 1. Purpose

Loop Engineering の制御中枢として、GitHub live state を観測し、現在の Mission / Work / implementation lineage を reconcile したうえで、次に安全に進める 1 Work と 1 transition を決定する。

Supervisor は product runtime の一部ではない。Development Tooling / Operations control plane であり、AI Liver ゆらの Core State、Goal、Attention、Memory、Body 等の production Authority を持たない。

### 1.1 Package boundary

Supervisor の正規配置は product package の外側にある
`tools/loop_engine/` とする。

```text
tools/loop_engine/
├─ __init__.py
├─ models.py          # typed contracts
├─ reconciliation.py  # observation conflict reconciliation
├─ scheduler.py       # readiness, selection, ScheduleKey
├─ write_gate.py      # mutation precondition/effect checks
└─ supervisor.py      # composition, certificate, packet, disposition
```

`app/operations/mission_supervisor.py` は旧配置であり、存在してはならない。
`tools.loop_engine` は Development Tooling のみから利用し、`app/runtime`、
`app/domain`、`app/usecases`、`app/adapters`、`app/infrastructure` および
`python -m app` の起動経路は import しない。したがってSupervisorはproduct
runtimeの起動・可用性・Authorityに不要である。

テストも `tests/tools/loop_engine/` に配置する。package boundary変更は
snapshot、reconciliation、selection、Write Gateの意味を変えず、OpenAI Reviewer
credential、`.env`、PostgreSQL operational store、GitHub mutation transportを
導入しない。

正規ループは次である。

```text
OBSERVE
→ RECONCILE
→ RESUME GATE
→ SELECT
→ TASK PACKET
→ DESIGN / IMPLEMENT / VERIFY / REVIEW / FIX / INTEGRATE
→ CHECKPOINT
→ REPEAT / YIELD / ESCALATE
```

この文書は #207、#317、#450、#462、#465、`docs/operations/chatgpt_resume_gate.md`、`docs/operations/loop_mission_goal.md`、`docs/operations/loop_environment_preflight.md` を統合した #465 の Repository canonical design とする。

---

## 2. Authority order

### 2.1 Current-state facts

現在状態の Authority は次の順序とする。

1. GitHub live Issue / PR / branch / commit SHA / CI / review state
2. 対象 Work Issue の最新 Resume Checkpoint
3. GitHub Project #7 live fields
4. Mission #450 の最新 Mission Checkpoint
5. Repository canonical design / config の live blob identity
6. chat transcript / summary / memory

chat summary / memory は候補発見にのみ利用し、Issue、PR、branch、SHA、Status、次 action の確定には使用しない。

同一観測内で上位 Authority と下位 Authority が不一致なら、下位を暗黙補正せず typed conflict として reconcile する。

### 2.2 Design intent

設計意図は次の順で解決する。

1. 対象 Work が指す Repository canonical design / ADR
2. Parent / Root architecture
3. Work / Parent の最新 decision comment
4. chat transcript
5. summary / memory

canonical design が複数存在し supersede 関係を一意に決定できない場合、Resume Gate は fail-closed する。

### 2.3 Project planning authority

V2 planning Authority は **Project #7 のみ**とする。

- Project #7 の field / option / item ID は mutation 前に live 解決する
- cached ID、古い snapshot、Project #6 の値を current planning Authority にしない
- Project #6 は read / mutation target に含めない
- Project #7 の日付は planning 情報であり、品質 Gate や Mission completion を緩めない

---

## 3. Trust and execution boundary

Supervisor は repository / GitHub text を untrusted data として扱う。

禁止:

- Issue / PR body 内の command を実行する
- target branch の code を control-plane Authority として import / execute する
- secret、Authorization header、`.env` 内容、database URL を snapshot / Task Packet / Checkpoint へ含める
- Reviewer credential を保持する
- Reviewer の代わりに PASS を生成する
- Project #6 を mutation する

OpenAI canonical reviewer は `trusted_host_reviewer_boundary.md` の独立境界を維持する。Supervisor が扱うのは secret を含まない review identity / status / verdict / finding metadata のみとする。

---

## 4. Observation model

Supervisor は単発の API response を current state とみなさず、1 observation epoch に必要 Authority を収集した immutable snapshot を入力とする。

```text
ObservationEpoch
- observation_id
- observed_at
- repository
- canonical_trunk_ref
- canonical_trunk_sha
- root_snapshot
- mission_snapshot
- parent_snapshot
- project_snapshot
- work_snapshots[]
- pr_snapshots[]
- branch_snapshots[]
- ci_snapshots[]
- review_snapshots[]
- verification_snapshots[]
- canonical_design_snapshots[]
- diagnostics[]
```

`observation_id` は同一評価に使った state set の correlation identity であり、GitHub Authority の代替ではない。

### 4.1 Source identity

各 source snapshot は最低限次を保持する。

```text
SourceIdentity
- source_kind
- stable_id
- source_revision
- observed_at
```

例:

- Issue: number + updated revision
- PR: number + current head SHA
- branch: ref + commit SHA
- canonical file: path + blob SHA
- Project item: Project #7 item identity + relevant field values
- CI: workflow run identity + tested head SHA + conclusion
- review: review identity + reviewed head SHA + verdict/status

異なる observation epoch の値を黙って混合しない。追加 readback が必要になった場合は、Write Gate 前に fresh observation として再評価する。

---

## 5. Typed snapshots

### 5.1 MissionSnapshot

```text
MissionSnapshot
- mission_issue
- mission_state
- latest_checkpoint_id?
- latest_checkpoint_state?
- root_completion_evidence[]
- current_work_id?
- current_lineage_identity?
- current_blockers[]
```

`Mission state` は #450 の current policy と live evidence を reconcile した結果であり、古い Checkpoint をそのまま truth としない。

### 5.2 WorkSnapshot

```text
WorkSnapshot
- issue_number
- title
- issue_state
- issue_level
- project_status
- priority
- area
- start_date?
- target_date?
- dependency_issue_ids[]
- canonical_design_refs[]
- latest_resume_checkpoint_id?
- active_lineages[]
- waits[]
- acceptance_state
```

Start / Target は selection の補助 planning metadata であり、dependency / safety / quality Gate より優先しない。

### 5.3 LineageSnapshot

```text
LineageSnapshot
- lineage_id
- classification
- branch_ref?
- base_ref?
- base_sha?
- head_sha?
- pr_number?
- pr_state?
- draft?
- merged?
- mergeable?
- exact_head_ci?
- canonical_review?
- verification_state?
```

classification:

- `CANONICAL`
- `SUPERSEDED`
- `VALIDATION_ONLY`
- `CI_ONLY`
- `ABANDONED`
- `UNKNOWN`

同一 Work に `CANONICAL` 候補が複数、または `UNKNOWN` が存在する場合は conflict とする。

### 5.4 CanonicalDesignSnapshot

```text
CanonicalDesignSnapshot
- path
- ref
- blob_sha
- authority_owner
- supersedes[]
- superseded_by?
```

Supervisor は file path の存在だけで canonicality を推測しない。

---

## 6. Reconciliation

Observation 後、selection より先に deterministic reconciliation を行う。

### 6.1 ConflictKind

最低限次を typed conflict とする。

- `AUTHORITY_UNAVAILABLE`
- `PROJECT_AUTHORITY_UNAVAILABLE`
- `CANONICAL_DESIGN_UNRESOLVED`
- `CANONICAL_DESIGN_MISMATCH`
- `MULTIPLE_ACTIVE_LINEAGES`
- `UNKNOWN_LINEAGE`
- `BASE_SHA_MISMATCH`
- `HEAD_SHA_MISMATCH`
- `UNEXPLAINED_SHA_CHANGE`
- `CHECKPOINT_LIVE_MISMATCH`
- `MISSION_CHECKPOINT_STALE`
- `PROJECT_STATE_MISMATCH`
- `REVIEW_HEAD_MISMATCH`
- `CI_HEAD_MISMATCH`
- `VERIFICATION_STATE_MISMATCH`
- `FORBIDDEN_PROJECT_IDENTITY`

### 6.2 Explainable state advance

Checkpoint より live SHA / state が新しいこと自体は直ちに corruption ではない。

ただし、次のいずれかで説明できる必要がある。

- 同一 canonical lineage の通常 push / merge
- exact-head CI / review / Verification の新しい結果
- explicit supersede / abandon / close checkpoint
- newer Work Resume Checkpoint

説明できない advance は `UNEXPLAINED_SHA_CHANGE` とする。

### 6.3 Mission Checkpoint lag

Work Resume Checkpoint / GitHub live が進んでいる一方で #450 の最新 Mission Checkpoint が古い場合、Supervisor は古い Mission Checkpoint を current truth として再利用しない。

この状態は `MISSION_CHECKPOINT_STALE` として一旦 reconcile action を生成し、#450 を live state へ同期した fresh observation 後に Resume Gate を再評価する。

Mission Checkpoint 更新遅れを理由に別 implementation lineage を作成してはならない。

---

## 7. Dependency-ready and actionable

`dependency-ready` と `actionable` を分離する。

### 7.1 Dependency-ready

Work が dependency-ready である条件:

- Issue が open
- required dependencies が live evidence 上で満了
- canonical design Authority が解決済み
- unresolved blocking conflict がない
- Project #7 planning state が Work を禁止していない

Start date 到来だけでは dependency-ready にならず、Target date 超過だけで unavailable にもしない。

### 7.2 Actionable

dependency-ready Work が現在 local action を持つ場合だけ actionable とする。

例:

- design が必要
- implementation / repair が必要
- CI failure の deterministic fix が必要
- review finding の fix が必要
- reconciliation / checkpoint mutation が必要
- merge preconditions が満たされ merge が next transition

次は waiting state であり、同じ状態を busy poll しない。

- exact-head CI 実行中
- canonical review pending
- Human Verification pending
- external credential / service availability pending

waiting Work は Mission から消さず、独立 actionable Work があれば selection 対象を切り替える。

---

## 8. Work selection policy

selection は deterministic である。

1. current Work が safe に actionable なら current Work を継続する
2. current Work が wait-only の場合、他の dependency-ready actionable Work を列挙する
3. unresolved conflict / unknown lineage / forbidden Project identity を持つ Work は implementation candidate から除外し reconcile candidate とする
4. candidate を Project #7 planning state と priority で rank する
5. 同順位は stable Issue number で tie-break する

基準 priority:

```text
P0 > P1 > P2 > P3 / unspecified
```

Project Status は progress continuity を優先するため、同等条件では `In progress` を `Ready` より先に扱う。ただし wait-only の `In progress` が actionable `Ready` を block しない。

Supervisor は単に最小 Issue 番号を選ぶ scheduler ではなく、dependency / current lineage continuity / actionable state を先に評価する。

---

## 9. Resume Gate

選択 Work に対し、Task Packet より先に Resume Gate を生成する。

```text
ResumeCertificate
- gate: PASS | STOP
- target_issue
- canonical_design_refs[]
- active_lineage
- working_branch?
- base_ref?
- base_sha?
- head_sha?
- current_status
- last_verification[]
- next_action
- conflicts[]
- source_freshness
- observation_id
```

Mission-wide Authority conflict が 1 件でも unresolved なら `STOP`。ただしWork固有の lineage / checkpoint / CI / review conflict は、そのWorkだけを候補から除外してreconcileする。無関係なWorkの stale / unknown lineage が、independentかつdependency-readyな actionable Work の継続を停止させてはならない。候補全件がWork固有conflictで除外された場合だけ、Task Packetを生成せず外部state待ちとして扱う。

`PASS` は「品質が最終完了した」意味ではなく、「この exact state から next action を安全に開始できる」ことだけを表す。

---

## 10. Task Packet

Resume Gate PASS 後だけ Task Packet を生成する。

```text
TaskPacket
- packet_id
- schedule_key
- observation_id
- authority_refs[]
- target_issue
- scope[]
- non_goals[]
- exact_target
- dependency_evidence[]
- acceptance_checks[]
- risk_boundary[]
- active_lineage
- expected_next_transition
- allowed_mutation_kinds[]
```

Task Packet は implementer へ current state を伝える durable contract であり、secret や raw credential を含めない。

`exact_target` は少なくとも base/head/canonical blob identity のうち、その action に必要なものを exact に bind する。

---

## 11. Duplicate scheduling and no-progress control

同じ Work / same exact state を繰り返し dispatch しない。

### 11.1 Schedule key

`ScheduleKey` は secret を含まない canonical serialization から生成する。

含める state:

- Mission / Work identity
- Project #7 relevant planning state
- dependency completion identities
- canonical design blob identities
- active lineage classification
- base/head SHA
- current CI/review/Verification identity
- latest Resume / Mission Checkpoint identity
- expected next transition

同じ ScheduleKey と next transition が既に dispatch / checkpoint 済みなら duplicate として抑止する。

`ScheduleKey` は上記identityを省略してはならない。dependency completion evidence、Work Resume Checkpoint、Mission Checkpointのいずれかが変化した場合は同じWork / transitionでも新しいkeyとなり、restart後に必要なdispatchを過去keyで抑止しない。

### 11.2 Restart-safe suppression

#465 自身は PostgreSQL operational store を所有しない。

restart を跨ぐ duplicate suppression は GitHub の latest durable Checkpoint / Task Packet identity を current live state と照合して行う。将来 #462 Operational Store が導入された場合も、DB は補助実行記憶であり GitHub live Authority を上書きしない。

### 11.3 No busy loop

state fingerprint が変化していないのに同じ external wait / same Task Packet を繰り返し生成しない。

---

## 12. Run disposition

```text
RunDisposition
- CONTINUE
- YIELD_EXTERNAL
- INTERVENTION_REQUIRED
- MISSION_COMPLETE
```

### CONTINUE

安全に実行可能な next transition がある。

例: design、implementation、fix、checkpoint reconciliation、merge 等。

### YIELD_EXTERNAL

有用な独立 actionable Work がなく、残る進行条件が external / asynchronous result 待ちだけである。

- CI pending
- canonical review pending
- Human Verification pending
- external service / credential availability pending

YIELD は Mission STOP ではなく、busy polling をしない run disposition である。

### INTERVENTION_REQUIRED

安全に推測できない human Authority / decision が本当に必要で、かつ独立 actionable Work もない。

例:

- conflicting canonical designs の採用判断
- irreversible mutation の authority 不足
- policy で人間判断を要求する escalation

通常の test failure / review finding / CI failure は INTERVENTION_REQUIRED にしない。

### MISSION_COMPLETE

個別 Work 完了や candidate 空集合だけでは返さない。

Root #317 / Mission #450 が要求する completion evidence、Integration、必要 Human Verification、runtime boot / continuous operation / restart / graceful shutdown 等が明示的に満了した live evidence がある場合のみ返す。

---

## 13. Review / Verification state handling

### Review

- review は exact HEAD bind 必須
- reviewed head != current head は stale
- same exact HEAD への canonical review は 1 回
- `REQUEST_CHANGES` は同一 lineage の fix-loop
- `PASS` は pre-merge gate へ進む
- `NOT_RUN` は review right を消費しない
- review pending だけで Mission を stop しない

### Human Verification

- Verification pending Work は wait state
- Human Verification が必要な surface を自動 PASS にしない
- 他の independent actionable Work があれば切り替える
- 全て Verification / external wait のみなら `YIELD_EXTERNAL`

---

## 14. Write Gate

Supervisor は mutation 実行前に fresh live precondition を必須化する。

```text
WriteIntent
- intent_id
- target_kind
- target_identity
- mutation_kind
- expected_preconditions
- source_observation_id
```

Write Gate:

1. target を fresh readback
2. expected preconditions と比較
3. mismatch があれば mutation せず `STALE_WRITE_GATE`
4. re-observe / reconcile

GitHub publisherを含むすべてのProject #7 mutationは、対象Project / item / field / option identityを独立したfresh readbackで再確認してからだけ実行する。複数fieldを更新する場合でも、batch開始時の一回の確認を後続mutationへ流用してはならない。**各 `item-edit` の直前**に、同じmutationで使用するProject / item / field / option identityをfresh snapshotから再解決し、Write Gateを通す。mismatchなら後続fieldを編集せず`STALE_WRITE_GATE`としてfail-closedにする。mutation後は同じowned fieldのeffect readbackを必須化し、不一致なら成功を返さず`MUTATION_EFFECT_MISMATCH`としてfail-closedにする。item addも同じprecondition/effect readback境界に含める。

GitHub Issues REST APIの`url`はAPI endpointであり、Project itemの`content.url`および`gh project item-add --url`に使用してはならない。既存Issue再利用時のProject lookup/addには、repository / Issue numberへbindしたGitHub web URLだけを用いる。
5. PASS 時のみ adapter へ mutation を許可
6. mutation 後に readback し effect を確認

hard deny:

- Project number != 7
- protected/canonical trunk への direct content implementation write
- expected branch / PR / head identity 不明
- no-op / duplicate mutation
- stale Project field / option ID
- content mutationでexpected branch / PR / head identityが不明

Write Gate は mutation API を discovery / probing に使わない。

---

## 15. Mutation boundary

Supervisor core は「何を次に行うべきか」と precondition を決定する。

GitHub / Project mutation は adapter 境界で実施し、core decision と API transport を分離する。

```text
MissionSupervisor
→ SupervisorDecision / WriteIntent
→ WriteGate
→ GitHubMutationPort
→ fresh readback
→ next ObservationEpoch
```

GitHubMutationPort が扱える target は repository `ktan514/ai-liver-yura` と Project #7 に明示的に制限する。

---

## 16. Supervisor decision

```text
SupervisorDecision
- observation_id
- disposition
- selected_work_id?
- resume_certificate?
- task_packet?
- reconciliation_actions[]
- write_intents[]
- wait_reasons[]
- completion_evidence[]
- diagnostics[]
```

invariant:

- Resume Gate STOP で implementation Task Packet を出さない
- MISSION_COMPLETE 以外で Root completion を主張しない
- selected Work は同時に 1 本
- same Work の canonical active lineage は同時に 1 本
- diagnostics に secret / raw provider body を含めない

health fingerprint、source referenceなど外部adapter由来の文字列もuntrusted dataである。GitHub Issue / Checkpoint本文へ出す必要がある場合は、元文字列を許可文字filterだけで通過させず、不可逆でboundedな参照identityへ変換する。credential-like値または未知のsensitive identifierを検出した場合は、元文字列を残さずfail-closed redactionする。

---

## 17. Ports and implementation boundary

#465 の実装は `tools/loop_engine/` 配下の production runtime 非依存 tooling
とする。`tools/loop_engine/` が唯一の正規implementation packageであり、
`app/operations/mission_supervisor.py` を含む `app/` 配下の配置は許可しない。

期待する logical components:

```text
MissionObservationPort
- read-only GitHub / Project #7 observation

MissionSupervisor
- reconciliation
- dependency/actionability evaluation
- selection
- Resume Certificate
- Task Packet
- Run disposition
- duplicate suppression decision

WriteGate
- fresh precondition validation

GitHubMutationPort
- explicit authorized mutation adapter
```

Provider SDK / GitHub CLI の具体 transport は port 外側へ閉じ、decision logic の unit test は fake snapshot / fake port で deterministic に検証可能にする。

production `app/runtime`, Brain, Body, Subsystem は Mission Supervisor を import しない。

---

## 18. Failure semantics

外部 read failure を空集合として扱わない。

例:

- Project #7 read failure → `PROJECT_AUTHORITY_UNAVAILABLE`
- PR head read failure → `AUTHORITY_UNAVAILABLE`
- canonical file identity unavailable → `CANONICAL_DESIGN_UNRESOLVED`
- malformed snapshot → invalid observation / fail-closed

一部 Work の external capability unavailable は、その Work の wait/block reason とする。Mission 全体の停止可否は independent actionable Work の有無まで評価して決める。

---

## 19. Secret-safe diagnostics

保持可能:

- stable Issue / PR / run / review ID
- branch ref
- commit / blob SHA
- typed status / conflict / disposition
- bounded counts
- timestamps

保持禁止:

- token / API key
- Authorization header
- `.env` contents
- DB URL / password
- raw provider error payload
- unnecessary Issue/PR natural-language body in ordinary diagnostic

---

## 20. Required acceptance tests

### Observation / reconciliation

- GitHub live + latest checkpoint一致 → conflictなし
- Mission Checkpointだけ古い → `MISSION_CHECKPOINT_STALE`、reconcile後PASS
- multiple canonical lineage → STOP
- unknown lineage → STOP
- canonical blob mismatch → STOP
- unexplained head change → STOP
- Project #7 unavailable → fail-closed
- Project #6 identity → hard reject

### Selection

- current actionable Workを継続
- current review pending + independent Ready Work → independent Workを選択
- Verification pending + independent Work → Mission ACTIVEで切替
- priority P0 > P1
- same rank stable Issue number tie-break
- wait-only In progress が actionable Ready をstarveしない

### Resume / Task Packet

- conflict 0 → Resume PASS
- conflict 1+ → STOP / Task Packetなし
- Task Packetにauthority/scope/non-goals/exact target/dependencies/acceptance/risk/lineage/transitionを含む
- secretを含まない

### Duplicate / wait

- same ScheduleKeyを二重dispatchしない
- Checkpointに同じ packet identityがあればrestart後も抑止
- review/CI待ちをbusy pollしない
- independent Workなし + external waitのみ → `YIELD_EXTERNAL`

### Mission completion

- 1 Work完了だけでMISSION_COMPLETEにならない
- candidate 0だけでMISSION_COMPLETEにならない
- explicit Root/Mission completion evidence満了時だけMISSION_COMPLETE

### Write Gate

- exact precondition一致 → PASS
- head変更 → `STALE_WRITE_GATE`
- Project field ID stale → reject
- Project #6 target → reject
- mutation後readback不一致 → effect未確認としてfail-closed

### Engineering gates

- targeted tests
- Ruff
- strict Mypy
- full pytest
- compileall
- `git diff --check`
- exact-head CI
- exact-head canonical review

---

## 21. Non-goals

#465では次を実装しない。

- OpenAI Responses API Reviewer transport / credential broker
- Reviewer credential保持
- PostgreSQL operational store schema / migration
- Codex coding engineそのもの
- product runtime scheduler
- Core Attention / Executive / Activity scheduling
- GitHub Project #6 support
- Human Verificationの自動代替

これらは #462 の別責務または product architecture の各 owner が持つ。

---

## 22. Completion contract

#465は、GitHub live snapshotから deterministic に SupervisorDecision を生成し、conflict時fail-closed、dependency-ready Work選定、Resume Certificate / Task Packet、wait切替、duplicate suppression、Write Gate、Mission completion非誤判定を automated test で証明し、exact-head CI と canonical review PASS を得た時点で implementation completion candidate となる。

個別 #465 完了後も Mission #450 は Root #317 completion まで `ACTIVE` を継続する。
