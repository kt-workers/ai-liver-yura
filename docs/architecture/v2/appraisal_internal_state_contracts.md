# V2 Appraisal・Internal State実装契約

Status: Issue #327 implementation canonical
Parent: `brain_architecture.md`
LLM: `llm_role_contracts.md`
Concurrency: `concurrency_architecture.md`

## 1. 責務とAuthority

Subjective Appraisalはtyped Event/Input Meaningを、現在のゆらの状態・関係・Goal・Activity・Values等に照らして評価し、`AppraisalCandidate`と`StateDeltaProposal`を生成する。candidateは事実やcurrent stateではない。

`InternalStateReducer`だけが`InternalStateSnapshot`を書き換える。LLM、Character、Body、Memory、Input Meaning、Appraisal自身はcurrent stateを直接mutationしない。AppraisalはFocus/Goal/Activityを決めず、salience/relevanceを#333へ候補として渡すだけである。

## 2. Internal State

facet familyは次を区別する。

- Emotion
- Desire
- Drive
- Motivation
- Value/Moral appraisal
- target Interest/Curiosity
- Relationship
- Energy
- Arousal

各`InternalStateFacet`は`facet_kind / state_key / target_ref? / current / previous / last_delta / causes / updated_at`を持つ。値は有限な`[-1, 1]`、confidenceは`[0, 1]`とし、bool、NaN、infinityを拒否する。Characterのstatic traitは入力感度になり得るがdynamic facetとして複製しない。

Snapshotはmonotonic `revision`とtimezone-aware `updated_at`を持つimmutable owned tupleである。同じ`facet_kind + state_key + target_ref`を重複保持しない。

`revision`は`source_context_revision`とは独立したstate世代である。Reducerがsource contextを変えずにstateだけ更新できるため、Internal Stateを入力にするlong-running Executiveはrequest時のこのrevisionを`ExecutiveFreshnessStamp`へ保持し、LLM完了後にcurrent state revisionを読み直して一致しない結果をcommitしない。これをFoundation共通`RevisionVector`へ暗黙に包含したものとして扱わない。

### 時間関数管理の基本原則

- 内部状態は数値を廃止するのではなく、**Reducerが確定した有限数値・原因・世代をアンカーとして、採用済みの時間関数を時刻指定で評価できる状態**とする。投影した値のみを「心理状態の全体」とみなさない。
- 既存9系統のfacet identity、`InternalStateSnapshot`、`InternalStateReducer`、`AppraisalCandidate`、`StateDeltaProposal`、stale/currentness規則を維持する。
- **確定状態**と**関数を読んで得た時点別投影**を別型・別Authorityとして扱う。投影のreadは状態更新、Goal、発話決定、実測事実ではない。
- LLMや記憶やBodyが確定状態を直接書かない。発話/沈黙はExecutiveの選択であり、値の閾値判定を新設しない。
- 任意のPython関数オブジェクト、LLM生成コード、eval、pickleを状態の保存形式にしない。関数種別・policy identity/revisionと検証済みパラメータを宣言的に保存する。

以下は新たに導入すべき**論理契約名**であり、現在のPythonに実装済みという意味ではない。

```text
StateTrajectoryAnchor
- facet_ref                         # 既存kind/key/target_ref
- committed_value                   # Reducerが確定した値 [-1,1]
- committed_at                      # timezone-aware絶対時刻
- state_revision
- source_context_revision
- confidence                        # [0,1]
- cause_refs[]
- evolution_policy_id/revision

TemporalFacetProjection
- facet_ref
- as_of                              # 1 request中共通の評価時刻
- anchor_identity
- projected_value?                   # [-1,1]; 評価不可ならなし
- evolution: DECAYED | HELD_NO_RULE | NOT_EVALUABLE
- delta_since_anchor?                # 算出根拠があるときのみ
- supported_trend?                   # 履歴・方針から示せる変化
- cause_refs[] / evidence_refs[]
- evolution_policy_id/revision

InternalStateTemporalView
- source_state_revision
- source_context_revision
- as_of
- projections[]
- supported_baseline_differences[]   # 根拠ある個体基準に限る
- evidence_refs[]
- view_identity
```

