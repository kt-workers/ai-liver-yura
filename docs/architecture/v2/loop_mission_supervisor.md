# Loop Mission監督 / Work選択器

所有Issue: #465  
親Issue: #462  
Root: #317  
Mission: #450  
状態: 正本設計 / 実装契約

## 1. 目的

Loop Engineeringの制御中枢としてGitHubの現在状態を観測し、現在のMission、Work、実装作業系列を再調整したうえで、次に安全に進める1件のWorkと1回の遷移を決定する。

Mission監督（Supervisor）は製品実行系の一部ではない。開発支援・運用制御系であり、AI Liver ゆらのCore State、Goal、Attention、Memory、Bodyなどの製品側正本を所有しない。

### 1.1 配置境界

正規配置は製品package外の`tools/loop_engine/`とする。

```text
tools/loop_engine/
├─ __init__.py
├─ models.py          # 型付き契約
├─ reconciliation.py # 観測競合の再調整
├─ scheduler.py       # 実行可能性、選択、ScheduleKey
├─ write_gate.py      # 変更前条件と効果確認
└─ supervisor.py      # 構成、証明書、作業パケット、実行結果
```

`app/operations/mission_supervisor.py`は旧配置であり、存在してはならない。`tools.loop_engine`は開発支援だけから利用し、`app/runtime`、`app/domain`、`app/usecases`、`app/adapters`、`app/infrastructure`、`python -m app`の起動経路から取り込まない。したがってMission監督は製品実行系の起動・可用性・正本性に不要である。

テストも`tests/tools/loop_engine/`へ配置する。配置変更によってsnapshot、再調整、選択、書込み判定の意味を変えず、OpenAIレビューワー認証情報、`.env`、PostgreSQL運用記憶、GitHub変更通信を導入しない。

正規Loopは次とする。

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

本書は#207、#317、#450、#462、#465、`docs/operations/chatgpt_resume_gate.md`、`docs/operations/loop_mission_goal.md`、`docs/operations/loop_environment_preflight.md`を統合した#465のRepository正本設計とする。

---

## 2. 正本の優先順位

### 2.1 現在状態の事実

現在状態の正本は次の順序とする。

1. GitHub上の現在Issue / PR / branch / commit SHA / CI / review状態
2. 対象Work Issueの最新再開Checkpoint
3. GitHub Project #7の現在field
4. Mission #450の最新Mission Checkpoint
5. Repository正本設計 / configの現在blob identity
6. chat transcript / summary / memory

chat summaryやmemoryは候補発見だけに利用し、Issue、PR、branch、SHA、Status、次の作業の確定には使用しない。

同一観測内で上位正本と下位情報が不一致なら、下位を暗黙補正せず型付き競合として再調整する。

### 2.2 設計意図

設計意図は次の順に解決する。

1. 対象Workが指すRepository正本設計 / ADR
2. Parent / Root architecture
3. Work / Parentの最新判断コメント
4. chat transcript
5. summary / memory

正本設計が複数存在し、置換関係を一意に決定できない場合、再開判定（Resume Gate）は安全側停止にする。

### 2.3 Project計画の正本

V2計画の正本は**Project #7だけ**とする。

- Project #7のfield / option / item IDは変更直前に現在値を解決する。
- 保存済みID、古いsnapshot、Project #6の値を現在計画の正本にしない。
- Project #6は読取・変更対象に含めない。
- Project #7の日付は計画情報であり、品質判定やMission完了条件を緩めない。

---

## 3. 信頼境界と実行境界

Mission監督はRepository / GitHub上の文章を信頼できないデータとして扱う。

禁止事項:

- Issue / PR本文のcommandを実行する。
- 対象branchのコードを制御系の正本としてimport / executeする。
- secret、Authorization header、`.env`内容、database URLをsnapshot / Task Packet / Checkpointへ含める。
- レビューワー認証情報を保持する。
- レビューワーの代わりに`PASS`を生成する。
- Project #6を変更する。

OpenAI正本レビューワーは`trusted_host_reviewer_boundary.md`の独立境界を維持する。Mission監督が扱うのは、秘密情報を含まないレビューidentity、status、verdict、finding管理情報だけとする。

---

## 4. 観測モデル

