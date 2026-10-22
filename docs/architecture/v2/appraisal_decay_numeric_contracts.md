# V2 Appraisal Decay / Numerical Contracts

Owner: #327
Parent: `appraisal_internal_state_contracts.md`
Design gate: #445 D10
Status: Canonical Supplement / implementation-decidability correction

## 1. 目的

`appraisal_internal_state_contracts.md` が要求するfacet decayを、実装者がhalf-lifeの単位、減衰式、rule選択、missing時挙動、数値許容を推測せず実装できるように固定する。

本書はInternal StateのAuthorityを変更しない。`InternalStateReducer`だけがcurrent stateをcommitし、本書はdeterministic `StateDeltaProposal`生成規則だけを定義する。

## 2. Versioned policy

```text
DecayPolicy
- policy_id: non-empty stable identity
- policy_revision: non-negative int
- rules: unique tuple[DecayFacetRule]

DecayFacetRule
- rule_id: non-empty unique identity
- facet_kind
- state_key: optional exact-match key
- target_scope: GLOBAL | TARGETED
- neutral_baseline: finite float in [-1, 1]
- half_life_seconds: finite float > 0
- minimum_elapsed_seconds: finite float >= 0
```

Rules:

- `half_life_seconds`と`minimum_elapsed_seconds`の単位は**秒**。
- bool、NaN、±Infinityをnumeric fieldとして受理しない。
- `(facet_kind, state_key, target_scope)`はpolicy内で重複不可。
- `TARGETED` ruleは`target_ref != null`のfacetだけに適用する。
- `GLOBAL` ruleは`target_ref == null`のfacetだけに適用する。target付きfacetをglobal ruleへ暗黙fallbackしない。
- policyはimmutable/versioned dataであり、Core codeにfacet名ごとのhidden half-lifeやbaselineを埋め込まない。

## 3. Rule selection

対象facetに対するruleは次のclosed precedenceでexactly oneを選ぶ。

```text
1. exact facet_kind + exact state_key + exact target_scope
2. exact facet_kind + state_key=null + exact target_scope
3. no rule
```

- substring、prefix、embedding、Character文言、LLMでruleを選ばない。
- 1または2の同順位で複数ruleがmatchするpolicyはconstructor時にinvalidとして拒否する。
- `no rule`は「neutralへ戻す」ことを意味しない。**そのfacetについてdecay proposalを生成せず、typed `DECAY_POLICY_RULE_MISSING` diagnosticを出す**。
- missing ruleを理由にcurrent valueを0へclamp/resetしない。

## 4. Canonical decay formula

入力:

```text
current_value = facet.current
baseline = rule.neutral_baseline
elapsed_seconds = max(0, now_absolute - facet.updated_at)
half_life = rule.half_life_seconds
```

`now_absolute`と`updated_at`はtimezone-aware timestampをUTC absolute instantへ正規化して差を取る。wall-clock fieldだけを比較しない。

`elapsed_seconds < minimum_elapsed_seconds`ならproposalを生成しない。

それ以外では指数half-life減衰を正本とする。

```text
decay_factor = 2 ** (-elapsed_seconds / half_life)
decayed_value = baseline + (current_value - baseline) * decay_factor
delta = decayed_value - current_value
```

Numerical rules:

- `elapsed_seconds`はfiniteかつ0以上でなければreject。
- `decay_factor`は理論上`(0, 1]`。計算結果が非有限ならproposal生成をfail-closedする。
- `decayed_value`はfloating errorを考慮してもsilent clampしない。`[-1,1]`外ならpolicy/state inconsistencyとしてrejectする。
- `delta == 0.0`（通常の浮動小数点等値）ならno-op proposalを生成しない。
- timer tick回数、sample数、処理回数をdeltaへ掛けない。同じ`current_value / baseline / elapsed_seconds / half_life`は同じproposalを返す。

### 時刻指定の純粋関数評価

```text
read_at(as_of, committed_snapshot, active_evolution_policy)
    -> InternalStateTemporalView
```

