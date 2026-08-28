# Loop統合と復旧

## フィールド別の正本

| フィールド | 正本 |
| --- | --- |
| Issue状態 | GitHub live Issue |
| PR / head / base | GitHub live PRとbranch |
| CI | exact-headのGitHub Actions証拠 |
| Project Status / Priority / Area / Issue level / Start / Target | Project #7 live |
| canonical design | repository canonicalのblob identity |
| Work checkpoint | transition、TaskPacket、health、永続的な経緯 |
| Mission checkpoint | current Workの経緯とnext action |

Checkpointの値でProject #7が所有するフィールドを上書きしない。liveの正本と矛盾した場合はlive stateから修復するか、fail-closedで停止する。

## 復旧順序

変更を伴うtransitionは、必ず `fresh observe → WriteIntent → fresh precondition → effect → effect readback → checkpoint → fresh observe` の順で実行する。timeoutやcrashが発生した場合、remote targetをreadbackするまでeffectの成否を確定しない。

v1では1つのtrusted hostだけがmutation leaseを保持する。外部待機は並行して存在してよいが、変更可能なactionable transitionは同時に1つだけ実行する。multi-host active-activeはv1の対象外とする。

## actual hostのtarget解決

通常のLoop CLIは、#450の**最新** `Mission Checkpoint` commentだけをdiscovery recordとして使用し、古いparse可能なCheckpointへ遡らない。変更可能なCheckpointは最低でも`current Work`を明示し、PRが存在する場合は`current PR`と観測したexact HEADも記録する。

Checkpointのtarget自体は実行Authorityではない。parse後、CI判定、Codex dispatch、Ready、merge、Issue close、Checkpoint投稿の前に、Work IssueとPR / branch HEADをGitHubからfresh readする。Checkpoint HEADとlive PR HEADが異なる場合はstaleとして扱い、reconciliationが完了するまで変更しない。

最新Mission Checkpointに明示的なcurrent targetがない、target identityが不正、またはGitHub live stateとreconcileできない場合、hostはtypedなfail-closed結果を返す。過去の完了済みWorkを再実行する危険があるため、古いMission Checkpointへsilent fallbackしてはならない。

次Workを選択するplanning-only Codexは、次のhost invocationが必要とするcurrent Work / PR / HEAD identityを明示した新しいMission Checkpointを必ず作成する。

## merge conflictのreconciliation

PRのmergeabilityはGitHub liveを正本とし、Readyまたはmerge mutationの直前にも再確認する。PRが`mergeable=false`または`mergeable_state=dirty`の場合、exact-head CIが成功していてもReady化せず、直接merge commandへ送らない。

merge conflictは、それ自体ではHuman interventionではなく、対処可能なproduct lineage状態である。hostはCodexへ1 bounded transitionだけfunctional reconciliationをdispatchする。Codexは修復方法を決める前に、最新Mission Checkpoint、current Work / PR、current trunk、canonical design、dependency state、Work固有のResume Gateをfresh readする。

- 既存lineageが有効なら、current trunkをfeature branchへnormal mergeし、競合を解消する。
- canonical Resume Gateが既存lineageをobsoleteと判定した場合は、current trunkから新しいlineageを作成してidentityを記録する。

force pushとrebaseは禁止する。reconciliation transition内ではproduct PRをmergeしない。必要なdesign / code / testを更新し、適用可能なmachine gateを実行し、normal push後に新しいexact HEADをfresh readして明示的なMission Checkpointを1回記録する。次のhost invocationが新しい状態を再観測し、CI / mergeを通常経路で処理する。

expected-head merge commandが失敗し、fresh GitHub readbackでもmerge conflictと確認できない場合、credential、permission、transport failure等をsource conflictとして誤分類せず、`EXPECTED_HEAD_MERGE_FAILED`を維持する。

## Codex host実行契約

trusted hostは、廃止・互換用の`--full-auto` shortcutへ依存せず、現在のCLI contractを明示してCodexを起動する。

actual hostでbranch / commit / pushを含む通常のGit操作まで自律実行するため、既定のCodex childは次と同等とする。

```text
codex -a never exec --sandbox danger-full-access <instruction>
```

`workspace-write`では`.git` metadataへの書込みが拒否される環境があり、branch作成、commit、normal pushを完遂できない。その状態でCodexがexit 0を返しても実装成功とは扱わない。

`codex --version`の成功だけでは、この実行契約が利用可能という証拠にならない。actual pilotでは、childが必要なbounded transitionを実際に実行できることを証明する。CLI syntax不整合、実効read-only状態、network不可、Git metadata書込み不可等で割り当てたtransitionを実行できない場合はfunctional blockerとして扱う。

Codex childへ渡すenvironmentは引き続きhost側で制限する。Reviewer credentialやdatabase credentialをchild environmentへ追加しない。`LOOP_CODEX_COMMAND_JSON`でtrusted host用commandを上書きできるが、上書き側も必要なGit操作能力とsecret boundaryを維持しなければならない。