単発のAPI応答を現在状態とはみなさず、1回の観測区間（observation epoch）に必要な正本情報を収集した不変snapshotを入力とする。

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

`observation_id`は同一評価に使用した状態集合の相関identityであり、GitHub正本の代替ではない。

### 4.1 情報源identity

各情報源snapshotは最低限次を保持する。

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

異なる観測区間の値を暗黙に混合しない。追加の再取得が必要になった場合は、書込み判定前に新しい観測として再評価する。

---

## 5. 型付きsnapshot

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

`Mission state`は#450の現在方針と現在証拠を再調整した結果であり、古いCheckpointをそのまま真実として扱わない。

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

Start / Targetは選択を補助する計画情報であり、依存関係、安全性、品質判定より優先しない。

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

分類値は`CANONICAL`、`SUPERSEDED`、`VALIDATION_ONLY`、`CI_ONLY`、`ABANDONED`、`UNKNOWN`とする。同一Workに`CANONICAL`候補が複数、または`UNKNOWN`が存在する場合は競合とする。

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

Mission監督はファイルpathが存在するだけで正本性を推測しない。

---

## 6. 再調整

観測後、Work選択より先に決定論的な再調整を行う。

### 6.1 ConflictKind

最低限、次を型付き競合とする。

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

### 6.2 説明可能な状態前進

Checkpointより現在SHAや状態が新しいこと自体は、直ちに破損を意味しない。ただし次のいずれかで説明できる必要がある。

- 同一正本作業系列の通常push / merge
- 厳密HEAD CI / review / Verificationの新しい結果
- 明示的な置換・廃止・終了Checkpoint
- より新しいWork再開Checkpoint

説明できない前進は`UNEXPLAINED_SHA_CHANGE`とする。

### 6.3 Mission Checkpointの遅れ

Work再開CheckpointやGitHubの現在状態が進んでいる一方、#450の最新Mission Checkpointが古い場合、その古いMission Checkpointを現在の真実として再利用しない。

この状態は`MISSION_CHECKPOINT_STALE`として再調整作業を生成し、#450を現在状態へ同期した新しい観測後に再開判定を評価し直す。Mission Checkpointの更新遅れを理由に別の実装作業系列を作成してはならない。

---

## 7. 依存関係準備済みと実行可能性

依存関係を満たした状態（dependency-ready）と、現在実行可能な状態（actionable）を分離する。

### 7.1 依存関係準備済み

Workが依存関係準備済みである条件:

- Issueがopen。
- 必須依存関係が現在証拠上で満了。
- 正本設計の所有関係が解決済み。
- 未解決の停止競合がない。
- Project #7の計画状態がWorkを禁止していない。

Start dateの到来だけでは準備済みにならず、Target date超過だけで利用不可にもしない。

### 7.2 実行可能

依存関係準備済みWorkが現在ローカルで行う作業を持つ場合だけ実行可能とする。

例:

- 設計が必要。
- 実装または修正が必要。
- CI失敗への決定論的な修正が必要。
- レビュー指摘の修正が必要。
- 再調整またはCheckpoint変更が必要。
- 統合前条件が満たされ、統合が次遷移になっている。

次は待機状態であり、同じ状態を高頻度監視しない。

- 厳密HEAD CI実行中。
- 正本レビュー待ち。
- 人間確認（Human Verification）待ち。
- 外部認証情報またはサービス可用性待ち。

待機中WorkをMissionから消さず、独立して実行可能なWorkがあれば選択対象を切り替える。

---

## 8. Work選択方針

選択は決定論的に行う。

1. 現在Workが安全かつ実行可能なら継続する。
2. 現在Workが待機専用なら、他の依存関係準備済み・実行可能Workを列挙する。
3. 未解決競合、不明作業系列、禁止Project identityを持つWorkは実装候補から除外し、再調整候補にする。
4. 候補をProject #7の計画状態と優先度で順位付けする。
5. 同順位は安定したIssue番号で決定する。

基準優先度は`P0 > P1 > P2 > P3 / unspecified`とする。

進行継続性を優先するため、同等条件では`In progress`を`Ready`より先に扱う。ただし待機専用の`In progress`が実行可能な`Ready`を妨げてはならない。