1. `as_of`は呼出し側がRuntimeClockから取得し、timezone-aware値として明示注入する。Domain内で壁時計やLLMを呼ばない。アンカー以前や未観測の未来の出来事を外挿しない。
2. 最新の確定facet値をanchorとする。適合するVersioned Decay ruleを、既存のexact facet kind/key/target scopeの優先順位で決定する。
3. ruleがあり必要経過時間を満たす場合、既存の正本指数式だけを使用する。
4. ruleがなくてもデータを勝手に変化させない。既存の`DECAY_POLICY_RULE_MISSING` diagnosticを保持し、`HELD_NO_RULE`は「最後の確定値を提示、自然変化は未定義」の意味とする。Policy全体の欠落・不正は評価失敗とし、`HELD_NO_RULE`で隠さない。
5. 最小経過時間未満はアンカー値の投影のみであり、正規Decay proposalは生成しない。評価で得た値を黙ってclampしない。
6. 同じanchor、policy generation、時刻なら同じ結果を返す。評価不能・非法値・世代不整合は型付き失敗であり、暗黙の別公式による修復を行わない。

既存の関数式は次を**そのまま継承する**。

```text
elapsed_seconds = max(0, as_of - anchor.committed_at)
factor = 2 ** (-elapsed_seconds / rule.half_life_seconds)
projected_value = rule.neutral_baseline
                  + (anchor.committed_value - rule.neutral_baseline) * factor
```

採用済み初期規則は Emotion(global/targeted)半減期300秒、Arousal(global/targeted)半減期120秒、baseline=0、minimum elapsed=1秒。これらは[本番構成](appraisal_production_configuration.md)における初期**校正値**であり、人間心理の実測最適値と主張しない。

Desire、Drive、Motivation、Value、Interest、Relationship、Energyには本番初期方針の自動Decay ruleが**ない**。そこへ減衰や回復の式を推測で追加しない。人格Traitを値へ一対一変換しない。

## 5. Proposal provenance

Decay由来`StateDeltaProposal`は通常の#327 schemaに加え、少なくとも次のprovenanceを保持する。

```text
- decay_policy_id
- decay_policy_revision
- decay_rule_id
- base_state_revision
- source_context_revision
- elapsed_seconds
- evaluated_at
```

`evaluated_at`はproposal生成時刻であり、Reducer commit時刻を捏造しない。

policy revision変更後に旧policy proposalをcurrent stateへ適用してはならない。

## 6. Freshness / commit

Decay proposal生成はpure calculationであり、Reducer commit直前に少なくとも次を再検証する。

- current state revision == proposal.base_state_revision
- current source context revision == proposal.source_context_revision
- current decay policy identity/revision == proposal policy identity/revision
- target facet identityが同じcurrent facetへgroundする

不一致はstale reject。old proposalをnew state/policy revisionへ付け替えない。

Policy ownerが別Storeの場合はversion-stabilized composite read等でcurrent state/policyの一貫した組を取得し、stable read不能ならfail-closedにする。Core global lockへ拡張しない。

## 7. Startup / resume

停止時間を反映する場合も同じ式を使う。

```text
elapsed_seconds = resume_at_absolute - persisted_facet.updated_at_absolute
```

- 起動回数やshutdown理由で倍率を変えない。
- previous snapshotを無条件復元した直後に固定neutralへresetしない。
- persisted stateがowner validationを通らない場合は本decay計算で修復せず、rehydration failureとして扱う。

## 8. Policy calibration boundary

具体的なYuraのhalf-life / baseline値はversioned `DecayPolicy` dataとして与える。Human Verificationで調整する場合もformulaを変更せずpolicy revisionを進める。

Production Compositionは有効なpolicyを明示注入する。policy全体がmissing/invalidの場合、automatic decayをhidden defaultで続けずtyped `DECAY_POLICY_UNAVAILABLE`としてfail-closedにする。ただしこれはCore Runtime全停止を意味せず、decay更新だけをdegradedにする。

## 9. Required tests

- half-life経過で`current-baseline`差が正確に1/2になる
- 2 half-lifeで1/4になる
- baselineより正/負どちら側からもbaselineへ単調接近する
- `minimum_elapsed_seconds`未満はproposalなし
- same elapsed/inputでtimer頻度に依存せず同一result
- targeted/global ruleを混同しない
- exact state_key ruleがkind default ruleより優先される
- missing ruleはno proposal + diagnosticで、0/neutralへresetしない
- invalid/duplicate/non-finite policy reject
- stale state/source/policy revision reject
- startup/resumeのabsolute elapsed計算
- no wall-clock read inside pure Domain calculation

## #690の本番構成参照

Deep Appraisal実行方針、fresh-start初期化方式、Decay具体規則と構成世代の値の正本は[Appraisalの本番構成](appraisal_production_configuration.md)とする。既存の意味・Reducer Authority・式・現在性を変更せず、ここへ具体値を重複定義しない。同文書は設計レビュー待ちであり、resource・loader・factoryの実装や本番採用は未完了。
