# Loop自律Runner

## continuous host command

`python -m tools.loop_engine`はtrusted host上で動く**continuous Mission runtime**である。内部のcontrol-plane transitionは引き続きboundedとする。

`Preflight → Observe → Reconcile → Resume Gate → Select → Plan/Execute/Wait/Integrate → Readback → Checkpoint`

安全なtransitionが1回完了しただけではprocessを終了しない。`COMPLETED`後はGitHubをfresh observeし、次のbounded transitionを自動開始する。これにより1 transitionごとのmutation safetyを維持しながら、人間がcommandを繰り返し起動する必要をなくす。

`python -m tools.loop_engine --once`は診断用の1 transition実行を維持する。

continuous runtimeは、machineで解決可能なcurrent-head CI pending状態だけを粗いbounded intervalで待機し、自動でfresh observeしてよい。review、Human Verification、credential、provider等の外部条件をbusy pollingしてよいという意味ではない。独立したactionable Workがない場合、これらはtypedな`YIELD_EXTERNAL`として現在のruntimeを終了する。

Codex executionには固定wall-clock kill timeoutを設けない。長時間でも生存しているCodex childは現在のbounded transitionへ接続したままにし、実行中はheartbeatを出す。処理時間そのものはfailure evidenceではないため、旧30分kill境界は禁止する。明示的なprocess failure、launch failure、SIGINT等のdeterministic failureは引き続きfail-closedとする。

`python -m tools.loop_engine --validate-installation`は非変更のinstallation smoke pathである。CLIはsecret-safeなtransition progressをstderrへ、構造化されたtransition resultをstdoutへ出力する。

## portと実行境界

決定論的Coreは`MissionSupervisor`、typed snapshot、Resume / Write gate、注入されたexecutor / verifier / checkpoint portを保持する。repositoryはこれらのcontrol-plane概念を`gh`、Codex、repository rootへ接続するai-liver-yura host compositionも提供し、Loop Engineeringを`app/**`へ混在させない。

host compositionは最新#450 Mission Checkpointをdiscovery candidateとしてのみ扱う。古いparse可能なCheckpointへ遡らない。最新Checkpointは`current Work`を明示し、PR-backed Workなら`current PR`とexact HEADも記録する。current target identityが欠落または不正な場合はfail-closedとし、Codex dispatchやGitHub mutationへ進まない。

planning-only Codexの出力もmachine-readable contractの一部である。選択した次WorkのCheckpointにはliteral field `- current Work: #<issue>`を必須とする。active PRがある場合は`- current PR: #<pr>`と`- exact HEAD: <40-hex-sha>`も必須とする。`選択した次Work:`等の別名で代用しない。active PRがないWorkではPR / HEADを捏造せず省略する。

安全に分類可能なobserve failureは、曖昧なstatusへ潰さずtyped causeを表示する。特に不正な最新Checkpointは`GITHUB_OBSERVE_FAILED:MISSION_CHECKPOINT_TARGET_UNRESOLVED`として表示する。credential、transport、invalid JSON、GitHub response shape不整合もsecretを出さずに個別分類する。

Codex start、CI判定、Ready、merge、Issue close、Checkpointの前に、hostはlive Issue / PR / branch / HEADをfresh readし、staleなCheckpoint targetを拒否する。chat memoryを実行Authorityとして扱わない。

`CodexExecutor`は固定argvとsanitized child environmentを使用する。Reviewer credentialやdatabase credentialを渡さず、TaskPacketやMission instructionをshell interpolationせず、repository rootから実行する。1 bounded transitionで起動できるCodex childは1つだけとする。

## CodexのGit操作境界

actual hostのImplementerはbranch作成、commit、push等のGit metadata変更を必要とする。`workspace-write` sandboxでは`.git`への書込みが拒否されるため、既定commandは`danger-full-access`を明示する。

```text
codex -a never exec --sandbox danger-full-access <instruction>
```

これはactual host上の自律実装を成立させるための機能要件である。child environmentのsecret制限は別境界として維持する。

Codex processがexit 0でも、それだけではexecution identity evidenceにならない。実装、CI repair、merge reconciliationの後はtrusted hostがGitHub live stateをfresh readし、Checkpoint identityとPR / HEAD identityが実際に前進したことを確認する。進捗がなければ`IMPLEMENTER_NO_PROGRESS`としてfail-closedにする。

## #471 pilot routing

#471はLoop Engineering bootstrap / integrationの状態を保持するIssueであり、actual product pilotそのものではない。