## implementer進捗のreadback

Codex processのexit code 0だけでは`COMPLETED`にしない。実装、CI repair、merge reconciliationをdispatchした後はGitHub live stateをfresh readし、次の両方を確認する。

- Mission Checkpointのcomment identityが更新されている。
- current PRまたはexact HEADのidentityが実際に前進している。

どちらかが変化していない場合は`IMPLEMENTER_NO_PROGRESS`としてfail-closedにする。これにより、Codex内部でGit操作が失敗したのにprocessだけ正常終了し、同一transitionを連続再実行する状態を防ぐ。

## #471 bootstrap後のrouting

PR #477はactual host Loopを実行可能にするbootstrap implementationである。PR #477のmergeだけでは#471のcompletion evidenceにならない。#477がtrunkへ入った後も#471はopenのまま保持し、hostがdependency-readyなactual V2 product Workをpilotとして選択する。

`current Work: #471`かつactive PRなしの状態は、通常のimplementation continuationではなく**pilot planning-only state**として扱う。この状態でCodexへ#471のコード実装を再dispatchしてはならない。

hostは#471をcompleted_workとしてplanning-only Codexを1回起動し、#462 / #471自身とLoop Engineering基盤Issueを除外してactual V2 product Workを選択させる。planning後は最新Checkpointをfresh readし、別のproduct Workへcurrent Workが移動したことを確認する。

Checkpointは更新されたがcurrent Workが#471のままなら、dependency-readyなproduct Workが存在しない待機状態として`PILOT_DEPENDENCY_WAIT`を返す。Checkpoint自体が更新されなければ`PILOT_PLANNING_NO_PROGRESS`として停止する。

## runtime observability契約

通常CLIはbounded transition中に無反応へ見えてはならないが、既定のterminal出力は読みやすく保つ。人間向けprogress、詳細diagnostic、machine-readable completion outputを分離する。

- 既定stderrにはstartup、log path、主要stage開始、Codex dispatch / completion、failure、final resultだけを簡潔に表示する。
- 成功したGitHub / API child commandの反復start / doneとCodex raw outputはpersistent run logへ保存し、既定terminalでは非表示にする。
- `--verbose`指定時だけ詳細child commandとCodex raw streamをstderrへ表示する。
- stdoutはfinal `HostTransitionResult` JSON専用とし、scriptが決定論的にparseできるようにする。
- terminal verbosityに関係なく、すべてのrunで安全なchild outputを`logs/loop_engine/`配下へ保存する。
- secret値、`.env`内容、Reviewer credential、database credential、sanitized environment全体、promptやsecret相当値を含むfull argvはlogへ出さない。

failure時は既定terminalへstageとexit / result codeを表示し、詳細log pathを案内する。observabilityはactual-host operabilityの一部だが、通常の低レベルtrafficでoperator consoleを埋めてはならない。

## exact-head CIの判定順序

CI evidenceは、まずexpected current headへbindしてからlifecycle statusを解釈する。observed workflow runが別HEADのものなら、そのrunが`queued`または`in_progress`でも`STALE`とする。old headのpending runによってcurrent Workを誤ってCI pendingとしてyieldしてはならない。

`evidence.head_sha == expected_head_sha`を確認した後にのみ、`queued` / `in_progress`を`YIELD_EXTERNAL`、`success`を`PASS`、その他のterminal conclusionを`FAILED`として扱える。

## 待機と完了

`CI_PENDING`、`REVIEW_PENDING`、`HUMAN_VERIFICATION_PENDING`、credential、provider、Project、database outageはtyped waitとして扱う。独立したactionable Workがあれば進め、なければbusy retryせずrunnerをyieldする。

review waitやprovider側の`NOT_RUN`だけではcompletion blockerにならない。review findingは、現在のMission policyでdeterministicまたはreproducibleなfunctional failureが証明された場合だけblockingとする。

`MISSION_COMPLETE`には、Root #317、required Work / Integration、human / system verification、runtime boot / continuous / restart / graceful-shutdown、functional blocking conflict 0件の明示的な証拠が必要である。candidate 0件やWork 1件のmergeだけでは不十分とする。

## E2E受け入れ条件

integration suiteでは、new Workからnormal merge、functional repair、pending yield / resume、stale CI / review rejection、push / review / merge後のcrash recovery、DB degradation、Project #7 outage、Project #6 reject、self-improvement dedupe、SIGINT、competing lineage stop、false-completion防止を検証する。

controlled fake-port integrationは必要だが、#471 completionには十分ではない。normal Loop CLIから到達できるhost compositionをrepositoryに備え、実際のPreflight / Observe / Supervisor / Implementer / Verify / Checkpoint境界で、人間がTaskPacketやreview findingをagent間転記せずにbounded transitionを実行できることを証明する。