Mission監督は単に最小Issue番号を選ぶ仕組みではなく、依存関係、現在作業系列の継続性、実行可能状態を先に評価する。

---

## 9. 再開判定

選択Workに対し、作業パケットより先に再開判定を生成する。

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

Mission全体に関わる正本競合が1件でも未解決なら`STOP`とする。ただしWork固有の作業系列、Checkpoint、CI、review競合はそのWorkだけを候補から除外して再調整する。無関係なWorkの古い状態や不明作業系列が、独立かつ依存関係準備済みの実行可能Workを止めてはならない。候補全件がWork固有競合で除外された場合だけ、作業パケットを生成せず外部状態待ちとして扱う。

`PASS`は品質最終完了を意味せず、「この厳密な状態から次の作業を安全に開始できる」ことだけを表す。

---

## 10. 作業パケット

再開判定`PASS`後だけ作業パケット（Task Packet）を生成する。

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

作業パケットは実装者へ現在状態を伝える永続契約であり、秘密情報や生の認証情報を含めない。`exact_target`はbase、head、正本blob identityのうち、その作業に必要なものを厳密に結び付ける。

---

## 11. 重複割当と進捗停止の制御

同じWorkと同じ厳密状態を繰り返し割り当てない。

### 11.1 ScheduleKey

`ScheduleKey`は秘密情報を含まない正規直列化から生成する。

含める状態:

- Mission / Work identity
- Project #7の関連計画状態
- 依存関係完了identity
- 正本設計blob identity
- 有効作業系列の分類
- base/head SHA
- 現在CI/review/Verification identity
- 最新再開Checkpoint / Mission Checkpoint identity
- 次の期待遷移

同じ`ScheduleKey`と次遷移がすでに割当・Checkpoint済みなら重複として抑止する。依存関係完了証拠、Work再開Checkpoint、Mission Checkpointのいずれかが変化した場合は、同じWork / transitionでも新しいkeyとし、再起動後に必要な割当を古いkeyで抑止しない。

### 11.2 再起動安全な重複抑止

#465自身はPostgreSQL運用記憶を所有しない。再起動をまたぐ重複抑止は、GitHubの最新永続Checkpoint / Task Packet identityを現在状態と照合して行う。将来#462の運用記憶を利用しても、DBは補助実行記憶でありGitHubの現在正本を上書きしない。

### 11.3 高頻度無限実行の禁止

状態指紋が変化していないのに、同じ外部待機または同じ作業パケットを繰り返し生成しない。

---

## 12. 実行結果

```text
RunDisposition
- CONTINUE
- YIELD_EXTERNAL
- INTERVENTION_REQUIRED
- MISSION_COMPLETE
```

### CONTINUE

安全に実行可能な次遷移がある。例: 設計、実装、修正、Checkpoint再調整、統合など。

### YIELD_EXTERNAL

有用な独立実行可能Workがなく、残る進行条件が外部・非同期結果待ちだけである。CI待ち、正本レビュー待ち、人間確認待ち、外部サービス・認証情報待ちなどが該当する。これはMission停止ではなく、高頻度監視をしないための実行結果である。

### INTERVENTION_REQUIRED

安全に推測できない人間の正本判断が本当に必要で、かつ独立実行可能Workもない場合だけ使用する。正本設計の採用競合、不可逆変更の権限不足、人間判断を明示要求する方針上の介入などが該当する。通常の試験失敗、レビュー指摘、CI失敗だけではこの状態にしない。

### MISSION_COMPLETE

個別Work完了や候補空集合だけでは返さない。Root #317 / Mission #450が要求する完了証拠、統合、必要な人間確認、実行起動・継続動作・再起動・安全終了などが現在証拠上で明示的に満了した場合だけ返す。

---

## 13. レビューと人間確認の状態処理

### レビュー

- reviewは厳密HEADへの結び付けを必須とする。
- reviewed headがcurrent headと異なれば古い結果とする。
- 同一厳密HEADへの正本レビューは1回とする。
- `REQUEST_CHANGES`は同一作業系列の修正Loopへ戻す。
- `PASS`は統合前判定へ進める。
- `NOT_RUN`はレビュー権を消費しない。
- review待ちだけでMissionを停止しない。

### 人間確認