#477 merge後に`current Work: #471`かつactive PRなしとなった場合、通常implementation continuationへ送ってはならない。hostはこの状態をpilot planning-only stateとして扱い、#471をcompleted_workとしてplanning-only Codexを起動する。

plannerは#462 / #471自身とLoop Engineering基盤Issueを除外し、GitHub live stateとProject #7からdependency-readyなactual V2 product Workを1件選択する。

planning後は最新Mission Checkpointをfresh readする。

- 別product Workへcurrent Workが移動した場合は`PILOT_PLANNING_DISPATCHED`として次transitionへ進む。
- Checkpointは更新されたがcurrent Workが#471のままなら`PILOT_DEPENDENCY_WAIT`としてyieldする。
- Checkpointが更新されなければ`PILOT_PLANNING_NO_PROGRESS`としてfail-closedにする。

## host stage routing

#450からdiscoveryしfresh resolveしたcurrent Workについて、次のように処理する。

- current implementation PRがない通常Work、またはimplementation / CI repairが必要な場合はCodexを1回起動し、その後GitHubをfresh readしてobserved resultをCheckpointへ記録する。
- exact current-head CIがない、または`queued` / `in_progress`ならbounded transitionは`YIELD_EXTERNAL`とする。continuous CLIはoperator介入なしで待機し、current-head CIをfresh re-observeしてよい。
- exact current-head CIがfailedなら同一lineageのfunctional repairとしてCodexを1回起動する。
- exact current-head CIがPASSし、既知のreproducible functional blockerがなければ、必要に応じてReady化し、normal expected-head merge、merge / trunk readback、Work completionへ進む。
- stale CI / head / checkpoint identityはreconciliationのためfail-closedにする。
- review `REQUEST_CHANGES` / `NOT_RUN`だけでは、現在のMission policy上functional pathをblockしない。

Work merge後は、次のbounded transitionでCodexをplanning-onlyとして1回起動し、#207 / #317 / #450 / #462とProject #7をfresh readして、次のdependency-ready Workを選択してよい。このplanning transitionではproduct / control-plane codeを変更せず、mergeも行わない。Checkpointには次transition用のcurrent Work / PR / HEADを明示する。

## continuous runtimeの規則

- `COMPLETED`なら直ちにfresh observeし、次のbounded transitionへ進む。
- `YIELD_EXTERNAL / CI_PENDING`ならcontinuous modeでは粗いintervalで待機し、fresh observeする。待機中はmutationしない。
- その他の`YIELD_EXTERNAL`は、schedulerが別のdependency-ready Workを既に選択していない限り安全にprocessを終了する。
- `INTERVENTION_REQUIRED`はtyped reasonとlog pathを残してfail-closedで停止する。
- Mission completionはRoot #317のcompletion evidenceがcanonical completion contractを満たした場合だけ正常終了する。
- `--once`は上記に関係なく1 bounded transitionでreturnする。

continuous host runtimeであっても、same-head review pollingは禁止する。review pending、Human Verification、credential、provider recovery等の外部待機はno-busy-poll規則を維持する。

## transition規則

- Resume conflictではimplementation TaskPacketを生成せず、mutationしない。
- CI evidenceはpending / success / failure判定の前にexpected live headへbindする。current-head CIがpending / runningならyieldし、failureなら同一lineageのrepair transitionへ戻す。
- independent reviewはdiagnosticである。deterministic / reproducibleなfunctional blockerだけがrepairを強制し、review provider failureやnon-functional hardeningではmergeを止めない。
- mutationはfresh precondition → effect → effect readback → checkpointの順で行う。canonical trunkへのdirect implementation writeとProject #6 targetはhard rejectする。
- Implementer completion → live-head readback → exact-head verificationを1つのidentity chainとして扱う。process exit code、old CI result、別SHAのverification resultだけでtransitionを前進させない。
- SIGINTでは新しいmutationを受け付けず、既存graceful-shutdown境界でcurrent childを終了し、次runでreconcileできるGitHub stateを残す。

## CLI exit semantics

`--once`では、`0`は安全なtransition完了、`2`は`YIELD_EXTERNAL`、`3`はfail-closed intervention / reconciliationを意味する。

既定continuous runtimeでは中間のcompleted transitionでprocessを終了しない。non-auto-resumable yield、intervention、またはMission completionに達した時だけ最終exitする。exit statusだけで外部API responseをeffect truthへ格上げしない。