- 既存の`InternalStateFacet.current/previous/last_delta/confidence/causes/updated_at`は確定値のまま保持する。新たな投影でその値を上書きしない。
- facetsが未登録なら0へ補完せず未観測として扱う。過去感情記憶やCharacter静的Traitから新しい現在facetを捏造しない。
- view全体を同じstate revision、source context revision、関数policy generation、`as_of`に束縛し、部分取得値を異なる世代から寄せ集めない。
- 現在値、直近の確定delta、原因、時間的推移、通常との差をそれぞれ別項目とする。未確定の基準や不連続点の導関数を作らない。

## 3. Appraisal Candidate

`AppraisalCandidate`は次を持つ。

- candidate/source event identity
- fast deterministic / deep LLMの生成経路
- source context revision / base state revision
- typed appraisal dimensions
- zero以上の`StateDeltaProposal`
- salience / relevance candidate
- causes / evidence refs
- created_at

appraisal dimensionsはpleasantness、novelty、goal congruence、controllability、certainty、social meaning等のtyped keyと有限値で表す。LLM自由文をstate valueとして使わない。

## 4. State Delta

`StateDeltaProposal`はfacet identity、signed delta、cause refs、confidenceを持つ。deltaは「次の絶対値」ではなく現在値への変更候補である。

Reducerは以下をcommit前に検証する。

- candidateのbase state revisionがcurrent revisionと一致
- source context revisionがcallerのcurrent revisionと一致
- candidate/source/cause identityが空でない
- proposal facet重複なし
- result valueが`[-1, 1]`内（silent clampしない）
- timestampがstate/candidateより前でない

成功時だけrevisionを1増やし、各facetのcurrent/previous/delta/causes/updated_atをatomicな新snapshotとして返す。競合candidateはrevision mismatchでstale rejectし、Core global lockへ拡張しない。

## 5. Fast / Deep path

```text
typed event / meaning
├─ deterministic fast appraisal rule → candidate
└─ optional deep LLM request          → candidate
                                      ↓
                         revision/authority validation
                                      ↓
                         InternalStateReducer commit
```

fast ruleはtyped event kind・typed meaning fieldを入力にし、raw text、keyword、regexを意味Authorityにしない。deep LLMは#323のRole request/resultを使い、Provider SDKをDomainへ入れない。Deep結果は後着時にrevisionを再検証し、staleならcurrent stateへ適用しない。

## 6. Decayと時間

decayは明示的な`DecayPolicy`と経過秒からdeterministic proposalを生成する。wall clockをDomain内部で読むこと、sample/timer回数をdelta量にすること、全facetをneutralへ即時resetすることを禁止する。facetごとのhalf-lifeとneutral baselineを使い、elapsedが同じなら同じproposalを返す。

### AppraisalとReducerの時刻別状態調停

```text
信頼済みEvent/Meaning/Memory等
 → AppraisalCandidate / StateDeltaProposal
 → ownerがcurrent snapshotとpolicy generationを確認
 → Decay確定が必要なら既存Decay ProposalをReducerへcommit
 → 新しい確定snapshotを基準にAppraisal候補を再構築/現在性検証
 → Reducerが唯一の短い原子的commitを行う
 → state revisionを進め、新しいanchorとして公開
 → 時刻指定read view、Attention/Executive/Bodyへ由来付きで投影
```

- 読み取っただけでは`InternalStateSnapshot.revision`を増やさない。減衰を先に正規commitした場合は、新しいanchorから将来分を評価する。同じ経過秒を二重に減衰しない。
- Appraisalの旧候補を新しいanchorへ付け替えず、元revision mismatchならstale reject。必要なら新requestを開始する。古い結果を最新状態へ暗黙mergeしない。
- Decay/Presentation/Executiveの独立した非同期処理はDomain lockを待ち続けない。Reducer lockは短いatomic mutationのみを保護し、LLM/DB/外部callbackを内包しない。
- この調停フローは**新しい設計要求**であり、現在のReducerが時点別投影を自動適用しているという意味ではない。

## 7. Startup / Resume

startup/resumeはtyped lifecycle eventとしてAppraisalへ入る。previous snapshot、停止時間、現在contextからdecay/reappraisal candidateを生成する。previous valueをcurrentへ無条件復元せず、固定neutralや固定Awakening presetにも置換しない。Speech/Body/Silence選択は後続Attention/Executive責務である。

## 8. LLM schema境界

Deep Appraisal Role inputはsource event/meaning参照、bounded current state view、relationship/goal/activity/value context、必要revisionだけを持つ。outputはstrict JSONのdimensions、salience/relevance、typed delta proposalsであり、schema外field、未知facet、重複proposal、非有限値を拒否する。