- 人間確認待ちWorkは待機状態とする。
- 人間確認が必要な対象を自動`PASS`にしない。
- 他の独立実行可能Workがあれば切り替える。
- 全Workが人間確認または外部待ちだけなら`YIELD_EXTERNAL`とする。

---

## 14. 書込み判定

変更実行前に新しい現在前条件を必須化する。

```text
WriteIntent
- intent_id
- target_kind
- target_identity
- mutation_kind
- expected_preconditions
- source_observation_id
```

書込み判定の基本手順:

1. 対象を現在状態から再取得する。
2. 期待前条件と比較する。
3. 不一致なら変更せず`STALE_WRITE_GATE`とする。
4. 再観測・再調整する。
5. `PASS`時だけ接続層へ変更を許可する。
6. 変更後に再取得して効果を確認する。

GitHub公開処理を含むすべてのProject #7変更は、対象Project / item / field / option identityを独立した現在値再取得で確認してから実行する。複数field更新でも、処理開始時の1回の確認を後続変更へ使い回さない。**各`item-edit`直前**に、その変更で使用するProject / item / field / option identityを新しいsnapshotから解決し直し、書込み判定を通す。不一致なら後続fieldを編集せず`STALE_WRITE_GATE`として安全側停止にする。

効果を期待する変更は、同じ所有fieldの効果再取得を必ず渡す。再取得不能、未指定、欠落、不一致のいずれも成功にせず`MUTATION_EFFECT_MISMATCH`とする。item addも同じ前条件・効果再取得境界に含める。

GitHub Issues REST APIの`url`はAPI endpointであり、Project itemの`content.url`や`gh project item-add --url`へ使用しない。既存Issue再利用時のProject探索・追加にはRepository / Issue番号へ結び付けたGitHub web URLだけを用いる。

明示拒否:

- Project number != 7
- 保護済み・正本基幹への直接的な実装書込み
- 期待branch / PR / head identity不明
- 実効果のない変更または重複変更
- 古いProject field / option ID
- 内容変更なのに期待branch / PR / head identity不明

書込み判定は変更APIを探索・試行目的に使用しない。

---

## 15. 変更境界

Mission監督Coreは「次に何を行うか」と前条件を決定する。GitHub / Project変更は接続層で実施し、Core判断とAPI通信を分離する。

```text
MissionSupervisor
→ SupervisorDecision / WriteIntent
→ WriteGate
→ GitHubMutationPort
→ fresh readback
→ next ObservationEpoch
```

`GitHubMutationPort`が扱える対象はRepository `ktan514/ai-liver-yura`とProject #7へ明示的に限定する。

---

## 16. Mission監督の判断

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

不変条件:

- 再開判定`STOP`で実装用Task Packetを出さない。
- `MISSION_COMPLETE`以外でRoot完了を主張しない。
- 選択Workは同時に1件だけ。
- 同一Workの正本有効作業系列は同時に1本だけ。
- diagnosticsへ秘密情報や提供元の生本文を含めない。

健全性指紋、情報源参照など外部接続層由来の文字列も信頼できないデータである。GitHub Issue / Checkpoint本文へ出す必要がある場合は、元文字列を許可文字filterだけで通さず、不可逆で上限付きの参照identityへ変換する。認証情報らしい値または未知の機密identityを検出した場合は、元文字列を残さず安全側に伏せる。

---

## 17. 接続口と実装境界

#465の実装は`tools/loop_engine/`配下の製品実行系に依存しない開発支援とする。`tools/loop_engine/`が唯一の正規実装packageであり、`app/operations/mission_supervisor.py`を含む`app/`配下への配置は許可しない。

期待する論理構成:

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

提供元SDK / GitHub CLIの具体通信は接続口の外側へ閉じ、判断処理の単体試験は偽snapshot / 偽接続口で決定論的に検証可能にする。製品側`app/runtime`、Brain、Body、SubsystemはMission監督を取り込まない。

---

## 18. 失敗時の意味

外部読取失敗を空集合として扱わない。

例:

- Project #7読取失敗 → `PROJECT_AUTHORITY_UNAVAILABLE`
- PR head読取失敗 → `AUTHORITY_UNAVAILABLE`
- 正本file identity取得不能 → `CANONICAL_DESIGN_UNRESOLVED`
- 不正snapshot → 不正観測として安全側停止