Role exchange identity/schema/timestamp/revisionを検証後も、Reducerのcurrent revision検証を必須とする。LLM成功はcommit成功ではない。

## 9. 因果境界

- Emotionは出来事の主観評価状態であり、表情parameterではない
- Desireは方向を持つ持続状態で、Goalそのものではない
- Drive/Energy/Arousalは行動準備状態で、Activityを選ばない
- Motivationは派生した「なぜしたいか」で、Executive decisionではない
- Interestはtarget付きで、全体curiosity値だけに退化しない
- Relationshipは相手ごとのdynamic stateで、Language後処理だけにしない
- Value/Moral stateはSafety/permissionの代替ではない
- Body pose、Character speech、Memory過去値からcurrent stateを逆算しない

## 10. 並行性

Deep Appraisal awaitは呼出taskだけを待たせ、global lock/queueを所有しない。新規Input、Body realtime、Speech/Game等は継続できる。fast candidateとdeep candidateが競合した場合もstate revisionで順序を閉じ、古いdeep resultを最新stateへmergeしない。

## 11. 受入条件

- cause / decay / conflicting affectをtyped snapshotで検証
- startup/resumeをprevious stateとdowntimeから因果評価
- target Interest/Relationshipをtargetなしglobal値へ潰さない
- deterministic fast appraisalがraw NL matcherを持たない
- Deep LLM candidateのstrict schema・identity・revisionを検証
- invalid/out-of-range/duplicate StateDeltaをreject
- stale candidateをcurrent stateへcommitしない
- slow Deep Appraisal中もunrelated async taskが進行
- Input Meaning、Goal、Attention、Character、Body、MemoryのAuthorityを奪わない
- 全公開snapshotがstrict JSON serializableかつimmutable

### 関数状態の未定義値と実装境界

本契約は**関数評価の正本構造**を定めるが、次を架空の値で埋めない。

- 未定義facetの自然変化・回復・相互作用に関する数式。
- 個体baselineの観測窓・品質・適用基準。
- 投影viewに固有の容量、秒数による意味失効、履歴圧縮・保存頻度。
- Owner固有のrestart-safe current stateを正式承認するための移行条件。

実装着手時は、Appraisalの正規状態更新Owner、Executiveの入力schema/port/fence、PersistenceのDomain-owned再構築、Speech/Characterの権限をそれぞれ個別に改修する。現在のソースがこの契約を満たしたという記述ではない。

## 12. Deep Appraisalのpost-await live freshness — Issue #414

Deep Appraisalは、LLM開始時にfreezeした入力snapshotと、LLM完了後のcommit freshness Authorityを分離する。

開始時の世代は次の2値で固定する。

- `request.revisions.source_context_revision`
- requestへ埋め込んだ`InternalStateSnapshot.revision`

これらはProviderへ渡した入力世代のprovenanceであり、LLM完了後のcurrent値として再利用しない。

production `DeepAppraisalInterpreter.appraise()` はProvider完了後、candidate確定直前にread-onlyなlive state read境界から、少なくとも次を一組のimmutable freshness stampとして取得する。

```text
DeepAppraisalFreshnessStamp
- source_context_revision
- state_revision
```

実装上のPort名は`DeepAppraisalLiveStatePort`または同等の責務名とする。Portはsource contextやInternal Stateをmutationせず、Provider SDK objectやmutable owner objectを返さない。

### 12.1 live readの一貫性

`source_context_revision`と`state_revision`を、LLM開始前にcallerが個別取得した値の寄せ集めで構成してはならない。post-await時点のlive世代を一貫したlogical readとして取得する。

所有Storeが別の場合、実装は次のいずれか同等の方法でstable readを成立させる。

- composition層が提供するversioned composite snapshot
- owner側のserialized read境界
- boundedなversion-stabilized readにより、読取中の世代変化を検出してretryまたはfail-closedする方式

stableな一組を確立できない場合はfail-closedとし、古い候補を採用するためにglobal lockへ拡張しない。

### 12.2 production commit順序

正規経路は次とする。

```text
request snapshot freeze
→ await Deep Appraisal Provider
→ post-await live freshness read
→ request時世代との完全一致検証
→ pure candidate commit validation
→ AppraisalCandidate
→ InternalStateReducer
```