一部Workの外部利用能力不足は、そのWorkの待機・停止理由とする。Mission全体の停止可否は独立実行可能Workの有無まで評価して決める。

---

## 19. 秘密情報を含まない診断

保持可能:

- 安定したIssue / PR / run / review ID
- branch ref
- commit / blob SHA
- 型付きstatus / conflict / disposition
- 上限付き件数
- timestamps

保持禁止:

- token / API key
- Authorization header
- `.env`内容
- DB URL / password
- 提供元の生エラー本文
- 通常診断に不要なIssue / PR自然言語本文

---

## 20. 必須受け入れ試験

### 観測・再調整

- GitHub現在状態と最新Checkpoint一致 → 競合なし
- Mission Checkpointだけ古い → `MISSION_CHECKPOINT_STALE`、再調整後`PASS`
- 複数正本作業系列 → `STOP`
- 不明作業系列 → `STOP`
- 正本blob不一致 → `STOP`
- 説明不能なHEAD変更 → `STOP`
- Project #7利用不可 → 安全側停止
- Project #6 identity → 明示拒否

### 選択

- 現在実行可能Workを継続
- 現在review待ち + 独立Ready Work → 独立Workを選択
- 人間確認待ち + 独立Work → Mission `ACTIVE`で切替
- 優先度`P0 > P1`
- 同順位は安定したIssue番号で決定
- 待機専用`In progress`が実行可能`Ready`を飢餓状態にしない

### 再開判定・作業パケット

- 競合0 → Resume `PASS`
- 競合1件以上 → `STOP` / Task Packetなし
- Task Packetにauthority / scope / non-goals / exact target / dependencies / acceptance / risk / lineage / transitionを含む
- 秘密情報を含まない

### 重複・待機

- 同一`ScheduleKey`を二重割当しない
- Checkpointに同一packet identityがあれば再起動後も抑止
- review / CI待ちを高頻度監視しない
- 独立Workなし + 外部待ちのみ → `YIELD_EXTERNAL`

### Mission完了

- 1 Work完了だけで`MISSION_COMPLETE`にならない
- 候補0だけで`MISSION_COMPLETE`にならない
- 明示的なRoot / Mission完了証拠満了時だけ`MISSION_COMPLETE`

### 書込み判定

- 厳密前条件一致 → `PASS`
- head変更 → `STALE_WRITE_GATE`
- Project field IDが古い → 拒否
- Project #6対象 → 拒否
- 変更後再取得不一致 → 効果未確認として安全側停止

### 技術品質判定

- 対象試験
- Ruff
- 厳格Mypy
- 全pytest
- compileall
- `git diff --check`
- 厳密HEAD CI
- 厳密HEAD正本レビュー

---

## 21. 対象外

#465では次を実装しない。

- OpenAI Responses APIレビューワー通信 / 認証情報仲介
- レビューワー認証情報保持
- PostgreSQL運用記憶schema / migration
- Codex実装エンジンそのもの
- 製品実行時の割当
- Core Attention / Executive / Activity scheduling
- GitHub Project #6対応
- 人間確認の自動代替

これらは#462の別責務、または製品設計の各所有者が持つ。

---

## 22. 完了契約

#465は、GitHubの現在snapshotから決定論的に`SupervisorDecision`を生成し、競合時の安全側停止、依存関係準備済みWork選定、Resume Certificate / Task Packet、待機切替、重複抑止、書込み判定、Mission完了の誤判定防止を自動試験で証明し、厳密HEAD CIと正本レビュー`PASS`を得た時点で実装完了候補となる。

個別#465完了後もMission #450はRoot #317完了まで`ACTIVE`を継続する。

## 23. Loop Engineeringの項目別正本

`loop_integration_recovery.md`の項目別正本表を本Mission監督の上位契約として採用する。特にProject #7が所有する`Status`、`Priority`、`Area`、`Issue level`、`Start date`、`Target date`はProject #7の現在値だけが正本であり、Work / Mission Checkpointは上書きしない。

Checkpointはtransition、TaskPacket、health、経緯の永続証拠に限定し、現在状態との不一致は修復または競合として扱う。