`DeepAppraisalInterpreter.appraise()`は、開始時の`current_source_context_revision`や`current_state_revision`をpost-await Authorityとして受け取るproduction APIを持たない。既存のpure `commit_deep_result()`がexplicit current revisionを受け取る形を維持することはできるが、production orchestrationは必ずpost-await live stampを渡す。

live read完了から`commit_deep_result()`までに、Provider call、別の外部I/O、不要なasync waitを挟まない。

### 12.3 stale判定

次のどちらかが一致しなければDeep resultはstaleとしてfail-closedする。

```text
request.revisions.source_context_revision
== live.source_context_revision

request時 InternalStateSnapshot.revision
== live.state_revision
```

staleまたはlive read failure時は`AppraisalCandidate`を生成しない。特に禁止する。

- old resultのsource context revisionをlive revisionへ付け替える
- old resultのbase state revisionをlive state revisionへ付け替える
- old resultをnew InternalStateSnapshot / new contextで再利用する
- stale検出時に暗黙の再LLM requestを開始する
- fallback AppraisalCandidateを補作する

再評価が必要なら、上流が新しいrequest generationとして起動する。

### 12.4 provenanceとReducerの二重Gate

正常に生成した`AppraisalCandidate`は、**request時**の`source_context_revision`と`base_state_revision`を保持する。post-await live stampは「まだ同じ世代か」を確認するAuthorityであり、candidate provenanceを書き換える値ではない。

LLM待機中にstaleになった候補はReducerへ渡す前に拒否する。その後、live gate通過からReducer atomic commitまでの短い競合窓で世代が進んだ場合は、`InternalStateReducer.commit()`自身のcurrent source/state revision検証が最終Authorityとして拒否する。したがってpre-reducer gateとReducer gateの両方を維持し、どちらか一方へ統合しない。

### 12.5 concurrency invariant

- post-await live readのためにCore global lockを導入しない
- Deep Appraisal待機中もnew Input、fast Appraisal、Body realtime、Speech/Game等を継続できる
- Deep Appraisal専用のserial blocking cycleを作らない
- stale Deep resultを最新stateへmergeしない

### 12.6 必須Regression

- request `(source=N, state=S)` でDeep LLM開始後、sourceだけ`N+1`へ進む → production `appraise()`でstale reject
- request `(N, S)` でDeep LLM開始後、stateだけ`S+1`へ進む → production `appraise()`でstale reject
- source/stateとも不変 → 正常candidate生成
- live freshness read失敗またはstable pair確立失敗 → fail-closed / candidateなし
- stale resultのsource/state revision付替えがない
- old resultをnew snapshot/contextへ再利用しない
- LLM待機中にstaleとなった候補がReducerへ渡らない
- live gate後に競合が発生した場合はReducerのatomic stale gateで拒否される
- slow Deep Appraisal中もunrelated async workが進行する

## 13. 文脈更新をまたぐ状態の由来と新しい評価

`InternalStateSnapshot.source_context_revision`は、その状態を最後に確定した際の文脈の由来である。目標・活動などにより現在文脈が進んでも、状態の値や由来を構成側で付け替えない。状態リビジョンと、今回の出来事・意味の文脈リビジョンは独立して保持する。

深い評価の要求は、状態の由来と同じ、またはそれより新しい文脈の出来事を受け取る。要求には元の内部状態をそのまま格納し、要求の文脈は出来事・意味の文脈とする。状態より古い文脈への後退は深い評価・定型評価の入口と状態確定で拒否する。意味と出来事の文脈一致は維持する。

応答後は従来どおり要求の文脈と現在文脈、要求時の状態リビジョンと現在状態リビジョンをそれぞれ再照合する。新しい文脈への要求を許可することは、待機中に古くなった結果の採用許可ではない。候補は要求の文脈と元状態のリビジョンを保持し、Reducerの確定成功時だけ更新後状態と評価事実が今回の文脈を持つ。元状態・候補のリビジョンを呼出し側で変更する入口を追加しない。

## #690の本番構成参照

Deep Appraisal実行方針、fresh-start初期化方式、Decay具体規則と構成世代の値の正本は[Appraisalの本番構成](appraisal_production_configuration.md)とする。既存の意味・Reducer Authority・式・現在性を変更せず、ここへ具体値を重複定義しない。同文書は設計レビュー待ちであり、resource・loader・factoryの実装や本番採用は未完了。
